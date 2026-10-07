"""Circuit statistics: a quick sanity check on any netlist."""
from __future__ import annotations

import argparse
from collections import Counter

from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit


def circuit_stats(c: Circuit) -> dict:
    lvl = c.levelize()
    return {
        "name": c.name,
        "inputs": len(c.primary_inputs),
        "outputs": len(c.primary_outputs),
        "gates": len(c.gates),
        "nets": len(c.nets),
        "depth": max(lvl.values()),
        "gate_types": dict(sorted(Counter(g.type.value for g in c.gates.values()).items())),
        "max_fanin": max(len(g.inputs) for g in c.gates.values()),
        "max_fanout": max(len(n.fanout) for n in c.nets.values()),
        "stems": len(c.stems),
        "po_fanout": c.po_with_fanout,
        "scan_cells": len(c.scan_cells),
        "po_buffers": c.po_buffers,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="VISTA circuit statistics")
    ap.add_argument("netlist")
    args = ap.parse_args()
    c = load_circuit(args.netlist)
    for k, v in circuit_stats(c).items():
        print(f"{k:<11}: {v}")
    universe = generate_stuck_at_faults(c)
    print(f"faults     : {len(universe)} uncollapsed -> "
          f"{len(collapse_equivalent(c, universe).classes)} collapsed")