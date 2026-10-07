"""Time serial (cone) vs packed fault simulation on identical patterns; assert identical results."""
from __future__ import annotations

import argparse
import time

from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.sim.parallel_sim import run_packed_fault_simulation
from vista.sim.pattern_sim import random_patterns, run_fault_simulation


def main() -> None:
    ap = argparse.ArgumentParser(description="serial vs packed fault simulation")
    ap.add_argument("netlist")
    ap.add_argument("--patterns", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    c = load_circuit(args.netlist)
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
    pats = random_patterns(c, args.patterns, args.seed)
    print(f"{c.name}: {len(faults)} faults, {len(pats)} random patterns")
    for drop in (True, False):
        t0 = time.perf_counter()
        base = run_fault_simulation(c, faults, pats, drop=drop)
        t_ser = time.perf_counter() - t0
        print(f"drop={drop!s:<5} serial          {t_ser:7.3f}s   detected {len(base.detected)}")
        for block in (1, 16, 64, 256, 1024):
            t0 = time.perf_counter()
            r = run_packed_fault_simulation(c, faults, pats, drop=drop, block=block)
            t = time.perf_counter() - t0
            ok = "same" if r.detections == base.detections else "MISMATCH <-- BUG"
            print(f"drop={drop!s:<5} packed block={block:<5}{t:7.3f}s   x{t_ser / t:5.1f}   {ok}")


if __name__ == "__main__":
    main()