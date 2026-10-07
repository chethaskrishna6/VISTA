import itertools
import random
from collections import Counter
from pathlib import Path

import pytest

from vista.atpg.loc import (REASON_HELD, LocFaultSimulator, generate_loc_tests, reference_agrees)
from vista.atpg.podem import Outcome
from vista.atpg.sat import SatAtpg
from vista.atpg.transition_atpg import generate_transition_tests
from vista.cli import main
from vista.faults.stuck_at import Fault
from vista.faults.transition import TransitionFault, generate_transition_faults
from vista.rtl.bench import parse_bench
from vista.rtl.loader import load_circuit
from vista.rtl.loc import LocModel
from vista.rtl.model import CircuitError
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import X
from vista.sim.transition_sim import TransitionFaultSimulator

SEQ = "INPUT(a)\nOUTPUT(y)\nq = DFF(d)\nd = NAND(a, q)\ny = NOT(q)\n"
S27 = Path("benchmarks/s27.bench")


def seq():
    return parse_bench(SEQ, "seq", scan=True)


def circuits():
    out = [pytest.param(seq, id="seq")]
    if S27.exists():
        out.append(pytest.param(lambda: load_circuit(S27), id="s27"))
    return out


def test_expansion_structure():
    c = seq()
    m = LocModel(c, hold_pi=True)
    assert m.circuit.primary_inputs == ["a", "q"] and len(m.circuit.gates) == 2 + 2 + 1
    assert set(m.circuit.primary_outputs) == {"d@2", "y@2"}
    assert LocModel(c, hold_pi=False).circuit.primary_inputs == ["a", "q", "a@2"]


def test_hand_derived_vector():
    sim = LocFaultSimulator(LocModel(seq()))
    v = {"a": 1, "q": 1}
    g = sim.good(v)
    assert (g["d@1"], g["y@1"], g["q@2"], g["y@2"], g["d@2"]) == (0, 0, 0, 1, 1)
    assert sim.detects(v, TransitionFault("y", True))
    assert sim.detects(v, TransitionFault("q", False))
    assert not sim.detects(v, TransitionFault("y", False))            # y does not start at 1
    assert not sim.detects({"a": 1, "q": 0}, TransitionFault("y", True))   # y@1 = 1: not initialized


def test_pair_conversion_hand_derived():
    c = seq()
    assert LocModel(c).pair_of({"a": 1, "q": 1}) == ({"a": 1, "q": 1}, {"a": 1, "q": 0})
    free = LocModel(c, hold_pi=False)
    assert free.pair_of({"a": 0, "q": 0, "a@2": 1}) == ({"a": 0, "q": 0}, {"a": 1, "q": 1})


def test_held_vs_free_primary_input():
    c, f = seq(), TransitionFault("a", True)
    hold, free = generate_loc_tests(c, hold_pi=True), generate_loc_tests(c, hold_pi=False)
    assert hold.untestable[f] == REASON_HELD
    assert f in free.covered_by and REASON_HELD not in free.untestable.values()


@pytest.mark.parametrize("make", circuits())
@pytest.mark.parametrize("hold", [True, False])
def test_expanded_detection_equals_enhanced_scan_pair_detection(make, hold):
    c = make()
    model, faults = LocModel(c, hold), generate_transition_faults(c)
    loc, enh = LocFaultSimulator(model), TransitionFaultSimulator(c)
    pis, rng = model.circuit.primary_inputs, random.Random(7)
    for _ in range(120):
        vec = {pi: rng.choice((0, 1, X)) for pi in pis}
        v1, v2 = model.pair_of(vec)
        for f in faults:
            assert loc.detects(vec, f) == enh.detects(v1, v2, f), (f.id, vec)


def exhaustive_detected(model, faults):
    sim, pis, found = LocFaultSimulator(model), model.circuit.primary_inputs, set()
    for bits in itertools.product((0, 1), repeat=len(pis)):
        good = sim.good(dict(zip(pis, bits)))
        found |= {f for f in faults if sim.detects_from_good(good, f)}
    return found


@pytest.mark.parametrize("hold", [True, False])
def test_seq_atpg_matches_exhaustive(hold):
    c = seq()
    res = generate_loc_tests(c, hold_pi=hold)
    ex = exhaustive_detected(res.model, res.faults)
    assert set(res.covered_by) == ex and set(res.untestable) == set(res.faults) - ex
    assert res.efficiency == 1.0 and reference_agrees(c, res)


@pytest.mark.skipif(not S27.exists(), reason="s27 not present")
def test_s27_hold_atpg_matches_exhaustive_and_has_held_pis():
    c = load_circuit(S27)
    res = generate_loc_tests(c, hold_pi=True)
    ex = exhaustive_detected(res.model, res.faults)
    assert set(res.covered_by) == ex and set(res.untestable) == set(res.faults) - ex
    assert Counter(res.untestable.values())[REASON_HELD] == 8        # 4 PIs x 2, no PI branches
    assert len(res.covered_by) <= 46
    assert reference_agrees(c, res)
    enh = generate_transition_tests(c, res.faults)
    assert set(res.covered_by) <= set(enh.covered_by)                # LOC is a restriction of enhanced scan


@pytest.mark.skipif(not S27.exists(), reason="s27 not present")
def test_s27_free_pi_atpg_is_verified():
    c = load_circuit(S27)
    res = generate_loc_tests(c, hold_pi=False)
    assert REASON_HELD not in res.untestable.values() and res.efficiency == 1.0
    assert reference_agrees(c, res)


def test_loc_rejects_circuits_without_flip_flops_and_reserved_names():
    with pytest.raises(CircuitError, match="full-scan"):
        LocModel(load_circuit("benchmarks/c17.bench"))
    c = parse_bench("INPUT(a)\nOUTPUT(y)\nq = DFF(a@1)\na@1 = NOT(a)\ny = NOT(q)\n", "bad", scan=True)
    with pytest.raises(CircuitError, match="reserved"):
        LocModel(c)


def test_sat_require_hand_derived():
    c = load_circuit("benchmarks/c17.bench")
    sat, sim = SatAtpg(c), SerialFaultSimulator(c)
    f = Fault("10", 1)                         # needs N1 = N3 = 1 to excite
    assert sat.generate(f, require=[("1", 0)]).outcome is Outcome.REDUNDANT
    r = sat.generate(f, require=[("2", 0)])
    assert r.outcome is Outcome.TESTED and r.pattern["2"] == 0 and sim.detects(r.pattern, f)
    assert sat.generate(f).outcome is Outcome.TESTED          # a failed require left no residue
    with pytest.raises(ValueError):
        sat.generate(f, require=[("nope", 1)])
    sat.close()


def test_cli(capsys):
    assert main(["loc-atpg", "benchmarks/s27.bench", "--compare"]) == 0
    out = capsys.readouterr().out
    assert "AGREES" in out and "subset of enhanced-detected: YES" in out