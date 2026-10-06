from pathlib import Path

import pytest

from vista.atpg.generate import generate_test_set
from vista.atpg.podem import Outcome, PodemEngine
from vista.atpg.scoap import Scoap
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.bench import parse_bench
from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit, GateType
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.pattern_sim import run_fault_simulation


@pytest.fixture(scope="module")
def c17():
    return load_circuit("benchmarks/c17.bench")


def test_c17_scoap_hand_values(c17):
    s = Scoap(c17)
    cc = {"10": (3, 2), "11": (3, 2), "16": (4, 2), "19": (4, 2), "22": (5, 4), "23": (5, 5)}
    for n, v in cc.items():
        assert (s.cc0[n], s.cc1[n]) == v, n
    assert all((s.cc0[p], s.cc1[p]) == (1, 1) for p in c17.primary_inputs)
    co = {"22": 0, "23": 0, "10": 3, "19": 3, "16": 3, "11": 5,
          "7": 6, "2": 6, "1": 5, "6": 7, "3": 5}
    assert {n: s.co[n] for n in co} == co
    assert s.pin_co(c17.gates["16"], 1) == 5 and s.pin_co(c17.gates["16"], 0) == 6


def test_xor_xnor_not_hand_values():
    c = parse_bench("INPUT(a)\nINPUT(b)\nINPUT(c)\nINPUT(d)\nOUTPUT(w)\nOUTPUT(x)\nOUTPUT(y)\n"
                    "z = AND(a, b)\nq = AND(c, d)\nw = XOR(z, q)\nx = XNOR(z, q)\ny = NOT(z)\n")
    s = Scoap(c)
    assert (s.cc0["z"], s.cc1["z"]) == (2, 3)
    assert (s.cc0["w"], s.cc1["w"]) == (5, 6)
    assert (s.cc0["x"], s.cc1["x"]) == (6, 5)
    assert (s.cc0["y"], s.cc1["y"]) == (4, 3)
    assert s.co["z"] == 1 and s.co["q"] == 3 and s.co["a"] == 3


def test_scoap_backtrace_differs_from_naive_and_is_justified(c17):
    # Need net 16 = 0: NAND(2,11)=0 needs BOTH inputs 1. Naive takes input '2' first.
    # SCOAP takes the harder input '11' first, then N11=1 needs one of 3/6 = 0 (tie -> '3').
    f = Fault("10", 1)
    naive = PodemEngine(c17, f)
    smart = PodemEngine(c17, f, Scoap(c17))
    v = naive.imply({})
    assert naive.backtrace(v, "16", 0) == ("2", 1)
    assert smart.backtrace(v, "16", 0) == ("3", 0)


def test_scoap_engine_still_tests_every_c17_fault(c17):
    sim, s = SerialFaultSimulator(c17), Scoap(c17)
    for f in generate_stuck_at_faults(c17):
        r = PodemEngine(c17, f, s).generate()
        assert r.outcome is Outcome.TESTED, f.id
        assert sim.detects({pi: r.cube.get(pi, 0) for pi in c17.primary_inputs}, f), f.id


def test_scoap_engine_still_proves_redundancy():
    c = Circuit("absorb")
    c.mark_pi("a"); c.mark_pi("b"); c.mark_po("y")
    c.add_gate("g1", GateType.AND, "n", ["a", "b"])
    c.add_gate("g2", GateType.OR, "y", ["a", "n"])
    c.validate()
    assert PodemEngine(c, Fault("n", 0), Scoap(c)).generate().outcome is Outcome.REDUNDANT


def test_scoap_run_on_c432_is_sound():
    if not Path("benchmarks/c432.bench").exists():
        pytest.skip("c432 not present")
    c = load_circuit("benchmarks/c432.bench")
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
    res = generate_test_set(c, faults, backtrack_limit=50, scoap=Scoap(c))
    rep = run_fault_simulation(c, faults, res.patterns, reference=True)   # slow oracle
    assert set(rep.detected) == set(res.covered_by)