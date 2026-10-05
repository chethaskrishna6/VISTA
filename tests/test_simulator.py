import pytest

from vista.rtl.parser import VerilogParser
from vista.sim.logic import to_str
from vista.sim.simulator import LogicSimulator


@pytest.fixture(scope="module")
def sim():
    return LogicSimulator(VerilogParser().parse_file("benchmarks/c17.v"))


def run(sim, bits):
    return to_str(sim.outputs(sim.pattern_from_string(bits)).values())  # order: N22, N23


# PI order: N1 N2 N3 N6 N7  ->  PO order: N22 N23
def test_all_zeros(sim):
    assert run(sim, "00000") == "00"

def test_all_ones(sim):
    assert run(sim, "11111") == "10"

def test_n2_high_others_low(sim):
    assert run(sim, "01000") == "11"

def test_x_masked_by_controlling_value(sim):
    # N3=0 forces N10=1 even though N1=X; N6=0 forces N11=1.
    assert run(sim, "X1000") == "11"

def test_all_x_gives_x(sim):
    assert run(sim, "XXXXX") == "XX"

def test_rejects_bad_input(sim):
    with pytest.raises(ValueError):
        sim.simulate({"nope": 1})
    with pytest.raises(ValueError):
        sim.pattern_from_string("0101")