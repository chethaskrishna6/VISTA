import itertools
from pathlib import Path

import pytest

from vista.atpg.loc import LocFaultSimulator
from vista.atpg.loc_compact import compact_loc
from vista.atpg.podem import Outcome, PodemEngine
from vista.cli import main
from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.bench import parse_bench
from vista.rtl.loader import load_circuit
from vista.sim.fault_sim import SerialFaultSimulator

SEQ = "INPUT(a)\nOUTPUT(y)\nq = DFF(d)\nd = NAND(a, q)\ny = NOT(q)\n"
S27 = Path("benchmarks/s27.bench")


@pytest.fixture(scope="module")
def c17():
    return load_circuit("benchmarks/c17.bench")


def test_podem_require_hand_derived(c17):
    f = Fault("10", 1)
    r = PodemEngine(c17, f, require=[("2", 0)]).generate()
    assert r.outcome is Outcome.TESTED and r.cube == {"2": 0, "1": 1, "3": 1}
    r = PodemEngine(c17, f, require=[("1", 0)]).generate()
    assert r.outcome is Outcome.REDUNDANT


def test_podem_require_validation_and_default_unchanged(c17):
    with pytest.raises(ValueError):
        PodemEngine(c17, Fault("10", 1), require=[("nope", 1)])
    a = PodemEngine(c17, Fault("10", 1)).generate()
    b = PodemEngine(c17, Fault("10", 1), require=()).generate()
    assert (a.outcome, a.cube, a.backtracks) == (b.outcome, b.cube, b.backtracks)


def test_podem_require_agrees_with_exhaustive_search(c17):
    sim = SerialFaultSimulator(c17)
    pats = list(sim.exhaustive_patterns())
    goods = [sim.simulate(p) for p in pats]
    for f in generate_stuck_at_faults(c17):
        for net, val in (("2", 0), ("11", 1), ("16", 0)):
            possible = any(g[net] == val and sim.detects(p, f) for p, g in zip(pats, goods))
            r = PodemEngine(c17, f, require=[(net, val)]).generate()
            assert (r.outcome is Outcome.TESTED) == possible, (f.id, net, val)
            if possible:
                for fill in (0, 1):
                    full = {pi: r.cube.get(pi, fill) for pi in c17.primary_inputs}
                    assert sim.simulate(full)[net] == val and sim.detects(full, f)


def seq():
    return parse_bench(SEQ, "seq", scan=True)


def circuits():
    out = [pytest.param(seq, id="seq")]
    if S27.exists():
        out.append(pytest.param(lambda: load_circuit(S27), id="s27"))
    return out


@pytest.mark.parametrize("make", circuits())
@pytest.mark.parametrize("hold", [True, False])
def test_compaction_is_sound(make, hold):
    c = make()
    r = compact_loc(c, hold_pi=hold)
    assert r.matrix_ok and r.preserved and r.classification_ok
    assert 0 < len(r.final) <= len(r.merged) <= len(r.cubes)
    sim = LocFaultSimulator(r.model)
    for f, cube in r.cubes.items():                       # every cube works under any fill
        for fill in (0, 1):
            vec = {pi: cube.get(pi, fill) for pi in r.model.circuit.primary_inputs}
            assert sim.detects(vec, f), (f.id, fill)


@pytest.mark.skipif(not S27.exists(), reason="s27 not present")
def test_s27_testable_counts():
    assert len(compact_loc(load_circuit(S27), hold_pi=True).cubes) == 19
    assert len(compact_loc(load_circuit(S27), hold_pi=False).cubes) == 54


@pytest.mark.skipif(not S27.exists(), reason="s27 not present")
def test_cli_vectors_replay_through_matrix(tmp_path, capsys):
    vf = tmp_path / "v.txt"
    assert main(["loc-compact", str(S27), "--write-vectors", str(vf)]) == 0
    capsys.readouterr()
    assert main(["matrix", str(S27), "--model", "loc", "--patterns", str(vf), "--verify"]) == 0
    assert "19/54" in capsys.readouterr().out