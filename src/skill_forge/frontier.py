"""Pareto frontier — pure functions for admit/evict/parent selection.

Paper reference: EvoSkill §D, Algorithm 1. Top-K=3 programs are kept;
weakest is evicted on admit. Ties on score are broken by preferring the
SHORTER skill text (parsimony). Parents are picked round-robin.

This module is intentionally IO-free: it operates on lists of
FrontierEntry dataclasses. Git-tag persistence lives in `git_tags.py`,
program.yaml round-trip lives in `program.py`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrontierEntry:
    id: str          # e.g. "g0-w0", "g1-w2"
    score: float     # weighted multi-tolerance score in [0, 1]
    skill_len: int   # length of the skill markdown (parsimony tiebreak)


def _weakness(entry: FrontierEntry) -> tuple[float, int]:
    """Lower score == weaker; on tie, LONGER skill is weaker (parsimony)."""
    return (entry.score, -entry.skill_len)


def admit(
    *,
    frontier: list[FrontierEntry],
    candidate: FrontierEntry,
    k: int,
) -> tuple[list[FrontierEntry], FrontierEntry | None]:
    """Admit `candidate` into the frontier if better than the current weakest.

    Returns (new_frontier, evicted_or_None). The new_frontier is sorted by
    `id` for deterministic ordering — round-robin parent selection depends on
    a stable iteration order that doesn't reshuffle on score updates.

    Behavior:
      - empty frontier or len < k: candidate is appended.
      - len == k: if candidate is strictly stronger than the weakest, the
        weakest is evicted and the candidate enters; otherwise no change.
    """
    if len(frontier) < k:
        return sorted(frontier + [candidate], key=lambda e: e.id), None

    weakest = min(frontier, key=_weakness)
    if _weakness(candidate) <= _weakness(weakest):
        return sorted(frontier, key=lambda e: e.id), None

    new = [e for e in frontier if e.id != weakest.id] + [candidate]
    return sorted(new, key=lambda e: e.id), weakest


def parent_for_iter(frontier: list[FrontierEntry], t: int) -> FrontierEntry:
    """Round-robin parent for iteration `t`. Frontier must be non-empty."""
    if not frontier:
        raise ValueError("parent_for_iter requires a non-empty frontier")
    ordered = sorted(frontier, key=lambda e: e.id)
    return ordered[t % len(ordered)]
