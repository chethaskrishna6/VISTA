"""Engine 3 (part 3): single-net justification. PODEM with one objective and no fault."""
from __future__ import annotations

from dataclasses import dataclass

from vista.atpg.podem import Outcome
from vista.rtl.model import Circuit, GateType
from vista.sim.logic import INVERTING, X
from vista.sim.simulator import LogicSimulator


@dataclass
class JustifyResult:
    net: str
    value: int
    outcome: Outcome            # TESTED = justified, REDUNDANT = impossible, ABORTED = limit hit
    cube: dict[str, int]        # assigned PIs only (empty unless justified)
    backtracks: int


class Justifier:
    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit
        self._sim = LogicSimulator(circuit)

    def _backtrace(self, values: dict[str, int], net: str, value: int) -> tuple[str, int]:
        c = self.circuit
        while not c.nets[net].is_pi:
            gate = c.gates[c.nets[net].driver]
            if gate.type in INVERTING:
                value = 1 - value
            pins = [i for i, n in enumerate(gate.inputs) if values[n] == X]
            i = pins[0]                     # net is X, so some input is X
            if gate.type in (GateType.XOR, GateType.XNOR):
                value ^= sum(values[n] for j, n in enumerate(gate.inputs)
                             if j != i and values[n] != X) & 1
            net = gate.inputs[i]
        return net, value

    def justify(self, net: str, value: int, backtrack_limit: int = 100) -> JustifyResult:
        if net not in self.circuit.nets:
            raise ValueError(f"unknown net '{net}'")
        if value not in (0, 1):
            raise ValueError(f"value must be 0/1, got {value!r}")
        assignment: dict[str, int] = {}
        stack: list[tuple[str, int, bool]] = []
        backtracks = 0
        while True:
            values = self._sim.simulate(assignment)
            if values[net] == value:
                return JustifyResult(net, value, Outcome.TESTED, dict(assignment), backtracks)
            if values[net] == X:
                pi, v = self._backtrace(values, net, value)
                assignment[pi] = v
                stack.append((pi, v, False))
                continue
            while stack:                    # net settled at the wrong value: flip last decision
                pi, v, flipped = stack.pop()
                if flipped:
                    del assignment[pi]
                    continue
                backtracks += 1
                if backtracks > backtrack_limit:
                    return JustifyResult(net, value, Outcome.ABORTED, {}, backtracks)
                assignment[pi] = 1 - v
                stack.append((pi, 1 - v, True))
                break
            else:
                return JustifyResult(net, value, Outcome.REDUNDANT, {}, backtracks)