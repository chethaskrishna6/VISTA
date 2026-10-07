from pathlib import Path

import pytest

from vista.atpg.compact import (evaluate, greedy_cover, prepare_stuck_at,
                                prepare_transition, reverse_order)
from vista.rtl.loader import load_circuit


def test_reverse_order_hand_case():
    # item 2 covers C; item 1 covers A,B; item 0 then adds nothing
    det = {"A": [0, 1], "B": [1], "C": [2]}
    assert reverse_order(3, det) == [1, 2]


def test_greedy_beats_reverse_order_on_chain_case():
    # sets: 0={A,B}  1={B,C}  2={C,D}
    det = {"A": [0], "B": [0, 1], "C": [1, 2], "D": [2]}
    assert greedy_cover(4 - 1, det) == [0, 2]
    assert reverse_order(3, det) == [0, 1, 2]


def test_undetected_faults_are_ignored():
    det = {"A": [], "B": [0]}
    assert reverse_order(2, det) == [0]
    assert greedy_cover(2, det) == [0]


def test_empty_set():
    assert reverse_order(0, {}) == [] and greedy_cover(0, {}) == []


def need(path):
    if not Path(path).exists():
        pytest.skip(f"{path} not present")
    return load_circuit(path)


@pytest.mark.parametrize("prep", [prepare_stuck_at, prepare_transition])
def test_c17_compaction_preserves_coverage(prep):
    c = load_circuit("benchmarks/c17.bench")
    items, det, verify = prep(c)
    for name, (kept, ok) in evaluate(len(items), det, verify).items():
        assert ok, name
        assert 0 < len(kept) <= len(items), name
        assert kept == sorted(set(kept)), name


@pytest.mark.parametrize("prep", [prepare_stuck_at, prepare_transition])
def test_c432_compaction_preserves_coverage(prep):
    c = need("benchmarks/c432.bench")
    items, det, verify = prep(c)
    for name, (kept, ok) in evaluate(len(items), det, verify).items():
        assert ok, name
        assert len(kept) <= len(items), name