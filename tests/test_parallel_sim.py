import itertools
import random
from pathlib import Path

import pytest

from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.rtl.model import GateType
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import ONE, X, ZERO, eval_gate
from vista.sim.parallel_sim import PackedSimulator, eval_packed, run_packed_fault_simulation
from vista.sim.pattern_sim import random_patterns, run_fault_simulation


def enc(v):
    return (int(v == ONE), int(v == ZERO))


def dec(p):
    return ONE if p[0] else ZERO if p[1] else X


@pytest.mark.parametrize("gtype", list(GateType))
def test_eval_packed_matches_eval_gate_on_all_3valued_inputs(gtype):
    for n in ([1] if gtype.is_unary else [2, 3]):
        for combo in itertools.product((ZERO, ONE, X), repeat=n):
            got = dec(eval_packed(gtype, [enc(v) for v in combo]))
            assert got == eval_gate(gtype, list(combo)), (gtype, combo)


def need(path):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    return load_circuit(path)


def mixed(c, n, seed):
    rng = random.Random(seed)
    return [{pi: rng.choice((0, 1, X)) for pi in c.primary_inputs} for _ in range(n)]


def test_hand_derived_mask():
    c = load_circuit("benchmarks/c17.bench")
    ps = PackedSimulator(c)
    pats = [dict(zip(c.primary_inputs, map(int, b))) for b in ("00100", "10100")]
    good, mask = ps.good(pats)
    assert ps.detect_mask(good, Fault("10", 0), mask) == 0b01


@pytest.mark.parametrize("path,n", [("benchmarks/c17.bench", 70), ("benchmarks/c432.bench", 20)])
def test_masks_equal_serial_per_pattern_with_x(path, n):
    c = need(path)
    ps, ser = PackedSimulator(c), SerialFaultSimulator(c)
    pats = mixed(c, n, seed=4) + random_patterns(c, n, seed=5)
    good, mask = ps.good(pats)
    for f in generate_stuck_at_faults(c):
        m = ps.detect_mask(good, f, mask)
        for i, p in enumerate(pats):
            assert bool(m >> i & 1) == ser.detects(p, f), (f.id, i)


@pytest.mark.parametrize("path", ["benchmarks/c17.bench", "benchmarks/c432.bench"])
@pytest.mark.parametrize("drop", [True, False])
@pytest.mark.parametrize("block", [1, 3, 64])
def test_runner_equals_reference_runner(path, drop, block):
    c = need(path)
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
    pats = random_patterns(c, 100, seed=8)
    a = run_packed_fault_simulation(c, faults, pats, drop=drop, block=block)
    b = run_fault_simulation(c, faults, pats, drop=drop, reference=True)
    assert a.detections == b.detections


def test_block_validation():
    c = load_circuit("benchmarks/c17.bench")
    with pytest.raises(ValueError):
        run_packed_fault_simulation(c, [], [], block=0)