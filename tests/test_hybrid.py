from pathlib import Path

import pytest

from vista.atpg.generate import generate_test_set
from vista.atpg.hybrid import run_hybrid
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit, GateType
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.pattern_sim import run_fault_simulation


def absorption() -> Circuit:
    c = Circuit("absorb")
    c.mark_pi("a"); c.mark_pi("b"); c.mark_po("y")
    c.add_gate("g1", GateType.AND, "n", ["a", "b"])
    c.add_gate("g2", GateType.OR, "y", ["a", "n"])
    c.validate()
    return c


def test_hybrid_resolves_everything_on_small_circuit():
    a = absorption()
    faults = generate_stuck_at_faults(a)
    plain = generate_test_set(a, faults, backtrack_limit=0)
    hyb = run_hybrid(a, faults, backtrack_limit=0)
    assert Fault("n", 0) in plain.unresolved
    assert hyb.unresolved == [] and Fault("n", 0) in hyb.sat_redundant
    assert hyb.efficiency == 1.0
    sim = SerialFaultSimulator(a)
    good = sim.signature(None)
    assert {f for f in faults if sim.signature(f) == good} == set(hyb.redundant)
    assert all(sim.signature(f) != good for f in hyb.covered_by)


@pytest.mark.parametrize("path,redundant", [("benchmarks/c432.bench", 4),
                                            ("benchmarks/c499.bench", 8)])
def test_hybrid_reaches_full_efficiency(path, redundant):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    c = load_circuit(path)
    col = collapse_equivalent(c, generate_stuck_at_faults(c))
    faults = col.representatives
    w = {r: len(m) for r, m in col.classes.items()}
    res = run_hybrid(c, faults, w, 100)
    assert res.unresolved == [] and res.efficiency == 1.0
    assert len(res.redundant) == redundant
    assert len(res.covered_by) + len(res.redundant) == len(faults)
    rep = run_fault_simulation(c, faults, res.patterns, reference=True)   # slow oracle
    assert set(rep.detected) == set(res.covered_by)