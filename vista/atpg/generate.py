"""Engine 3 driver: PODEM + fault dropping -> test set."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from vista.atpg.podem import Outcome, PodemEngine, PodemResult
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.model import Circuit
from vista.rtl.loader import load_circuit
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import X, to_str

Pattern = dict[str, int]


@dataclass
class AtpgResult:
    circuit: str
    pi_order: list[str]
    faults: list[Fault]
    weights: dict[Fault, int]
    patterns: list[Pattern] = field(default_factory=list)      # fully specified
    cubes: list[Pattern] = field(default_factory=list)         # with don't-cares (absent PIs)
    covered_by: dict[Fault, int] = field(default_factory=dict)  # fault -> pattern index
    podem: dict[Fault, PodemResult] = field(default_factory=dict)

    def _w(self, fs) -> int:
        return sum(self.weights[f] for f in fs)

    @property
    def redundant(self): return [f for f, r in self.podem.items() if r.outcome is Outcome.REDUNDANT]
    @property
    def aborted(self): return [f for f, r in self.podem.items() if r.outcome is Outcome.ABORTED]

    @property
    def coverage(self) -> float:
        return self._w(self.covered_by) / self._w(self.faults)

    @property
    def efficiency(self) -> float:
        return (self._w(self.covered_by) + self._w(self.redundant)) / self._w(self.faults)

    def bits(self, p: Pattern) -> str:
        return to_str([p.get(pi, X) for pi in self.pi_order])

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1", "circuit": self.circuit, "fault_model": "stuck_at",
            "algorithm": "podem", "pi_order": self.pi_order,
            "summary": {
                "total_faults": len(self.faults), "detected": len(self.covered_by),
                "redundant": len(self.redundant), "aborted": len(self.aborted),
                "patterns": len(self.patterns),
                "weighted_coverage_pct": round(100 * self.coverage, 2),
                "weighted_efficiency_pct": round(100 * self.efficiency, 2),
            },
            "patterns": [{"index": i, "bits": self.bits(p), "cube": self.bits(self.cubes[i])}
                         for i, p in enumerate(self.patterns)],
            "faults": [{"id": f.id, "class_size": self.weights[f],
                        "status": "detected" if f in self.covered_by else
                                  self.podem[f].outcome.value,
                        "pattern": self.covered_by.get(f),
                        "backtracks": self.podem[f].backtracks if f in self.podem else 0}
                       for f in self.faults],
        }


def generate_test_set(circuit: Circuit, faults: list[Fault],
                      weights: dict[Fault, int] | None = None,
                      backtrack_limit: int = 100, fill: int = 0) -> AtpgResult:
    sim = SerialFaultSimulator(circuit)
    res = AtpgResult(circuit.name, circuit.primary_inputs, faults,
                     {f: (weights or {}).get(f, 1) for f in faults})
    for f in faults:
        if f in res.covered_by:
            continue                                   # dropped by an earlier pattern
        r = PodemEngine(circuit, f).generate(backtrack_limit)
        res.podem[f] = r
        if r.outcome is not Outcome.TESTED:
            continue
        pattern = {pi: r.cube.get(pi, fill) for pi in res.pi_order}
        idx = len(res.patterns)
        res.patterns.append(pattern)
        res.cubes.append(r.cube)
        good = sim.outputs(pattern)
        for g in faults:                               # fault-simulate the new pattern
            if g not in res.covered_by and sim.detected_outputs(pattern, g, good):
                res.covered_by[g] = idx
        assert f in res.covered_by, f"PODEM/simulator disagree on {f.id}"
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="VISTA PODEM test generation")
    ap.add_argument("netlist", nargs="?", default="benchmarks/c17.v")
    ap.add_argument("--limit", type=int, default=100, help="backtrack limit per fault")
    ap.add_argument("--fill", type=int, choices=(0, 1), default=0, help="don't-care fill")
    ap.add_argument("--uncollapsed", action="store_true")
    ap.add_argument("--json", metavar="FILE")
    args = ap.parse_args(argv)

    c = load_circuit(args.netlist)
    universe = generate_stuck_at_faults(c)
    if args.uncollapsed:
        faults, weights = universe, None
    else:
        col = collapse_equivalent(c, universe)
        faults, weights = col.representatives, {r: len(m) for r, m in col.classes.items()}

    res = generate_test_set(c, faults, weights, args.limit, args.fill)
    print(f"{c.name}: {len(faults)} faults, PI order {res.pi_order}")
    for f in faults:
        r = res.podem.get(f)
        how = (f"pattern {res.covered_by[f]}" + ("" if r else " (dropped, no PODEM run)")
               if f in res.covered_by else r.outcome.value)
        bt = f"  backtracks={r.backtracks}" if r else ""
        print(f"  {f.id:<22} {how}{bt}")
    print("patterns:")
    for i, p in enumerate(res.patterns):
        print(f"  p{i:<2} {res.bits(p)}   cube {res.bits(res.cubes[i])}")
    print(f"fault coverage   : {100 * res.coverage:.1f}%")
    print(f"fault efficiency : {100 * res.efficiency:.1f}%")
    print(f"redundant={len(res.redundant)} aborted={len(res.aborted)} patterns={len(res.patterns)}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(res.to_dict(), indent=2))
        print(f"report written to {args.json}")


if __name__ == "__main__":
    main()