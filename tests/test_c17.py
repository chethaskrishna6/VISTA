from vista.rtl.parser import VerilogParser

C17 = "benchmarks/c17.v"


def test_c17_structure():
    c = VerilogParser().parse_file(C17)
    assert sorted(c.primary_inputs) == ["N1", "N2", "N3", "N6", "N7"]
    assert sorted(c.primary_outputs) == ["N22", "N23"]
    assert len(c.gates) == 6
    assert all(g.type.value == "nand" for g in c.gates.values())


def test_c17_gate_pin_order():
    c = VerilogParser().parse_file(C17)
    g = c.gates["NAND2_1"]
    assert g.output == "N10" and g.inputs == ["N1", "N3"]


def test_c17_stems_and_levels():
    c = VerilogParser().parse_file(C17)
    assert sorted(c.stems) == ["N11", "N16", "N3"]
    lvl = c.levelize()
    assert lvl["N10"] == 1 and lvl["N11"] == 1
    assert lvl["N16"] == 2 and lvl["N19"] == 2
    assert lvl["N22"] == 3 and lvl["N23"] == 3