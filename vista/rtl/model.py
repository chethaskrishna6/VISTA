"""Core circuit data model for VISTA (Engine 1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import networkx as nx


class GateType(str, Enum):
    AND = "and"
    NAND = "nand"
    OR = "or"
    NOR = "nor"
    XOR = "xor"
    XNOR = "xnor"
    NOT = "not"
    BUF = "buf"

    @property
    def is_unary(self) -> bool:
        return self in (GateType.NOT, GateType.BUF)


@dataclass
class Net:
    name: str
    driver: str | None = None          # gate name driving this net (None for PIs)
    fanout: list[str] = field(default_factory=list)  # gate names reading this net
    is_pi: bool = False
    is_po: bool = False

    @property
    def is_stem(self) -> bool:
        return len(self.fanout) > 1


@dataclass
class Gate:
    name: str
    type: GateType
    output: str                         # output net name
    inputs: list[str]                   # input net names (order preserved)


class CircuitError(ValueError):
    """Raised for structurally illegal netlists."""


class Circuit:
    def __init__(self, name: str) -> None:
        self.name = name
        self.nets: dict[str, Net] = {}
        self.gates: dict[str, Gate] = {}

    # ---- construction -------------------------------------------------
    def net(self, name: str) -> Net:
        """Get-or-create a net."""
        if name not in self.nets:
            self.nets[name] = Net(name)
        return self.nets[name]

    def mark_pi(self, name: str) -> None:
        self.net(name).is_pi = True

    def mark_po(self, name: str) -> None:
        self.net(name).is_po = True

    def add_gate(self, name: str, gtype: GateType, output: str, inputs: list[str]) -> Gate:
        if name in self.gates:
            raise CircuitError(f"duplicate gate name '{name}'")
        if not inputs:
            raise CircuitError(f"gate '{name}' has no inputs")
        if gtype.is_unary and len(inputs) != 1:
            raise CircuitError(f"{gtype.value} gate '{name}' needs exactly 1 input")
        out_net = self.net(output)
        if out_net.is_pi:
            raise CircuitError(f"gate '{name}' drives primary input '{output}'")
        if out_net.driver is not None:
            raise CircuitError(
                f"net '{output}' has multiple drivers: '{out_net.driver}' and '{name}'"
            )
        gate = Gate(name, gtype, output, list(inputs))
        self.gates[name] = gate
        out_net.driver = name
        for n in inputs:
            self.net(n).fanout.append(name)
        return gate

    # ---- queries ------------------------------------------------------
    @property
    def primary_inputs(self) -> list[str]:
        return [n.name for n in self.nets.values() if n.is_pi]

    @property
    def primary_outputs(self) -> list[str]:
        return [n.name for n in self.nets.values() if n.is_po]

    @property
    def stems(self) -> list[str]:
        return [n.name for n in self.nets.values() if n.is_stem]
    @property
    def po_with_fanout(self) -> list[str]:
        """POs that also feed gates. Their gate-input branches are not modelled as faults yet."""
        return [n.name for n in self.nets.values() if n.is_po and n.fanout]
    

    def validate(self) -> None:
        """Check structural legality: no floating nets, no loops, POs driven."""
        for n in self.nets.values():
            if n.driver is None and not n.is_pi:
                raise CircuitError(f"net '{n.name}' is undriven (not a PI, no driver)")
            if n.is_po and n.driver is None and not n.is_pi:
                raise CircuitError(f"primary output '{n.name}' is undriven")
        if not nx.is_directed_acyclic_graph(self.to_networkx()):
            raise CircuitError("combinational loop detected (graph is not a DAG)")

    def to_networkx(self) -> nx.DiGraph:
        """Net-level DAG: edge (in_net -> out_net) per gate input, tagged with the gate."""
        g = nx.DiGraph(name=self.name)
        g.add_nodes_from(self.nets)
        for gate in self.gates.values():
            for src in gate.inputs:
                g.add_edge(src, gate.output, gate=gate.name)
        return g

    def levelize(self) -> dict[str, int]:
        """Net name -> logic level (PIs = 0)."""
        g = self.to_networkx()
        level: dict[str, int] = {}
        for n in nx.topological_sort(g):
            preds = list(g.predecessors(n))
            level[n] = 0 if not preds else 1 + max(level[p] for p in preds)
        return level

    def gates_in_topo_order(self) -> list[Gate]:
        """Gates sorted so every gate appears after all gates feeding it."""
        lvl = self.levelize()
        return sorted(self.gates.values(), key=lambda g: (lvl[g.output], g.name))

    # ---- export (JSON contract for Member 2) --------------------------
    def to_dict(self) -> dict:
        lvl = self.levelize()
        return {
            "schema_version": "0.1",
            "circuit": self.name,
            "primary_inputs": self.primary_inputs,
            "primary_outputs": self.primary_outputs,
            "nets": [
                {
                    "name": n.name,
                    "level": lvl[n.name],
                    "driver": n.driver,
                    "fanout": n.fanout,
                    "is_stem": n.is_stem,
                }
                for n in self.nets.values()
            ],
            "gates": [
                {"name": g.name, "type": g.type.value, "output": g.output, "inputs": g.inputs}
                for g in self.gates_in_topo_order()
            ],
        }

    def __repr__(self) -> str:
        return (f"Circuit({self.name!r}: {len(self.primary_inputs)} PI, "
                f"{len(self.primary_outputs)} PO, {len(self.gates)} gates, "
                f"{len(self.nets)} nets)")