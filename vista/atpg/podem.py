"""Engine 3 (part 1): PODEM building blocks. The decision/backtracking loop comes in Step 11."""
from __future__ import annotations
from dataclasses import dataclass
import argparse
from enum import Enum
from vista.atpg.scoap import Scoap
from vista.atpg.dalgebra import Pair, has_x, is_effect, symbol
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.model import Circuit, Gate, GateType
from vista.rtl.parser import VerilogParser
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import CONTROLLING, INVERTING, X, from_str, non_controlling
from vista.sim.incremental import IncrementalSimulator
Objective = tuple[str, int]          # (net, desired good-machine value)
SCOAP_PARTS = frozenset({"backtrace", "frontier", "side"})

class Status(Enum):
    DETECTED = "detected"            # a PO shows D or D'
    FAILED = "failed"                # this partial assignment cannot lead to a test
    CONTINUE = "continue"            # keep searching; an objective is available

class Outcome(Enum):
    TESTED = "tested"
    REDUNDANT = "redundant"      # search exhausted: provably untestable
    ABORTED = "aborted"          # backtrack limit hit: unknown


@dataclass
class PodemResult:
    fault: Fault
    outcome: Outcome
    cube: dict[str, int]
    backtracks: int
    seconds: float = 0.0
class PodemEngine:
    def __init__(self, circuit: Circuit, fault: Fault, scoap: Scoap | None = None,
                 use: frozenset[str] | set[str] = SCOAP_PARTS) -> None:
        unknown = set(use) - SCOAP_PARTS
        if unknown:
            raise ValueError(f"unknown SCOAP parts: {sorted(unknown)}")
        self.circuit = circuit
        self.fault = fault
        self.scoap = scoap                      # None -> all naive "first X input" heuristics
        self.use = frozenset(use)               # which SCOAP components are active
        self._sim = SerialFaultSimulator(circuit)
        self._order = circuit.gates_in_topo_order()
        self._inc = IncrementalSimulator(circuit, self._order)
        self._cone = self._sim.cone_for(fault)
        fl = self.fault
        live = {g.output for g in self._cone} | (set() if fl.is_branch else {fl.net})
        forced = fl.gate if fl.is_branch else None
        # (gate, input nets that can carry an effect, is this the branch-forced gate)
        self._frontier_plan = [(g, tuple(n for n in g.inputs if n in live), g.name == forced)
                               for g in self._cone]   # gates that can ever see a fault effect
    def _on(self, part: str) -> bool:
        return self.scoap is not None and part in self.use

    # ---- implication: forward-simulate the (good, faulty) pair --------
    def imply(self, assignment: dict[str, int]) -> dict[str, Pair]:
        """Net -> (good, faulty). Unassigned PIs are X."""
        good = self._inc.update(assignment)               # event-driven, from the previous state
        bad = self._sim.simulate_faulty(good, self.fault)  # copies `good`, then walks the cone
        return {n: (good[n], bad[n]) for n in good}

    def pin_pair(self, values: dict[str, Pair], gate: Gate, pin: int) -> Pair:
        """Value seen at a gate input pin (applies a branch fault on that exact pin)."""
        g, f = values[gate.inputs[pin]]
        fl = self.fault
        if fl.is_branch and fl.gate == gate.name and fl.pin == pin:
            f = fl.value
        return (g, f)

    # ---- status queries ------------------------------------------------
    def detected(self, values: dict[str, Pair]) -> bool:
        return any(is_effect(values[po]) for po in self.circuit.primary_outputs)
    def d_frontier(self, values: dict[str, Pair]) -> list[Gate]:
        """Cone gates with an undetermined output and a fault effect on some input pin.
        Same contents and order as d_frontier_reference."""
        frontier = []
        for g, live_inputs, is_forced in self._frontier_plan:
            o = values[g.output]
            if o[0] != X and o[1] != X:                  # output fully known: not on the frontier
                continue
            if is_forced:                                # the one gate whose pin is overridden
                hit = any(is_effect(self.pin_pair(values, g, i)) for i in range(len(g.inputs)))
            else:
                hit = False
                for n in live_inputs:
                    p = values[n]
                    if p[0] != p[1] and p[0] != X and p[1] != X:   # inlined is_effect
                        hit = True
                        break
            if hit:
                frontier.append(g)
        return frontier
    def d_frontier_reference(self, values: dict[str, Pair]) -> list[Gate]:
        """Gates with an undetermined output and a fault effect on some input pin."""
        frontier = []
        for g in self._order:
            if not has_x(values[g.output]):
                continue
            if any(is_effect(self.pin_pair(values, g, i)) for i in range(len(g.inputs))):
                frontier.append(g)
        return frontier

    # ---- objective -------------------------------------------------------
        # ---- heuristic helpers ---------------------------------------------
    def _cc(self, net: str, v: int) -> int:
        return (self.scoap.cc1 if v else self.scoap.cc0)[net]

    def _xor_need(self, values: dict[str, Pair], gate: Gate, i: int, value: int) -> int:
        """Value input i must take so the XOR output reaches `value`, given known side inputs."""
        parity = sum(values[n][0] for j, n in enumerate(gate.inputs)
                     if j != i and values[n][0] != X) & 1
        return value ^ parity

    def _pick_input(self, gate: Gate, pins: list[int], value: int) -> int:
        if not self._on("backtrace") or len(pins) == 1:
            return pins[0]
        cost = lambda p: self._cc(gate.inputs[p], value)
        if value == non_controlling(gate.type):        # every input must take this value
            return max(pins, key=cost)                 # hardest first: fail early
        return min(pins, key=cost)                     # one input suffices: easiest

    # ---- objective -------------------------------------------------------
    def objective(self, values: dict[str, Pair]) -> tuple[Status, Objective | None]:
        if self.detected(values):
            return Status.DETECTED, None
        fl = self.fault
        site_good = values[fl.net][0]
        if site_good == fl.value:
            return Status.FAILED, None
        if site_good == X:
            return Status.CONTINUE, (fl.net, 1 - fl.value)
        frontier = self.d_frontier(values)
        if self._on("frontier"):                       # stable sort: ties keep topological order
            frontier.sort(key=lambda g: self.scoap.co[g.output])
        for gate in frontier:
            pins = [p for p in range(len(gate.inputs))
                    if has_x(self.pin_pair(values, gate, p))]
            if not pins:
                continue
            if not self._on("side"):
                pin = pins[0]
                want = non_controlling(gate.type) if gate.type in CONTROLLING else 0
            elif gate.type in CONTROLLING:
                want = non_controlling(gate.type)
                pin = max(pins, key=lambda p: self._cc(gate.inputs[p], want))
            else:                                      # XOR/XNOR: any side value lets D through
                pin = min(pins, key=lambda p: min(self.scoap.cc0[gate.inputs[p]],
                                                  self.scoap.cc1[gate.inputs[p]]))
                n = gate.inputs[pin]
                want = 0 if self.scoap.cc0[n] <= self.scoap.cc1[n] else 1
            return Status.CONTINUE, (gate.inputs[pin], want)
        return Status.FAILED, None
    # ---- backtrace -------------------------------------------------------
    def backtrace(self, values: dict[str, Pair], net: str, value: int) -> tuple[str, int]:
        c = self.circuit
        while not c.nets[net].is_pi:
            gate = c.gates[c.nets[net].driver]
            if gate.type in INVERTING:
                value = 1 - value
            pins = [i for i in range(len(gate.inputs))
                    if has_x(self.pin_pair(values, gate, i))]
            if not pins:
                raise RuntimeError(f"backtrace stuck at gate '{gate.name}'")
            if gate.type in (GateType.XOR, GateType.XNOR):
                if not self._on("backtrace"):
                    i = pins[0]
                else:
                    i = min(pins, key=lambda p: self._cc(
                        gate.inputs[p], self._xor_need(values, gate, p, value)))
                value = self._xor_need(values, gate, i, value)
            else:
                i = self._pick_input(gate, pins, value)
            net = gate.inputs[i]
        return net, value
    # ---- pruning ---------------------------------------------------------
    def x_path_exists(self, values: dict[str, Pair]) -> bool:
        """Can some D-frontier gate still reach a PO through undetermined (X) outputs?"""
        c = self.circuit
        seen: set[str] = set()
        todo = [g.output for g in self.d_frontier(values)]
        while todo:
            net = todo.pop()
            if net in seen:
                continue
            seen.add(net)
            if c.nets[net].is_po:
                return True
            for gname in c.nets[net].fanout:
                out = c.gates[gname].output
                if has_x(values[out]):
                    todo.append(out)
        return False

    # ---- the search ------------------------------------------------------
    def generate(self, backtrack_limit: int = 100) -> PodemResult:
        assignment: dict[str, int] = {}
        stack: list[tuple[str, int, bool]] = []      # (pi, value, already_flipped)
        backtracks = 0
        while True:
            values = self.imply(assignment)
            status, obj = self.objective(values)
            if status is Status.DETECTED:
                return PodemResult(self.fault, Outcome.TESTED, dict(assignment), backtracks)

            excited = values[self.fault.net][0] != X
            if status is Status.CONTINUE and (not excited or self.x_path_exists(values)):
                pi, val = self.backtrace(values, *obj)
                assignment[pi] = val
                stack.append((pi, val, False))
                continue

            # dead end: flip the most recent unflipped decision
            while stack:
                pi, val, flipped = stack.pop()
                if flipped:
                    del assignment[pi]               # both values tried: undo it
                    continue
                backtracks += 1
                if backtracks > backtrack_limit:
                    return PodemResult(self.fault, Outcome.ABORTED, {}, backtracks)
                assignment[pi] = 1 - val
                stack.append((pi, 1 - val, True))
                break
            else:                                    # stack exhausted, nothing left to flip
                return PodemResult(self.fault, Outcome.REDUNDANT, {}, backtracks)

