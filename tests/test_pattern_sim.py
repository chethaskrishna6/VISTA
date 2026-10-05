import json

import pytest

from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.parser import VerilogParser
from vista.sim.pattern_sim import (exhaustive_patterns, random_patterns,
                                   run_fault_simulation, weights_from_collapse)


@pytest.fixture(scope="module")
def c17():
    return VerilogParser().parse_file("benchmarks/c17.v")


@pytest.fixture(scope="module")
def collapsed(c17):
    return collapse_equivalent(c17, generate_stuck_at_faults(c17))


ALL_ONES = {pi: 1 for pi in ["N1", "N2", "N3", "N6", "N7"]}


def test_single_pattern_hand_checked(c17):
    # 11111 -> good N22=1, N23=0. Only N22/SA0 and N23/SA1 disagree with the good value.
    faults = [Fault("N22", 0), Fault("N22", 1), Fault("N23", 0), Fault("N23", 1)]
    rep = run_fault_simulation(c17, faults, [ALL_ONES])
    assert {f.id for f in rep.detected} == {"N22/SA0", "N23/SA1"}
    assert {f.id for f in rep.undetected} == {"N22/SA1", "N23/SA0"}


def test_dropping_vs_full_matrix(c17):
    f = Fault("N22", 0)
    dropped = run_fault_simulation(c17, [f], [ALL_ONES, ALL_ONES], drop=True)
    full = run_fault_simulation(c17, [f], [ALL_ONES, ALL_ONES], drop=False)
    assert dropped.detections[f] == [0]
    assert full.detections[f] == [0, 1]


def test_exhaustive_detects_every_collapsed_fault(c17, collapsed):
    rep = run_fault_simulation(c17, collapsed.representatives, exhaustive_patterns(c17),
                               weights_from_collapse(collapsed))
    assert rep.undetected == []
    assert rep.coverage == 1.0 and rep.weighted_coverage == 1.0


def test_drop_and_nodrop_agree_on_first_detect(c17, collapsed):
    pats = exhaustive_patterns(c17)
    a = run_fault_simulation(c17, collapsed.representatives, pats, drop=True)
    b = run_fault_simulation(c17, collapsed.representatives, pats, drop=False)
    for f in collapsed.representatives:
        assert a.first_detect(f) == b.first_detect(f)


def test_coverage_curve_is_monotonic_and_complete(c17, collapsed):
    pats = random_patterns(c17, 6, seed=3)
    rep = run_fault_simulation(c17, collapsed.representatives, pats)
    curve = rep.coverage_curve()
    assert len(curve) == 6
    assert curve == sorted(curve)
    assert curve[-1] == len(rep.detected)


def test_weights_cover_full_universe(collapsed):
    assert sum(weights_from_collapse(collapsed).values()) == 34


def test_random_patterns_reproducible(c17):
    a, b = random_patterns(c17, 5, seed=7), random_patterns(c17, 5, seed=7)
    assert a == b and len(a) == 5
    assert all(set(p) == set(c17.primary_inputs) and set(p.values()) <= {0, 1} for p in a)


def test_json_report(c17, collapsed):
    rep = run_fault_simulation(c17, collapsed.representatives, exhaustive_patterns(c17),
                               weights_from_collapse(collapsed), drop=False)
    d = json.loads(json.dumps(rep.to_dict()))
    assert d["summary"]["total_faults"] == 22
    assert d["summary"]["weighted_total"] == 34
    assert d["summary"]["coverage_pct"] == 100.0
    assert len(d["patterns"]) == 32 and len(d["faults"]) == 22