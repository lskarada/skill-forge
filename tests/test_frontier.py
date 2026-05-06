"""Task 5.1 — Pareto frontier pure-fn admit / evict / round-robin parent."""
from __future__ import annotations

from skill_forge.frontier import FrontierEntry, admit, parent_for_iter


def _e(id_: str, score: float, skill_len: int) -> FrontierEntry:
    return FrontierEntry(id=id_, score=score, skill_len=skill_len)


def test_admit_into_empty_frontier_keeps_candidate() -> None:
    new, evicted = admit(frontier=[], candidate=_e("a", 0.5, 100), k=3)
    assert [e.id for e in new] == ["a"]
    assert evicted is None


def test_admit_when_not_full_appends() -> None:
    f = [_e("a", 0.5, 100), _e("b", 0.7, 80)]
    new, evicted = admit(frontier=f, candidate=_e("c", 0.6, 90), k=3)
    assert sorted(e.id for e in new) == ["a", "b", "c"]
    assert evicted is None


def test_admit_evicts_weakest_when_full_and_better() -> None:
    f = [_e("a", 0.5, 100), _e("b", 0.7, 80), _e("c", 0.6, 90)]
    new, evicted = admit(frontier=f, candidate=_e("d", 0.8, 70), k=3)
    assert evicted is not None
    assert evicted.id == "a"  # weakest = lowest score
    assert {e.id for e in new} == {"b", "c", "d"}


def test_no_admit_when_worse_than_min() -> None:
    f = [_e("a", 0.5, 100), _e("b", 0.7, 80), _e("c", 0.6, 90)]
    new, evicted = admit(frontier=f, candidate=_e("d", 0.4, 70), k=3)
    assert evicted is None
    # frontier unchanged
    assert {e.id for e in new} == {"a", "b", "c"}


def test_round_robin_parent_cycles() -> None:
    f = [_e("a", 0.5, 100), _e("b", 0.7, 80), _e("c", 0.6, 90)]
    # Order is by id (deterministic). t modulo len(frontier).
    parents = [parent_for_iter(f, t).id for t in range(7)]
    assert parents == ["a", "b", "c", "a", "b", "c", "a"]


def test_ties_broken_by_shorter_skill_text() -> None:
    """When two candidates tie on score, the SHORTER skill (skill_len) is preferred."""
    f = [_e("a", 0.5, 100), _e("b", 0.7, 80), _e("c", 0.7, 200)]
    # adding a candidate at score 0.7 with len 50 — should evict "c" (longer at same score)
    new, evicted = admit(frontier=f, candidate=_e("d", 0.7, 50), k=3)
    assert evicted is not None
    assert evicted.id == "a"  # weakest is "a" (lower score)
    assert {e.id for e in new} == {"b", "c", "d"}

    # When candidate ties with frontier minimum on score: prefer shorter to enter
    f2 = [_e("a", 0.7, 200), _e("b", 0.7, 80), _e("c", 0.7, 90)]
    new2, evicted2 = admit(frontier=f2, candidate=_e("d", 0.7, 50), k=3)
    assert evicted2 is not None
    # weakest = highest skill_len at min score (200 → "a")
    assert evicted2.id == "a"
