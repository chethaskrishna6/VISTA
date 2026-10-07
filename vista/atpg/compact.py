"""Engine 3 (part 5): static compaction by removing whole patterns (or pairs)."""
from __future__ import annotations

import argparse
from typing import Callable, Mapping, Sequence


def _by_item(n: int, detections: Mapping) -> list[set]:
    per: list[set] = [set() for _ in range(n)]
    for fault, idxs in detections.items():
        for i in idxs:
            per[i].add(fault)
    return per


def reverse_order(n: int, detections: Mapping[object, Sequence[int]]) -> list[int]:
    """Keep an item only if it detects a fault no later item covers."""
    per = _by_item(n, detections)
    covered: set = set()
    keep = []
    for i in range(n - 1, -1, -1):
        if per[i] - covered:
            keep.append(i)
            covered |= per[i]
    return sorted(keep)


def greedy_cover(n: int, detections: Mapping[object, Sequence[int]]) -> list[int]:
    """Repeatedly take the item covering the most uncovered faults (ties: lowest index)."""
    per = _by_item(n, detections)
    uncovered = {f for f, idxs in detections.items() if idxs}
    keep = []
    while uncovered:
        best = max(range(n), key=lambda i: (len(per[i] & uncovered), -i))
        gain = per[best] & uncovered
        if not gain:
            break
        keep.append(best)
        uncovered -= gain
    return sorted(keep)


METHODS = (("reverse-order", reverse_order), ("greedy set cover", greedy_cover))


def prepare_stuck_at(c, limit: int = 100, fill: int = 0):
    from vista.atpg.hybrid import run_hybrid
    from vista.faults.collapse import collapse_equivalent
    from vista.faults.stuck_at import generate_stuck_at_faults
    from vista.sim.pattern_sim import run_fault_simulation

    col = collapse_equivalent(c, generate_stuck_at_faults(c))
    faults = col.representatives
    w = {r: len(m) for r, m in col.classes.items()}
    res = run_hybrid(c, faults, w, limit, fill)
    items = res.patterns
    det = run_fault_simulation(c, faults, items, w, drop=False).detections
    assert {f for f, i in det.items() if i} == set(res.covered_by), "matrix disagrees with ATPG"

    def verify(kept: list[int]) -> set:
        sub = [items[i] for i in kept]
        return set(run_fault_simulation(c, faults, sub, reference=True).detected)

    return items, det, verify


def prepare_transition(c, limit: int = 100, fill: str = "random", seed: int = 1):
    from vista.atpg.transition_atpg import generate_transition_tests, reference_detected
    from vista.faults.transition import generate_transition_faults
    from vista.sim.transition_sim import run_transition_simulation

    faults = generate_transition_faults(c)
    res = generate_transition_tests(c, faults, limit, fill, seed)
    items = res.pairs
    det = run_transition_simulation(c, faults, items, drop=False).detections
    assert {f for f, i in det.items() if i} == set(res.covered_by), "matrix disagrees with ATPG"

    def verify(kept: list[int]) -> set:
        return reference_detected(c, faults, [items[i] for i in kept])

    return items, det, verify


def evaluate(n: int, detections: Mapping, verify: Callable[[list[int]], set]) -> dict:
    """Run every method; return name -> (kept indices, coverage preserved per the slow oracle)."""
    base = {f for f, idxs in detections.items() if idxs}
    out = {}
    for name, fn in METHODS:
        kept = fn(n, detections)
        out[name] = (kept, verify(kept) == base)
    return out


def main(argv: list[str] | None = None) -> None:
    from vista.rtl.loader import load_circuit

    ap = argparse.ArgumentParser(description="VISTA static compaction")
    ap.add_argument("netlist")
    ap.add_argument("--model", choices=("stuck-at", "transition"), default="stuck-at")
    ap.add_argument("--fill", choices=("0", "1", "random"), default=None,
                    help="default: 0 for stuck-at, random for transition")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    c = load_circuit(args.netlist)
    if args.model == "stuck-at":
        fill = args.fill or "0"
        if fill == "random":
            raise SystemExit("stuck-at generation supports --fill 0 or 1 only")
        items, det, verify = prepare_stuck_at(c, args.limit, int(fill))
    else:
        fill = args.fill or "random"
        items, det, verify = prepare_transition(c, args.limit, fill, args.seed)

    n = len(items)
    covered = sum(1 for idxs in det.values() if idxs)
    unit = "patterns" if args.model == "stuck-at" else "pairs"
    print(f"{c.name} [{args.model}, fill={fill}]: {n} {unit}, {covered} faults detected by the set")
    for name, (kept, ok) in evaluate(n, det, verify).items():
        print(f"  {name:<17}: {len(kept):>4} kept ({100 * (1 - len(kept) / n):5.1f}% removed)"
              f"   coverage preserved: {'YES' if ok else 'NO  <-- BUG'}")


if __name__ == "__main__":
    main()