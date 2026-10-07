"""Pattern-set files: read test vectors in, write them out."""
from __future__ import annotations

import json
from pathlib import Path

from vista.rtl.model import Circuit
from vista.sim.logic import X, from_str, to_str

Pattern = dict[str, int]
Pair = tuple[Pattern, Pattern]
MODELS = ("stuck-at", "transition")


class PatternFileError(ValueError):
    """A pattern file is malformed or does not match the circuit."""


def _vec(bits: str, pis: list[str], where: str) -> Pattern:
    if len(bits) != len(pis):
        raise PatternFileError(f"{where}: expected {len(pis)} bits (one per PI), got {len(bits)}")
    try:
        return dict(zip(pis, from_str(bits)))
    except ValueError as e:
        raise PatternFileError(f"{where}: {e}") from None


def _encode(p: Pattern, pis: list[str]) -> str:
    return to_str([p.get(pi, X) for pi in pis])


def write_patterns(path: str | Path, circuit: Circuit, items: list, model: str) -> None:
    pis = circuit.primary_inputs
    lines = [f"# pi_order: {' '.join(pis)}"]
    for it in items:
        lines.append(_encode(it, pis) if model == "stuck-at"
                     else f"{_encode(it[0], pis)} {_encode(it[1], pis)}")
    Path(path).write_text("\n".join(lines) + "\n")


def read_patterns(path: str | Path, circuit: Circuit, model: str,
                  method: str | None = None) -> list:
    """Patterns (stuck-at) or (v1, v2) pairs (transition). `method` picks a method from a
    compaction_report (default: its last one)."""
    if model not in MODELS:
        raise ValueError(f"model must be one of {MODELS}")
    p = Path(path)
    if p.suffix.lower() == ".json":
        return _from_json(p, circuit, model, method)
    pis = circuit.primary_inputs
    items: list = []
    for n, raw in enumerate(p.read_text().splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            body = line[1:].strip()
            if body.lower().startswith("pi_order:"):
                declared = body.split(":", 1)[1].split()
                if declared != pis:
                    raise PatternFileError(
                        f"{p.name}: pi_order header {declared} does not match the circuit's {pis}")
            continue
        parts = line.split("#", 1)[0].split()
        if not parts:
            continue
        where = f"{p.name} line {n}"
        want = 1 if model == "stuck-at" else 2
        if len(parts) != want:
            raise PatternFileError(f"{where}: expected {want} bit string(s), got {len(parts)}")
        items.append(_vec(parts[0], pis, where) if model == "stuck-at"
                     else (_vec(parts[0], pis, where), _vec(parts[1], pis, where)))
    return items


def _from_json(p: Path, circuit: Circuit, model: str, method: str | None) -> list:
    doc = json.loads(p.read_text())
    kind = doc.get("document") if isinstance(doc, dict) else None
    pis = circuit.primary_inputs
    if doc.get("pi_order") != pis:
        raise PatternFileError(f"{p.name}: pi_order {doc.get('pi_order')} does not match the circuit's {pis}")
    where = p.name
    if kind == "compaction_report":
        if doc["fault_model"].replace("_", "-") != model:
            raise PatternFileError(f"{where}: report is for {doc['fault_model']}, not {model}")
        methods = doc["methods"]
        if method is not None:
            methods = [m for m in methods if m["name"] == method]
            if not methods:
                raise PatternFileError(f"{where}: no method named {method!r}")
        rows = methods[-1]["items"]
    elif kind in ("atpg_report", "fault_sim_report") and model == "stuck-at":
        rows = doc["patterns"]
    elif kind in ("transition_atpg_report", "transition_sim_report") and model == "transition":
        rows = doc["pairs"]
    else:
        raise PatternFileError(f"{where}: a {kind!r} document has no {model} patterns")
    if model == "stuck-at":
        return [_vec(r["bits"], pis, f"{where} item {i}") for i, r in enumerate(rows)]
    return [(_vec(r["v1"], pis, f"{where} item {i}"), _vec(r["v2"], pis, f"{where} item {i}"))
            for i, r in enumerate(rows)]