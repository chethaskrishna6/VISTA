import json
import random
from pathlib import Path

import pytest

from vista.atpg.generate import generate_test_set
from vista.cli import main
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.faults.transition import generate_transition_faults
from vista.patterns import PatternFileError, read_patterns, write_patterns
from vista.rtl.loader import load_circuit
from vista.schema import validate
from vista.sim.logic import X
from vista.sim.parallel_sim import run_packed_transition_simulation
from vista.sim.pattern_sim import exhaustive_patterns
from vista.sim.transition_sim import run_transition_simulation


@pytest.fixture(scope="module")
def c17():
    return load_circuit("benchmarks/c17.bench")


def mixed_pairs(c, n, seed, with_x=True):
    rng = random.Random(seed)
    vals = (0, 1, X) if with_x else (0, 1)
    mk = lambda: {pi: rng.choice(vals) for pi in c.primary_inputs}
    return [(mk(), mk()) for _ in range(n)]


def test_text_roundtrip_with_x(c17, tmp_path):
    f = tmp_path / "p.txt"
    items = [{pi: v for pi, v in zip(c17.primary_inputs, vals)} for vals in ([0, 1, X, 1, 0], [1, 1, 1, 1, 1])]
    write_patterns(f, c17, items, "stuck-at")
    assert read_patterns(f, c17, "stuck-at") == items
    pairs = [(items[0], items[1])]
    write_patterns(f, c17, pairs, "transition")
    assert read_patterns(f, c17, "transition") == pairs


@pytest.mark.parametrize("text,needle", [
    ("# pi_order: a b c\n00100\n", "pi_order"),
    ("0010\n", "expected 5 bits"),
    ("00Z00\n", "invalid logic"),
    ("00100 00100\n", "expected 1"),
])
def test_bad_pattern_files(c17, tmp_path, text, needle):
    f = tmp_path / "bad.txt"
    f.write_text(text)
    with pytest.raises(PatternFileError, match=needle):
        read_patterns(f, c17, "stuck-at")


def test_comments_and_blank_lines(c17, tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("# pi_order: 1 2 3 6 7\n\n00100  # first\n  10100\n")
    assert len(read_patterns(f, c17, "stuck-at")) == 2


def test_read_patterns_from_atpg_report_json(c17, tmp_path):
    faults = collapse_equivalent(c17, generate_stuck_at_faults(c17)).representatives
    res = generate_test_set(c17, faults)
    f = tmp_path / "atpg.json"
    f.write_text(json.dumps(res.to_dict()))
    assert read_patterns(f, c17, "stuck-at") == res.patterns
    with pytest.raises(PatternFileError, match="no transition"):
        read_patterns(f, c17, "transition")


def test_matrix_cli_stuck_at_hand_derived(c17, tmp_path, capsys):
    pf, out = tmp_path / "p.txt", tmp_path / "m.json"
    pf.write_text("00100\n10100\n")
    assert main(["matrix", "benchmarks/c17.bench", "--patterns", str(pf), "--uncollapsed",
                 "--verify", "--json", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert validate(doc) == "fault_sim_report" and doc["fault_dropping"] is False
    assert next(f for f in doc["faults"] if f["id"] == "10/SA0")["detecting_patterns"] == [0]
    assert "AGREES" in capsys.readouterr().out


def test_matrix_cli_transition_hand_derived(c17, tmp_path):
    pf, out = tmp_path / "p.txt", tmp_path / "m.json"
    pf.write_text("10100 00100\n")
    assert main(["matrix", "benchmarks/c17.bench", "--model", "transition", "--patterns", str(pf),
                 "--verify", "--json", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert validate(doc) == "transition_sim_report"
    assert next(f for f in doc["faults"] if f["id"] == "10/STR")["detecting_pairs"] == [0]


def test_matrix_of_exhaustive_set_is_complete(c17, tmp_path, capsys):
    pf = tmp_path / "all.txt"
    write_patterns(pf, c17, exhaustive_patterns(c17), "stuck-at")
    assert main(["matrix", "benchmarks/c17.bench", "--patterns", str(pf)]) == 0
    assert "22/22" in capsys.readouterr().out


@pytest.mark.parametrize("path,n", [("benchmarks/c17.bench", 80), ("benchmarks/c432.bench", 70)])
@pytest.mark.parametrize("drop", [True, False])
@pytest.mark.parametrize("block", [1, 3, 64])
def test_packed_transition_equals_serial(path, n, drop, block):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    c = load_circuit(path)
    fl = generate_transition_faults(c)
    pairs = mixed_pairs(c, n, seed=6, with_x=path.endswith("c17.bench"))
    a = run_packed_transition_simulation(c, fl, pairs, drop=drop, block=block)
    b = run_transition_simulation(c, fl, pairs, drop=drop)
    assert a.detections == b.detections


def test_packed_transition_block_validation(c17):
    with pytest.raises(ValueError):
        run_packed_transition_simulation(c17, [], [], block=0)