import json
from collections import Counter
from pathlib import Path

import pytest

from vista.atpg.justify import Justifier
from vista.atpg.podem import Outcome
from vista.atpg.sat import SatAtpg
from vista.atpg.transition_atpg import (REASON_INIT, REASON_SA, generate_transition_tests,
                                        reference_detected)
from vista.faults.transition import TransitionFault, generate_transition_faults
from vista.rtl.bench import parse_bench
from vista.rtl.loader import load_circuit
from vista.sim.pattern_sim import exhaustive_patterns
from vista.sim.simulator import LogicSimulator
from vista.sim.transition_sim import run_transition_simulation

ALWAYS_ONE = "INPUT(a)\nOUTPUT(y)\nn = NOT(a)\ny = OR(a, n)\n"
ALWAYS_ZERO = "INPUT(a)\nOUTPUT(y)\nn = NOT(a)\ny = AND(a, n)\n"


@pytest.fixture(scope="module")
def c17():
    return load_circuit("benchmarks/c17.bench")


def need(path):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    return load_circuit(path)


def test_justify_hand_derived(c17):
    j = Justifier(c17)
    for net, val, cube in [("10", 0, {"1": 1, "3": 1}), ("10", 1, {"1": 0}),
                           ("22", 0, {"1": 0, "2": 0})]:
        r = j.justify(net, val)
        assert (r.outcome, r.cube, r.backtracks) == (Outcome.TESTED, cube, 0), (net, val)


def test_justify_proves_impossible_and_aborts():
    c = parse_bench(ALWAYS_ZERO, "z")
    j = Justifier(c)
    assert j.justify("y", 0).outcome is Outcome.TESTED
    assert j.justify("y", 1).outcome is Outcome.REDUNDANT
    assert j.justify("y", 1, backtrack_limit=0).outcome is Outcome.ABORTED
    with pytest.raises(ValueError):
        j.justify("nope", 1)


def test_justify_matches_exhaustive_on_every_c17_net(c17):
    sim, j = LogicSimulator(c17), Justifier(c17)
    pats = exhaustive_patterns(c17)
    for net in c17.nets:
        for v in (0, 1):
            possible = any(sim.simulate(p)[net] == v for p in pats)
            r = j.justify(net, v)
            assert (r.outcome is Outcome.TESTED) == possible, (net, v)
            if possible:
                for fill in (0, 1):
                    full = {pi: r.cube.get(pi, fill) for pi in c17.primary_inputs}
                    assert sim.simulate(full)[net] == v


@pytest.mark.parametrize("path", ["benchmarks/c432.bench", "benchmarks/c499.bench"])
def test_justify_agrees_with_sat_on_every_net(path):
    c = need(path)
    sim, j, sat = LogicSimulator(c), Justifier(c), SatAtpg(c)
    for net in c.nets:
        for v in (0, 1):
            r = j.justify(net, v, backtrack_limit=1000)
            assert r.outcome is not Outcome.ABORTED, (net, v)       # tell me if this trips
            assert (r.outcome is Outcome.TESTED) == (sat.justify(net, v) is not None), (net, v)
            if r.outcome is Outcome.TESTED:
                full = {pi: r.cube.get(pi, 0) for pi in c.primary_inputs}
                assert sim.simulate(full)[net] == v, (net, v)
    sat.close()


def test_c17_transition_atpg(c17):
    faults = generate_transition_faults(c17)
    res = generate_transition_tests(c17, faults)
    assert res.coverage == 1.0 and res.efficiency == 1.0 and not res.untestable
    assert 0 < len(res.pairs) <= len(faults)
    assert reference_detected(c17, faults, res.pairs) == set(res.covered_by)
    again = generate_transition_tests(c17, faults)                  # same seed -> same pairs
    assert again.pairs == res.pairs


def test_untestable_classification_matches_exhaustive_pairs():
    c = parse_bench(ALWAYS_ONE, "one")
    faults = generate_transition_faults(c)
    res = generate_transition_tests(c, faults)
    pats = exhaustive_patterns(c)
    ex = run_transition_simulation(c, faults, [(a, b) for a in pats for b in pats])
    assert set(res.covered_by) == set(ex.detected)
    assert set(res.untestable) == set(ex.undetected)
    assert res.untestable[TransitionFault("y", True)] == REASON_INIT    # y is never 0
    assert res.untestable[TransitionFault("y", False)] == REASON_SA     # SA1 on a constant 1


@pytest.mark.parametrize("path,sa_redundant", [("benchmarks/c432.bench", 10),
                                               ("benchmarks/c499.bench", 8)])
def test_exact_classification_against_sat(path, sa_redundant):
    c = need(path)
    faults = generate_transition_faults(c)
    res = generate_transition_tests(c, faults)
    sat = SatAtpg(c)
    expected = {f for f in faults if sat.generate(f.stuck).outcome is Outcome.REDUNDANT
                or sat.justify(f.net, f.init_value) is None}
    sat.close()
    assert set(res.untestable) == expected
    assert set(res.covered_by).isdisjoint(res.untestable)
    assert len(res.covered_by) + len(res.untestable) == len(faults)
    assert res.efficiency == 1.0
    assert Counter(res.untestable.values())[REASON_SA] == sa_redundant   # from your SAT weights
    assert reference_detected(c, faults, res.pairs) == set(res.covered_by)


def test_fill_validation_and_json(c17):
    with pytest.raises(ValueError):
        generate_transition_tests(c17, fill="2")
    res = generate_transition_tests(c17, fill="0")
    d = json.loads(json.dumps(res.to_dict()))
    assert d["fault_model"] == "transition" and d["summary"]["total_faults"] == 34
    assert len(d["pairs"]) == len(res.pairs) and len(d["faults"]) == 34