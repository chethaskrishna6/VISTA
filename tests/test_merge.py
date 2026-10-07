from pathlib import Path

import pytest

from vista.atpg.merge import (CubeFactory, compatible, merge_items, run_stuck_at,
                              run_transition)
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.sim.fault_sim import SerialFaultSimulator


def test_compatible():
    assert compatible({"a": 1}, {"b": 0}) and compatible({}, {"a": 1})
    assert compatible({"a": 1, "b": 0}, {"a": 1})
    assert not compatible({"a": 1}, {"a": 0})


def test_merge_single_frame_hand_case():
    items = [({"a": 1},), ({"a": 0},), ({"b": 1},)]
    groups, assign = merge_items(items)
    assert assign == [0, 1, 0]
    assert groups == [[{"a": 1, "b": 1}], [{"a": 0}]]
    assert items[0] == ({"a": 1},)                       # inputs untouched


def test_merge_two_frames_both_must_be_compatible():
    items = [({"a": 1}, {"b": 0}), ({"a": 1}, {"b": 1}), ({"c": 1}, {"b": 0})]
    groups, assign = merge_items(items)
    assert assign == [0, 1, 0]
    assert groups[0] == [{"a": 1, "c": 1}, {"b": 0}]


def test_merge_empty():
    assert merge_items([]) == ([], [])


def test_c17_merged_patterns_detect_every_member_under_any_fill():
    c = load_circuit("benchmarks/c17.bench")
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
    fac = CubeFactory(c)
    cubes = {f: fac.stuck_at(f) for f in faults}
    fac.close()
    assert all(v is not None for v in cubes.values())
    groups, assign = merge_items([(cubes[f],) for f in faults])
    assert len(groups) < len(faults)                     # merging must actually merge
    sim = SerialFaultSimulator(c)
    for f, gi in zip(faults, assign):
        for fill in (0, 1):
            full = {pi: groups[gi][0].get(pi, fill) for pi in c.primary_inputs}
            assert sim.detects(full, f), (f.id, fill)


@pytest.mark.parametrize("run", [run_stuck_at, run_transition])
@pytest.mark.parametrize("fill", ["0", "random"])
def test_c17_reports(run, fill):
    r = run(load_circuit("benchmarks/c17.bench"), fill=fill)
    assert r.matrix_ok and r.preserved and r.untestable == 0
    assert 0 < r.kept <= r.merged < r.targets


@pytest.mark.parametrize("run", [run_stuck_at, run_transition])
def test_c432_reports(run):
    if not Path("benchmarks/c432.bench").exists():
        pytest.skip("c432 not present")
    r = run(load_circuit("benchmarks/c432.bench"))
    assert r.matrix_ok and r.preserved
    assert r.kept <= r.merged < r.targets