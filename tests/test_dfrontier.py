import random
from pathlib import Path

import pytest

from vista.atpg.podem import PodemEngine
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.loader import load_circuit


def partial_assignment(c, rng):
    density = rng.random()                      # from nearly all-X to nearly fully specified
    return {pi: rng.getrandbits(1) for pi in c.primary_inputs if rng.random() < density}


@pytest.mark.parametrize("path,step,trials", [("benchmarks/c17.bench", 1, 40),
                                              ("benchmarks/c432.bench", 5, 15)])
def test_cone_dfrontier_equals_reference(path, step, trials):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    c = load_circuit(path)
    rng = random.Random(12)
    nonempty = branch_nonempty = 0
    for f in generate_stuck_at_faults(c)[::step]:
        e = PodemEngine(c, f)
        for _ in range(trials):
            v = e.imply(partial_assignment(c, rng))
            new = [g.name for g in e.d_frontier(v)]
            assert new == [g.name for g in e.d_frontier_reference(v)], f.id
            nonempty += bool(new)
            branch_nonempty += bool(new) and f.is_branch
    assert nonempty > 0 and branch_nonempty > 0, "test never saw a non-empty frontier"


def test_fault_not_matching_netlist_fails_at_construction():
    from vista.faults.stuck_at import Fault
    c = load_circuit("benchmarks/c17.bench")
    with pytest.raises(ValueError):
        PodemEngine(c, Fault("nope", 0))