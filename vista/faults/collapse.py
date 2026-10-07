"""Engine 2: structural equivalence fault collapsing."""
from __future__ import annotations

from vista.schema import SCHEMA_VERSION

import json
import sys
from collections import defaultdict
from dataclasses import dataclass

from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.model import Circuit, Gate, GateType
from vista.rtl.parser import VerilogParser

# gate type -> ((input_stuck_value, output_stuck_value), ...) pairs that are equivalent
RULES: dict[GateType, tuple[tuple[int, int], ...]] = {
    GateType.AND: ((0, 0),),
    GateType.NAND: ((0, 1),),
    GateType.OR: ((1, 1),),
    GateType.NOR: ((1, 0),),
    GateType.NOT: ((0, 1), (1, 0)),
    GateType.BUF: ((0, 0), (1, 1)),
}


class _UnionFind:
    def __init__(self, items) -> None:
        self._parent = {x: x for x in items}

    def find(self, x):
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]    # path halving
            x = self._parent[x]
        return x

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


@dataclass
class CollapseResult:
    classes: dict[Fault, list[Fault]]      # representative -> all members (incl. itself)

    @property
    def representatives(self) -> list[Fault]:
        return list(self.classes)

    @property
    def total_uncollapsed(self) -> int:
        return sum(len(m) for m in self.classes.values())

    def representative_of(self, fault: Fault) -> Fault:
        for rep, members in self.classes.items():
            if fault in members:
                return rep
        raise KeyError(fault.id)


def _input_line_fault(circuit: Circuit, gate: Gate, pin: int, value: int) -> Fault:
    """The fault on the *line* entering `gate` at `pin` (branch if the net is a stem)."""
    net = gate.inputs[pin]
    if circuit.nets[net].is_stem:
        return Fault(net, value, gate.name, pin)
    return Fault(net, value)


def collapse_equivalent(circuit: Circuit, faults: list[Fault]) -> CollapseResult:
    present = set(faults)
    uf = _UnionFind(faults)
    for gate in circuit.gates.values():
        for in_v, out_v in RULES.get(gate.type, ()):
            out_fault = Fault(gate.output, out_v)
            if out_fault not in present:
                continue
            for pin in range(len(gate.inputs)):
                in_fault = _input_line_fault(circuit, gate, pin, in_v)
                if in_fault in present:
                    uf.union(out_fault, in_fault)

    lvl = circuit.levelize()
    position = {f: i for i, f in enumerate(faults)}
    groups: dict[Fault, list[Fault]] = defaultdict(list)
    for f in faults:
        groups[uf.find(f)].append(f)

    classes: dict[Fault, list[Fault]] = {}
    for members in groups.values():
        rep = min(members, key=lambda f: (-lvl[f.net], f.id))   # closest to the outputs
        classes[rep] = members
    ordered = dict(sorted(classes.items(), key=lambda kv: position[kv[0]]))
    return CollapseResult(ordered)


def collapsed_to_dict(circuit: Circuit, result: CollapseResult) -> dict:
    """JSON contract for Member 2. Additive to the Step 7 schema."""
    return {
        "schema_version": SCHEMA_VERSION, "document": "fault_list",
        "circuit": circuit.name,
        "fault_model": "stuck_at",
        "collapsed": True,
        "collapse_method": "equivalence",
        "total_uncollapsed": result.total_uncollapsed,
        "total": len(result.classes),
        "faults": [
            {**rep.to_dict(),
             "class_size": len(members),
             "equivalent_faults": [m.id for m in members if m != rep]}
            for rep, members in result.classes.items()
        ],
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/c17.v"
    c = VerilogParser().parse_file(src)
    universe = generate_stuck_at_faults(c)
    res = collapse_equivalent(c, universe)
    pct = 100 * (1 - len(res.classes) / len(universe))
    print(f"{c.name}: {len(universe)} -> {len(res.classes)} faults ({pct:.1f}% reduction)")
    if "--json" in sys.argv:
        print(json.dumps(collapsed_to_dict(c, res), indent=2))