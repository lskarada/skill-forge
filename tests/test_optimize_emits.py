"""Phase-3 gate 3.1 — emit_event call sites in the real optimize loop.

Drives `run_optimize()` against the same in-memory fakes as
`test_optimize_m3.py`, but with the dashboard event bus subscribed via
a recorder. Asserts:
  * the recorded event sequence is correct
  * losing-worker `diff.patch` and `tests.txt` sidecars exist after
    worktree cleanup, so the Phase-4 drilldown can read them
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from skill_forge import baseline as baseline_mod
from skill_forge import optimize as opt_mod
from skill_forge import worktree as wt_mod
from skill_forge.dashboard import events as ev


# Reuse the helper functions from test_optimize_m3 (sibling module).
import sys
sys.path.insert(0, str(Path(__file__).parent))
from test_optimize_m3 import _setup, _make_io  # noqa: E402


def test_callsite_sequence(tmp_path: Path) -> None:
    """A real run emits the canonical lifecycle in order."""
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    plans = [
        {"index": 0, "post_counts": (1, 1, 0), "body": "loser-a\n"},
        {"index": 1, "post_counts": (2, 0, 0), "body": "winning body\n"},
        {"index": 2, "post_counts": (1, 1, 0), "body": "loser-c\n"},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)

    bus = ev.EventBus()
    recorded: list[object] = []
    bus.subscribe_callback(recorded.append)
    # Bind a fake "loop": for the recorder-callback path we don't need
    # an asyncio loop — emit() runs the callback inline if no loop is
    # bound, but the bus design says it's a no-op without a loop. Use
    # the stub-loop helper that just runs callbacks synchronously.
    _bind_inline_loop(bus)

    ev.reset_global_bus()
    # Re-point the global bus at our recorder.
    ev._global_bus = bus  # type: ignore[attr-defined]
    try:
        result = opt_mod.run_optimize(config, io)
    finally:
        ev.reset_global_bus()

    assert result.outcome == "merged"
    kinds = [getattr(e, "kind", None) for e in recorded]
    # The exact emit ordering: RunStarted → PhaseChanged(1) →
    # BaselineCaptured → PhaseChanged(2) → WorkerSpawned →
    # WorkerStatus(mutating) → WorkerStatus(testing) → WorkerTested →
    # WorkerStatus(done) → WorkerStatus(merged) → WorkerMerged →
    # PhaseChanged(5) → RunFinished.
    assert kinds[0] == "RunStarted"
    assert "BaselineCaptured" in kinds
    # Worker lifecycle in order
    worker_kinds = [k for k in kinds if k and "Worker" in k]
    assert worker_kinds[0] == "WorkerSpawned"
    # WorkerTested must precede the terminal status.
    tested_idx = worker_kinds.index("WorkerTested")
    # The merged status comes after WorkerTested.
    merged_status_idx = next(
        (i for i, e in enumerate(recorded)
         if getattr(e, "kind", None) == "WorkerStatus"
         and getattr(e, "status", None) == "merged"),
        None,
    )
    tested_global_idx = next(
        i for i, e in enumerate(recorded)
        if getattr(e, "kind", None) == "WorkerTested"
    )
    assert merged_status_idx is not None
    assert tested_global_idx < merged_status_idx
    assert kinds[-1] == "RunFinished"


def test_diff_persisted_for_losing_workers(tmp_path: Path) -> None:
    """A run where w1 wins and w0/w2 lose: every worker's diff.patch
    and tests.txt must exist on disk after worktree cleanup so the
    Phase-4 drilldown can read them."""
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    plans = [
        {"index": 0, "post_counts": (1, 1, 0), "body": "loser-a\n"},
        {"index": 1, "post_counts": (2, 0, 0), "body": "winner-b\n"},
        {"index": 2, "post_counts": (1, 1, 0), "body": "loser-c\n"},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)

    result = opt_mod.run_optimize(config, io)
    assert result.outcome == "merged"
    runs_root = config.output_root / "runs"
    # run_id is "<skill>/<timestamp>"; sidecars sit at
    # runs/<skill>/<timestamp>/<wid>/. Find the per-worker dirs by glob.
    for wid in ("w0", "w1", "w2"):
        matches = list(runs_root.glob(f"**/{wid}/diff.patch"))
        assert matches, f"missing diff.patch for {wid}"
        diff = matches[0]
        tests = diff.with_name("tests.txt")
        assert tests.is_file(), f"missing tests.txt for {wid}"
        assert diff.read_text().strip(), f"diff for {wid} is empty"


def test_tiebreak_losers_emit_discarded(tmp_path: Path) -> None:
    """When all workers strictly beat baseline and the picker breaks the
    tie on SUT length, the non-winners must emit WorkerStatus(discarded)
    so the dashboard's discarded count is correct."""
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    plans = [
        {"index": 0, "post_counts": (2, 0, 0), "body": "x" * 50 + "\n"},  # long
        {"index": 1, "post_counts": (2, 0, 0), "body": "short\n"},  # winner
        {"index": 2, "post_counts": (2, 0, 0), "body": "x" * 30 + "\n"},  # medium
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)

    bus = ev.EventBus()
    recorded: list[object] = []
    bus.subscribe_callback(recorded.append)
    _bind_inline_loop(bus)
    ev.reset_global_bus()
    ev._global_bus = bus  # type: ignore[attr-defined]
    try:
        result = opt_mod.run_optimize(config, io)
    finally:
        ev.reset_global_bus()

    assert result.outcome == "merged"
    discarded_emits = {
        getattr(e, "worker_id", None)
        for e in recorded
        if getattr(e, "kind", None) == "WorkerStatus"
        and getattr(e, "status", None) == "discarded"
    }
    # w0 and w2 lost the tiebreak — both must be marked discarded.
    assert discarded_emits == {"w0", "w2"}, (
        f"expected {{w0, w2}} discarded, got {discarded_emits}"
    )


