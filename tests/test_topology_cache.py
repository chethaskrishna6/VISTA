from pathlib import Path

import networkx as nx
import pytest

from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit, GateType


def reference_levels(c):
    g = c.to_networkx()
    level = {}
    for n in nx.topological_sort(g):
        preds = list(g.predecessors(n))
        level[n] = 0 if not preds else 1 + max(level[p] for p in preds)
    return level


def test_cache_is_invalidated_by_construction():
    c = Circuit("t")
    c.mark_pi("a"); c.mark_pi("b")
    c.add_gate("g1", GateType.AND, "n", ["a", "b"])
    assert [g.name for g in c.gates_in_topo_order()] == ["g1"]
    assert c.levelize()["n"] == 1
    c.add_gate("g2", GateType.NOT, "y", ["n"])
    assert [g.name for g in c.gates_in_topo_order()] == ["g1", "g2"]
    assert c.levelize()["y"] == 2 and c.levelize() == reference_levels(c)
    c.net("floating")
    assert c.levelize()["floating"] == 0


def test_callers_cannot_corrupt_the_cache():
    c = load_circuit("benchmarks/c17.bench")
    lv = c.levelize()
    lv["10"] = 99
    order = c.gates_in_topo_order()
    order.clear()
    assert c.levelize()["10"] == 1 and len(c.gates_in_topo_order()) == 6


@pytest.mark.parametrize("path", ["benchmarks/c17.bench", "benchmarks/c432.bench", "benchmarks/c499.bench"])
def test_cached_levels_equal_uncached_reference(path):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    c = load_circuit(path)
    for _ in range(2):                       # first call fills the cache, second reads it
        assert c.levelize() == reference_levels(c)
    names = [g.name for g in c.gates_in_topo_order()]
    lvl = c.levelize()
    assert names == [g.name for g in sorted(c.gates.values(), key=lambda g: (lvl[g.output], g.name))]