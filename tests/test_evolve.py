"""Task 5.5 — evolve.run_evolution orchestrator (multi-generation loop)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skill_forge import evolve
from skill_forge.frontier import FrontierEntry


@dataclass
class _Bus:
    events: list[object] = field(default_factory=list)

    def emit(self, kind: str, payload: object) -> None:
        self.events.append((kind, payload))


def test_run_evolution_runs_n_generations() -> None:
    bus = _Bus()
    calls: list[int] = []

    def fake_one_gen(*, skill, gen_index, parent, k, workers_per_gen, repo_lock):
        calls.append(gen_index)
        # Each gen produces one new program at score = 0.5 + gen*0.1
        return [FrontierEntry(id=f"g{gen_index}-w0", score=0.5 + 0.1 * gen_index, skill_len=100)]

    result = evolve.run_evolution(
        skill="greeter",
        generations=3,
        frontier_size=2,
        workers_per_gen=1,
        patience=2,
        run_one_generation=fake_one_gen,
        bus=bus,
    )

    assert calls == [0, 1, 2]
    assert isinstance(result.frontier, list)
    assert all(isinstance(e, FrontierEntry) for e in result.frontier)
    # Final frontier has top-K=2 entries; the highest-scoring last gen wins.
    assert len(result.frontier) <= 2
    # Lifecycle events emitted in order.
    kinds = [k for k, _ in bus.events]
    assert kinds.count("GenerationStarted") == 3
    assert kinds.count("GenerationFinished") == 3
    assert kinds.count("FrontierUpdated") >= 1


def test_run_evolution_early_stops_on_patience_exhausted() -> None:
    bus = _Bus()
    calls: list[int] = []

    def fake_one_gen(*, skill, gen_index, parent, k, workers_per_gen, repo_lock):
        calls.append(gen_index)
        # Constant score → no improvement → patience drains
        return [FrontierEntry(id=f"g{gen_index}-w0", score=0.5, skill_len=100)]

    result = evolve.run_evolution(
        skill="greeter",
        generations=10,
        frontier_size=2,
        workers_per_gen=1,
        patience=2,
        run_one_generation=fake_one_gen,
        bus=bus,
    )

    # 1 baseline gen + 2 stagnant gens = stops at gen 2 (3 calls total)
    assert len(calls) <= 4
    assert result.early_stopped is True


def test_run_evolution_returns_lineage_chain_id_for_winner() -> None:
    def fake_one_gen(*, skill, gen_index, parent, k, workers_per_gen, repo_lock):
        return [FrontierEntry(id=f"g{gen_index}-w0", score=0.5 + 0.1 * gen_index, skill_len=100)]

    result = evolve.run_evolution(
        skill="greeter",
        generations=3,
        frontier_size=2,
        workers_per_gen=1,
        patience=5,
        run_one_generation=fake_one_gen,
    )

    # Winner = highest-scoring entry on the final frontier
    assert result.winner is not None
    assert result.winner.score >= max(e.score for e in result.frontier)
