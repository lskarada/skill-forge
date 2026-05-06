"""Multi-skill campaign orchestrator (v0.8 retro).

Runs `evolve.run_evolution` once per attributed skill, in parallel via
ThreadPoolExecutor, with a SHARED `repo_lock` plumbed through to each
inner `_locked_worktree` invocation. Aggregates the results into a
`Portfolio` consumable by the campaign view (Task 8.9).

Hard concurrency cap: M skills × workers_per_skill ≤ 16 (matches the
existing `--workers ∈ [1,16]` clamp). The `--min-confidence` filter
drops attributions below the requested rank before pool dispatch.
Skills whose synthesis admits zero tests are surfaced as non-accepted
PortfolioEntry rather than fed to `run_evolution` (no signal → no run).
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable

from skill_forge import evolve as evolve_mod
from skill_forge import synthesis as synthesis_mod
from skill_forge.attribution import CONFIDENCE_RANK, SkillAttribution

CONCURRENCY_CAP = 16


@dataclass(frozen=True)
class PortfolioEntry:
    skill: str
    accepted: bool
    confidence: str
    score: float
    reason: str = ""


@dataclass(frozen=True)
class Portfolio:
    entries: list[PortfolioEntry]


def _filter_by_confidence(
    attributions: Iterable[SkillAttribution], min_confidence: str,
) -> list[SkillAttribution]:
    threshold = CONFIDENCE_RANK[min_confidence]
    return [a for a in attributions if CONFIDENCE_RANK[a.confidence] >= threshold]


def run_campaign(
    attributions: Iterable[SkillAttribution],
    *,
    generations: int,
    frontier_size: int,
    workers_per_skill: int,
    patience: int,
    min_confidence: str = "low",
    synthesize_test: Callable[[str, SkillAttribution], object | None] | None = None,
) -> Portfolio:
    """Run M skill-evolutions concurrently. Returns Portfolio of results."""
    attrs = _filter_by_confidence(attributions, min_confidence)
    M = len(attrs)
    if M * workers_per_skill > CONCURRENCY_CAP:
        raise ValueError(
            f"M={M} × workers_per_skill={workers_per_skill} = "
            f"{M * workers_per_skill} exceeds concurrency cap of {CONCURRENCY_CAP}; "
            f"reduce --workers-per-skill or --generations"
        )

    if M == 0:
        return Portfolio(entries=[])

    repo_lock = threading.Lock()
    entries: list[PortfolioEntry] = []

    def _run_for_attr(attr: SkillAttribution) -> PortfolioEntry:
        # 8.7e: zero synthesizable tests admitted → skip run_evolution
        if synthesize_test is not None:
            synthesized = synthesize_test(attr.skill, attr)
            if synthesized is None:
                return PortfolioEntry(
                    skill=attr.skill, accepted=False,
                    confidence=attr.confidence, score=0.0,
                    reason="no synthesizable tests admitted",
                )

        result = evolve_mod.run_evolution(
            skill=attr.skill,
            generations=generations,
            frontier_size=frontier_size,
            workers_per_gen=workers_per_skill,
            patience=patience,
            run_one_generation=lambda **_kw: [],
            repo_lock=repo_lock,
        )
        score = result.winner.score if result.winner else 0.0
        accepted = result.winner is not None
        return PortfolioEntry(
            skill=attr.skill, accepted=accepted,
            confidence=attr.confidence, score=score,
            reason=("winner=" + result.winner.id) if result.winner else "no winner",
        )

    with ThreadPoolExecutor(max_workers=min(M, CONCURRENCY_CAP)) as pool:
        for entry in pool.map(_run_for_attr, attrs):
            entries.append(entry)

    return Portfolio(entries=entries)
