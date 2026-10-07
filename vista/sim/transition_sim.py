"""Engine 4 (part 3): two-pattern (V1, V2) transition-fault simulation."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from vista.faults.transition import TransitionFault, generate_transition_faults
from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import to_str
from vista.sim.pattern_sim import exhaustive_patterns, random_patterns

Pattern = dict[str, int]
Pair = tuple[Pattern, Pattern]


class TransitionFaultSimulator:
    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit
        self._sim = SerialFaultSimulator(circuit)

    def good(self, pattern: Pattern) -> dict[str, int]:
        return self._sim.simulate(pattern)

    def detects_from_good(self, good1: dict[str, int], good2: dict[str, int],
                          tf: TransitionFault) -> bool:
        if good1[tf.net] != tf.init_value:            # frame 1 must initialize (X does not count)
            return False
        return bool(self._sim.detected_from_good(good2, tf.stuck))   # frame 2: stuck-at detect

    def detects(self, v1: Pattern, v2: Pattern, tf: TransitionFault) -> bool:
        return self.detects_from_good(self.good(v1), self.good(v2), tf)


@dataclass
class TransitionReport:
    circuit: str
    pi_order: list[str]
    pairs: list[Pair]
    faults: list[TransitionFault]
    detections: dict[TransitionFault, list[int]]
    drop: bool

    def bits(self, p: Pattern) -> str:
        return to_str([p[pi] for pi in self.pi_order])

    @property
    def detected(self) -> list[TransitionFault]:
        return [f for f in self.faults if self.detections[f]]

    @property
    def undetected(self) -> list[TransitionFault]:
        return [f for f in self.faults if not self.detections[f]]

    @property
    def coverage(self) -> float:
        return len(self.detected) / len(self.faults) if self.faults else 1.0

    def coverage_curve(self) -> list[int]:
        new = [0] * len(self.pairs)
        for f in self.detected:
            new[self.detections[f][0]] += 1
        total, curve = 0, []
        for n in new:
            total += n
            curve.append(total)
        return curve

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1", "circuit": self.circuit, "fault_model": "transition",
            "fault_dropping": self.drop, "pi_order": self.pi_order,
            "summary": {"total_faults": len(self.faults), "detected": len(self.detected),
                        "undetected": len(self.undetected),
                        "coverage_pct": round(100 * self.coverage, 2)},
            "pairs": [{"index": i, "v1": self.bits(a), "v2": self.bits(b)}
                      for i, (a, b) in enumerate(self.pairs)],
            "coverage_curve": self.coverage_curve(),
            "faults": [{"id": f.id, "detected": bool(self.detections[f]),
                        "first_detect": self.detections[f][0] if self.detections[f] else None,
                        "detecting_pairs": self.detections[f]} for f in self.faults],
        }


def run_transition_simulation(circuit: Circuit, faults: list[TransitionFault],
                              pairs: list[Pair], drop: bool = True) -> TransitionReport:
    sim = TransitionFaultSimulator(circuit)
    detections: dict[TransitionFault, list[int]] = {f: [] for f in faults}
    active = list(faults)
    for idx, (v1, v2) in enumerate(pairs):
        g1, g2 = sim.good(v1), sim.good(v2)           # once per pair, not per fault
        keep = []
        for f in active:
            if sim.detects_from_good(g1, g2, f):
                detections[f].append(idx)
                if drop:
                    continue
            keep.append(f)
        active = keep
        if not active:
            break
    return TransitionReport(circuit.name, circuit.primary_inputs, pairs, faults, detections, drop)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="VISTA transition-fault simulation")
    ap.add_argument("netlist")
    ap.add_argument("--mode", choices=("random", "exhaustive", "stuck-at"), default="random",
                    help="random: independent pairs; exhaustive: all 2^n x 2^n pairs (tiny circuits); "
                         "stuck-at: PODEM stuck-at test set applied as consecutive pairs")
    ap.add_argument("--count", type=int, default=200, help="number of random pairs")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", metavar="FILE")
    args = ap.parse_args(argv)

    c = load_circuit(args.netlist)
    faults = generate_transition_faults(c)
    if args.mode == "exhaustive":
        if len(c.primary_inputs) > 6:
            raise SystemExit("exhaustive pairs only for circuits with <= 6 PIs")
        pats = exhaustive_patterns(c)
        pairs = [(a, b) for a in pats for b in pats]
    elif args.mode == "stuck-at":
        from vista.atpg.generate import generate_test_set
        from vista.faults.collapse import collapse_equivalent
        from vista.faults.stuck_at import generate_stuck_at_faults
        reps = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
        pats = generate_test_set(c, reps, backtrack_limit=100).patterns
        pairs = list(zip(pats, pats[1:]))
        print(f"stuck-at set: {len(pats)} patterns -> {len(pairs)} consecutive pairs")
    else:
        pats = random_patterns(c, 2 * args.count, args.seed)
        pairs = [(pats[2 * i], pats[2 * i + 1]) for i in range(args.count)]

    rep = run_transition_simulation(c, faults, pairs)
    str_f = [f for f in faults if f.rising]
    stf_f = [f for f in faults if not f.rising]
    n = lambda fs: sum(1 for f in fs if rep.detections[f])
    print(f"{c.name}: {len(pairs)} pairs ({args.mode}), {len(faults)} transition faults")
    print(f"coverage   : {len(rep.detected)}/{len(faults)} = {100 * rep.coverage:.2f}%")
    print(f"  STR      : {n(str_f)}/{len(str_f)}   STF: {n(stf_f)}/{len(stf_f)}")
    print(f"undetected : {len(rep.undetected)} {[f.id for f in rep.undetected][:8]}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep.to_dict(), indent=2))
        print(f"report written to {args.json}")


if __name__ == "__main__":
    main()