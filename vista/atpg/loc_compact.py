"""Engine 3 (part 8): launch-on-capture compaction.
Joint PODEM over both frames gives cubes with don't-cares; cubes are merged, then greedy cover."""
from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field

from vista.atpg.compact import greedy_cover
from vista.atpg.loc import (REASON_F2, REASON_HELD, REASON_LAUNCH, LocFaultSimulator,
                            generate_loc_tests)
from vista.atpg.merge import merge_items
from vista.atpg.podem import Outcome, PodemEngine
from vista.atpg.sat import SatAtpg
from vista.atpg.transition_atpg import _fill, reference_detected
from vista.faults.transition import TransitionFault, generate_transition_faults
from vista.patterns import write_patterns
from vista.rtl.loader import load_circuit
from vista.rtl.loc import LocModel
from vista.rtl.model import Circuit, CircuitError

Cube = dict[str, int]


@dataclass
class LocCompactReport:
    model: LocModel
    faults: list[TransitionFault]
    cubes: dict[TransitionFault, Cube] = field(default_factory=dict)
    untestable: dict[TransitionFault, str] = field(default_factory=dict)
    podem_cubes: int = 0
    sat_cubes: int = 0
    merged: list[Cube] = field(default_factory=list)       # filled vectors after merging
    final: list[Cube] = field(default_factory=list)        # after merging + greedy cover
    baseline: int = 0                                      # vectors from the SAT-only flow
    matrix_ok: bool = False         # merged set detects exactly the testable faults
    preserved: bool = False         # final set does too (slow base-circuit oracle)
    classification_ok: bool = False  # same untestable set as the exact SAT-only flow


def compact_loc(c: Circuit, hold_pi: bool = True, limit: int = 100, fill: str = "random",
                seed: int = 1) -> LocCompactReport:
    model = LocModel(c, hold_pi)
    faults = generate_transition_faults(c)
    rep = LocCompactReport(model, faults)
    sat: SatAtpg | None = None
    try:
        for f in faults:
            target = model.target(f)
            if target is None:
                rep.untestable[f] = REASON_HELD
                continue
            init_net, init_val, stuck = target
            req = [(init_net, init_val)]
            r = PodemEngine(model.circuit, stuck, require=req).generate(limit)
            if r.outcome is Outcome.TESTED:
                rep.cubes[f] = r.cube
                rep.podem_cubes += 1
                continue
            sat = sat or SatAtpg(model.circuit)
            s = sat.generate(stuck, require=req)
            if s.outcome is Outcome.TESTED:
                assert r.outcome is not Outcome.REDUNDANT, \
                    f"PODEM proved {f.id} untestable but SAT found a test"
                rep.cubes[f] = s.pattern
                rep.sat_cubes += 1
                continue
            alone = sat.generate(stuck)
            rep.untestable[f] = REASON_LAUNCH if alone.outcome is Outcome.TESTED else REASON_F2
    finally:
        if sat is not None:
            sat.close()

    targets = list(rep.cubes)
    groups, _ = merge_items([(rep.cubes[f],) for f in targets])
    rng, pis = random.Random(seed), model.circuit.primary_inputs
    rep.merged = [_fill(g[0], pis, fill, rng) for g in groups]

    sim = LocFaultSimulator(model)
    det: dict[TransitionFault, list[int]] = {f: [] for f in faults}
    for i, v in enumerate(rep.merged):
        good = sim.good(v)
        for f in faults:
            if sim.detects_from_good(good, f):
                det[f].append(i)
    rep.matrix_ok = {f for f in faults if det[f]} == set(targets)
    kept = greedy_cover(len(rep.merged), det)
    rep.final = [rep.merged[i] for i in kept]
    pairs = [model.pair_of(v) for v in rep.final]           # base circuit, independent of the expansion
    rep.preserved = reference_detected(c, faults, pairs) == set(targets)

    base = generate_loc_tests(c, faults, hold_pi)
    rep.baseline = len(base.vectors)
    rep.classification_ok = set(base.untestable) == set(rep.untestable)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vista loc-compact",
                                 description="Launch-on-capture compaction (joint PODEM + merging)")
    ap.add_argument("netlist")
    ap.add_argument("--free-pi", action="store_true")
    ap.add_argument("--fill", choices=("0", "1", "random"), default="random")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--write-vectors", metavar="FILE",
                    help="write the final vectors; replay with `vista matrix --model loc`")
    args = ap.parse_args(argv)

    c = load_circuit(args.netlist)
    try:
        r = compact_loc(c, not args.free_pi, args.limit, args.fill, args.seed)
    except CircuitError as e:
        raise SystemExit(f"error: {e}")
    t = len(r.cubes)
    print(f"{c.name} [LOC compaction, {'PIs free' if args.free_pi else 'PIs held'}]: "
          f"{t} testable, {len(r.untestable)} untestable")
    print(f"  cubes             : {r.podem_cubes} from joint PODEM, {r.sat_cubes} from SAT fallback")
    print(f"  SAT-only baseline : {r.baseline} vectors")
    print(f"  after merging     : {len(r.merged)} vectors")
    print(f"  merging + greedy  : {len(r.final)} vectors")
    print(f"  merged set detects exactly the testable faults : {'YES' if r.matrix_ok else 'NO  <-- BUG'}")
    print(f"  coverage preserved (base-circuit oracle)       : {'YES' if r.preserved else 'NO  <-- BUG'}")
    print(f"  same untestable set as the exact SAT flow      : {'YES' if r.classification_ok else 'NO  <-- BUG'}")
    if args.write_vectors:
        write_patterns(args.write_vectors, r.model.circuit, r.final, "stuck-at")
        print(f"vectors written to {args.write_vectors}")
    return 0 if (r.matrix_ok and r.preserved and r.classification_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())