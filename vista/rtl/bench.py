"""Engine 1: ISCAS .bench netlist -> Circuit (combinational gates only)."""
from __future__ import annotations

import re

from vista.rtl.model import Circuit, CircuitError, GateType

_IO = re.compile(r"^(INPUT|OUTPUT)\s*\(\s*([^\s()]+)\s*\)$", re.I)
_GATE = re.compile(r"^([^\s=()]+)\s*=\s*([A-Za-z]+)\s*\(\s*([^()]*?)\s*\)$")
_TYPES = {t.name: t for t in GateType} | {"BUFF": GateType.BUF}


def parse_bench(text: str, name: str = "bench") -> Circuit:
    inputs: list[str] = []
    outputs: list[str] = []
    gates: list[tuple[int, str, GateType, list[str]]] = []

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _IO.match(line)
        if m:
            (inputs if m.group(1).upper() == "INPUT" else outputs).append(m.group(2))
            continue
        m = _GATE.match(line)
        if not m:
            raise CircuitError(f"line {lineno}: cannot parse '{line}'")
        out, kind, args = m.groups()
        gtype = _TYPES.get(kind.upper())
        if gtype is None:
            raise CircuitError(
                f"line {lineno}: unsupported gate type '{kind}' (combinational gates only)")
        gates.append((lineno, out, gtype, [a.strip() for a in args.split(",") if a.strip()]))

    c = Circuit(name)
    for n in inputs:                       # PIs first, so 'gate drives a PI' is caught
        c.mark_pi(n)
    for lineno, out, gtype, ins in gates:
        try:
            c.add_gate(out, gtype, out, ins)
        except CircuitError as e:
            raise CircuitError(f"line {lineno}: {e}") from None
    for n in outputs:
        c.mark_po(n)
    c.validate()
    return c