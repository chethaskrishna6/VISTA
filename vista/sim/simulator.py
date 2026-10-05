"""Good-circuit (fault-free) levelized logic simulator."""
from __future__ import annotations

import sys

from vista.rtl.model import Circuit
from vista.rtl.parser import VerilogParser
from vista.sim.logic import VALUES, X, eval_gate, from_str, to_str


class LogicSimulator:
    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit
        self._order = circuit.gates_in_topo_order()   # computed once, reused per pattern
        self._pis = circuit.primary_inputs
        self._pos = circuit.primary_outputs

    def simulate(self, pattern: dict[str, int]) -> dict[str, int]:
        """Return the value of every net. Unassigned PIs default to X."""
        unknown = set(pattern) - set(self._pis)
        if unknown:
            raise ValueError(f"not primary inputs: {sorted(unknown)}")
        values = {pi: pattern.get(pi, X) for pi in self._pis}
        for pi, v in values.items():
            if v not in VALUES:
                raise ValueError(f"invalid value {v!r} on '{pi}'")
        for g in self._order:
            values[g.output] = eval_gate(g.type, [values[n] for n in g.inputs])
        return values

    def outputs(self, pattern: dict[str, int]) -> dict[str, int]:
        values = self.simulate(pattern)
        return {po: values[po] for po in self._pos}

    def pattern_from_string(self, bits: str) -> dict[str, int]:
        """'01X10' -> dict, using the circuit's PI order."""
        if len(bits) != len(self._pis):
            raise ValueError(f"need {len(self._pis)} bits for PIs {self._pis}, got {len(bits)}")
        return dict(zip(self._pis, from_str(bits)))


if __name__ == "__main__":
    path, bits = sys.argv[1], sys.argv[2]
    sim = LogicSimulator(VerilogParser().parse_file(path))
    pat = sim.pattern_from_string(bits)
    out = sim.outputs(pat)
    print("PI order :", sim._pis)
    print("inputs   :", to_str(pat.values()))
    print("outputs  :", dict(zip(out, to_str(out.values()))))