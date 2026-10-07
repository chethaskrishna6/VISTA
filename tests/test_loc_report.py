import json
from pathlib import Path

import jsonschema
import pytest

from vista.atpg.loc import generate_loc_tests
from vista.cli import main
from vista.patterns import PatternFileError, read_loc_vectors, write_patterns
from vista.rtl.bench import parse_bench
from vista.rtl.loc import LocModel
from vista.schema import schema_for, strict, validate

SEQ = "INPUT(a)\nOUTPUT(y)\nq = DFF(d)\nd = NAND(a, q)\ny = NOT(q)\n"
S27 = Path("benchmarks/s27.bench")


@pytest.fixture
def seq_file(tmp_path):
    f = tmp_path / "seq.bench"
    f.write_text(SEQ)
    return f


def seq():
    return parse_bench(SEQ, "seq", scan=True)


@pytest.mark.parametrize("hold", [True, False])
def test_report_is_valid_consistent_and_fully_declared(hold):
    doc = json.loads(json.dumps(generate_loc_tests(seq(), hold_pi=hold).to_dict()))
    assert validate(doc) == "loc_atpg_report" and doc["pi_mode"] == ("held" if hold else "free")
    jsonschema.Draft202012Validator(strict(schema_for("loc_atpg_report"))).validate(doc)


def test_matrix_loc_hand_derived(seq_file, tmp_path):
    pf, out = tmp_path / "v.txt", tmp_path / "m.json"
    pf.write_text("# pi_order: a q\n11\n")
    assert main(["matrix", str(seq_file), "--model", "loc", "--patterns", str(pf),
                 "--verify", "--json", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert validate(doc) == "transition_sim_report"
    assert doc["pairs"] == [{"index": 0, "v1": "11", "v2": "10"}]
    by = {f["id"]: f["detecting_pairs"] for f in doc["faults"]}
    assert by["y/STR"] == [0] and by["q/STF"] == [0] and by["y/STF"] == []


@pytest.mark.parametrize("free", [False, True])
def test_matrix_replays_the_atpg_report(seq_file, tmp_path, free):
    res = generate_loc_tests(seq(), hold_pi=not free)
    rj, out = tmp_path / "loc.json", tmp_path / "m.json"
    rj.write_text(json.dumps(res.to_dict()))
    args = ["matrix", str(seq_file), "--model", "loc", "--patterns", str(rj),
            "--verify", "--json", str(out)] + (["--free-pi"] if free else [])
    assert main(args) == 0
    assert json.loads(out.read_text())["summary"]["detected"] == len(res.covered_by)


def test_matrix_rejects_mode_mismatch(seq_file, tmp_path):
    rj = tmp_path / "loc.json"
    rj.write_text(json.dumps(generate_loc_tests(seq(), hold_pi=True).to_dict()))
    with pytest.raises(SystemExit, match="held"):
        main(["matrix", str(seq_file), "--model", "loc", "--patterns", str(rj), "--free-pi"])


def test_text_roundtrip_and_bad_header(tmp_path):
    model = LocModel(seq(), hold_pi=False)
    vectors = generate_loc_tests(seq(), hold_pi=False).vectors
    f = tmp_path / "v.txt"
    write_patterns(f, model.circuit, vectors, "stuck-at")      # header = expanded PI order
    assert read_loc_vectors(f, model) == vectors
    f.write_text("# pi_order: a\n1\n")
    with pytest.raises(PatternFileError, match="pi_order"):
        read_loc_vectors(f, model)


@pytest.mark.skipif(not S27.exists(), reason="s27 not present")
def test_s27_report_replays_through_matrix(tmp_path):
    rj, out = tmp_path / "loc.json", tmp_path / "m.json"
    assert main(["loc-atpg", str(S27), "--json", str(rj)]) == 0
    assert main(["matrix", str(S27), "--model", "loc", "--patterns", str(rj),
                 "--verify", "--json", str(out)]) == 0
    assert (json.loads(out.read_text())["summary"]["detected"]
            == json.loads(rj.read_text())["summary"]["detected"])