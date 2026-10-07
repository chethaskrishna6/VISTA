"""`vista matrix`: simulate a given pattern set and export the full detection matrix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.faults.transition import generate_transition_faults
from vista.patterns import PatternFileError, read_loc_vectors, read_patterns
from vista.rtl.loader import load_circuit
from vista.rtl.model import CircuitError
from vista.sim.parallel_sim import run_packed_fault_simulation, run_packed_transition_simulation


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vista matrix",
                                 description="Detection matrix for a given pattern set (no fault dropping)")
    ap.add_argument("netlist")
    ap.add_argument("--patterns", required=True,
                    help="text file, or a VISTA .json report (atpg/sim/compaction/loc)")
    ap.add_argument("--model", choices=("stuck-at", "transition", "loc"), default="stuck-at",
                    help="loc: launch-on-capture vectors (full-scan circuits)")
    ap.add_argument("--free-pi", action="store_true", help="loc: frame-2 PIs have their own bits")
    ap.add_argument("--method", help="method name to take from a compaction_report")
    ap.add_argument("--uncollapsed", action="store_true", help="stuck-at: simulate every fault")
    ap.add_argument("--block", type=int, default=256, help="patterns packed per pass")
    ap.add_argument("--verify", action="store_true", help="re-check with an independent simulator")
    ap.add_argument("--json", metavar="FILE")
    args = ap.parse_args(argv)

    c = load_circuit(args.netlist)
    model = None
    try:
        if args.model == "loc":
            from vista.rtl.loc import LocModel
            model = LocModel(c, hold_pi=not args.free_pi)
            items = read_loc_vectors(args.patterns, model)
        else:
            items = read_patterns(args.patterns, c, args.model, args.method)
    except (PatternFileError, CircuitError) as e:
        raise SystemExit(f"error: {e}")
    if not items:
        raise SystemExit("no patterns found in " + args.patterns)

    stuck = args.model == "stuck-at"
    if stuck:
        universe = generate_stuck_at_faults(c)
        if args.uncollapsed:
            faults, weights = universe, None
        else:
            col = collapse_equivalent(c, universe)
            faults, weights = col.representatives, {r: len(m) for r, m in col.classes.items()}
        rep = run_packed_fault_simulation(c, faults, items, weights, drop=False, block=args.block)
    else:
        faults = generate_transition_faults(c)
        # loc: pair i is the enhanced-scan equivalent of LOC vector i
        pairs = items if args.model == "transition" else [model.pair_of(v) for v in items]
        rep = run_packed_transition_simulation(c, faults, pairs, drop=False, block=args.block)

    unit = {"stuck-at": "patterns", "transition": "pairs", "loc": "vectors"}[args.model]
    print(f"{c.name} [{args.model}]: {len(items)} {unit}, {len(faults)} faults")
    print(f"coverage : {len(rep.detected)}/{len(faults)} = {100 * rep.coverage:.2f}%")
    if stuck:
        print(f"weighted : {100 * rep.weighted_coverage:.2f}% (full fault universe)")
    print(f"undetected: {len(rep.undetected)} {[f.id for f in rep.undetected][:8]}")
    rc = 0
    if args.verify:
        if stuck:
            from vista.sim.pattern_sim import run_fault_simulation
            ref = run_fault_simulation(c, faults, items, drop=False, reference=True)
            ok = ref.detections == rep.detections
        elif args.model == "loc":
            from vista.atpg.loc import LocFaultSimulator      # expanded circuit: a different code path
            lsim = LocFaultSimulator(model)
            expected = {f: [] for f in faults}
            for i, v in enumerate(items):
                good = lsim.good(v)
                for f in faults:
                    if lsim.detects_from_good(good, f):
                        expected[f].append(i)
            ok = expected == rep.detections
        else:
            from vista.atpg.transition_atpg import reference_detected
            ok = reference_detected(c, faults, items) == set(rep.detected)
        print(f"reference check: {'AGREES' if ok else 'MISMATCH <-- BUG'}")
        rc = 0 if ok else 1
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep.to_dict(), indent=2))
        print(f"matrix written to {args.json}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())