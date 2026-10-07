"""Engine 2: single stuck-at fault model and fault-universe generation."""
from __future__ import annotations

from vista.schema import SCHEMA_VERSION

import json
import sys
from dataclasses import dataclass

from vista.rtl.model import Circuit
from vista.rtl.parser import VerilogParser


@dataclass(frozen=True)
class Fault:
    """Stem fault if gate is None; otherwise a branch fault on input `pin` of `gate`."""
    net: str
    value: int                    # stuck-at value: 0 or 1
    gate: str | None = None
    pin: int | None = None

    def __post_init__(self) -> None:
        if self.value not in (0, 1):
            raise ValueError(f"stuck-at value must be 0/1, got {self.value!r}")
        if (self.gate is None) != (self.pin is None):
            raise ValueError("gate and pin must be given together")

    @property
    def is_branch(self) -> bool:
        return self.gate is not None

    @property
    def id(self) -> str:
        loc = f"{self.net}->{self.gate}.{self.pin}" if self.is_branch else self.net
        return f"{loc}/SA{self.value}"

    def to_dict(self) -> dict:
        return {"id": self.id, "net": self.net, "stuck_at": self.value,
                "kind": "branch" if self.is_branch else "stem",
                "gate": self.gate, "pin": self.pin}


def generate_stuck_at_faults(circuit: Circuit) -> list[Fault]:
    """Full (uncollapsed) single stuck-at fault universe, in deterministic order."""
    consumers: dict[str, list[tuple[str, int]]] = {n: [] for n in circuit.nets}
    for gate in circuit.gates.values():
        for pin, net in enumerate(gate.inputs):
            consumers[net].append((gate.name, pin))

    faults: list[Fault] = []
    for name, net in circuit.nets.items():
        faults += [Fault(name, 0), Fault(name, 1)]
        if net.is_stem:
            for gate, pin in consumers[name]:
                faults += [Fault(name, 0, gate, pin), Fault(name, 1, gate, pin)]
    return faults


def universe_to_dict(circuit: Circuit, faults: list[Fault]) -> dict:
    """JSON contract for Member 2 (and for our own ATPG/simulator)."""
    return {
        "schema_version": SCHEMA_VERSION, "document": "fault_list",
        "circuit": circuit.name,
        "fault_model": "stuck_at",
        "collapsed": False,
        "total": len(faults),
        "faults": [f.to_dict() for f in faults],
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/c17.v"
    c = VerilogParser().parse_file(src)
    fl = generate_stuck_at_faults(c)
    sites = len(fl) // 2
    branch = sum(f.is_branch for f in fl)
    print(f"{c.name}: {sites} fault sites, {len(fl)} stuck-at faults "
          f"({len(fl) - branch} stem, {branch} branch)")
    if "--json" in sys.argv:
        print(json.dumps(universe_to_dict(c, fl), indent=2))