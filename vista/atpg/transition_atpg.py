"""Engine 3 (part 4): transition-fault ATPG (independent frames) = justify V1 + stuck-at test V2."""
from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from vista.atpg.justify import Justifier
from vista.atpg.podem import Outcome, PodemEngine
from vista.atpg.sat import SatAtpg
from vista.faults.transition import TransitionFault, generate_transition_faults
from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import X, to_str
from vista.sim.transition_sim import TransitionFaultSimulator

Pattern = dict[str, int]
Pair = tuple[Pattern, Pattern]

REASON_SA = "stuck-at redundant"      # frame 2 impossible
REASON_INIT = "cannot initialize"     # frame 1 impossible


@dataclass
class TdfAtpgResult:
    circuit: str
    pi_order: list[str]
    faults: list[TransitionFault]
    pairs: list[Pair] = field(default_factory=list)
    cubes: list[tuple[Pattern, Pattern]] = field(default_factory=list)
    covered_by: dict[TransitionFault, int] = field(default_factory=dict)
    untestable: dict[TransitionFault, str] = field(default_factory=dict)
    sat_calls: int = 0
    seconds: float = 0.0

    @property
    def coverage(self) -> float:
        return len(self.covered_by) / len(self.faults) if self.faults else 1.0

    @property
    def efficiency(self) -> float:
        return (len(self.covered_by) + len(self.untestable)) / len(self.faults) if self.faults else 1.0

    def bits(self, p: Pattern) -> str:
        return to_str([p.get(pi, X) for pi in self.pi_order])

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1", "circuit": self.circuit, "fault_model": "transition",
            "algorithm": "podem+justify+sat", "pi_order": self.pi_order,
            "summary": {"total_faults": len(self.faults), "detected": len(self.covered_by),
                        "untestable": len(self.untestable), "pairs": len(self.pairs),
                        "untestable_reasons": dict(Counter(self.untestable.values())),
                        "coverage_pct": round(100 * self.coverage, 2),
                        "efficiency_pct": round(100 * self.efficiency, 2)},
            "pairs": [{"index": i, "v1": self.bits(a), "v2": self.bits(b),
                       "cube1": self.bits(ca), "cube2": self.bits(cb)}
                      for i, ((a, b), (ca, cb)) in enumerate(zip(self.pairs, self.cubes))],
            "faults": [{"id": f.id,
                        "status": "detected" if f in self.covered_by else "untestable",
                        "pair": self.covered_by.get(f), "reason": self.untestable.get(f)}
                       for f in self.faults],
        }


def _fill(cube: Pattern, pis: list[str], fill: str, rng: random.Random) -> Pattern:
    if fill == "random":
        return {pi: cube[pi] if pi in cube else rng.getrandbits(1) for pi in pis}
    return {pi: cube.get(pi, int(fill)) for pi in pis}


