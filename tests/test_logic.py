import itertools

import pytest

from vista.rtl.model import GateType as G
from vista.sim.logic import ONE, X, ZERO, eval_gate, non_controlling


def test_controlling_value_beats_x():
    assert eval_gate(G.AND, [ZERO, X]) == ZERO
    assert eval_gate(G.NAND, [ZERO, X]) == ONE
    assert eval_gate(G.OR, [ONE, X]) == ONE
    assert eval_gate(G.NOR, [ONE, X]) == ZERO


def test_x_propagates_when_not_controlled():
    assert eval_gate(G.AND, [ONE, X]) == X
    assert eval_gate(G.OR, [ZERO, X]) == X
    assert eval_gate(G.XOR, [ZERO, X]) == X
    assert eval_gate(G.NOT, [X]) == X


@pytest.mark.parametrize("a,b", list(itertools.product([0, 1], repeat=2)))
def test_two_input_truth_tables(a, b):
    assert eval_gate(G.AND, [a, b]) == (a & b)
    assert eval_gate(G.NAND, [a, b]) == 1 - (a & b)
    assert eval_gate(G.OR, [a, b]) == (a | b)
    assert eval_gate(G.NOR, [a, b]) == 1 - (a | b)
    assert eval_gate(G.XOR, [a, b]) == (a ^ b)
    assert eval_gate(G.XNOR, [a, b]) == 1 - (a ^ b)


def test_wide_gates_and_unary():
    assert eval_gate(G.AND, [1, 1, 1, 1]) == 1
    assert eval_gate(G.NOR, [0, 0, 0]) == 1
    assert eval_gate(G.XOR, [1, 1, 1]) == 1          # odd parity
    assert eval_gate(G.NOT, [0]) == 1 and eval_gate(G.BUF, [1]) == 1


def test_non_controlling():
    assert non_controlling(G.AND) == ONE and non_controlling(G.NOR) == ZERO