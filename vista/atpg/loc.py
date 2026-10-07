"""Engine 3 (part 7): launch-on-capture transition ATPG on the two-frame expansion (exact, SAT)."""
from __future__ import annotations

import argparse
import time
from collections import Counter
from dataclasses import dataclass, field

from vista.atpg.podem import Outcome
from vista.atpg.sat import SatAtpg
from vista.atpg.transition_atpg import generate_transition_tests, reference_detected
from vista.faults.transition import TransitionFault, generate_transition_faults
from vista.rtl.loader import load_circuit
from vista.rtl.loc import LocModel
from vista.rtl.model import Circuit, CircuitError
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import to_str

REASON_HELD = "held primary input"               # PI is constant across frames: no transition
REASON_F2 = "undetectable in capture frame"      # even ignoring the init, no vector detects it
REASON_LAUNCH = "launch/init conflict"           # detectable alone, but not together with the init

Pattern = dict[str, int]


class LocFaultSimulator:
    """One vector over the expanded PIs vs. a transition fault, via the expanded circuit."""

    def __init__(self, model: LocModel) -> None:
        self.model = model
        self._sim = SerialFaultSimulator(model.circuit)

    def good(self, vec: Pattern) -> dict[str, int]:
        return self._sim.simulate(vec)

    def detects_from_good(self, good: dict[str, int], tf: TransitionFault) -> bool:
        target = self.model.target(tf)
        if target is None:
            return False
        init_net, init_val, stuck = target
        if good[init_net] != init_val:                 # X never initializes
            return False
        return bool(self._sim.detected_from_good(good, stuck))

    def detects(self, vec: Pattern, tf: TransitionFault) -> bool:
        return self.detects_from_good(self.good(vec), tf)


@dataclass
class LocResult:
    model: LocModel
    faults: list[TransitionFault]
    vectors: list[Pattern] = field(default_factory=list)
    covered_by: dict[TransitionFault, int] = field(default_factory=dict)
    untestable: dict[TransitionFault, str] = field(default_factory=dict)
    seconds: float = 0.0

    @property
    def coverage(self) -> float:
        return len(self.covered_by) / len(self.faults) if self.faults else 1.0

    @property
    def efficiency(self) -> float:
        return (len(self.covered_by) + len(self.untestable)) / len(self.faults) if self.faults else 1.0


def generate_loc_tests(c: Circuit, faults: list[TransitionFault] | None = None,
                       hold_pi: bool = True) -> LocResult:
    model = LocModel(c, hold_pi)
    faults = generate_transition_faults(c) if faults is None else faults
    sim, res = LocFaultSimulator(model), LocResult(model, faults)
    t0 = time.perf_counter()
    sat = SatAtpg(model.circuit)
    try:
        for f in faults:
            if f in res.covered_by or f in res.untestable:
                continue
            target = model.target(f)
            if target is None:
                res.untestable[f] = REASON_HELD
                continue
            init_net, init_val, stuck = target
            r = sat.generate(stuck, require=[(init_net, init_val)])
            if r.outcome is Outcome.REDUNDANT:
                alone = sat.generate(stuck)
                res.untestable[f] = REASON_LAUNCH if alone.outcome is Outcome.TESTED else REASON_F2
                continue
            idx = len(res.vectors)
            res.vectors.append(r.pattern)
            good = sim.good(r.pattern)
            for g in faults:                           # fault dropping with the two-frame simulator
                if (g not in res.covered_by and g not in res.untestable
                        and sim.detects_from_good(good, g)):
                    res.covered_by[g] = idx
            assert f in res.covered_by, f"vector failed to detect its own target {f.id}"
    finally:
        sat.close()
    res.seconds = time.perf_counter() - t0
    return res


def reference_agrees(c: Circuit, res: LocResult) -> bool:
    """Independent oracle: turn each LOC vector into an enhanced-scan pair on the BASE circuit and
    run the slow full-circuit transition check from Step 21."""
    pairs = [res.model.pair_of(v) for v in res.vectors]
    return reference_detected(c, res.faults, pairs) == set(res.covered_by)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vista loc-atpg",
                                 description="Launch-on-capture transition ATPG (full-scan circuits)")
    ap.add_argument("netlist")
    ap.add_argument("--free-pi", action="store_true",
                    help="frame-2 PIs get their own bits (default: PIs held constant)")
    ap.add_argument("--compare", action="store_true", help="also run enhanced-scan ATPG and compare")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args(argv)

    c = load_circuit(args.netlist)
    try:
        res = generate_loc_tests(c, hold_pi=not args.free_pi)
    except CircuitError as e:
        raise SystemExit(f"error: {e}")
    n = len(res.faults)
    cnt = lambda rising: sum(1 for f in res.faults if f.rising == rising and f in res.covered_by)
    tot = lambda rising: sum(1 for f in res.faults if f.rising == rising)
    mode = "PIs free in frame 2" if args.free_pi else "PIs held"
    print(f"{c.name} [launch-on-capture, {mode}]: {n} transition faults, {len(c.scan_cells)} scan cells")
    print(f"vectors     : {len(res.vectors)}   (one scan load + launch + capture each)")
    print(f"coverage    : {len(res.covered_by)}/{n} = {100 * res.coverage:.2f}%"
          f"   (STR {cnt(True)}/{tot(True)}, STF {cnt(False)}/{tot(False)})")
    print(f"efficiency  : {100 * res.efficiency:.2f}%")
    print(f"untestable  : {len(res.untestable)} {dict(Counter(res.untestable.values()))}")
    print(f"  ids       : {[f.id for f in res.untestable][:12]}")
    print(f"time        : {res.seconds:.2f}s")
    rc = 0
    if args.compare:
        enh = generate_transition_tests(c, res.faults)
        sub = set(res.covered_by) <= set(enh.covered_by)
        print(f"enhanced scan: {len(enh.covered_by)}/{n} detected with {len(enh.pairs)} pairs")
        print(f"LOC-detected is a subset of enhanced-detected: {'YES' if sub else 'NO  <-- BUG'}")
        rc |= 0 if sub else 1
    if not args.no_verify:
        ok = reference_agrees(c, res)
        print(f"independent re-simulation: {'AGREES' if ok else 'MISMATCH <-- BUG'} ({len(res.covered_by)} detected)")
        rc |= 0 if ok else 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())