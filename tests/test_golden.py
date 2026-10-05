import shutil

import pytest

from vista.rtl.parser import VerilogParser
from vista.sim.golden import compare_with_golden
from vista.sim.simulator import LogicSimulator

pytestmark = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog missing")


def test_c17_matches_icarus_exhaustively():
    path = "benchmarks/c17.v"
    sim = LogicSimulator(VerilogParser().parse_file(path))
    checked, mismatches = compare_with_golden(sim, path)
    assert checked == 32
    assert mismatches == []