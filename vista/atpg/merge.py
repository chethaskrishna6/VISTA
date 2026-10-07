"""Engine 3 (part 6): static compaction by cube merging (+ greedy cover on top)."""
from __future__ import annotations

import argparse
import random
import json
from dataclasses import dataclass, field
from pathlib import Path
from vista.atpg.compact import compaction_to_dict, greedy_cover
from vista.atpg.justify import Justifier
from vista.atpg.podem import Outcome, PodemEngine
from vista.atpg.sat import SatAtpg
from vista.atpg.transition_atpg import REASON_INIT, REASON_SA, _fill, reference_detected
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.faults.transition import generate_transition_faults
from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit
from vista.sim.pattern_sim import run_fault_simulation
from vista.sim.transition_sim import run_transition_simulation
from vista.sim.parallel_sim import run_packed_fault_simulation, run_packed_transition_simulation
Cube = dict[str, int]


def compatible(a: Cube, b: Cube) -> bool:
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return all(big.get(k, v) == v for k, v in small.items())


def merge_items(items: list[tuple[Cube, ...]]) -> tuple[list[list[Cube]], list[int]]:
    """First-fit merge. Item = tuple of cubes (one per time frame).
    Returns (merged groups, group index of each input item). Inputs are not modified."""
    k = len(items[0]) if items else 0
    order = sorted(range(len(items)), key=lambda i: (-sum(len(c) for c in items[i]), i))
    groups: list[list[Cube]] = []
    assign = [0] * len(items)
    for i in order:
        it = items[i]
        for gi, g in enumerate(groups):
            if all(compatible(g[f], it[f]) for f in range(k)):
                for f in range(k):
                    g[f].update(it[f])
                assign[i] = gi
                break
        else:
            groups.append([dict(c) for c in it])
            assign[i] = len(groups) - 1
    return groups, assign


class CubeFactory:
    """Cubes for stuck-at tests and net justification: PODEM first, SAT if aborted. Cached."""
    
    def __init__(self, circuit: Circuit, limit: int = 100) -> None:
        self.circuit, self.limit = circuit, limit
        self._just = Justifier(circuit)
        self._sat: SatAtpg | None = None
        self._sa: dict[Fault, Cube | None] = {}
        self._init: dict[tuple[str, int], Cube | None] = {}
        self.sat_calls = 0

    def _engine(self) -> SatAtpg:
        if self._sat is None:
            self._sat = SatAtpg(self.circuit)
        return self._sat

    def stuck_at(self, fault: Fault) -> Cube | None:
        """A cube detecting `fault`, or None if it is redundant."""
        if fault not in self._sa:
            r = PodemEngine(self.circuit, fault).generate(self.limit)
            if r.outcome is Outcome.TESTED:
                cube = r.cube
            elif r.outcome is Outcome.ABORTED:
                self.sat_calls += 1
                s = self._engine().generate(fault)
                cube = s.pattern if s.outcome is Outcome.TESTED else None
            else:
                cube = None
            self._sa[fault] = cube
        return self._sa[fault]

    def justify(self, net: str, value: int) -> Cube | None:
        key = (net, value)
        if key not in self._init:
            r = self._just.justify(net, value, self.limit)
            if r.outcome is Outcome.TESTED:
                cube = r.cube
            elif r.outcome is Outcome.ABORTED:
                self.sat_calls += 1
                cube = self._engine().justify(net, value)
            else:
                cube = None
            self._init[key] = cube
        return self._init[key]

    def close(self) -> None:
        if self._sat is not None:
            self._sat.close()
def _check_stuck(c, faults, items, check):
        """check='reference': slow full-circuit oracle. 'cone': serial cone simulator (fast, different code path from the packed matrix)."""
        return set(run_fault_simulation(c, faults, items, reference=(check == "reference")).detected)

def _check_transition(c, faults, items, check):
        if check == "reference":
            return reference_detected(c, faults, items)
        return set(run_transition_simulation(c, faults, items).detected)

@dataclass
class MergeReport:
    circuit: str
    model: str
    unit: str
    targets: int            # testable faults, each with its own cube
    untestable: int
    merged: int             # items after merging
    kept: int               # items after merging + greedy cover
    matrix_ok: bool         # merged set detects exactly the testable faults (fast simulator)
    preserved: bool         # kept set detects them too (slow reference simulator)
    sat_calls: int
    merged_items: list = field(default_factory=list)
    final_items: list = field(default_factory=list)


