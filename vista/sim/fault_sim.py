"""Engine 4 (part 1): serial stuck-at fault simulation, one fault at a time."""
from __future__ import annotations

from itertools import product
from typing import Iterator

from vista.faults.stuck_at import Fault
from vista.rtl.model import Circuit, Gate 
from vista.sim.logic import ONE, VALUES, X, ZERO, eval_gate, to_str

MAX_EXHAUSTIVE_PIS = 16


class SerialFaultSimulator:
    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit
        self._order = circuit.gates_in_topo_order()
        self._pis = circuit.primary_inputs
        self._pos = circuit.primary_outputs
        self._gate_index = {g.name: i for i, g in enumerate(self._order)}
        self._cones: dict[tuple[str, str], list[Gate]] = {}

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
        # ---- cone-restricted faulty simulation ----------------------------
    def _cone(self, key: tuple[str, str], starts: list[str]) -> list[Gate]:
        """Gates that can see a fault effect, in topological order (cached per site)."""
        cone = self._cones.get(key)
        if cone is None:
            seen: set[str] = set()
            todo = list(starts)
            while todo:
                name = todo.pop()
                if name in seen:
                    continue
                seen.add(name)
                todo.extend(self.circuit.nets[self.circuit.gates[name].output].fanout)
            cone = [self._order[i] for i in sorted(self._gate_index[n] for n in seen)]
            self._cones[key] = cone
        return cone

    def simulate_faulty(self, good: dict[str, int], fault: Fault) -> dict[str, int]:
        """Faulty-machine value of every net, given the good-machine values of the same pattern.
        Equivalent to simulate(pattern, fault), but only re-evaluates gates in the fault's
        fanout cone whose inputs changed."""
        self._check_fault(fault)
        values = dict(good)
        if good[fault.net] == fault.value:
            return values                                  # not excited: nothing changes
        changed: set[str] = set()
        if fault.is_branch:
            forced = fault.gate
            cone = self._cone(("b", forced), [forced])
        else:
            forced = None
            values[fault.net] = fault.value
            changed.add(fault.net)
            cone = self._cone(("s", fault.net), self.circuit.nets[fault.net].fanout)
        for g in cone:
            if g.name != forced and not any(n in changed for n in g.inputs):
                continue                                   # no event reaches this gate
            ins = [values[n] for n in g.inputs]
            if g.name == forced:
                ins[fault.pin] = fault.value               # only this one pin is stuck
            out = eval_gate(g.type, ins)
            if out != values[g.output]:
                values[g.output] = out
                changed.add(g.output)
        return values

    def detected_from_good(self, good: dict[str, int], fault: Fault) -> list[str]:
        """Same detection rule as detected_outputs, from full good-machine net values."""
        bad = self.simulate_faulty(good, fault)
        return [po for po in self._pos
                if good[po] != X and bad[po] != X and good[po] != bad[po]]