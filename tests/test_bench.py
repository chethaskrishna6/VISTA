import pytest

from vista.atpg.generate import generate_test_set
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.bench import parse_bench
from vista.rtl.loader import load_circuit
from vista.rtl.model import CircuitError
from vista.rtl.stats import circuit_stats
from vista.sim.simulator import LogicSimulator


@pytest.fixture(scope="module")
def bench():
    return load_circuit("benchmarks/c17.bench")


@pytest.fixture(scope="module")
def verilog():
    return load_circuit("benchmarks/c17.v")


def test_matches_verilog_version_exhaustively(bench, verilog):
    assert verilog.primary_inputs == ["N" + p for p in bench.primary_inputs]
    sb, sv = LogicSimulator(bench), LogicSimulator(verilog)
    for i in range(32):
        bits = format(i, "05b")
        ob = sb.outputs(sb.pattern_from_string(bits))
        ov = sv.outputs(sv.pattern_from_string(bits))
        assert {"N" + k: v for k, v in ob.items()} == ov


def test_structure(bench):
    assert len(bench.gates) == 6 and sorted(bench.stems) == ["11", "16", "3"]
    assert sorted(bench.primary_outputs) == ["22", "23"]


def test_fault_counts_match_verilog_flow(bench):
    universe = generate_stuck_at_faults(bench)
    assert len(universe) == 34
    assert len(collapse_equivalent(bench, universe).classes) == 22


def test_atpg_runs_on_bench_circuit(bench):
    col = collapse_equivalent(bench, generate_stuck_at_faults(bench))
    w = {r: len(m) for r, m in col.classes.items()}
    res = generate_test_set(bench, col.representatives, w)
    assert res.coverage == 1.0 and not res.aborted


def test_syntax_tolerance():
    text = "# c\n\ninput(a)\nINPUT( b )\nOUTPUT(y)  # trailing\nn1 = and(a, b)\ny = BUFF(n1)\n"
    c = parse_bench(text, "tiny")
    assert len(c.gates) == 2 and c.gates["y"].type.value == "buf"


@pytest.mark.parametrize("text,pattern", [
    ("INPUT(a)\nOUTPUT(y)\ny = DFF(a)\n", "unsupported"),
    ("INPUT(a)\nOUTPUT(y)\ny = FOO(a)\n", "unsupported"),
    ("INPUT(a)\nOUTPUT(y)\ny NAND a\n", "line 3"),
    ("INPUT(a)\nOUTPUT(y)\ny = NOT(a, a)\n", "line 3"),
    ("INPUT(a)\nOUTPUT(y)\ny = AND(a, ghost)\n", "undriven"),
    ("INPUT(a)\nOUTPUT(y)\ny = NOT(a)\ny = BUF(a)\n", "duplicate"),
])
def test_rejects_bad_netlists(text, pattern):
    with pytest.raises(CircuitError, match=pattern):
        parse_bench(text)


def test_loader_dispatch():
    assert load_circuit("benchmarks/c17.v").name == "c17"
    assert load_circuit("benchmarks/c17.bench").name == "c17"
    with pytest.raises(CircuitError):
        load_circuit("design.vhd")


def test_stats(bench):
    s = circuit_stats(bench)
    assert (s["inputs"], s["outputs"], s["gates"], s["depth"]) == (5, 2, 6, 3)
    assert s["gate_types"] == {"nand": 6} and s["max_fanin"] == 2 and s["stems"] == 3
def test_po_with_fanout_detection(bench):
    assert bench.po_with_fanout == []
    c = parse_bench("INPUT(a)\nINPUT(b)\nOUTPUT(n)\nOUTPUT(y)\nn = AND(a, b)\ny = NOT(n)\n", "pof")
    assert c.po_with_fanout == ["n"]
    # Documents the known gap: n is PO + gate input (2 branches), yet only 4 nets x 2 = 8 faults exist.
    assert len(generate_stuck_at_faults(c)) == 8