def run_stuck_at(c: Circuit, limit: int = 100, fill: str = "random", seed: int = 1,check: str = "reference") -> MergeReport:
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
    fac = CubeFactory(c, limit)
    cubes: dict[Fault, Cube] = {}
    try:
        for f in faults:
            cube = fac.stuck_at(f)
            if cube is not None:
                cubes[f] = cube
    finally:
        fac.close()
    targets = list(cubes)
    groups, _ = merge_items([(cubes[f],) for f in targets])
    rng = random.Random(seed)
    patterns = [_fill(g[0], c.primary_inputs, fill, rng) for g in groups]
    det = run_packed_fault_simulation(c, faults, patterns, drop=False).detections
    matrix_ok = {f for f, i in det.items() if i} == set(targets)
    kept = greedy_cover(len(patterns), det)
    return MergeReport(c.name, "stuck-at", "patterns", len(targets), len(faults) - len(targets),
                       len(patterns), len(kept), matrix_ok, _check_stuck(c, faults, [patterns[i] for i in kept], check) == set(targets),
                       fac.sat_calls, merged_items=patterns, final_items=[patterns[i] for i in kept])


def run_transition(c: Circuit, limit: int = 100, fill: str = "random", seed: int = 1, check: str = "reference") -> MergeReport:
    faults = generate_transition_faults(c)
    fac = CubeFactory(c, limit)
    pairs: dict = {}
    untestable: dict = {}
    try:
        for tf in faults:
            c2 = fac.stuck_at(tf.stuck)
            if c2 is None:
                untestable[tf] = REASON_SA
                continue
            c1 = fac.justify(tf.net, tf.init_value)
            if c1 is None:
                untestable[tf] = REASON_INIT
                continue
            pairs[tf] = (c1, c2)
    finally:
        fac.close()
    targets = list(pairs)
    groups, _ = merge_items([pairs[f] for f in targets])
    rng = random.Random(seed)
    items = [(_fill(g[0], c.primary_inputs, fill, rng), _fill(g[1], c.primary_inputs, fill, rng))
             for g in groups]
    det = run_packed_transition_simulation(c, faults, items, drop=False).detections
    matrix_ok = {f for f, i in det.items() if i} == set(targets)
    kept = greedy_cover(len(items), det)
    return MergeReport(c.name, "transition", "pairs", len(targets), len(untestable),
                       len(items), len(kept), matrix_ok,_check_transition(c, faults, [items[i] for i in kept], check) == set(targets), 
                       fac.sat_calls, merged_items=items, final_items=[items[i] for i in kept])
def report_from_merge(c: Circuit, r: MergeReport) -> dict:
    base = {"description": "one cube per testable fault, before merging", "items": r.targets,
            "faults_total": r.targets + r.untestable, "faults_detected": r.targets}
    return compaction_to_dict(c.name, r.model, "cube_merging", c.primary_inputs, base,
                              [("merging", r.merged_items, None, r.matrix_ok),
                               ("merging + greedy", r.final_items, None, r.preserved)])

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="VISTA cube-merging compaction")
    ap.add_argument("netlist")
    ap.add_argument("--model", choices=("stuck-at", "transition"), default="stuck-at")
    ap.add_argument("--fill", choices=("0", "1", "random"), default="random")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--check", choices=("reference", "cone"), default="reference",
                    help="coverage re-check: slow oracle (default) or fast cone simulator")
    args = ap.parse_args(argv)
    c = load_circuit(args.netlist)
    run = run_stuck_at if args.model == "stuck-at" else run_transition
    r = run(c, args.limit, args.fill, args.seed, args.check)
    pct = lambda n: 100 * (1 - n / r.targets)
    print(f"{r.circuit} [{r.model}, fill={args.fill}, seed={args.seed}]: "
          f"{r.targets} testable faults, {r.untestable} untestable, SAT calls {r.sat_calls}")
    print(f"  one {r.unit[:-1]} per fault : {r.targets}")
    print(f"  after merging       : {r.merged} {r.unit} ({pct(r.merged):.1f}% fewer)")
    print(f"  merging + greedy    : {r.kept} {r.unit} ({pct(r.kept):.1f}% fewer)")
    print(f"  merged set detects exactly the testable faults: {'YES' if r.matrix_ok else 'NO  <-- BUG'}")
    how = "slow oracle" if args.check == "reference" else "cone simulator"
    print(f"  coverage preserved after greedy ({how}) : {'YES' if r.preserved else 'NO  <-- BUG'}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report_from_merge(c, r), indent=2))
        print(f"report written to {args.json}")

if __name__ == "__main__":
    main()