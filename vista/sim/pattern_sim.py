"""Engine 4 (part 2): pattern-set fault simulation, fault dropping, detection matrix."""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path

from vista.faults.collapse import CollapseResult, collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.model import Circuit
from vista.rtl.loader import load_circuit
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import to_str

Pattern = dict[str, int]


# ---- pattern sources ---------------------------------------------------
def random_patterns(circuit: Circuit, count: int, seed: int = 0) -> list[Pattern]:
    """Fully specified (0/1) random vectors. Same seed -> same vectors."""
    rng = random.Random(seed)
    pis = circuit.primary_inputs
    return [{pi: rng.getrandbits(1) for pi in pis} for _ in range(count)]


def exhaustive_patterns(circuit: Circuit) -> list[Pattern]:
    return list(SerialFaultSimulator(circuit).exhaustive_patterns())


def weights_from_collapse(result: CollapseResult) -> dict[Fault, int]:
    """Representative -> class size, so coverage can be reported on the full universe."""
    return {rep: len(members) for rep, members in result.classes.items()}


# ---- result container --------------------------------------------------
@dataclass
class SimReport:
    circuit: str
    pi_order: list[str]
    po_order: list[str]
    patterns: list[Pattern]
    faults: list[Fault]
    weights: dict[Fault, int]
    drop: bool
    detections: dict[Fault, list[int]]     # fault -> indices of detecting patterns
                                           # (with dropping: at most the first one)

    def pattern_bits(self, i: int) -> str:
        return to_str([self.patterns[i][pi] for pi in self.pi_order])

    def first_detect(self, fault: Fault) -> int | None:
        hits = self.detections[fault]
        return hits[0] if hits else None

    @property
    def detected(self) -> list[Fault]:
        return [f for f in self.faults if self.detections[f]]

    @property
    def undetected(self) -> list[Fault]:
        return [f for f in self.faults if not self.detections[f]]

    @property
    def coverage(self) -> float:
        return len(self.detected) / len(self.faults) if self.faults else 1.0

    @property
    def weighted_coverage(self) -> float:
        total = sum(self.weights[f] for f in self.faults)
        hit = sum(self.weights[f] for f in self.detected)
        return hit / total if total else 1.0

    def new_detections(self) -> list[list[Fault]]:
        """Per pattern: faults whose FIRST detection is that pattern."""
        per: list[list[Fault]] = [[] for _ in self.patterns]
        for f in self.faults:
            i = self.first_detect(f)
            if i is not None:
                per[i].append(f)
        return per

    def coverage_curve(self) -> list[int]:
        """Cumulative detected-fault count after each pattern."""
        total, curve = 0, []
        for new in self.new_detections():
            total += len(new)
            curve.append(total)
        return curve

    def to_dict(self) -> dict:
        """JSON contract for Member 2 (additive to earlier schemas)."""
        new = self.new_detections()
        wt = sum(self.weights[f] for f in self.faults)
        wd = sum(self.weights[f] for f in self.detected)
        return {
            "schema_version": "0.1",
            "circuit": self.circuit,
            "fault_model": "stuck_at",
            "fault_dropping": self.drop,
            "pi_order": self.pi_order,
            "po_order": self.po_order,
            "summary": {
                "total_faults": len(self.faults),
                "detected": len(self.detected),
                "undetected": len(self.undetected),
                "coverage_pct": round(100 * self.coverage, 2),
                "weighted_total": wt,
                "weighted_detected": wd,
                "weighted_coverage_pct": round(100 * self.weighted_coverage, 2),
            },
            "patterns": [
                {"index": i, "bits": self.pattern_bits(i),
                 "new_detections": [f.id for f in new[i]]}
                for i in range(len(self.patterns))
            ],
            "coverage_curve": self.coverage_curve(),
            "faults": [
                {"id": f.id, "class_size": self.weights[f],
                 "detected": bool(self.detections[f]),
                 "first_detect": self.first_detect(f),
                 "detecting_patterns": self.detections[f]}
                for f in self.faults
            ],
        }


# ---- the driver --------------------------------------------------------
def run_fault_simulation(circuit: Circuit, faults: list[Fault], patterns: list[Pattern],
                         weights: dict[Fault, int] | None = None,
                         drop: bool = True, reference: bool = False) -> SimReport:
    """reference=True uses the slow full-circuit path, kept as an independent oracle."""
    sim = SerialFaultSimulator(circuit)
    detections: dict[Fault, list[int]] = {f: [] for f in faults}
    active = list(faults)
    for idx, pat in enumerate(patterns):
        if reference:
            good = sim.outputs(pat)
            detect = lambda f: sim.detected_outputs(pat, f, good)
        else:
            good = sim.simulate(pat)
            detect = lambda f: sim.detected_from_good(good, f)
        still_active = []
        for f in active:
            if detect(f):
                detections[f].append(idx)
                if drop:
                    continue
            still_active.append(f)
        active = still_active
        if not active:
            break
    w = {f: (weights or {}).get(f, 1) for f in faults}
    return SimReport(circuit.name, circuit.primary_inputs, circuit.primary_outputs,
                     patterns, faults, w, drop, detections)

# ---- CLI ---------------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="VISTA pattern-set fault simulation")
    ap.add_argument("netlist", nargs="?", default="benchmarks/c17.v")
    ap.add_argument("--random", type=int, default=8, metavar="N", help="N random patterns")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--exhaustive", action="store_true", help="all 2^n patterns")
    ap.add_argument("--no-drop", action="store_true", help="full detection matrix")
    ap.add_argument("--uncollapsed", action="store_true", help="simulate all faults")
    ap.add_argument("--json", metavar="FILE", help="write JSON report")
    args = ap.parse_args(argv)

    c = load_circuit(args.netlist)
    universe = generate_stuck_at_faults(c)
    if args.uncollapsed:
        faults, weights = universe, None
    else:
        res = collapse_equivalent(c, universe)
        faults, weights = res.representatives, weights_from_collapse(res)
    patterns = exhaustive_patterns(c) if args.exhaustive else random_patterns(c, args.random, args.seed)

    rep = run_fault_simulation(c, faults, patterns, weights, drop=not args.no_drop)
    curve, new = rep.coverage_curve(), rep.new_detections()
    print(f"{c.name}: {len(patterns)} patterns, {len(faults)} faults, "
          f"dropping={'on' if rep.drop else 'off'}")
    for i in range(len(patterns)):
        print(f"  p{i:<3} {rep.pattern_bits(i)}  +{len(new[i]):<2} -> {curve[i]}/{len(faults)}")
    print(f"coverage          : {len(rep.detected)}/{len(faults)} = {100 * rep.coverage:.1f}%")
    print(f"weighted coverage : {100 * rep.weighted_coverage:.1f}% (full universe)")
    print(f"undetected        : {[f.id for f in rep.undetected]}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep.to_dict(), indent=2))
        print(f"report written to {args.json}")


if __name__ == "__main__":
    main()