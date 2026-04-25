"""RunState aggregator.

Receives event objects from the bus, mutates the in-memory snapshot of
the run. Snapshot is consumed by:
- `/` (initial render — late tabs see the current state)
- `/events` first frame (StateSnapshot for SSE reconnect resync)

State machine for one worker:

    queued → mutating → testing → done|errored
                                  └── (merge logic) → merged|discarded

`WorkerTested` always precedes the terminal `WorkerStatus`. `errored`
workers do NOT fire `WorkerTested` — UI knows to render `err`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from skill_forge.dashboard import events as ev


@dataclass
class TestCounts:
    passed: int
    failed: int
    errors: int


@dataclass
class WorkerView:
    id: str  # "w0", "w1", ...
    strategy: str = ""
    status: str = "queued"  # queued|mutating|testing|done|errored|merged|discarded
    phase: str = "queued"
    tests: Optional[TestCounts] = None
    delta_pass: Optional[int] = None  # vs. baseline
    merged: bool = False  # convenience flag for kept-row CSS


@dataclass
class RunStats:
    baseline: Optional[TestCounts] = None
    best: Optional[TestCounts] = None
    delta_pass: int = 0
    merge_target: Optional[str] = None  # e.g. "v3"
    merged_count: int = 0
    elapsed: str = "0s"


class RunState:
    """In-memory aggregator. Thread-safe (mutated only on the loop thread,
    but `snapshot()` may be called from request handlers / tests on other
    threads — we lock to be safe)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.skill: str = ""
        self.run_id: str = ""
        self.phase: int = 0
        self.running: bool = False
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.workers: dict[str, WorkerView] = {}
        self.baseline: Optional[TestCounts] = None
        self.best: Optional[TestCounts] = None
        self.merge_target: Optional[str] = None
        self.merged_count: int = 0

    # ---- event ingest ------------------------------------------------

    def apply(self, evt: object) -> None:
        with self._lock:
            self._apply_locked(evt)

    def _apply_locked(self, evt: object) -> None:
        kind = getattr(evt, "kind", None)
        if kind == "RunStarted":
            self.skill = evt.skill  # type: ignore[attr-defined]
            self.run_id = evt.run_id  # type: ignore[attr-defined]
            self.running = True
            self.started_at = time.monotonic()
            self.phase = 0
            self.workers.clear()
            self.baseline = None
            self.best = None
            self.merge_target = None
            self.merged_count = 0
        elif kind == "PhaseChanged":
            self.phase = evt.phase  # type: ignore[attr-defined]
        elif kind == "BaselineCaptured":
            self.baseline = TestCounts(evt.passed, evt.failed, evt.errors)  # type: ignore[attr-defined]
        elif kind == "WorkerSpawned":
            wid = evt.worker_id  # type: ignore[attr-defined]
            self.workers[wid] = WorkerView(
                id=wid,
                strategy=getattr(evt, "strategy", ""),
                status="queued",
                phase="queued",
            )
        elif kind == "WorkerStatus":
            wid = evt.worker_id  # type: ignore[attr-defined]
            w = self.workers.setdefault(wid, WorkerView(id=wid))
            w.status = evt.status  # type: ignore[attr-defined]
            w.phase = _phase_label(evt.status)  # type: ignore[attr-defined]
            if w.status == "merged":
                w.merged = True
                self.merged_count += 1
                self.merge_target = f"v{self.merged_count}"
        elif kind == "WorkerTested":
            wid = evt.worker_id  # type: ignore[attr-defined]
            w = self.workers.setdefault(wid, WorkerView(id=wid))
            w.tests = TestCounts(evt.passed, evt.failed, evt.errors)  # type: ignore[attr-defined]
            if self.baseline is not None:
                w.delta_pass = w.tests.passed - self.baseline.passed
            # Update best so far
            if self.best is None or w.tests.passed > self.best.passed:
                self.best = w.tests
        elif kind == "WorkerMerged":
            wid = evt.worker_id  # type: ignore[attr-defined]
            w = self.workers.setdefault(wid, WorkerView(id=wid))
            w.merged = True
            w.status = "merged"
            w.phase = "complete"
        elif kind == "RunFinished":
            self.running = False
            self.finished_at = time.monotonic()

    # ---- read side ---------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = self._elapsed_locked()
            counts = self._counts_locked()
            stats = RunStats(
                baseline=self.baseline,
                best=self.best,
                delta_pass=(self.best.passed - self.baseline.passed)
                    if self.best is not None and self.baseline is not None
                    else 0,
                merge_target=self.merge_target,
                merged_count=self.merged_count,
                elapsed=elapsed,
            )
            workers = [_worker_view_for_render(w) for w in _sorted_workers(self.workers)]
            return {
                "skill": self.skill or "skill",
                "run_id": self.run_id or "—",
                "phase": self.phase,
                "running": self.running,
                "pill_label": _pill_label(self),
                "pill_class": "" if self.running else "done",
                "stats": stats,
                "counts": counts,
                "workers": workers,
            }

    def _elapsed_locked(self) -> str:
        if self.started_at is None:
            return "0s"
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        secs = max(0, int(end - self.started_at))
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m{secs % 60:02d}s"

    def _counts_locked(self) -> dict:
        merged = sum(1 for w in self.workers.values() if w.status == "merged" or w.merged)
        discarded = sum(1 for w in self.workers.values() if w.status == "discarded")
        errored = sum(1 for w in self.workers.values() if w.status == "errored")
        active = sum(
            1 for w in self.workers.values()
            if w.status in {"queued", "mutating", "testing"}
        )
        return {
            "total": len(self.workers),
            "merged": merged,
            "discarded": discarded,
            "errored": errored,
            "active": active,
        }


