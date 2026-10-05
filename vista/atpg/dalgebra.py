"""D-algebra helpers. A value is a (good, faulty) pair of 3-valued logic values."""
from __future__ import annotations

from vista.sim.logic import X, to_str

Pair = tuple[int, int]
D: Pair = (1, 0)        # good=1, faulty=0
DBAR: Pair = (0, 1)     # good=0, faulty=1


def is_effect(p: Pair) -> bool:
    """True for D or D': both machines known and different."""
    return X not in p and p[0] != p[1]


def has_x(p: Pair) -> bool:
    """True if either machine's value is still unknown."""
    return X in p


def symbol(p: Pair) -> str:
    if p == D:
        return "D"
    if p == DBAR:
        return "D'"
    if p[0] == p[1]:
        return to_str([p[0]])
    return f"{to_str([p[0]])}/{to_str([p[1]])}"      # partial, e.g. 1/X