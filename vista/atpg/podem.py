"""Engine 3 (part 1): PODEM building blocks. The decision/backtracking loop comes in Step 11."""
from __future__ import annotations

import argparse
from enum import Enum

from vista.atpg.dalgebra import Pair, has_x, is_effect, symbol
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.model import Circuit, Gate, GateType
from vista.rtl.parser import VerilogParser
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import CONTROLLING, INVERTING, X, from_str, non_controlling

Objective = tuple[str, int]          # (net, desired good-machine value)


class Status(Enum):
    DETECTED = "detected"            # a PO shows D or D'
    FAILED = "failed"                # this partial assignment cannot lead to a test
    CONTINUE = "continue"            # keep searching; an objective is available


class PodemEngine:
    def __init__(self, circuit: Circuit, fault: Fault) -> None:
        self.circuit = circuit
        self.fault = fault
        self._sim = SerialFaultSimulator(circuit)
        self._order = circuit.gates_in_topo_order()

    # ---- implication: forward-simulate the (good, faulty) pair --------
    def imply(self, assignment: dict[str, int]) -> dict[str, Pair]:
        """Net -> (good, faulty). Unassigned PIs are X."""
        good = self._sim.simulate(assignment)
        bad = self._sim.simulate(assignment, self.fault)
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
        """Gates with an undetermined output and a fault effect on some input pin."""
        frontier = []
        for g in self._order:
            if not has_x(values[g.output]):
                continue
            if any(is_effect(self.pin_pair(values, g, i)) for i in range(len(g.inputs))):
                frontier.append(g)
        return frontier

    # ---- objective -------------------------------------------------------
    def objective(self, values: dict[str, Pair]) -> tuple[Status, Objective | None]:
        if self.detected(values):
            return Status.DETECTED, None
        fl = self.fault
        site_good = values[fl.net][0]
        if site_good == fl.value:                       # site can no longer be excited
            return Status.FAILED, None
        if site_good == X:                              # goal 1: excite the fault
            return Status.CONTINUE, (fl.net, 1 - fl.value)
        # goal 2: advance the fault effect through a D-frontier gate.
        # Heuristic (swappable later): take the first frontier gate in topological order.
        for gate in self.d_frontier(values):
            for pin, net in enumerate(gate.inputs):
                if has_x(self.pin_pair(values, gate, pin)):
                    # side input -> non-controlling value (XOR/XNOR have none: any value works)
                    want = non_controlling(gate.type) if gate.type in CONTROLLING else 0
                    return Status.CONTINUE, (net, want)
        return Status.FAILED, None                      # empty D-frontier

    # ---- backtrace -------------------------------------------------------
    def backtrace(self, values: dict[str, Pair], net: str, value: int) -> tuple[str, int]:
        """Walk from (net, value) back to an unassigned PI; return (pi, value_to_try)."""
        c = self.circuit
        while not c.nets[net].is_pi:
            gate = c.gates[c.nets[net].driver]
            if gate.type in INVERTING:
                value = 1 - value                       # now: required XOR/OR/AND-family value
            pins = [i for i in range(len(gate.inputs))
                    if has_x(self.pin_pair(values, gate, i))]
            if not pins:
                raise RuntimeError(f"backtrace stuck at gate '{gate.name}'")
            i = pins[0]                                 # heuristic: first undetermined input
            if gate.type in (GateType.XOR, GateType.XNOR):
                parity = sum(values[n][0] for j, n in enumerate(gate.inputs)
                             if j != i and values[n][0] != X) & 1
                value ^= parity                         # make the parity come out right
            net = gate.inputs[i]
        return net, value


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