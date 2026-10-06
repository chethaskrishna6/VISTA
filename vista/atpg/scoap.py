"""SCOAP combinational testability measures: CC0/CC1 controllability, CO observability."""
from __future__ import annotations

import argparse
from math import inf

from vista.rtl.model import Circuit, Gate, GateType
from vista.sim.logic import INVERTING

AND_FAM = (GateType.AND, GateType.NAND)
OR_FAM = (GateType.OR, GateType.NOR)
XOR_FAM = (GateType.XOR, GateType.XNOR)


class Scoap:
    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit
        self.cc0: dict[str, int] = {}
        self.cc1: dict[str, int] = {}
        self.co: dict[str, float] = {}          # inf = cannot reach any PO
        self._controllability()
        self._observability()

    def _controllability(self) -> None:
        for pi in self.circuit.primary_inputs:
            self.cc0[pi] = self.cc1[pi] = 1
        for g in self.circuit.gates_in_topo_order():
            z = [self.cc0[n] for n in g.inputs]
            o = [self.cc1[n] for n in g.inputs]
            t = g.type
            if t in AND_FAM:
                b0, b1 = min(z) + 1, sum(o) + 1
            elif t in OR_FAM:
                b0, b1 = sum(z) + 1, min(o) + 1
            elif t in XOR_FAM:
                p0, p1 = 0, inf                       # cheapest cost for even / odd parity
                for a, b in zip(z, o):
                    p0, p1 = min(p0 + a, p1 + b), min(p0 + b, p1 + a)
                b0, b1 = p0 + 1, p1 + 1
            else:                                     # BUF / NOT
                b0, b1 = z[0] + 1, o[0] + 1
            if t in INVERTING:
                b0, b1 = b1, b0
            self.cc0[g.output], self.cc1[g.output] = b0, b1

    def _side_cost(self, g: Gate, pin: int) -> int:
        """Cost of putting every OTHER input of g at a value that lets `pin` through."""
        others = [n for i, n in enumerate(g.inputs) if i != pin]
        if g.type in AND_FAM:
            return sum(self.cc1[n] for n in others)
        if g.type in OR_FAM:
            return sum(self.cc0[n] for n in others)
        if g.type in XOR_FAM:
            return sum(min(self.cc0[n], self.cc1[n]) for n in others)
        return 0

    def pin_co(self, g: Gate, pin: int) -> float:
        """Observability of the line entering gate g at `pin`."""
        return self.co[g.output] + self._side_cost(g, pin) + 1

    def _observability(self) -> None:
        c = self.circuit
        lvl = c.levelize()
        for n in sorted(c.nets, key=lambda n: -lvl[n]):     # consumers before producers
            if c.nets[n].is_po:
                self.co[n] = 0
                continue
            best: float = inf
            for gname in c.nets[n].fanout:
                g = c.gates[gname]
                for pin, src in enumerate(g.inputs):
                    if src == n:
                        best = min(best, self.pin_co(g, pin))
            self.co[n] = best


if __name__ == "__main__":
    from vista.rtl.loader import load_circuit

    ap = argparse.ArgumentParser(description="VISTA SCOAP report")
    ap.add_argument("netlist")
    args = ap.parse_args()
    c = load_circuit(args.netlist)
    s = Scoap(c)
    lvl = c.levelize()
    nets = sorted(c.nets, key=lambda n: (lvl[n], n))
    if len(nets) <= 40:
        for n in nets:
            print(f"  {n:<8} L{lvl[n]:<3} CC0={s.cc0[n]:<4} CC1={s.cc1[n]:<4} CO={s.co[n]}")
    else:
        hard_c = sorted(nets, key=lambda n: -max(s.cc0[n], s.cc1[n]))[:5]
        hard_o = sorted(nets, key=lambda n: -s.co[n])[:5]
        print("hardest to control:", [(n, s.cc0[n], s.cc1[n]) for n in hard_c])
        print("hardest to observe:", [(n, s.co[n]) for n in hard_o])