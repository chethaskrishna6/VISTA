"""Compare PODEM (naive and SCOAP) against the SAT oracle on one circuit."""
from __future__ import annotations

import argparse
import time

from vista.atpg.generate import generate_test_set
from vista.atpg.podem import Outcome
from vista.atpg.sat import SatAtpg
from vista.atpg.scoap import Scoap
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.sim.fault_sim import SerialFaultSimulator


def main() -> None:
    ap = argparse.ArgumentParser(description="PODEM vs SAT oracle")
    ap.add_argument("netlist")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    c = load_circuit(args.netlist)
    col = collapse_equivalent(c, generate_stuck_at_faults(c))
    faults = col.representatives
    weights = {r: len(m) for r, m in col.classes.items()}
    W = lambda fs: sum(weights[f] for f in fs)
    total = W(faults)

    t0 = time.perf_counter()
    sat = SatAtpg(c)
    truth = {f: sat.generate(f) for f in faults}
    sat_time = time.perf_counter() - t0
    sat.close()

    sim = SerialFaultSimulator(c)
    bad_tests = [f.id for f, r in truth.items()
                 if r.outcome is Outcome.TESTED and not sim.detects(r.pattern, f)]
    redundant = [f for f, r in truth.items() if r.outcome is Outcome.REDUNDANT]
    print(f"{c.name}: {len(faults)} collapsed faults, SAT solved all in {sat_time:.2f}s")
    print(f"SAT truth        : {len(faults) - len(redundant)} testable, {len(redundant)} redundant "
          f"(weight {W(redundant)}/{total})")
    print(f"max achievable   : coverage {100 * (1 - W(redundant) / total):.2f}%, efficiency 100%")
    print(f"redundant faults : {[f.id for f in redundant][:20]}")
    print(f"SAT vectors that FAIL simulator check: {bad_tests}   (must be [])")

    for label, scoap in (("naive", None), ("scoap", Scoap(c))):
        res = generate_test_set(c, faults, weights, args.limit, 0, scoap)
        ab = res.aborted
        ab_testable = [f for f in ab if truth[f].outcome is Outcome.TESTED]
        ab_redundant = [f for f in ab if truth[f].outcome is Outcome.REDUNDANT]
        det_but_red = [f.id for f in res.covered_by if truth[f].outcome is Outcome.REDUNDANT]
        wrong_red = [f.id for f in res.redundant if truth[f].outcome is not Outcome.REDUNDANT]
        print(f"--- PODEM {label}, limit {args.limit} ---")
        print(f"aborted {len(ab)}: {len(ab_testable)} testable by SAT, {len(ab_redundant)} truly redundant")
        print(f"  testable-but-aborted  : {[f.id for f in ab_testable][:10]}")
        print(f"  redundant-but-aborted : {[f.id for f in ab_redundant][:10]}")
        print(f"PODEM-declared redundant: {len(res.redundant)}, wrong: {wrong_red}   (must be [])")
        print(f"detected yet SAT-redundant: {det_but_red}   (must be [])")


if __name__ == "__main__":
    main()