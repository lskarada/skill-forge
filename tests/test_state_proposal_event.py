"""Task 4.7 — MutationProposal event populates worker.last_proposal."""
from __future__ import annotations

from skill_forge.dashboard.events import MutationProposal, WorkerSpawned
from skill_forge.dashboard.state import RunState


def test_mutation_proposal_event_lands_on_worker_last_proposal() -> None:
    state = RunState()
    state.apply(WorkerSpawned(worker_id="w0", strategy=""))

    proposal = {
        "action": "edit",
        "target_skill": "greeter",
        "proposed_skill": "Add JSON envelope schema.",
        "justification": "Test asserts schema match.",
    }
    state.apply(MutationProposal(worker_id="w0", proposal=proposal))

    assert state.workers["w0"].last_proposal == proposal


def test_mutation_proposal_event_creates_worker_if_missing() -> None:
    """Event arrival ordering may put MutationProposal before WorkerSpawned;
    the state should self-heal by creating a default WorkerView."""
    state = RunState()
    proposal = {"action": "create", "target_skill": None,
                "proposed_skill": "x", "justification": "y"}

    state.apply(MutationProposal(worker_id="w7", proposal=proposal))

    assert state.workers["w7"].last_proposal == proposal
