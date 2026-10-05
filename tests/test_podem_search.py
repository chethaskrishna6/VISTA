import pytest

from vista.atpg.generate import generate_test_set
from vista.atpg.podem import Outcome, PodemEngine
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.model import Circuit, GateType
from vista.rtl.parser import VerilogParser
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.pattern_sim import run_fault_simulation


@pytest.fixture(scope="module")
def c17():
    return VerilogParser().parse_file("benchmarks/c17.v")


def absorption():
    c = Circuit("absorb")
    c.mark_pi("a"); c.mark_pi("b"); c.mark_po("y")
    c.add_gate("g1", GateType.AND, "n", ["a", "b"])
    c.add_gate("g2", GateType.OR, "y", ["a", "n"])
    c.validate()
    return c


def test_n10_sa1_hand_derived_cube(c17):
    r = PodemEngine(c17, Fault("N10", 1)).generate()
    assert r.outcome is Outcome.TESTED and r.backtracks == 0
    assert r.cube == {"N1": 1, "N3": 1, "N2": 0}          # = 101XX


def test_every_c17_fault_gets_a_verified_test(c17):
    sim = SerialFaultSimulator(c17)
    for f in generate_stuck_at_faults(c17):               # all 34, uncollapsed
        r = PodemEngine(c17, f).generate()
        assert r.outcome is Outcome.TESTED, f.id
        assert sim.detects(r.cube, f), f.id                # cube with X's still detects
        for fill in (0, 1):                                # ...and so does any fill
            full = {pi: r.cube.get(pi, fill) for pi in c17.primary_inputs}
            assert sim.detects(full, f), (f.id, fill)


def test_redundant_fault_is_proven_redundant():
    c = absorption()
    r = PodemEngine(c, Fault("n", 0)).generate()
    assert r.outcome is Outcome.REDUNDANT
    sim = SerialFaultSimulator(c)                          # confirm exhaustively, independently
    assert sim.signature(Fault("n", 0)) == sim.signature(None)


def test_backtrack_limit_aborts():
    r = PodemEngine(absorption(), Fault("n", 0)).generate(backtrack_limit=0)
    assert r.outcome is Outcome.ABORTED


def test_testable_faults_in_absorption_circuit():
    c = absorption()
    sim = SerialFaultSimulator(c)
    for f in generate_stuck_at_faults(c):
        r = PodemEngine(c, f).generate()
        if sim.signature(f) == sim.signature(None):
            assert r.outcome is Outcome.REDUNDANT, f.id    # PODEM never misses a test...
        else:
            assert r.outcome is Outcome.TESTED, f.id       # ...and never claims a false one
            assert sim.detects({pi: r.cube.get(pi, 0) for pi in c.primary_inputs}, f)


def test_test_set_full_coverage_and_independent_resimulation(c17):
    col = collapse_equivalent(c17, generate_stuck_at_faults(c17))
    w = {r: len(m) for r, m in col.classes.items()}
    res = generate_test_set(c17, col.representatives, w)
    assert res.coverage == 1.0 and res.efficiency == 1.0
    assert not res.redundant and not res.aborted
    assert len(res.patterns) < len(col.representatives)    # dropping must compact
    rep = run_fault_simulation(c17, col.representatives, res.patterns, w)
    assert rep.undetected == []      
def test_podem_results_carry_timing(c17):
    col = collapse_equivalent(c17, generate_stuck_at_faults(c17))
    res = generate_test_set(c17, col.representatives)
    assert res.podem and all(r.seconds >= 0 for r in res.podem.values())                      # a separate code path agrees