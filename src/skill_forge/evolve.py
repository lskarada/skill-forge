"""Multi-generation evolution loop — wraps single-gen mutation rounds.

Composition:
  - `run_evolution()` is the v0.5 entry point. It calls `run_one_generation`
    once per generation, threads the Pareto frontier (frontier.py) across
    rounds, and stops early when patience exhausts.
  - `run_one_generation` is injected (a thin wrapper around optimize.py's
    existing single-gen orchestrator). v0.4's `optimize.run_optimize` IS
    the single-gen primitive; the extraction is just a kwarg rather than
    a refactor — see CLAUDE.md "do not refactor optimize.py."
  - Frontier admit/evict logic lives in frontier.py (pure functions).
  - Programs are persisted to `.skill-forge/programs/<skill>/<id>/program.yaml`
    (program.py) and tagged via git_tags.py once a generation finishes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from skill_forge import frontier as _frontier
from skill_forge.frontier import FrontierEntry


@dataclass
class EvolutionResult:
    skill: str
    frontier: list[FrontierEntry]
    winner: Optional[FrontierEntry]
    generations_run: int
    early_stopped: bool


GenerationFn = Callable[..., Iterable[FrontierEntry]]
"""Signature: run_one_generation(*, skill, gen_index, parent, k,
workers_per_gen, repo_lock) -> Iterable[FrontierEntry]."""


def _emit(bus: object | None, kind: str, payload: object) -> None:
    if bus is None:
        return
    bus.emit(kind, payload)  # type: ignore[attr-defined]


def run_evolution(
    *,
    skill: str,
    generations: int,
    frontier_size: int,
    workers_per_gen: int,
    patience: int,
    run_one_generation: GenerationFn,
    bus: object | None = None,
    repo_lock: object | None = None,
) -> EvolutionResult:
    """Run up to `generations` rounds of mutation against `skill`.

    Each round calls `run_one_generation`, which returns an iterable of
    candidate FrontierEntry. We admit each candidate via frontier.admit,
    track best-so-far for early stopping, and stop when no improvement
    has occurred for `patience` consecutive generations.
    """
    frontier: list[FrontierEntry] = []
    best_score = float("-inf")
    stagnant = 0
    early_stopped = False
    gens_run = 0

    for gen_index in range(generations):
        parent = (
            _frontier.parent_for_iter(frontier, gen_index)
            if frontier
            else FrontierEntry(id="baseline", score=0.0, skill_len=0)
        )
        _emit(bus, "GenerationStarted", {"gen": gen_index, "parent": parent.id})

        candidates = list(run_one_generation(
            skill=skill,
            gen_index=gen_index,
            parent=parent,
            k=frontier_size,
            workers_per_gen=workers_per_gen,
            repo_lock=repo_lock,
        ))

        gen_best_score = best_score
        for cand in candidates:
            new_frontier, evicted = _frontier.admit(
                frontier=frontier, candidate=cand, k=frontier_size,
            )
            frontier = new_frontier
            if cand.score > gen_best_score:
                gen_best_score = cand.score
            _emit(bus, "FrontierUpdated", {
                "gen": gen_index, "admitted": cand.id,
                "evicted": evicted.id if evicted else None,
            })

        _emit(bus, "GenerationFinished", {"gen": gen_index, "best": gen_best_score})
        gens_run = gen_index + 1

        if gen_best_score > best_score + 1e-12:
            best_score = gen_best_score
            stagnant = 0
        else:
            stagnant += 1
            if stagnant >= patience:
                early_stopped = True
                break

    winner = max(frontier, key=lambda e: e.score) if frontier else None
    return EvolutionResult(
        skill=skill,
        frontier=frontier,
        winner=winner,
        generations_run=gens_run,
        early_stopped=early_stopped,
    )