def generate_transition_tests(circuit: Circuit, faults: list[TransitionFault] | None = None,
                              backtrack_limit: int = 100, fill: str = "random",
                              seed: int = 1) -> TdfAtpgResult:
    if fill not in ("0", "1", "random"):
        raise ValueError(f"fill must be 0, 1 or random, got {fill!r}")
    faults = generate_transition_faults(circuit) if faults is None else faults
    res = TdfAtpgResult(circuit.name, circuit.primary_inputs, faults)
    tsim, just, rng = TransitionFaultSimulator(circuit), Justifier(circuit), random.Random(seed)
    t0 = time.perf_counter()
    sat: SatAtpg | None = None
    try:
        for f in faults:
            if f in res.covered_by or f in res.untestable:
                continue
            # frame 2: V2 must detect the stuck-at fault (PODEM, SAT if aborted)
            cube2 = None
            r2 = PodemEngine(circuit, f.stuck).generate(backtrack_limit)
            if r2.outcome is Outcome.TESTED:
                cube2 = r2.cube
            elif r2.outcome is Outcome.ABORTED:
                sat = sat or SatAtpg(circuit)
                res.sat_calls += 1
                s = sat.generate(f.stuck)
                cube2 = s.pattern if s.outcome is Outcome.TESTED else None
            if cube2 is None:
                res.untestable[f] = REASON_SA
                continue
            # frame 1: V1 must put the site at its pre-transition value
            cube1 = None
            r1 = just.justify(f.net, f.init_value, backtrack_limit)
            if r1.outcome is Outcome.TESTED:
                cube1 = r1.cube
            elif r1.outcome is Outcome.ABORTED:
                sat = sat or SatAtpg(circuit)
                res.sat_calls += 1
                cube1 = sat.justify(f.net, f.init_value)
            if cube1 is None:
                res.untestable[f] = REASON_INIT
                continue
            v1 = _fill(cube1, res.pi_order, fill, rng)
            v2 = _fill(cube2, res.pi_order, fill, rng)
            idx = len(res.pairs)
            res.pairs.append((v1, v2))
            res.cubes.append((cube1, cube2))
            g1, g2 = tsim.good(v1), tsim.good(v2)
            for g in faults:                       # two-frame fault dropping
                if (g not in res.covered_by and g not in res.untestable
                        and tsim.detects_from_good(g1, g2, g)):
                    res.covered_by[g] = idx
            assert f in res.covered_by, f"pair failed to detect its own target {f.id}"
    finally:
        if sat is not None:
            sat.close()
    res.seconds = time.perf_counter() - t0
    return res


def reference_detected(circuit: Circuit, faults: list[TransitionFault],
                       pairs: list[Pair]) -> set[TransitionFault]:
    """Slow independent oracle: full-circuit simulation for both frames, no cones."""
    ref = SerialFaultSimulator(circuit)
    found: set[TransitionFault] = set()
    for v1, v2 in pairs:
        g1 = ref.simulate(v1)
        for f in faults:
            if f not in found and g1[f.net] == f.init_value and ref.detects(v2, f.stuck):
                found.add(f)
    return found


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="VISTA transition-fault ATPG")
    ap.add_argument("netlist")
    ap.add_argument("--limit", type=int, default=100, help="backtrack limit per search")
    ap.add_argument("--fill", choices=("0", "1", "random"), default="random")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-verify", action="store_true", help="skip the slow re-simulation")
    ap.add_argument("--json", metavar="FILE")
    args = ap.parse_args(argv)

    c = load_circuit(args.netlist)
    faults = generate_transition_faults(c)
    res = generate_transition_tests(c, faults, args.limit, args.fill, args.seed)
    n = lambda fs: sum(1 for f in fs if f in res.covered_by)
    str_f = [f for f in faults if f.rising]
    stf_f = [f for f in faults if not f.rising]
    print(f"{c.name}: {len(faults)} transition faults, fill={args.fill}, seed={args.seed}")
    print(f"pairs       : {len(res.pairs)}")
    print(f"coverage    : {len(res.covered_by)}/{len(faults)} = {100 * res.coverage:.2f}%"
          f"   (STR {n(str_f)}/{len(str_f)}, STF {n(stf_f)}/{len(stf_f)})")
    print(f"efficiency  : {100 * res.efficiency:.2f}%")
    print(f"untestable  : {len(res.untestable)} {dict(Counter(res.untestable.values()))}")
    print(f"  ids       : {[f.id for f in res.untestable][:10]}")
    print(f"SAT calls   : {res.sat_calls}   time {res.seconds:.2f}s")
    if not args.no_verify:
        ok = reference_detected(c, faults, res.pairs) == set(res.covered_by)
        print(f"independent re-simulation: {'AGREES' if ok else 'MISMATCH'} ({len(res.covered_by)} detected)")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(res.to_dict(), indent=2))
        print(f"report written to {args.json}")


if __name__ == "__main__":
    main()