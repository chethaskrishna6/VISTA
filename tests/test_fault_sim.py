import pytest

from vista.faults.stuck_at import Fault
from vista.rtl.parser import VerilogParser
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import X, to_str
from vista.sim.simulator import LogicSimulator


@pytest.fixture(scope="module")
def c17():
    return VerilogParser().parse_file("benchmarks/c17.v")


@pytest.fixture(scope="module")
def fsim(c17):
    return SerialFaultSimulator(c17)


def pat(sim, bits):
    return dict(zip(sim._pis, [int(b) for b in bits]))      # PI order N1 N2 N3 N6 N7


def out(sim, bits, fault=None):
    return to_str(sim.outputs(pat(sim, bits), fault).values())   # order N22 N23


def test_no_fault_matches_good_simulator(c17, fsim):
    good = LogicSimulator(c17)
    for p in fsim.exhaustive_patterns():
        assert fsim.outputs(p) == good.outputs(p)


def test_stem_vs_branch_differ(fsim):
    stem = Fault("N11", 1)
    branch = Fault("N11", 1, "NAND2_3", 1)
    assert out(fsim, "00111") == "00"
    assert out(fsim, "00111", stem) == "01"      # stem: both consumers see 1
    assert out(fsim, "00111", branch) == "00"    # branch: only NAND2_3 sees 1


def test_po_fault_detected_at_that_output_only(fsim):
    assert fsim.detected_outputs(pat(fsim, "11111"), Fault("N22", 0)) == ["N22"]


def test_pi_stem_fault(fsim):
    # 11111: good 10. N6 stuck-at-0 -> N11=1, N16=0, N19=0 -> outputs 11
    assert out(fsim, "11111", Fault("N6", 0)) == "11"
    assert fsim.detected_outputs(pat(fsim, "11111"), Fault("N6", 0)) == ["N23"]


def test_x_is_not_detection(fsim):
    assert not fsim.detects({pi: X for pi in fsim._pis}, Fault("N22", 0))


def test_rejects_bad_faults(fsim):
    with pytest.raises(ValueError):
        fsim.simulate({}, Fault("nope", 0))
    with pytest.raises(ValueError):
        fsim.simulate({}, Fault("N3", 0, "NAND2_1", 0))      # N3 is pin 1, not 0