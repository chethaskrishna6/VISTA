"""Hybrid ATPG: PODEM first, then the complete SAT engine on whatever is unresolved."""
from __future__ import annotations

from vista.atpg.generate import AtpgResult, generate_test_set
from vista.atpg.podem import Outcome, SCOAP_PARTS
from vista.atpg.sat import SatAtpg
from vista.atpg.scoap import Scoap
from vista.faults.stuck_at import Fault
from vista.rtl.model import Circuit
from vista.sim.fault_sim import SerialFaultSimulator


def run_hybrid(circuit: Circuit, faults: list[Fault],
               weights: dict[Fault, int] | None = None,
               backtrack_limit: int = 100, fill: int = 0,
               scoap: Scoap | None = None,
               use: frozenset[str] = SCOAP_PARTS) -> AtpgResult:
    res = generate_test_set(circuit, faults, weights, backtrack_limit, fill, scoap, use)
    todo = res.unresolved
    if not todo:
        return res
    sim = SerialFaultSimulator(circuit)
    sat = SatAtpg(circuit)
    try:
        for f in todo:
            if f in res.covered_by:                  # retired by an earlier SAT pattern
                continue
            r = sat.generate(f)
            res.sat_seconds += r.seconds
            if r.outcome is Outcome.REDUNDANT:
                res.sat_redundant.append(f)
                continue
            idx = len(res.patterns)
            res.patterns.append(r.pattern)           # fully specified: no don't-cares
            res.cubes.append(dict(r.pattern))
            res.sat_patterns += 1
            good = sim.simulate(r.pattern)
            for g in faults:
                if g not in res.covered_by and sim.detected_from_good(good, g):
                    res.covered_by[g] = idx
            assert f in res.covered_by, f"SAT vector failed to detect {f.id}"
    finally:
        sat.close()
    return res