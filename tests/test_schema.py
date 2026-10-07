import copy
import json
from pathlib import Path

import jsonschema
import pytest
from vista.atpg.compact import evaluate, prepare_stuck_at, prepare_transition, report_from_results
from vista.atpg.merge import report_from_merge, run_transition as merge_transition
from vista.atpg.generate import generate_test_set
from vista.atpg.hybrid import run_hybrid
from vista.atpg.transition_atpg import generate_transition_tests
from vista.faults.collapse import collapse_equivalent, collapsed_to_dict
from vista.faults.stuck_at import generate_stuck_at_faults, universe_to_dict
from vista.faults.transition import generate_transition_faults
from vista.rtl.bench import parse_bench
from vista.rtl.loader import load_circuit
from vista.schema import SCHEMA_VERSION, SCHEMAS, SchemaError, schema_for, strict, validate
from vista.sim.pattern_sim import exhaustive_patterns, run_fault_simulation
from vista.sim.transition_sim import run_transition_simulation

ABSORB = "INPUT(a)\nINPUT(b)\nOUTPUT(y)\nn = AND(a, b)\ny = OR(a, n)\n"
ALWAYS_ONE = "INPUT(a)\nOUTPUT(y)\nn = NOT(a)\ny = OR(a, n)\n"


def documents() -> dict[str, dict]:
    c = load_circuit("benchmarks/c17.bench")
    faults = generate_stuck_at_faults(c)
    col = collapse_equivalent(c, faults)
    reps = col.representatives
    w = {r: len(m) for r, m in col.classes.items()}
    pats = exhaustive_patterns(c)
    absorb = parse_bench(ABSORB, "absorb")
    pairs = [(pats[i], pats[(i * 7 + 3) % 32]) for i in range(32)]
    sa_items, sa_det, sa_verify = prepare_stuck_at(c)
    td_items, td_det, td_verify = prepare_transition(c)
    return {
        "circuit": c.to_dict(),
        "fault_list/uncollapsed": universe_to_dict(c, faults),
        "fault_list/collapsed": collapsed_to_dict(c, col),
        "fault_sim_report/drop": run_fault_simulation(c, reps, pats, w).to_dict(),
        "fault_sim_report/matrix": run_fault_simulation(c, reps, pats, w, drop=False).to_dict(),
        "atpg_report/podem": generate_test_set(c, reps, w).to_dict(),
        "atpg_report/hybrid": run_hybrid(absorb, generate_stuck_at_faults(absorb),
                                         backtrack_limit=0).to_dict(),
        "transition_sim_report": run_transition_simulation(
            c, generate_transition_faults(c), pairs).to_dict(),
        "transition_atpg_report/c17": generate_transition_tests(c).to_dict(),
        "transition_atpg_report/untestable": generate_transition_tests(
            parse_bench(ALWAYS_ONE, "one")).to_dict(),
        "compaction_report/compact_sa": report_from_results(
            c, "stuck-at", sa_items, sa_det, evaluate(len(sa_items), sa_det, sa_verify)),
        "compaction_report/compact_tdf": report_from_results(
            c, "transition", td_items, td_det, evaluate(len(td_items), td_det, td_verify)),
        "compaction_report/merge_tdf": report_from_merge(c, merge_transition(c)),
    }


DOCS = documents()


def mutate(label, fn):
    doc = copy.deepcopy(DOCS[label])
    fn(doc)
    return doc


def strict_validate(name, doc):
    jsonschema.Draft202012Validator(strict(schema_for(name))).validate(doc)


@pytest.mark.parametrize("label", DOCS)
def test_document_is_valid_consistent_and_fully_declared(label):
    name = label.split("/")[0]
    doc = json.loads(json.dumps(DOCS[label]))              # must survive a real JSON round trip
    assert doc["document"] == name and doc["schema_version"] == SCHEMA_VERSION
    assert validate(doc) == name                           # consumer schema + consistency checks
    strict_validate(name, doc)                             # producer emits nothing undeclared


def test_every_document_type_is_exercised():
    assert {label.split("/")[0] for label in DOCS} == set(SCHEMAS)


def test_the_variants_really_exercise_the_interesting_paths():
    assert any(f["status"] == "redundant" for f in DOCS["atpg_report/hybrid"]["faults"])
    assert "sat_patterns" in DOCS["atpg_report/hybrid"]["summary"]
    reasons = DOCS["transition_atpg_report/untestable"]["summary"]["untestable_reasons"]
    assert "cannot initialize" in reasons and "stuck-at redundant" in reasons
    assert DOCS["fault_list/collapsed"]["collapsed"] is True


def test_schemas_are_valid_json_schema():
    for name in SCHEMAS:
        jsonschema.Draft202012Validator.check_schema(schema_for(name))
        jsonschema.Draft202012Validator.check_schema(strict(schema_for(name)))


def test_exported_schema_files_are_current():
    for name in SCHEMAS:
        path = Path("docs/schemas") / f"{name}.schema.json"
        assert path.exists(), "run: vista schema export"
        assert json.loads(path.read_text()) == json.loads(json.dumps(schema_for(name))), name


def test_missing_required_key_rejected():
    with pytest.raises(SchemaError, match="patterns"):
        validate(mutate("atpg_report/podem", lambda d: d["summary"].pop("patterns")))


def test_wrong_type_rejected():
    with pytest.raises(SchemaError, match="not of type"):
        validate(mutate("circuit", lambda d: d["nets"][0].update(level="zero")))


def test_unknown_major_version_rejected():
    with pytest.raises(SchemaError, match="schema_version"):
        validate(mutate("circuit", lambda d: d.update(schema_version="2.0")))


def test_unknown_document_rejected():
    with pytest.raises(SchemaError, match="unknown document"):
        validate({"document": "nope"})
    with pytest.raises(SchemaError):
        validate([1, 2])


def test_minor_additions_pass_consumers_but_fail_the_strict_producer_check():
    doc = mutate("atpg_report/podem", lambda d: (
        d.update(schema_version="1.7", extra={"x": 1}), d["faults"][0].update(new_field=1)))
    assert validate(doc) == "atpg_report"                  # consumers ignore unknown fields
    with pytest.raises(jsonschema.ValidationError):
        strict_validate("atpg_report", doc)                # producers must declare them


FLIP = str.maketrans("01", "10")


@pytest.mark.parametrize("label,edit,needle", [
    ("atpg_report/podem", lambda d: d["summary"].update(detected=d["summary"]["detected"] + 1),
     "summary.detected"),
    ("fault_sim_report/matrix", lambda d: d["coverage_curve"].reverse(), "coverage_curve"),
    ("circuit", lambda d: next(n for n in d["nets"] if n["driver"]).update(level=99), "level"),
    ("fault_list/collapsed", lambda d: d["faults"][0].update(class_size=99), "class_size"),
    ("transition_atpg_report/c17",
     lambda d: d["pairs"][0].update(v1=d["pairs"][0]["v1"].translate(FLIP)), "not a fill"),
    ("compaction_report/compact_sa",
     lambda d: d["methods"][0].update(count=d["methods"][0]["count"] + 1), "count"),
    ("compaction_report/merge_tdf",
     lambda d: d["methods"][0].update(origin=[0]), "origin"),
])
def test_consistency_checks_catch_structurally_valid_lies(label, edit, needle):
    with pytest.raises(SchemaError, match=needle):
        validate(mutate(label, edit))