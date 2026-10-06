import random
from pathlib import Path

import pytest

from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import X
from vista.sim.pattern_sim import random_patterns, run_fault_simulation


def mixed_patterns(circuit, n, seed):
    rng = random.Random(seed)
    return [{pi: rng.choice((0, 1, X)) for pi in circuit.primary_inputs} for _ in range(n)]


def load_or_skip(path):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    return load_circuit(path)


@pytest.mark.parametrize("path,n", [("benchmarks/c17.bench", 40), ("benchmarks/c432.bench", 6)])
def test_cone_simulation_equals_full_simulation(path, n):
    c = load_or_skip(path)
    sim = SerialFaultSimulator(c)
    faults = generate_stuck_at_faults(c)                  # all faults, stems and branches
    for p in mixed_patterns(c, n, seed=5) + random_patterns(c, n, seed=6):
        good = sim.simulate(p)
        for f in faults:
            assert sim.simulate_faulty(good, f) == sim.simulate(p, f), (f.id, p)


def test_fast_and_reference_fault_simulation_agree():
    c = load_or_skip("benchmarks/c432.bench")
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
    pats = random_patterns(c, 30, seed=11)
    fast = run_fault_simulation(c, faults, pats, drop=False)
    slow = run_fault_simulation(c, faults, pats, drop=False, reference=True)
    assert fast.detections == slow.detections