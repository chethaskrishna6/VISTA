"""Single entry point for reading a netlist, whatever its format."""
from __future__ import annotations

from pathlib import Path

from vista.rtl.bench import parse_bench
from vista.rtl.model import Circuit, CircuitError
from vista.rtl.parser import VerilogParser


def load_circuit(path: str | Path) -> Circuit:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".bench":
        return parse_bench(p.read_text(), p.stem)
    if suffix in (".v", ".sv"):
        return VerilogParser().parse_file(p)
    raise CircuitError(f"unsupported netlist format '{p.suffix}' (use .v or .bench)")