import pytest

from vista.atpg.dalgebra import D, DBAR
from vista.atpg.podem import PodemEngine, Status
from vista.faults.stuck_at import Fault
from vista.rtl.parser import VerilogParser


@pytest.fixture(scope="module")
def c17():
    return VerilogParser().parse_file("benchmarks/c17.v")


def test_unexcited_stem_fault_objective_and_backtrace(c17):
    e = PodemEngine(c17, Fault("N10", 1))
    v = e.imply({})
    assert e.objective(v) == (Status.CONTINUE, ("N10", 0))
    assert e.backtrace(v, "N10", 0) == ("N1", 1)       # NAND=0 needs inputs 1; first X input N1


def test_backtrace_two_levels(c17):
    e = PodemEngine(c17, Fault("N10", 1))
    v = e.imply({})
    # N22=0 needs N10=1 (first input), which needs N1=0
    assert e.backtrace(v, "N22", 0) == ("N1", 0)


def test_excited_fault_dfrontier_objective(c17):
    e = PodemEngine(c17, Fault("N10", 1))
    v = e.imply({"N1": 1, "N3": 1})
    assert v["N10"] == DBAR                            # good 0, faulty 1
    assert [g.name for g in e.d_frontier(v)] == ["NAND2_5"]
    assert e.objective(v) == (Status.CONTINUE, ("N16", 1))
    assert e.backtrace(v, "N16", 1) == ("N2", 0)


def test_detected_when_effect_reaches_po(c17):
    e = PodemEngine(c17, Fault("N10", 1))
    v = e.imply({"N1": 1, "N3": 1, "N2": 0})
    assert v["N22"] == D
    assert e.objective(v) == (Status.DETECTED, None)


def test_failed_when_site_cannot_be_excited(c17):
    e = PodemEngine(c17, Fault("N10", 1))
    v = e.imply({"N1": 0})                              # N10 = 1 in the good machine
    assert e.objective(v) == (Status.FAILED, None)


def test_branch_fault_effect_lives_on_the_pin(c17):
    e = PodemEngine(c17, Fault("N3", 0, "NAND2_1", 1))
    v0 = e.imply({})
    assert e.objective(v0) == (Status.CONTINUE, ("N3", 1))
    v = e.imply({"N3": 1})
    assert v["N3"] == (1, 1)                            # the net itself is fault-free
    assert e.pin_pair(v, c17.gates["NAND2_1"], 1) == D  # only that pin sees D
    assert [g.name for g in e.d_frontier(v)] == ["NAND2_1"]
    assert e.objective(v) == (Status.CONTINUE, ("N1", 1))