def test_aborts_when_sut_has_staged_changes(tmp_path: Path, monkeypatch) -> None:
    """If the parent repo has uncommitted changes to the SUT, the
    Phase-5 `git merge --no-ff` fails with 'local changes would be
    overwritten'. Catch it at the start so we don't burn subagent API."""
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    plans = [
        {"index": 0, "post_counts": (2, 0, 0), "body": "a\n"},
        {"index": 1, "post_counts": (2, 0, 0), "body": "b\n"},
        {"index": 2, "post_counts": (2, 0, 0), "body": "c\n"},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)

    # Simulate `git status --porcelain` reporting the SUT as modified.
    monkeypatch.setattr(
        opt_mod, "_check_sut_clean",
        lambda repo_path, sut_path: f"{sut_path} has uncommitted changes",
    )

    result = opt_mod.run_optimize(config, io)
    assert result.outcome == "aborted"
    # No subagents got dispatched — money saved.
    assert calls.mutator == []
    # User got a clear actionable message in the printer log.
    joined = "\n".join(calls.printed)
    assert "uncommitted" in joined.lower() or "stash" in joined.lower()


def test_no_subscribers_zero_cost() -> None:
    """Phase-3 gate 3.2 — emit_event() with no bound loop is a true
    no-op. Cheap enough to live unconditionally in the optimize loop."""
    import time

    ev.reset_global_bus()
    t0 = time.perf_counter()
    for i in range(10_000):
        ev.emit_event(("noop", i))
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.05, f"no-op path too slow: {elapsed:.3f}s for 10k emits"


# ---- helpers -------------------------------------------------------------


def _bind_inline_loop(bus: ev.EventBus) -> None:
    """A stand-in for `bus.bind_loop` that runs callbacks immediately on
    the calling thread. Lets the recorder see events without spinning up
    an asyncio loop."""
    class _InlineLoop:
        def call_soon_threadsafe(self, fn, *args):
            fn(*args)
    bus.loop = _InlineLoop()  # type: ignore[assignment]
