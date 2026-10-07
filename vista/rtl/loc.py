"""Engine 1: launch-on-capture (broadside) two-frame expansion of a full-scan circuit."""
from __future__ import annotations

from vista.faults.stuck_at import Fault
from vista.faults.transition import TransitionFault
from vista.rtl.model import Circuit, CircuitError, GateType
from vista.rtl.scan import isolate_po_fanout
from vista.sim.logic import X
from vista.sim.simulator import LogicSimulator

F1, F2 = "@1", "@2"
Target = tuple[str, int, Fault]      # (frame-1 net, init value, frame-2 stuck-at fault)


class LocModel:
    """circuit = the expanded combinational circuit. Its PIs are the base PIs and scan Q nets
    (frame 1), plus `<pi>@2` for each true PI when hold_pi is False. Its POs are the base POs, frame 2."""

    def __init__(self, base: Circuit, hold_pi: bool = True) -> None:
        if not base.scan_cells:
            raise CircuitError("launch-on-capture needs a full-scan circuit (no flip-flops found)")
        bad = [n for n in list(base.nets) + list(base.gates) if "@" in n]
        if bad:
            raise CircuitError(f"names containing '@' are reserved for time frames: {bad[:5]}")
        self.base, self.hold_pi = base, hold_pi
        self._d_of = dict(base.scan_cells)                       # Q net -> D net
        self._pis = base.primary_inputs
        self._pi_set = set(self._pis)
        self._free = [p for p in self._pis if p not in self._d_of]   # true primary inputs
        self._free_set = set(self._free)
        self._lsim = LogicSimulator(base)
        self._targets: dict[TransitionFault, Target | None] = {}
        self.circuit = self._build()

    def f1(self, net: str) -> str:
        return net if net in self._pi_set else net + F1

    def f2(self, net: str) -> str:
        if net in self._d_of:
            return net + F2                                      # Q in frame 2 = BUF of frame-1 D
        if net in self._free_set and self.hold_pi:
            return net                                           # held: same PI as frame 1
        return net + F2

    def _build(self) -> Circuit:
        b = self.base
        ex = Circuit(b.name + "_loc")
        for p in self._pis:
            ex.mark_pi(p)
        if not self.hold_pi:
            for p in self._free:
                ex.mark_pi(p + F2)
        order = b.gates_in_topo_order()
        for g in order:
            ex.add_gate(g.name + F1, g.type, self.f1(g.output), [self.f1(n) for n in g.inputs])
        for q, d in b.scan_cells:
            ex.add_gate(q + F2, GateType.BUF, q + F2, [self.f1(d)])
        for g in order:
            ex.add_gate(g.name + F2, g.type, self.f2(g.output), [self.f2(n) for n in g.inputs])
        for po in b.primary_outputs:
            ex.mark_po(self.f2(po))
        ex.validate()
        return isolate_po_fanout(ex)

    def target(self, tf: TransitionFault) -> Target | None:
        """None if the fault can never transition (a held primary input)."""
        if tf not in self._targets:
            net2 = self.f2(tf.net)
            if tf.is_branch:
                stuck = Fault(net2, tf.init_value, tf.gate + F2, tf.pin)
            elif self.hold_pi and tf.net in self._free_set:
                self._targets[tf] = None
                return None
            else:
                stuck = Fault(net2, tf.init_value)
            self._targets[tf] = (self.f1(tf.net), tf.init_value, stuck)
        return self._targets[tf]

    def pair_of(self, vec: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
        """The enhanced-scan (V1, V2) pair on the BASE circuit that this LOC vector produces.
        Computed with the base circuit's own simulator, so it is independent of the expansion."""
        v1 = {p: vec.get(p, X) for p in self._pis}
        s1 = self._lsim.simulate(v1)
        v2 = {}
        for p in self._pis:
            if p in self._d_of:
                v2[p] = s1[self._d_of[p]]                        # launch: captured state
            else:
                v2[p] = vec.get(p, X) if self.hold_pi else vec.get(p + F2, X)
        return v1, v2