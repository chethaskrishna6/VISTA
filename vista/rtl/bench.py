"""Engine 1: ISCAS .bench netlist -> Circuit (combinational gates only)."""
from __future__ import annotations

import re

from vista.rtl.model import Circuit, CircuitError, GateType

_IO = re.compile(r"^(INPUT|OUTPUT)\s*\(\s*([^\s()]+)\s*\)$", re.I)
_GATE = re.compile(r"^([^\s=()]+)\s*=\s*([A-Za-z]+)\s*\(\s*([^()]*?)\s*\)$")
_TYPES = {t.name: t for t in GateType} | {"BUFF": GateType.BUF}


def parse_bench(text: str, name: str = "bench", scan: bool = False) -> Circuit:
    """scan=True: full-scan conversion. Each `Q = DFF(D)` makes Q a pseudo-PI and D a pseudo-PO."""
    inputs: list[str] = []
    outputs: list[str] = []
    gates: list[tuple[int, str, GateType, list[str]]] = []
    dffs: list[tuple[int, str, str]] = []                  # (line, Q net, D net)

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
        names = [a.strip() for a in args.split(",") if a.strip()]
        if kind.upper() == "DFF":
            if not scan:
                raise CircuitError(f"line {lineno}: unsupported gate type 'DFF' "
                                   "(combinational gates only; load with scan=True for full scan)")
            if len(names) != 1:
                raise CircuitError(f"line {lineno}: DFF needs exactly 1 input, got {len(names)}")
            dffs.append((lineno, out, names[0]))
            continue
        gtype = _TYPES.get(kind.upper())
        if gtype is None:
            raise CircuitError(
                f"line {lineno}: unsupported gate type '{kind}' (combinational gates only)")
        gates.append((lineno, out, gtype, names))

    c = Circuit(name)
    for n in inputs:                       # PIs first, so 'gate drives a PI' is caught
        c.mark_pi(n)
    for lineno, q, _ in dffs:
        if q in c.nets:
            raise CircuitError(
                f"line {lineno}: scan cell output '{q}' is already a primary input or scan output")
        c.mark_pi(q)
    for lineno, out, gtype, ins in gates:
        try:
            c.add_gate(out, gtype, out, ins)
        except CircuitError as e:
            raise CircuitError(f"line {lineno}: {e}") from None
    for n in outputs:
        c.mark_po(n)
    for _, q, d in dffs:
        c.mark_po(d)
        c.scan_cells.append((q, d))
    c.validate()
    return c