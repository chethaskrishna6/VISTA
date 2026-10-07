"""Event-driven good-machine simulation that updates from a changing PI assignment."""
from __future__ import annotations

import heapq

from vista.rtl.model import Circuit, Gate
from vista.sim.logic import VALUES, X, eval_gate


class IncrementalSimulator:
    def __init__(self, circuit: Circuit, order: list[Gate] | None = None) -> None:
        self.circuit = circuit
        self._order = order if order is not None else circuit.gates_in_topo_order()
        self._rank = {g.name: i for i, g in enumerate(self._order)}
        self._pis = set(circuit.primary_inputs)
        self.values: dict[str, int] = {n: X for n in circuit.nets}   # all-X = empty assignment
        self._assignment: dict[str, int] = {}

    def update(self, assignment: dict[str, int]) -> dict[str, int]:
        """Net -> good value for `assignment` (unassigned PIs are X). The returned dict is
        internal state: copy it if you need it after the next update."""
        unknown = set(assignment) - self._pis
        if unknown:
            raise ValueError(f"not primary inputs: {sorted(unknown)}")
        nets, heap, queued = self.circuit.nets, [], set()

        def push_fanout(net: str) -> None:
            for gname in nets[net].fanout:
                if gname not in queued:
                    queued.add(gname)
                    heapq.heappush(heap, self._rank[gname])

        for pi in self._assignment.keys() | assignment.keys():
            new, old = assignment.get(pi, X), self._assignment.get(pi, X)
            if new not in VALUES:
                raise ValueError(f"invalid value {new!r} on '{pi}'")
            if new != old:
                self.values[pi] = new
                push_fanout(pi)
        while heap:
            g = self._order[heapq.heappop(heap)]
            out = eval_gate(g.type, [self.values[n] for n in g.inputs])
            if out != self.values[g.output]:
                self.values[g.output] = out
                push_fanout(g.output)
        self._assignment = dict(assignment)
        return self.values