from itertools import combinations
from pathlib import Path

import pytest

from vista.atpg.generate import generate_test_set
from vista.atpg.podem import Outcome, PodemEngine, SCOAP_PARTS
from vista.atpg.scoap import Scoap
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit, GateType
from vista.sim.fault_sim import SerialFaultSimulator

SUBSETS = [frozenset(s) for r in range(4) for s in combinations(sorted(SCOAP_PARTS), r)]


def absorption() -> Circuit:
    c = Circuit("absorb")
    c.mark_pi("a"); c.mark_pi("b"); c.mark_po("y")
    c.add_gate("g1", GateType.AND, "n", ["a", "b"])
    c.add_gate("g2", GateType.OR, "y", ["a", "n"])
    c.validate()
    return c


def key(r):
    return (r.outcome, r.cube, r.backtracks)


def need(path):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    return load_circuit(path)


@pytest.mark.parametrize("path,count", [("benchmarks/c17.bench", None),
                                        ("benchmarks/c432.bench", 60)])
def test_scoap_with_no_parts_is_exactly_naive(path, count):
    c = need(path)
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives[:count]
    s = Scoap(c)
    for f in faults:
        assert key(PodemEngine(c, f).generate(50)) == key(PodemEngine(c, f, s, frozenset()).generate(50)), f.id


@pytest.mark.parametrize("use_scoap,expect", [(False, (89, 954, 8)), (True, (61, 5099, 48))])
def test_c432_regression_pins(use_scoap, expect):
    c = need("benchmarks/c432.bench")
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
    res = generate_test_set(c, faults, backtrack_limit=100, scoap=Scoap(c) if use_scoap else None)
    got = (len(res.patterns), sum(r.backtracks for r in res.podem.values()), len(res.aborted))
    assert got == expect


@pytest.mark.parametrize("use", SUBSETS, ids=lambda u: "+".join(sorted(u)) or "none")
def test_every_subset_is_sound(use):
    c = load_circuit("benchmarks/c17.bench")
    s, sim = Scoap(c), SerialFaultSimulator(c)
    for f in generate_stuck_at_faults(c):
        r = PodemEngine(c, f, s, use).generate()
        assert r.outcome is Outcome.TESTED, f.id
        assert sim.detects({pi: r.cube.get(pi, 0) for pi in c.primary_inputs}, f), f.id
    a = absorption()
    assert PodemEngine(a, Fault("n", 0), Scoap(a), use).generate().outcome is Outcome.REDUNDANT


def test_unknown_part_rejected():
    c = load_circuit("benchmarks/c17.bench")
    with pytest.raises(ValueError):
        PodemEngine(c, Fault("10", 1), Scoap(c), {"nope"})


def test_unresolved_excludes_faults_detected_later():
    a = absorption()
    res = generate_test_set(a, generate_stuck_at_faults(a), backtrack_limit=0)
    assert Fault("n", 0) in res.unresolved                 # redundant: aborted, can never be covered
    assert all(f not in res.covered_by for f in res.unresolved)
    assert set(res.unresolved) <= set(res.aborted)