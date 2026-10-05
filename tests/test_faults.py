import pytest

from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.parser import VerilogParser


@pytest.fixture(scope="module")
def faults():
    return generate_stuck_at_faults(VerilogParser().parse_file("benchmarks/c17.v"))


def test_c17_uncollapsed_counts(faults):
    assert len(faults) == 34                              # 17 lines x 2
    assert sum(not f.is_branch for f in faults) == 22     # 11 stems x 2
    assert sum(f.is_branch for f in faults) == 12         # 6 branches x 2


def test_ids_are_unique(faults):
    assert len({f.id for f in faults}) == len(faults)


def test_branch_faults_only_on_stems(faults):
    assert {f.net for f in faults if f.is_branch} == {"N3", "N11", "N16"}
    assert [f.id for f in faults if f.net == "N1"] == ["N1/SA0", "N1/SA1"]


def test_n3_branches_use_correct_pins(faults):
    # NAND2_1 (N10, N1, N3) -> N3 is input pin 1; NAND2_2 (N11, N3, N6) -> pin 0
    ids = {f.id for f in faults if f.net == "N3" and f.is_branch}
    assert ids == {"N3->NAND2_1.1/SA0", "N3->NAND2_1.1/SA1",
                   "N3->NAND2_2.0/SA0", "N3->NAND2_2.0/SA1"}


def test_fault_validation():
    with pytest.raises(ValueError):
        Fault("N1", 2)
    with pytest.raises(ValueError):
        Fault("N1", 0, gate="NAND2_1")