"""3-valued logic (0, 1, X) and gate evaluation. Shared by ATPG and fault simulation."""
from __future__ import annotations

from typing import Sequence

from vista.rtl.model import GateType

ZERO, ONE, X = 0, 1, 2
VALUES = (ZERO, ONE, X)
_CHAR = {ZERO: "0", ONE: "1", X: "X"}
_FROM_CHAR = {"0": ZERO, "1": ONE, "X": X, "x": X}

# Used by PODEM backtrace/objective selection (Engine 3).
CONTROLLING: dict[GateType, int] = {
    GateType.AND: ZERO, GateType.NAND: ZERO,
    GateType.OR: ONE, GateType.NOR: ONE,
}
INVERTING = frozenset({GateType.NAND, GateType.NOR, GateType.XNOR, GateType.NOT})


def non_controlling(gtype: GateType) -> int:
    return ONE - CONTROLLING[gtype]


def _base(gtype: GateType, ins: Sequence[int]) -> int:
    """Evaluate the non-inverted function of the gate family."""
    if gtype in (GateType.AND, GateType.NAND):
        if ZERO in ins:
            return ZERO
        return X if X in ins else ONE
    if gtype in (GateType.OR, GateType.NOR):
        if ONE in ins:
            return ONE
        return X if X in ins else ZERO
    if gtype in (GateType.XOR, GateType.XNOR):
        if X in ins:
            return X
        return sum(ins) & 1
    # BUF / NOT
    return ins[0]


def eval_gate(gtype: GateType, ins: Sequence[int]) -> int:
    out = _base(gtype, ins)
    if gtype in INVERTING and out != X:
        out = ONE - out
    return out


def to_str(values: Sequence[int]) -> str:
    return "".join(_CHAR[v] for v in values)


def from_str(s: str) -> list[int]:
    try:
        return [_FROM_CHAR[c] for c in s]
    except KeyError as e:
        raise ValueError(f"invalid logic character {e} in '{s}' (use 0/1/X)") from None