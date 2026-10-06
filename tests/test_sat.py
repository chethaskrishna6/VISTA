import itertools
from pathlib import Path

import pytest

pytest.importorskip("pysat")
from pysat.solvers import Glucose4

from vista.atpg.podem import Outcome
from vista.atpg.sat import SatAtpg, _Cnf, encode_gate
from vista.faults.collapse import collapse_equivalent
from vista.faults.stuck_at import generate_stuck_at_faults
from vista.rtl.loader import load_circuit
from vista.rtl.model import Circuit, GateType
from vista.sim.fault_sim import SerialFaultSimulator
from vista.sim.logic import eval_gate


def absorption() -> Circuit:
    c = Circuit("absorb")
    c.mark_pi("a"); c.mark_pi("b"); c.mark_po("y")
    c.add_gate("g1", GateType.AND, "n", ["a", "b"])
    c.add_gate("g2", GateType.OR, "y", ["a", "n"])
    c.validate()
    return c


@pytest.mark.parametrize("gtype", list(GateType))
def test_gate_encoding_matches_eval_gate(gtype):
    for n in ([1] if gtype.is_unary else [2, 3, 4]):
        solver = Glucose4()
        cnf = _Cnf(solver)
        ins = [cnf.new_var() for _ in range(n)]
        out = cnf.new_var()
        encode_gate(cnf, gtype, out, ins)
        for combo in itertools.product((0, 1), repeat=n):
            assume = [v if b else -v for v, b in zip(ins, combo)]
            want = eval_gate(gtype, list(combo))
            assert solver.solve(assumptions=assume + [out if want else -out])
            assert not solver.solve(assumptions=assume + [-out if want else out])
        solver.delete()


def test_sat_agrees_with_exhaustive_simulation():
    for c in (absorption(), load_circuit("benchmarks/c17.bench")):
        sat, sim = SatAtpg(c), SerialFaultSimulator(c)
        good = sim.signature(None)
        for f in generate_stuck_at_faults(c):
            r = sat.generate(f)
            testable = sim.signature(f) != good
            assert (r.outcome is Outcome.TESTED) == testable, f.id
            if testable:
                assert sim.detects(r.pattern, f), f.id
        sat.close()


def test_incremental_solver_is_order_independent():
    c = absorption()
    faults = generate_stuck_at_faults(c)
    a, b = SatAtpg(c), SatAtpg(c)
    fwd = {f: a.generate(f).outcome for f in faults}
    rev = {f: b.generate(f).outcome for f in reversed(faults)}
    assert fwd == rev and Outcome.REDUNDANT in fwd.values()
    a.close(); b.close()


def test_sat_vectors_detect_on_c432():
    if not Path("benchmarks/c432.bench").exists():
        pytest.skip("c432 not present")
    c = load_circuit("benchmarks/c432.bench")
    faults = collapse_equivalent(c, generate_stuck_at_faults(c)).representatives
    sat, sim = SatAtpg(c), SerialFaultSimulator(c)
    for f in faults:
        r = sat.generate(f)
        if r.outcome is Outcome.TESTED:
            assert sim.detects(r.pattern, f), f.id
    sat.close()