"""Engine 4 (part 4): pattern-parallel 3-valued fault simulation using Python big ints."""
from __future__ import annotations

from vista.faults.stuck_at import Fault
from vista.rtl.model import Circuit, GateType
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import INVERTING, ONE, X, ZERO
from vista.sim.pattern_sim import SimReport
from vista.faults.transition import TransitionFault
from vista.sim.transition_sim import TransitionReport
Planes = tuple[int, int]          # (p1, p0): bit i of p1 = pattern i is 1, of p0 = pattern i is 0
AND_FAM = (GateType.AND, GateType.NAND)
OR_FAM = (GateType.OR, GateType.NOR)


def eval_packed(gtype: GateType, ins: list[Planes]) -> Planes:
    if gtype in AND_FAM:
        o1, o0 = ins[0]
        for a1, a0 in ins[1:]:
            o1, o0 = o1 & a1, o0 | a0
    elif gtype in OR_FAM:
        o1, o0 = ins[0]
        for a1, a0 in ins[1:]:
            o1, o0 = o1 | a1, o0 & a0
    elif gtype in (GateType.XOR, GateType.XNOR):
        o1, o0 = ins[0]
        for a1, a0 in ins[1:]:
            o1, o0 = (o1 & a0) | (o0 & a1), (o1 & a1) | (o0 & a0)
    else:                                          # BUF / NOT
        o1, o0 = ins[0]
    return (o0, o1) if gtype in INVERTING else (o1, o0)


def _set_bits(m: int) -> list[int]:
    out = []
    while m:
        low = m & -m
        out.append(low.bit_length() - 1)
        m ^= low
    return out


class PackedSimulator:
    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit
        self._ser = SerialFaultSimulator(circuit)      # cones + fault validation only
        self._order = circuit.gates_in_topo_order()
        self._pis = circuit.primary_inputs
        self._pos = circuit.primary_outputs

    def good(self, patterns: list[dict[str, int]]) -> tuple[dict[str, Planes], int]:
        """Good-machine planes for every net, and the all-ones mask of this block."""
        planes = {pi: [0, 0] for pi in self._pis}
        for i, p in enumerate(patterns):
            for pi in self._pis:
                v = p.get(pi, X)
                if v == ONE:
                    planes[pi][0] |= 1 << i
                elif v == ZERO:
                    planes[pi][1] |= 1 << i
        values: dict[str, Planes] = {pi: (a, b) for pi, (a, b) in planes.items()}
        for g in self._order:
            values[g.output] = eval_packed(g.type, [values[n] for n in g.inputs])
        return values, (1 << len(patterns)) - 1

    def detect_mask(self, good: dict[str, Planes], fault: Fault, mask: int) -> int:
        """Bit i set <=> pattern i detects `fault` (same X rule as the serial simulator)."""
        cone = self._ser.cone_for(fault)               # also validates the fault
        forced: Planes = (mask, 0) if fault.value else (0, mask)
        vals: dict[str, Planes] = {}
        if fault.is_branch:
            gate = self.circuit.gates[fault.gate]
            if good[gate.inputs[fault.pin]] == forced:
                return 0                               # pin already stuck value everywhere
            forced_gate, pin = fault.gate, fault.pin
        else:
            if good[fault.net] == forced:
                return 0
            vals[fault.net] = forced
            forced_gate, pin = None, -1
        for g in cone:
            if g.name != forced_gate and not any(n in vals for n in g.inputs):
                continue                               # no event reaches this gate
            ins = [vals.get(n, good[n]) for n in g.inputs]
            if g.name == forced_gate:
                ins[pin] = forced
            out = eval_packed(g.type, ins)
            if out != good[g.output]:
                vals[g.output] = out
        det = 0
        for po in self._pos:
            if po in vals:
                b1, b0 = vals[po]
                g1, g0 = good[po]
                det |= (g1 & b0) | (g0 & b1)
        return det


def run_packed_fault_simulation(circuit: Circuit, faults: list[Fault],
                                patterns: list[dict[str, int]],
                                weights: dict[Fault, int] | None = None,
                                drop: bool = True, block: int = 64) -> SimReport:
    """Drop-in for run_fault_simulation: same SimReport, same detection indices."""
    if block < 1:
        raise ValueError("block must be >= 1")
    sim = PackedSimulator(circuit)
    detections: dict[Fault, list[int]] = {f: [] for f in faults}
    active = list(faults)
    for start in range(0, len(patterns), block):
        good, mask = sim.good(patterns[start:start + block])
        keep = []
        for f in active:
            m = sim.detect_mask(good, f, mask)
            if m:
                idxs = _set_bits(m)
                detections[f].extend(start + i for i in (idxs[:1] if drop else idxs))
                if drop:
                    continue
            keep.append(f)
        active = keep
        if not active:
            break
    w = {f: (weights or {}).get(f, 1) for f in faults}
    return SimReport(circuit.name, circuit.primary_inputs, circuit.primary_outputs,
                     patterns, faults, w, drop, detections)
def run_packed_transition_simulation(circuit: Circuit, faults: list[TransitionFault],
                                     pairs: list, drop: bool = True,
                                     block: int = 64) -> TransitionReport:
    """Drop-in for run_transition_simulation: same report, same detection indices."""
    if block < 1:
        raise ValueError("block must be >= 1")
    sim = PackedSimulator(circuit)
    detections: dict[TransitionFault, list[int]] = {f: [] for f in faults}
    active = list(faults)
    for start in range(0, len(pairs), block):
        chunk = pairs[start:start + block]
        g1, mask = sim.good([a for a, _ in chunk])
        g2, _ = sim.good([b for _, b in chunk])
        keep = []
        for f in active:
            p1, p0 = g1[f.net]
            init = p1 if f.init_value else p0            # pairs whose frame 1 initializes the site
            m = (init & sim.detect_mask(g2, f.stuck, mask)) if init else 0
            if m:
                idxs = _set_bits(m)
                detections[f].extend(start + i for i in (idxs[:1] if drop else idxs))
                if drop:
                    continue
            keep.append(f)
        active = keep
        if not active:
            break
    return TransitionReport(circuit.name, circuit.primary_inputs, pairs, faults, detections, drop)