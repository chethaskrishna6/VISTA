"""Engine 3 (oracle): complete SAT-based ATPG. Cross-checks PODEM and settles redundancy."""
from __future__ import annotations

import time
from dataclasses import dataclass

from pysat.solvers import Glucose4

from vista.atpg.podem import Outcome
from vista.atpg.scoap import AND_FAM, OR_FAM, XOR_FAM
from vista.faults.stuck_at import Fault
from vista.rtl.model import Circuit, GateType
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import INVERTING


class _Cnf:
    """Clause sink with fresh-variable allocation; clauses may be guarded by an activation literal."""

    def __init__(self, solver) -> None:
        self.solver = solver
        self.nvars = 0
        self.guard: int | None = None

    def new_var(self) -> int:
        self.nvars += 1
        return self.nvars

    def add(self, *lits: int) -> None:
        clause = list(lits)
        if self.guard is not None:
            clause.append(-self.guard)         # clause only binds while `guard` is assumed
        self.solver.add_clause(clause)


def _xor2(cnf: _Cnf, c: int, a: int, b: int) -> None:
    cnf.add(-c, a, b)
    cnf.add(-c, -a, -b)
    cnf.add(c, -a, b)
    cnf.add(c, a, -b)


def encode_gate(cnf: _Cnf, gtype: GateType, out: int, ins: list[int]) -> None:
    """Tseitin clauses for out = gtype(ins). Inverting gates reuse the base function with ~out."""
    if gtype in INVERTING:
        out = -out
    if gtype in AND_FAM:
        for a in ins:
            cnf.add(-out, a)
        cnf.add(out, *[-a for a in ins])
    elif gtype in OR_FAM:
        for a in ins:
            cnf.add(-a, out)
        cnf.add(-out, *ins)
    elif gtype in XOR_FAM:
        t = ins[0]
        for a in ins[1:]:                       # chain of 2-input XORs
            n = cnf.new_var()
            _xor2(cnf, n, t, a)
            t = n
        cnf.add(-out, t)
        cnf.add(out, -t)
    else:                                       # BUF / NOT (NOT = BUF with ~out)
        cnf.add(-out, ins[0])
        cnf.add(out, -ins[0])


@dataclass
class SatResult:
    fault: Fault
    outcome: Outcome                            # TESTED or REDUNDANT (never ABORTED)
    pattern: dict[str, int]                     # fully specified; empty if redundant
    seconds: float


class SatAtpg:
    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit
        self._sim = SerialFaultSimulator(circuit)      # used only for fanout cones
        self._solver = Glucose4()
        self._cnf = _Cnf(self._solver)
        self._gv: dict[str, int] = {}                  # net -> good-machine variable
        for pi in circuit.primary_inputs:
            self._gv[pi] = self._cnf.new_var()
        for g in circuit.gates_in_topo_order():
            out = self._cnf.new_var()
            self._gv[g.output] = out
            encode_gate(self._cnf, g.type, out, [self._gv[n] for n in g.inputs])

    def close(self) -> None:
        self._solver.delete()

    def _const(self, value: int) -> int:
        v = self._cnf.new_var()
        self._cnf.add(v if value else -v)
        return v

    def generate(self, fault: Fault, require: list[tuple[str, int]] | tuple = ()) -> SatResult:
        """require: extra good-machine conditions, e.g. [(net, value)] (used for launch-on-capture)."""
        unknown = [n for n, _ in require if n not in self._gv]
        if unknown:
            raise ValueError(f"unknown nets in require: {unknown}")
        t0 = time.perf_counter()
        cone = self._sim.cone_for(fault)
        cnf = self._cnf
        act = cnf.new_var()
        cnf.guard = act
        try:
            fv: dict[str, int] = {}                  # net -> faulty-machine variable (cone only)
            forced = fault.gate if fault.is_branch else None
            if not fault.is_branch:
                fv[fault.net] = self._const(fault.value)
            for g in cone:
                ins = [fv.get(n, self._gv[n]) for n in g.inputs]
                if g.name == forced:
                    ins[fault.pin] = self._const(fault.value)
                out = cnf.new_var()
                fv[g.output] = out
                encode_gate(cnf, g.type, out, ins)
            diffs = []
            for po in self.circuit.primary_outputs:
                if po in fv:
                    d = cnf.new_var()
                    _xor2(cnf, d, self._gv[po], fv[po])
                    diffs.append(d)
            cnf.add(*diffs)                          # some PO must differ (empty -> UNSAT)
        finally:
            cnf.guard = None
            
        lits = [self._gv[n] if v else -self._gv[n] for n, v in require]
        sat = self._solver.solve(assumptions=[act, *lits])
        
        pattern: dict[str, int] = {}
        if sat:
            true = {lit for lit in self._solver.get_model() if lit > 0}
            pattern = {pi: int(self._gv[pi] in true) for pi in self.circuit.primary_inputs}
        self._solver.add_clause([-act])              # retire this fault's clauses
        return SatResult(fault, Outcome.TESTED if sat else Outcome.REDUNDANT,
                         pattern, time.perf_counter() - t0)
    def justify(self, net: str, value: int) -> dict[str, int] | None:
        """Exact: a full vector putting `net` at `value` in the good circuit, or None if impossible."""
        lit = self._gv[net] if value else -self._gv[net]
        if not self._solver.solve(assumptions=[lit]):
            return None
        true = {l for l in self._solver.get_model() if l > 0}
        return {pi: int(self._gv[pi] in true) for pi in self.circuit.primary_inputs}