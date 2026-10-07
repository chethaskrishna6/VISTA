import random
from pathlib import Path

import pytest

from vista.faults.stuck_at import Fault
from vista.faults.transition import TransitionFault, generate_transition_faults
from vista.rtl.loader import load_circuit
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import X
from vista.sim.pattern_sim import exhaustive_patterns
from vista.sim.transition_sim import TransitionFaultSimulator, run_transition_simulation


@pytest.fixture(scope="module")
def c17():
    return load_circuit("benchmarks/c17.bench")


@pytest.fixture(scope="module")
def tsim(c17):
    return TransitionFaultSimulator(c17)


def pat(c, bits):
    return dict(zip(c.primary_inputs, [int(b) for b in bits]))      # PI order 1 2 3 6 7


def mixed_pairs(c, n, seed):
    rng = random.Random(seed)
    mk = lambda: {pi: rng.choice((0, 1, X)) for pi in c.primary_inputs}
    return [(mk(), mk()) for _ in range(n)]


def test_universe(c17):
    fl = generate_transition_faults(c17)
    assert len(fl) == 34 and sum(f.rising for f in fl) == 17
    assert len({f.id for f in fl}) == 34
    ids = {f.id for f in fl}
    assert {"10/STR", "10/STF", "3->10.1/STR", "3->11.0/STF"} <= ids


def test_stuck_mapping_and_validation():
    assert TransitionFault("10", True).stuck == Fault("10", 0)
    assert TransitionFault("10", False).stuck == Fault("10", 1)
    assert TransitionFault("3", True, "10", 1).stuck == Fault("3", 0, "10", 1)
    with pytest.raises(ValueError):
        TransitionFault("3", True, gate="10")


def test_stem_hand_derived(c17, tsim):
    a, b = pat(c17, "10100"), pat(c17, "00100")
    str10, stf10 = TransitionFault("10", True), TransitionFault("10", False)
    assert tsim.detects(a, b, str10)              # init N10=0, then SA0 detected by 00100
    assert not tsim.detects(b, a, str10)          # reversed pair launches a FALL
    assert tsim.detects(b, a, stf10)              # ...which is what STF needs
    assert not tsim.detects(b, b, str10)          # V2 detects SA0, but V1 did not initialize N10=0
    assert not tsim.detects(a, a, str10)          # initialized, but no launch: N10 stays 0


def test_branch_hand_derived(c17, tsim):
    f = TransitionFault("3", True, "10", 1)       # N3 -> NAND(1,3), STR
    assert tsim.detects(pat(c17, "10000"), pat(c17, "10100"), f)    # N3: 0 -> 1, N1=1, N2=0
    assert not tsim.detects(pat(c17, "10100"), pat(c17, "10100"), f)


def test_x_never_initializes(c17, tsim):
    v1 = pat(c17, "00100")
    v1["1"] = X                                   # N10 = NAND(X,1) = X in frame 1
    assert not tsim.detects(v1, pat(c17, "00100"), TransitionFault("10", True))


@pytest.mark.parametrize("path,n", [("benchmarks/c17.bench", 60), ("benchmarks/c432.bench", 8)])
def test_fast_path_equals_full_reference(path, n):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    c = load_circuit(path)
    ts, ref = TransitionFaultSimulator(c), SerialFaultSimulator(c)
    for v1, v2 in mixed_pairs(c, n, seed=3):
        g1 = ref.simulate(v1)
        for f in generate_transition_faults(c):
            slow = g1[f.net] == f.init_value and ref.detects(v2, f.stuck)   # full-circuit path
            assert ts.detects(v1, v2, f) == slow, (f.id, v1, v2)


def test_tdf_detection_implies_stuck_at_detection(c17, tsim):
    ref = SerialFaultSimulator(c17)
    for v1, v2 in mixed_pairs(c17, 80, seed=9):
        for f in generate_transition_faults(c17):
            if tsim.detects(v1, v2, f):
                assert ref.detects(v2, f.stuck)


def test_exhaustive_pairs_detect_every_c17_transition_fault(c17):
    pats = exhaustive_patterns(c17)
    pairs = [(a, b) for a in pats for b in pats]
    rep = run_transition_simulation(c17, generate_transition_faults(c17), pairs)
    assert rep.undetected == [] and rep.coverage == 1.0


def test_dropping_agrees_with_full_matrix_on_first_detect(c17):
    pairs = mixed_pairs(c17, 40, seed=2)
    pairs = [({k: (v if v != X else 0) for k, v in a.items()},
              {k: (v if v != X else 1) for k, v in b.items()}) for a, b in pairs]
    fl = generate_transition_faults(c17)
    d = run_transition_simulation(c17, fl, pairs, drop=True)
    n = run_transition_simulation(c17, fl, pairs, drop=False)
    for f in fl:
        assert (d.detections[f][:1]) == (n.detections[f][:1])
    curve = d.coverage_curve()
    assert curve == sorted(curve) and curve[-1] == len(d.detected)