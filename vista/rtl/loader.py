"""Single entry point for reading a netlist, whatever its format."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from vista.rtl.bench import parse_bench
from vista.rtl.model import Circuit, CircuitError
from vista.rtl.parser import VerilogParser
from vista.rtl.scan import isolate_po_fanout

_DFF = re.compile(r"=\s*DFF\s*\(", re.I)


def load_circuit(path: str | Path, scan: bool | None = None) -> Circuit:
    """scan=None: full-scan conversion happens automatically if the .bench file has DFFs (with a
    notice on stderr). scan=True forces it, scan=False rejects flip-flops."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".bench":
        text = p.read_text()
        has_dff = any(_DFF.search(line.split("#", 1)[0]) for line in text.splitlines())
        use_scan = has_dff if scan is None else scan
        c = parse_bench(text, p.stem, scan=use_scan)
        if scan is None and c.scan_cells:
            print(f"note: {p.name}: full-scan conversion, {len(c.scan_cells)} flip-flop(s) "
                  "-> pseudo-PI/PO", file=sys.stderr)
        return isolate_po_fanout(c)
    if suffix in (".v", ".sv"):
        if scan:
            raise CircuitError("scan conversion applies to .bench netlists only")
        return isolate_po_fanout(VerilogParser().parse_file(p))
    raise CircuitError(f"unsupported netlist format '{p.suffix}' (use .v or .bench)")