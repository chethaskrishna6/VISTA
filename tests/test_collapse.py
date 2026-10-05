import pytest

from vista.faults.collapse import collapse_equivalent, collapsed_to_dict
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.model import Circuit, GateType
from vista.rtl.parser import VerilogParser
from vista.sim.fault_sim import SerialFaultSimulator


@pytest.fixture(scope="module")
def c17():
    return VerilogParser().parse_file("benchmarks/c17.v")


@pytest.fixture(scope="module")
def universe(c17):
    return generate_stuck_at_faults(c17)


@pytest.fixture(scope="module")
def result(c17, universe):
    return collapse_equivalent(c17, universe)


def test_c17_collapses_to_22(result):
    assert len(result.classes) == 22
    assert result.total_uncollapsed == 34


def test_classes_partition_the_universe(result, universe):
    flat = [m for ms in result.classes.values() for m in ms]
    assert len(flat) == len(universe) and set(flat) == set(universe)


def test_six_nand_classes_of_three(result):
    sizes = [len(m) for m in result.classes.values()]
    assert sizes.count(3) == 6 and sizes.count(1) == 16


def test_gate1_class_contents_and_representative(result):
    cls = {r.id: {m.id for m in ms} for r, ms in result.classes.items()}
    assert cls["N10/SA1"] == {"N1/SA0", "N3->NAND2_1.1/SA0", "N10/SA1"}


def test_equivalent_faults_have_identical_behavior(c17, result):
    sim = SerialFaultSimulator(c17)
    for rep, members in result.classes.items():
        assert len({sim.signature(m) for m in members}) == 1, rep.id


def test_c17_has_no_redundant_faults(c17, universe):
    sim = SerialFaultSimulator(c17)
    good = sim.signature(None)
    assert [f.id for f in universe if sim.signature(f) == good] == []


def test_inverter_chain_rules():
    c = Circuit("inv2")
    c.mark_pi("a")
    c.mark_po("y")
    c.add_gate("g1", GateType.NOT, "b", ["a"])
    c.add_gate("g2", GateType.NOT, "y", ["b"])
    res = collapse_equivalent(c, generate_stuck_at_faults(c))
    cls = {r.id: {m.id for m in ms} for r, ms in res.classes.items()}
    assert cls == {"y/SA0": {"y/SA0", "b/SA1", "a/SA0"},
                   "y/SA1": {"y/SA1", "b/SA0", "a/SA1"}}


def test_json_contract(c17, result):
    d = collapsed_to_dict(c17, result)
    assert d["collapsed"] is True and d["total"] == 22 and d["total_uncollapsed"] == 34
    assert all("class_size" in f and "equivalent_faults" in f for f in d["faults"])