# ---- inspection CLI --------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Inspect PODEM state for a fault + partial assignment")
    ap.add_argument("netlist")
    ap.add_argument("fault", help='fault id, e.g. "N10/SA1" (QUOTE IT: ids contain ->)')
    ap.add_argument("assignment", nargs="?", help="PI values in PI order, e.g. 11XXX")
    args = ap.parse_args(argv)

    c = VerilogParser().parse_file(args.netlist)
    fault = next((f for f in generate_stuck_at_faults(c) if f.id == args.fault), None)
    if fault is None:
        raise SystemExit(f"unknown fault '{args.fault}'")
    pis = c.primary_inputs
    bits = args.assignment or "X" * len(pis)
    eng = PodemEngine(c, fault)
    values = eng.imply(dict(zip(pis, from_str(bits))))

    lvl = c.levelize()
    print(f"fault {fault.id}   PI order {pis}   assignment {bits}")
    for n in sorted(values, key=lambda n: (lvl[n], n)):
        print(f"  {n:<5} L{lvl[n]}  {symbol(values[n])}")
    status, obj = eng.objective(values)
    print("status     :", status.value)
    print("D-frontier :", [g.name for g in eng.d_frontier(values)])
    if obj:
        print("objective  :", obj)
        print("backtrace  :", eng.backtrace(values, *obj), "(PI, value)")


if __name__ == "__main__":
    main()