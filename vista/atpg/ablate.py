"""Ablation: which SCOAP component helps or hurts PODEM? Ground truth from the SAT oracle."""
from __future__ import annotations

import argparse

from vista.atpg.generate import generate_test_set
from vista.atpg.podem import Outcome, SCOAP_PARTS
from vista.atpg.sat import SatAtpg
from vista.atpg.scoap import Scoap
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.loader import load_circuit


def configs():
    yield "naive", None
    for p in sorted(SCOAP_PARTS):
        yield f"only {p}", frozenset({p})
    for p in sorted(SCOAP_PARTS):
        yield f"all but {p}", SCOAP_PARTS - {p}
    yield "all (scoap)", SCOAP_PARTS


def main() -> None:
    ap = argparse.ArgumentParser(description="SCOAP component ablation")
    ap.add_argument("netlist")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    c = load_circuit(args.netlist)
    col = collapse_equivalent(c, generate_stuck_at_faults(c))
    faults = col.representatives
    weights = {r: len(m) for r, m in col.classes.items()}

    sat = SatAtpg(c)
    redundant = {f for f in faults if sat.generate(f).outcome is Outcome.REDUNDANT}
    sat.close()
    scoap = Scoap(c)
    wred = sum(weights[f] for f in redundant)
    total = sum(weights.values())
    print(f"{c.name}: limit {args.limit}; SAT says {len(redundant)} redundant "
          f"(max coverage {100 * (1 - wred / total):.2f}%)")
    print(f"{'config':<20}{'pats':>5}{'runs':>6}{'backtr':>8}{'abort':>6}"
          f"{'fail':>5}{'unprv':>6}{'cover%':>8}{'time':>8}")

    for label, use in configs():
        sc, parts = (None, SCOAP_PARTS) if use is None else (scoap, use)
        res = generate_test_set(c, faults, weights, args.limit, 0, sc, parts)
        runs = list(res.podem.values())
        stuck = res.unresolved
        fail = [f for f in stuck if f not in redundant]          # testable but lost
        unproven = len(stuck) - len(fail)                        # redundant, not proven
        unsound = [f.id for f in res.redundant if f not in redundant] + \
                  [f.id for f in res.covered_by if f in redundant]
        print(f"{label:<20}{len(res.patterns):>5}{len(runs):>6}"
              f"{sum(r.backtracks for r in runs):>8}{len(res.aborted):>6}"
              f"{len(fail):>5}{unproven:>6}{100 * res.coverage:>8.2f}"
              f"{sum(r.seconds for r in runs):>7.2f}s"
              + (f"   UNSOUND {unsound}" if unsound else ""))


if __name__ == "__main__":
    main()