from vista.atpg.dalgebra import D, DBAR, has_x, is_effect, symbol
from vista.sim.logic import X


def test_effects_and_symbols():
    assert is_effect(D) and is_effect(DBAR)
    assert not is_effect((1, 1)) and not is_effect((1, X)) and not is_effect((X, X))
    assert has_x((1, X)) and has_x((X, 0)) and not has_x(D)
    assert [symbol(p) for p in [D, DBAR, (0, 0), (1, 1), (X, X), (1, X)]] == \
           ["D", "D'", "0", "1", "X", "1/X"]