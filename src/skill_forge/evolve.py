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
from pathlib import Path
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
    emit_dashboard_events: bool = False,
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

    # Lazy import so non-dashboard callers (unit tests) don't need ui extras.
    if emit_dashboard_events:
        from skill_forge.dashboard import events as _dash_ev

    for gen_index in range(generations):
        parent = (
            _frontier.parent_for_iter(frontier, gen_index)
            if frontier
            else FrontierEntry(id="baseline", score=0.0, skill_len=0)
        )
        parent_label = parent.id if gen_index > 0 else "baseline"
        _emit(bus, "GenerationStarted", {"gen": gen_index, "parent": parent_label})
        if emit_dashboard_events:
            _dash_ev.emit_event(_dash_ev.GenerationStarted(
                gen=gen_index, parent=parent_label,
            ))

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
            if emit_dashboard_events:
                _dash_ev.emit_event(_dash_ev.FrontierUpdated(
                    gen=gen_index, admitted_id=cand.id,
                    admitted_score=cand.score,
                    evicted_id=evicted.id if evicted else None,
                ))
        if emit_dashboard_events:
            _dash_ev.emit_event(_dash_ev.SparklineSample(
                t=gen_index, score=gen_best_score,
            ))

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


# --- v0.8.1: real run_one_generation wired to optimize.run_optimize ------


def build_real_run_one_generation(
    *,
    output_root: Path,
    repo_path: Path,
    tests_dir: Path | None = None,
    assume_yes: bool = True,
    printer: Callable[[str], None] | None = None,
) -> GenerationFn:
    """Return a `run_one_generation` callable that drives a real mutation
    round via `optimize.run_optimize`.

    Translates `OptimizeResult.worker_results` into `FrontierEntry`s the
    multi-gen orchestrator can admit. Score is `passed / total` from the
    post-mutation pytest run (paper §C weighted score is approximated as
    a single-tau pass rate until a multi-tolerance test runner lands).
    """
    from skill_forge.optimize import (
        OptimizeConfig,
        OptimizeIO,
        run_optimize,
    )
    import typer

    _printer = printer or (lambda msg: typer.echo(msg))

    def _real_one_gen(
        *, skill: str, gen_index: int, parent, k: int,
        workers_per_gen: int, repo_lock,
    ) -> Iterable[FrontierEntry]:
        config = OptimizeConfig(
            skill=skill,
            repo_path=repo_path,
            output_root=output_root,
            tests_dir=tests_dir,
            assume_yes=assume_yes,
            num_workers=workers_per_gen,
        )
        io = OptimizeIO(
            printer=_printer,
            prompter=lambda _msg: "y",
        )
        result = run_optimize(config, io)

        entries: list[FrontierEntry] = []
        for wr in result.worker_results:
            if wr.post is None:
                continue
            total = wr.post.total or 1
            score = wr.post.passed / total
            entries.append(FrontierEntry(
                id=f"g{gen_index}-w{wr.index}",
                score=score,
                skill_len=wr.mutated_sut_length or 0,
            ))
        # Single-worker fallback when result.worker_results is empty (N=1 path
        # uses post_mutation directly).
        if not entries and result.post_mutation is not None:
            total = result.post_mutation.total or 1
            score = result.post_mutation.passed / total
            entries.append(FrontierEntry(
                id=f"g{gen_index}-w0",
                score=score,
                skill_len=0,
            ))
        return entries

    return _real_one_gen
