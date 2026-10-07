"""Frozen JSON contract (major version 1) between the core EDA engines and their consumers.

Policy (details in docs/SCHEMA.md): producers stamp SCHEMA_VERSION; consumers accept any 1.x and ignore
unknown fields. Adding a field -> bump the minor number. Removing, renaming or changing the meaning of a
field -> bump the major number. This module imports nothing from the rest of vista (no cycles).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

SCHEMA_VERSION = "1.0"
MAJOR = SCHEMA_VERSION.split(".")[0]
DRAFT = "https://json-schema.org/draft/2020-12/schema"

_STR = {"type": "string"}
_INT = {"type": "integer", "minimum": 0}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}
_OPT_INT = {"type": ["integer", "null"], "minimum": 0}
_OPT_STR = {"type": ["string", "null"]}
_BITS = {"type": "string", "pattern": "^[01X]*$"}       # one char per PI in pi_order; X = don't-care
_STR_LIST = {"type": "array", "items": _STR}
_INT_LIST = {"type": "array", "items": _INT}
_STUCK_AT = {"const": "stuck_at"}
_TRANSITION = {"const": "transition"}
_GATE_TYPES = ["and", "nand", "or", "nor", "xor", "xnor", "not", "buf"]


def _obj(required: dict, optional: dict | None = None) -> dict:
    return {"type": "object", "properties": {**required, **(optional or {})},
            "required": list(required)}


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


def _doc(name: str, required: dict, optional: dict | None = None) -> dict:
    head = {"schema_version": {"type": "string", "pattern": rf"^{MAJOR}\.\d+$"},
            "document": {"const": name}, "circuit": _STR}
    return _obj({**head, **required}, optional)


_FAULT_BASE = {"id": _STR, "net": _STR, "stuck_at": {"enum": [0, 1]},
               "kind": {"enum": ["stem", "branch"]}, "gate": _OPT_STR, "pin": _OPT_INT}
_FAULT_ITEM = _obj(_FAULT_BASE, {"class_size": _INT, "equivalent_faults": _STR_LIST})
_CLASS_ITEM = _obj({**_FAULT_BASE, "class_size": _INT, "equivalent_faults": _STR_LIST})

_FAULT_LIST = _doc(
    "fault_list",
    {"fault_model": _STUCK_AT, "collapsed": _BOOL, "total": _INT, "faults": _arr(_FAULT_ITEM)},
    {"collapse_method": _STR, "total_uncollapsed": _INT})
_FAULT_LIST["if"] = {"properties": {"collapsed": {"const": True}}}
_FAULT_LIST["then"] = {"required": ["collapse_method", "total_uncollapsed"],
                       "properties": {"faults": _arr(_CLASS_ITEM)}}

SCHEMAS: dict[str, dict] = {
    "circuit": _doc("circuit", {
        "primary_inputs": _STR_LIST, "primary_outputs": _STR_LIST,
        "nets": _arr(_obj({"name": _STR, "level": _INT, "driver": _OPT_STR,
                           "fanout": _STR_LIST, "is_stem": _BOOL})),
        "gates": _arr(_obj({"name": _STR, "type": {"enum": _GATE_TYPES},
                            "output": _STR, "inputs": _STR_LIST}))}),
    "fault_list": _FAULT_LIST,
    "fault_sim_report": _doc("fault_sim_report", {
        "fault_model": _STUCK_AT, "fault_dropping": _BOOL,
        "pi_order": _STR_LIST, "po_order": _STR_LIST,
        "summary": _obj({"total_faults": _INT, "detected": _INT, "undetected": _INT,
                         "coverage_pct": _NUM, "weighted_total": _INT, "weighted_detected": _INT,
                         "weighted_coverage_pct": _NUM}),
        "patterns": _arr(_obj({"index": _INT, "bits": _BITS, "new_detections": _STR_LIST})),
        "coverage_curve": _INT_LIST,
        "faults": _arr(_obj({"id": _STR, "class_size": _INT, "detected": _BOOL,
                             "first_detect": _OPT_INT, "detecting_patterns": _INT_LIST}))}),
    "atpg_report": _doc("atpg_report", {
        "fault_model": _STUCK_AT, "algorithm": _STR, "pi_order": _STR_LIST,
        "summary": _obj({"total_faults": _INT, "detected": _INT, "redundant": _INT, "aborted": _INT,
                         "patterns": _INT, "weighted_coverage_pct": _NUM,
                         "weighted_efficiency_pct": _NUM}, {"sat_patterns": _INT}),
        "patterns": _arr(_obj({"index": _INT, "bits": _BITS, "cube": _BITS})),
        "faults": _arr(_obj({"id": _STR, "class_size": _INT,
                             "status": {"enum": ["detected", "redundant", "aborted"]},
                             "pattern": _OPT_INT, "backtracks": _INT}))}),
    "transition_sim_report": _doc("transition_sim_report", {
        "fault_model": _TRANSITION, "fault_dropping": _BOOL, "pi_order": _STR_LIST,
        "summary": _obj({"total_faults": _INT, "detected": _INT, "undetected": _INT,
                         "coverage_pct": _NUM}),
        "pairs": _arr(_obj({"index": _INT, "v1": _BITS, "v2": _BITS})),
        "coverage_curve": _INT_LIST,
        "faults": _arr(_obj({"id": _STR, "detected": _BOOL, "first_detect": _OPT_INT,
                             "detecting_pairs": _INT_LIST}))}),
    "transition_atpg_report": _doc("transition_atpg_report", {
        "fault_model": _TRANSITION, "algorithm": _STR, "pi_order": _STR_LIST,
        "summary": _obj({"total_faults": _INT, "detected": _INT, "untestable": _INT, "pairs": _INT,
                         "untestable_reasons": {"type": "object", "additionalProperties": _INT},
                         "coverage_pct": _NUM, "efficiency_pct": _NUM}),
        "pairs": _arr(_obj({"index": _INT, "v1": _BITS, "v2": _BITS,
                            "cube1": _BITS, "cube2": _BITS})),
        "faults": _arr(_obj({"id": _STR, "status": {"enum": ["detected", "untestable"]},
                             "pair": _OPT_INT, "reason": _OPT_STR}))}),
}


def schema_for(name: str) -> dict:
    return {"$schema": DRAFT, "title": f"VISTA {name} (schema {MAJOR}.x)", **SCHEMAS[name]}


def strict(schema):
    """Copy of `schema` that also rejects undeclared keys. Tests use it so additions are deliberate."""
    if isinstance(schema, dict):
        out = {k: strict(v) for k, v in schema.items()}
        if out.get("type") == "object" and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [strict(v) for v in schema]
    return schema


class SchemaError(ValueError):
    """A document violates the VISTA JSON contract."""


def _pct(num: float, den: float) -> float:
    return 100.0 * num / den if den else 100.0


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.01                 # producers round to 2 decimals


def _consistency(doc: dict) -> list[str]:
    """Cross-field invariants a structural schema cannot express. Assumes the structure is valid."""
    bad: list[str] = []

    def need(ok: bool, msg: str) -> None:
        if not ok:
            bad.append(msg)

    kind, fs = doc["document"], doc.get("faults", [])
    if kind == "circuit":
        nets = {n["name"]: n for n in doc["nets"]}
        need(len(nets) == len(doc["nets"]), "duplicate net names")
        need(set(doc["primary_inputs"]) <= set(nets) and set(doc["primary_outputs"]) <= set(nets),
             "a primary input/output is not a net")
        for g in doc["gates"]:
            if g["output"] in nets and all(i in nets for i in g["inputs"]):
                need(nets[g["output"]]["driver"] == g["name"],
                     f"net {g['output']} driver is not gate {g['name']}")
                need(nets[g["output"]]["level"] == 1 + max(nets[i]["level"] for i in g["inputs"]),
                     f"level of net {g['output']} is inconsistent with its driver gate")
            else:
                need(False, f"gate {g['name']} references an unknown net")
    elif kind == "fault_list":
        need(doc["total"] == len(fs), "total != len(faults)")
        need(len({f["id"] for f in fs}) == len(fs), "duplicate fault ids")
        need(all((f["kind"] == "branch") == (f["gate"] is not None and f["pin"] is not None)
                 for f in fs), "branch/stem fields (gate, pin) are inconsistent")
        if doc["collapsed"]:
            need(all(f["class_size"] == 1 + len(f["equivalent_faults"]) for f in fs),
                 "class_size != 1 + len(equivalent_faults)")
            need(sum(f["class_size"] for f in fs) == doc["total_uncollapsed"],
                 "class sizes do not sum to total_uncollapsed")
    elif kind in ("fault_sim_report", "transition_sim_report"):
        stuck = kind == "fault_sim_report"
        items, hits = ("patterns", "detecting_patterns") if stuck else ("pairs", "detecting_pairs")
        n, s = len(doc[items]), doc["summary"]
        det = [f for f in fs if f["detected"]]
        need(s["total_faults"] == len(fs), "summary.total_faults disagrees with the fault list")
        need(s["detected"] == len(det) and s["undetected"] == len(fs) - len(det),
             "summary.detected/undetected disagree with the fault list")
        need(_close(s["coverage_pct"], _pct(len(det), len(fs))), "summary.coverage_pct disagrees")
        need([it["index"] for it in doc[items]] == list(range(n)), f"{items} indices are not 0..n-1")
        curve = doc["coverage_curve"]
        need(len(curve) == n, f"coverage_curve length != number of {items}")
        need(curve == sorted(curve), "coverage_curve is not non-decreasing")
        need(not curve or curve[-1] == len(det), "coverage_curve does not end at summary.detected")
        for f in fs:
            h = f[hits]
            need(f["detected"] == bool(h) and f["first_detect"] == (min(h) if h else None)
                 and all(0 <= i < n for i in h), f"fault {f['id']}: detection fields are inconsistent")
        width = len(doc["pi_order"])
        need(all(len(it[k]) == width for it in doc[items] for k in (("bits",) if stuck else ("v1", "v2"))),
             f"a {items} entry is not len(pi_order) wide")
        if stuck:
            wt, wd = sum(f["class_size"] for f in fs), sum(f["class_size"] for f in det)
            need(s["weighted_total"] == wt and s["weighted_detected"] == wd,
                 "summary.weighted_* disagree with class sizes")
            need(_close(s["weighted_coverage_pct"], _pct(wd, wt)), "summary.weighted_coverage_pct disagrees")
            first: dict[int, set] = {}
            for f in det:
                first.setdefault(f["first_detect"], set()).add(f["id"])
            need(all(set(p["new_detections"]) == first.get(p["index"], set()) for p in doc["patterns"]),
                 "new_detections disagree with first_detect")
    elif kind == "atpg_report":
        s, ps = doc["summary"], doc["patterns"]
        n, width = len(ps), len(doc["pi_order"])
        by = lambda name: [f for f in fs if f["status"] == name]
        need(s["total_faults"] == len(fs), "summary.total_faults disagrees with the fault list")
        need(s["detected"] == len(by("detected")), "summary.detected disagrees with fault statuses")
        need(s["redundant"] == len(by("redundant")), "summary.redundant disagrees with fault statuses")
        need(s["aborted"] >= len(by("aborted")), "summary.aborted is below the number of aborted faults")
        need(s["patterns"] == n and [p["index"] for p in ps] == list(range(n)), "pattern count/indices")
        need(all(len(p["bits"]) == width and len(p["cube"]) == width for p in ps),
             "a pattern is not len(pi_order) wide")
        need(all(c in ("X", b) for p in ps for b, c in zip(p["bits"], p["cube"])),
             "a pattern is not a fill of its cube")
        need(all((f["status"] == "detected") == (f["pattern"] is not None)
                 and (f["pattern"] is None or f["pattern"] < n) for f in fs),
             "fault -> pattern links are inconsistent")
        wt = sum(f["class_size"] for f in fs)
        wd = sum(f["class_size"] for f in by("detected"))
        wr = sum(f["class_size"] for f in by("redundant"))
        need(_close(s["weighted_coverage_pct"], _pct(wd, wt)), "summary.weighted_coverage_pct disagrees")
        need(_close(s["weighted_efficiency_pct"], _pct(wd + wr, wt)),
             "summary.weighted_efficiency_pct disagrees")
    elif kind == "transition_atpg_report":
        s, ps = doc["summary"], doc["pairs"]
        n, width = len(ps), len(doc["pi_order"])
        det = [f for f in fs if f["status"] == "detected"]
        unt = [f for f in fs if f["status"] == "untestable"]
        need(s["total_faults"] == len(fs), "summary.total_faults disagrees with the fault list")
        need(s["detected"] == len(det) and s["untestable"] == len(unt),
             "summary.detected/untestable disagree with fault statuses")
        need(s["untestable_reasons"] == dict(Counter(f["reason"] for f in unt)),
             "untestable_reasons disagree with fault reasons")
        need(s["pairs"] == n and [p["index"] for p in ps] == list(range(n)), "pair count/indices")
        need(all((f["status"] == "detected") == (f["pair"] is not None)
                 and (f["pair"] is None or f["pair"] < n) for f in fs), "fault -> pair links are inconsistent")
        need(all((f["status"] == "untestable") == (f["reason"] is not None) for f in fs),
             "untestable faults must (only) carry a reason")
        need(all(len(p[k]) == width for p in ps for k in ("v1", "v2", "cube1", "cube2")),
             "a pair entry is not len(pi_order) wide")
        need(all(c in ("X", b) for p in ps for v, cu in (("v1", "cube1"), ("v2", "cube2"))
                 for b, c in zip(p[v], p[cu])), "a pair vector is not a fill of its cube")
        need(_close(s["coverage_pct"], _pct(len(det), len(fs))), "summary.coverage_pct disagrees")
        need(_close(s["efficiency_pct"], _pct(len(det) + len(unt), len(fs))),
             "summary.efficiency_pct disagrees")
    return bad


def validate(doc, document: str | None = None, semantic: bool = True) -> str:
    """Validate against the lenient (consumer) schema, then the consistency checks. Returns the name."""
    import jsonschema                      # deferred: only validation needs it

    name = document or (doc.get("document") if isinstance(doc, dict) else None)
    if not isinstance(name, str) or name not in SCHEMAS:
        raise SchemaError(f"unknown document type {name!r}; known: {sorted(SCHEMAS)}")
    errors = sorted(jsonschema.Draft202012Validator(schema_for(name)).iter_errors(doc),
                    key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        lines = [f"  - /{'/'.join(map(str, e.absolute_path))}: {e.message[:160]}" for e in errors[:10]]
        raise SchemaError(f"{name}: {len(errors)} schema problem(s)\n" + "\n".join(lines))
    if semantic:
        bad = _consistency(doc)
        if bad:
            raise SchemaError(f"{name}: {len(bad)} consistency problem(s)\n"
                              + "\n".join(f"  - {m}" for m in bad[:10]))
    return name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vista schema", description="VISTA JSON contract tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write the JSON Schema files")
    ex.add_argument("outdir", nargs="?", default="docs/schemas")
    va = sub.add_parser("validate", help="validate VISTA JSON documents")
    va.add_argument("files", nargs="+")
    va.add_argument("--structure-only", action="store_true", help="skip the consistency checks")
    args = ap.parse_args(argv)

    if args.cmd == "export":
        out = Path(args.outdir)
        out.mkdir(parents=True, exist_ok=True)
        for name in SCHEMAS:
            (out / f"{name}.schema.json").write_text(json.dumps(schema_for(name), indent=2) + "\n")
        print(f"wrote {len(SCHEMAS)} schemas to {out}/ (version {SCHEMA_VERSION})")
        return 0
    rc = 0
    for f in args.files:
        try:
            doc = json.loads(Path(f).read_text())
            name = validate(doc, semantic=not args.structure_only)
            print(f"OK    {f}  ({name}, schema_version {doc['schema_version']})")
        except (SchemaError, OSError, json.JSONDecodeError) as e:
            print(f"FAIL  {f}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())