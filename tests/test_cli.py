import json

import pytest

from vista.cli import COMMANDS, main
from vista.schema import SCHEMAS

CASES = {
    "atpg": (["atpg", "benchmarks/c17.bench"], "atpg_report"),
    "atpg-hybrid": (["atpg", "benchmarks/c17.bench", "--hybrid"], "atpg_report"),
    "tdf-atpg": (["tdf-atpg", "benchmarks/c17.bench"], "transition_atpg_report"),
    "fsim": (["fsim", "benchmarks/c17.bench", "--exhaustive", "--no-drop"], "fault_sim_report"),
    "tdf-sim": (["tdf-sim", "benchmarks/c17.bench", "--count", "30"], "transition_sim_report"),
}


def test_help_version_and_unknown_command(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in COMMANDS)
    assert main(["--version"]) == 0
    assert "schema" in capsys.readouterr().out
    assert main(["bogus"]) == 2
    assert "unknown command" in capsys.readouterr().err


@pytest.mark.parametrize("label", CASES)
def test_cli_json_output_validates(label, tmp_path, capsys):
    args, doc_name = CASES[label]
    out = tmp_path / "out.json"
    assert main([*args, "--json", str(out)]) == 0
    assert json.loads(out.read_text())["document"] == doc_name
    capsys.readouterr()
    assert main(["schema", "validate", str(out)]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_reports_failure(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"document": "circuit"}')
    assert main(["schema", "validate", str(bad)]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert main(["schema", "validate", str(tmp_path / "missing.json")]) == 1


def test_schema_export(tmp_path):
    assert main(["schema", "export", str(tmp_path)]) == 0
    assert {p.stem for p in tmp_path.glob("*.json")} == {f"{n}.schema" for n in SCHEMAS}