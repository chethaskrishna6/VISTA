import itertools
from pathlib import Path

import pytest

from vista.atpg.hybrid import run_hybrid
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.bench import parse_bench
from vista.rtl.loader import load_circuit
from vista.rtl.model import CircuitError
from vista.rtl.scan import PO_SUFFIX, isolate_po_fanout
from vista.rtl.stats import circuit_stats
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import to_str
from vista.sim.simulator import LogicSimulator

POF = "INPUT(a)\nINPUT(b)\nOUTPUT(n)\nOUTPUT(y)\nn = AND(a, b)\ny = NOT(n)\n"
SEQ = "INPUT(a)\nOUTPUT(y)\nq = DFF(d)\nd = NAND(a, q)\ny = NOT(q)\n"
S27 = Path("benchmarks/s27.bench")


def same_function(raw, iso):
    a, b = LogicSimulator(raw), LogicSimulator(iso)
    for bits in itertools.product((0, 1), repeat=len(raw.primary_inputs)):
        p = dict(zip(raw.primary_inputs, bits))
        got = {k.removesuffix(PO_SUFFIX): v for k, v in b.outputs(p).items()}
        assert got == a.outputs(p), bits


def test_isolation_hand_derived():
    raw = parse_bench(POF, "pof")
    c = isolate_po_fanout(raw)
    assert raw.po_with_fanout == ["n"] and c.po_with_fanout == []
    assert c.primary_outputs == ["y", "n$po"] and c.po_buffers == ["n$po"]
    assert len(generate_stuck_at_faults(raw)) == 8
    assert len(generate_stuck_at_faults(c)) == 14
    same_function(raw, c)


def test_po_pin_branch_differs_from_stem():
    sim = SerialFaultSimulator(isolate_po_fanout(parse_bench(POF, "pof")))
    p = {"a": 1, "b": 1}
    stem, branch = Fault("n", 0), Fault("n", 0, "n$po", 0)
    assert to_str(sim.outputs(p).values()) == "01"
    assert to_str(sim.outputs(p, stem).values()) == "10"
    assert to_str(sim.outputs(p, branch).values()) == "00"


def test_untouched_when_no_po_fanout():
    for path in ("benchmarks/c17.bench", "benchmarks/c432.bench"):
        if Path(path).exists():
            c = parse_bench(Path(path).read_text(), "x")
            assert isolate_po_fanout(c) is c


def test_name_clash_rejected():
    c = parse_bench(POF + "w = NOT(a)\n", "pof")
    c.net("n$po")
    with pytest.raises(CircuitError, match="already used"):
        isolate_po_fanout(c)


def test_dff_rejected_without_scan():
    with pytest.raises(CircuitError, match="unsupported"):
        parse_bench(SEQ, "seq")


def test_scan_conversion():
    c = parse_bench(SEQ, "seq", scan=True)
    assert c.primary_inputs == ["a", "q"] and c.primary_outputs == ["d", "y"]
    assert c.scan_cells == [("q", "d")]


@pytest.mark.parametrize("text,needle", [
    ("INPUT(a)\nOUTPUT(y)\ny = DFF(a, a)\n", "exactly 1"),
    ("INPUT(q)\nOUTPUT(y)\nq = DFF(y)\ny = NOT(q)\n", "already"),
    ("INPUT(a)\nOUTPUT(y)\nq = DFF(a)\nq = DFF(y)\ny = NOT(q)\n", "already"),
    ("INPUT(a)\nOUTPUT(y)\nq = DFF(ghost)\ny = NOT(q)\n", "undriven"),
])
def test_bad_scan_netlists(text, needle):
    with pytest.raises(CircuitError, match=needle):
        parse_bench(text, "bad", scan=True)


def test_dff_fed_directly_by_a_pi():
    c = parse_bench("INPUT(a)\nOUTPUT(y)\nq = DFF(a)\ny = NOT(q)\n", "t", scan=True)
    assert "a" in c.primary_inputs and "a" in c.primary_outputs
    assert run_hybrid(c, generate_stuck_at_faults(c)).efficiency == 1.0


def test_loader_scan_modes(tmp_path, capsys):
    f = tmp_path / "seq.bench"
    f.write_text(SEQ)
    assert load_circuit(f).scan_cells == [("q", "d")]            # auto-detected
    assert "scan" in capsys.readouterr().err
    assert load_circuit(f, scan=True).scan_cells == [("q", "d")]
    with pytest.raises(CircuitError, match="unsupported"):
        load_circuit(f, scan=False)
    v = tmp_path / "x.v"
    v.write_text("module m(a,y); input a; output y; not g(y,a); endmodule\n")
    with pytest.raises(CircuitError, match="bench"):
        load_circuit(v, scan=True)


@pytest.mark.skipif(not S27.exists(), reason="s27 not present")
def test_s27_structure_and_fault_counts():
    c = load_circuit(S27)
    s = circuit_stats(c)
    assert (s["inputs"], s["outputs"], s["gates"], s["depth"], s["stems"]) == (7, 4, 11, 6, 4)
    assert s["scan_cells"] == 3 and c.po_buffers == ["G11$po"]
    faults = generate_stuck_at_faults(c)
    assert len(faults) == 54
    assert len(collapse_equivalent(c, faults).classes) == 32
    raw = parse_bench(S27.read_text(), "s27", scan=True)           # without the PO-pin fix
    assert raw.po_with_fanout == ["G11"]
    raw_faults = generate_stuck_at_faults(raw)
    assert len(raw_faults) == 50
    assert len(collapse_equivalent(raw, raw_faults).classes) == 30   # two classes missing
    same_function(raw, c)