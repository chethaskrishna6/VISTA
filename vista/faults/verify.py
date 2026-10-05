"""Verify fault collapsing by exhaustive faulty-circuit simulation."""
from __future__ import annotations

import sys

from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.parser import VerilogParser
from vista.sim.fault_sim import SerialFaultSimulator

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/c17.v"
    c = VerilogParser().parse_file(src)
    faults = generate_stuck_at_faults(c)
    res = collapse_equivalent(c, faults)
    sim = SerialFaultSimulator(c)

    sig = {f: sim.signature(f) for f in faults}
    good = sim.signature(None)
    bad = [r.id for r, ms in res.classes.items() if len({sig[m] for m in ms}) != 1]
    redundant = [f.id for f in faults if sig[f] == good]
    distinct = len({sig[r] for r in res.representatives})

    print(f"{c.name}: {len(faults)} faults -> {len(res.classes)} classes")
    print(f"equivalence check : {len(res.classes) - len(bad)}/{len(res.classes)} classes "
          f"behaviorally identical over {len(good)} vectors")
    for b in bad:
        print("  UNSOUND CLASS:", b)
    print(f"undetectable faults: {len(redundant)} {redundant}")
    print(f"distinct faulty behaviors among representatives: {distinct}")