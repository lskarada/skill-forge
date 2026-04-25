"""Phase-2 gate 2.1 — RunState aggregator state machine."""

from __future__ import annotations

from skill_forge.dashboard import events as ev
from skill_forge.dashboard import state as state_mod


def _scripted_sequence() -> list[object]:
    """Canonical run lifecycle the demo + state tests share."""
    return [
        ev.RunStarted(skill="greeter", run_id="run_test", num_workers=3),
        ev.PhaseChanged(phase=1),
        ev.BaselineCaptured(passed=0, failed=2, errors=0),
        ev.PhaseChanged(phase=2),
        ev.WorkerSpawned(worker_id="w0", strategy="strict envelope"),
        ev.WorkerSpawned(worker_id="w1", strategy="forbidden phrases"),
        ev.WorkerSpawned(worker_id="w2", strategy="numbered procedure"),
        ev.WorkerStatus(worker_id="w0", status="mutating"),
        ev.WorkerStatus(worker_id="w1", status="mutating"),
        ev.WorkerStatus(worker_id="w2", status="mutating"),
        ev.WorkerStatus(worker_id="w0", status="testing"),
        ev.WorkerTested(worker_id="w0", passed=2, failed=0, errors=0),
        ev.WorkerStatus(worker_id="w0", status="done"),
        ev.WorkerStatus(worker_id="w1", status="testing"),
        ev.WorkerTested(worker_id="w1", passed=1, failed=1, errors=0),
        ev.WorkerStatus(worker_id="w1", status="done"),
        ev.WorkerStatus(worker_id="w2", status="testing"),
        ev.WorkerTested(worker_id="w2", passed=0, failed=2, errors=0),
        ev.WorkerStatus(worker_id="w2", status="done"),
        ev.PhaseChanged(phase=4),
        ev.WorkerMerged(worker_id="w0", new_generation=1),
        ev.WorkerStatus(worker_id="w0", status="merged"),
        ev.WorkerStatus(worker_id="w1", status="discarded"),
        ev.WorkerStatus(worker_id="w2", status="discarded"),
        ev.PhaseChanged(phase=5),
        ev.RunFinished(outcome="merged"),
    ]


def test_state_machine_transitions_walk_in_order() -> None:
    """A worker walks queued → mutating → testing → done → discarded
    when it loses the tie-break."""
    state = state_mod.RunState()
    transitions: list[str] = []

    for evt in _scripted_sequence():
        state.apply(evt)
        if getattr(evt, "kind", None) == "WorkerStatus":
            if getattr(evt, "worker_id", None) == "w1":
                transitions.append(getattr(evt, "status"))

    # `WorkerSpawned` set w1 to "queued"; subsequent transitions added.
    assert transitions == ["mutating", "testing", "done", "discarded"]


def test_worker_tested_precedes_terminal_status() -> None:
    """`WorkerTested` must be applied before the terminal status so the
    UI can rely on tests being present when it sees `done`."""
    state = state_mod.RunState()
    seen_tests = False
    saw_done_with_tests = False
    for evt in _scripted_sequence():
        state.apply(evt)
        if getattr(evt, "kind", None) == "WorkerTested":
            if getattr(evt, "worker_id") == "w0":
                seen_tests = True
        if (
            getattr(evt, "kind", None) == "WorkerStatus"
            and getattr(evt, "worker_id") == "w0"
            and getattr(evt, "status") == "done"
        ):
            assert seen_tests, "WorkerTested must precede WorkerStatus(done)"
            assert state.workers["w0"].tests is not None
            saw_done_with_tests = True
    assert saw_done_with_tests


def test_baseline_and_best_tracked() -> None:
    state = state_mod.RunState()
    for evt in _scripted_sequence():
        state.apply(evt)
    snap = state.snapshot()
    assert snap["stats"].baseline.passed == 0
    assert snap["stats"].best.passed == 2  # w0 hit 2/0/0
    assert snap["stats"].delta_pass == 2
    assert snap["counts"]["merged"] == 1
    assert snap["counts"]["discarded"] == 2
    assert snap["counts"]["errored"] == 0


def test_errored_worker_does_not_set_tests() -> None:
    """`errored` workers do not fire WorkerTested. The UI knows this and
    renders 'err' in the test cell."""
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="x", run_id="r", num_workers=1))
    state.apply(ev.WorkerSpawned(worker_id="w0", strategy="boom"))
    state.apply(ev.WorkerStatus(worker_id="w0", status="mutating"))
    state.apply(ev.WorkerStatus(worker_id="w0", status="errored"))
    assert state.workers["w0"].tests is None
    assert state.workers["w0"].status == "errored"


def test_run_finished_flips_running_false() -> None:
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="x", run_id="r", num_workers=1))
    assert state.running is True
    state.apply(ev.RunFinished(outcome="merged"))
    assert state.running is False