def _phase_label(status: str) -> str:
    return {
        "queued": "queued",
        "mutating": "mutating",
        "testing": "testing",
        "done": "complete",
        "errored": "errored",
        "merged": "complete",
        "discarded": "complete",
    }.get(status, status)


def _pill_label(state: "RunState") -> str:
    if not state.running and state.run_id:
        return "complete"
    active = sum(
        1 for w in state.workers.values()
        if w.status in {"queued", "mutating", "testing"}
    )
    if active:
        return f"{active} workers running"
    return "running"


def _sorted_workers(workers: dict[str, WorkerView]) -> list[WorkerView]:
    # Active first, then merged, then discarded/errored — matches the
    # mockup ordering. Within each group, by id descending (newest top).
    def order(w: WorkerView) -> tuple[int, str]:
        rank = {
            "queued": 0, "mutating": 0, "testing": 0,
            "merged": 1,
            "done": 2, "discarded": 2, "errored": 2,
        }.get(w.status, 3)
        return (rank, w.id)
    return sorted(workers.values(), key=order)


def _worker_view_for_render(w: WorkerView) -> dict:
    dot = {
        "queued": "active", "mutating": "active", "testing": "active",
        "merged": "kept",
        "done": "skip", "discarded": "skip",
        "errored": "err",
    }.get(w.status, "skip")
    label = {
        "queued": "Queued",
        "mutating": "Active",
        "testing": "Active",
        "done": "Discarded",
        "merged": "Merged",
        "discarded": "Discarded",
        "errored": "Errored",
    }.get(w.status, w.status)
    return {
        "id": w.id,
        "strategy": w.strategy or "",
        "status": w.status,
        "phase": w.phase,
        "tests": w.tests,
        "delta": w.delta_pass,
        "merged": w.merged,
        "dot_class": dot,
        "status_label": label,
    }


# ---- module-global state (paired with the global event bus) -------------

_state = RunState()


def get_state() -> RunState:
    return _state


def reset_state() -> None:
    global _state
    _state = RunState()


def attach_to_bus(bus: ev.EventBus, state: RunState) -> None:
    """Register the state aggregator as a callback subscriber on the bus.
    Called once during server startup."""
    bus.subscribe_callback(state.apply)
