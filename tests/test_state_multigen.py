"""v0.8.1-B1 — multi-gen state: GenerationStarted/FrontierUpdated/SparklineSample."""
from __future__ import annotations

from skill_forge.dashboard.events import (
    FrontierUpdated,
    GenerationStarted,
    MutationProposal,
    RunStarted,
    SparklineSample,
    WorkerSpawned,
)
from skill_forge.dashboard.state import RunState


def test_generation_started_snapshots_prior_workers() -> None:
    state = RunState()
    state.apply(RunStarted(skill="greeter", run_id="r1", num_workers=3))
    state.apply(WorkerSpawned(worker_id="w0", strategy="x"))
    state.apply(WorkerSpawned(worker_id="w1", strategy="y"))

    # Now move to gen 1 — the prior workers should snapshot
    state.apply(GenerationStarted(gen=1, parent="v1"))

    assert state.current_generation == 1
    assert state.parent_label == "v1"
    assert state.workers == {}  # cleared for new gen
    assert len(state.lineage_history) == 1
    snap = state.lineage_history[0]
    assert {w.id for w in snap.workers} == {"w0", "w1"}


def test_multiple_generations_accumulate_in_lineage_history() -> None:
    state = RunState()
    state.apply(RunStarted(skill="greeter", run_id="r1", num_workers=3))
    for gen in range(3):
        state.apply(WorkerSpawned(worker_id=f"g{gen}-w0", strategy="s"))
        state.apply(GenerationStarted(gen=gen + 1, parent=f"v{gen + 1}"))

    assert len(state.lineage_history) == 3
    assert [s.parent for s in state.lineage_history] == ["baseline", "v1", "v2"]


def test_frontier_updated_event_admits_and_evicts() -> None:
    state = RunState()
    state.apply(FrontierUpdated(gen=0, admitted_id="g0-w0", admitted_score=0.5))
    state.apply(FrontierUpdated(gen=0, admitted_id="g0-w1", admitted_score=0.7))
    state.apply(FrontierUpdated(
        gen=1, admitted_id="g1-w0", admitted_score=0.85, evicted_id="g0-w0",
    ))

    ids = {fe.id for fe in state.frontier}
    assert ids == {"g0-w1", "g1-w0"}
    # Most recent admit is the only one with active=True
    actives = [fe for fe in state.frontier if fe.active]
    assert len(actives) == 1
    assert actives[0].id == "g1-w0"


def test_sparkline_sample_appends_to_state() -> None:
    state = RunState()
    state.apply(SparklineSample(t=0, score=0.4))
    state.apply(SparklineSample(t=1, score=0.55))
    state.apply(SparklineSample(t=2, score=0.72))

    assert [(p.t, p.score) for p in state.sparkline] == [(0, 0.4), (1, 0.55), (2, 0.72)]


def test_mutation_proposal_still_works_after_b1_changes() -> None:
    """Regression check: pre-existing MutationProposal handler unchanged."""
    state = RunState()
    state.apply(WorkerSpawned(worker_id="w0", strategy=""))
    proposal = {"action": "edit", "target_skill": "greeter",
                "proposed_skill": "x", "justification": "y"}
    state.apply(MutationProposal(worker_id="w0", proposal=proposal))
    assert state.workers["w0"].last_proposal == proposal
