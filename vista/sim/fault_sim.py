"""Engine 4 (part 1): serial stuck-at fault simulation, one fault at a time."""
from __future__ import annotations

from itertools import product
from typing import Iterator

from vista.faults.stuck_at import Fault
from vista.rtl.model import Circuit
from vista.sim.logic import ONE, VALUES, X, ZERO, eval_gate, to_str

MAX_EXHAUSTIVE_PIS = 16


class SerialFaultSimulator:
    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit
        self._order = circuit.gates_in_topo_order()
        self._pis = circuit.primary_inputs
        self._pos = circuit.primary_outputs

    # ---- validation ---------------------------------------------------
    def _check_fault(self, fault: Fault) -> None:
        if fault.net not in self.circuit.nets:
            raise ValueError(f"unknown net '{fault.net}' in fault {fault.id}")
        if fault.is_branch:
            gate = self.circuit.gates.get(fault.gate)
            if gate is None or fault.pin >= len(gate.inputs) or gate.inputs[fault.pin] != fault.net:
                raise ValueError(f"fault {fault.id} does not match the netlist")

    # ---- simulation ---------------------------------------------------
    def simulate(self, pattern: dict[str, int], fault: Fault | None = None) -> dict[str, int]:
        """Value of every net with `fault` injected (fault=None -> good circuit)."""
        if fault is not None:
            self._check_fault(fault)
        unknown = set(pattern) - set(self._pis)
        if unknown:
            raise ValueError(f"not primary inputs: {sorted(unknown)}")
        values = {pi: pattern.get(pi, X) for pi in self._pis}
        for pi, v in values.items():
            if v not in VALUES:
                raise ValueError(f"invalid value {v!r} on '{pi}'")

        stem = fault is not None and not fault.is_branch
        branch = fault is not None and fault.is_branch
        if stem and fault.net in values:                  # stem fault on a PI
            values[fault.net] = fault.value
        for g in self._order:
            ins = [values[n] for n in g.inputs]
            if branch and g.name == fault.gate:
                ins[fault.pin] = fault.value              # only this one pin is stuck
            out = eval_gate(g.type, ins)
            if stem and g.output == fault.net:
                out = fault.value                         # every consumer sees it
            values[g.output] = out
        return values

    def outputs(self, pattern: dict[str, int], fault: Fault | None = None) -> dict[str, int]:
        values = self.simulate(pattern, fault)
        return {po: values[po] for po in self._pos}

    # ---- detection ----------------------------------------------------
    def detected_outputs(self, pattern: dict[str, int], fault: Fault,
                         good: dict[str, int] | None = None) -> list[str]:
        """POs where good and faulty values are both known and differ.
        X on either side is NOT counted (conservative; 'potential detects' ignored).
        Pass `good` (from self.outputs(pattern)) to avoid recomputing it per fault."""
        good = self.outputs(pattern) if good is None else good
        bad = self.outputs(pattern, fault)
        return [po for po in self._pos
                if good[po] != X and bad[po] != X and good[po] != bad[po]]

    def detects(self, pattern: dict[str, int], fault: Fault) -> bool:
        return bool(self.detected_outputs(pattern, fault))

    # ---- exhaustive behavior signature (small circuits) ---------------
    def exhaustive_patterns(self) -> Iterator[dict[str, int]]:
        n = len(self._pis)
        if n > MAX_EXHAUSTIVE_PIS:
            raise ValueError(f"{n} PIs is too many for exhaustive simulation")
        for bits in product((ZERO, ONE), repeat=n):      # first PI = MSB, like golden.py
            yield dict(zip(self._pis, bits))

    def signature(self, fault: Fault | None = None) -> tuple[str, ...]:
        """Output string for every input vector. Equal signatures = equivalent behavior."""
        return tuple(to_str(self.outputs(p, fault).values()) for p in self.exhaustive_patterns())