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

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from skill_forge.dashboard import events as ev


@dataclass
class TestCounts:
    passed: int
    failed: int
    errors: int


# v0.7 Mission Control state types -----------------------------------------

@dataclass
class GenerationSnapshot:
    """One generation worth of bracket data preserved across rounds.

    Used by the multi-gen tree renderer (`_evo_tree.html`) to show the
    surviving trunk + discard branches at every level.
    """
    gen: int
    parent: str
    workers: list["WorkerView"]   # snapshot at GenerationStarted boundary


@dataclass
class LineageView:
    """One node in the top-bar lineage strip (baseline → v1 → v2 → ...)."""
    label: str
    score: float
    parent: str = ""


@dataclass
class FrontierEntryView:
    """One card in the top-K frontier panel."""
    id: str
    score: float
    parent: str = ""
    active: bool = False  # most recent admit pulse


@dataclass
class SparklinePoint:
    """One score-over-time data point per frontier program."""
    t: int
    score: float


@dataclass
class WorkerView:
    id: str  # "w0", "w1", ...
    strategy: str = ""
    status: str = "queued"  # queued|mutating|testing|done|errored|merged|discarded
    phase: str = "queued"
    tests: Optional[TestCounts] = None
    delta_pass: Optional[int] = None  # vs. baseline
    merged: bool = False  # convenience flag for kept-row CSS
    spawned_at: Optional[float] = None  # time.monotonic at spawn (for live clock)
    last_proposal: Optional[object] = None  # v0.4: Proposer JSON, consumed by v0.7 why-rail


@dataclass
class RunStats:
    baseline: Optional[TestCounts] = None
    best: Optional[TestCounts] = None
    delta_pass: int = 0
    merge_target: Optional[str] = None  # e.g. "v3"
    merged_count: int = 0
    elapsed: str = "0s"
    elapsed_secs: int = 0  # raw seconds — drives client-side 1s ticker


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
        # Phase C: bracket parent label, e.g. "baseline" or "v2".
        self.parent_label: str = "baseline"
        # v0.7 Mission Control fields (consumed by _lineage / _frontier / _sparkline).
        self.generations: list[LineageView] = []
        self.frontier: list[FrontierEntryView] = []
        self.sparkline: list[SparklinePoint] = []
        # v0.7.1: multi-generation tree state. Each entry preserves a frozen
        # snapshot of `workers` from one generation so the evo-tree renderer
        # can show every round's fan-out in a single growing tree.
        self.lineage_history: list[GenerationSnapshot] = []
        self.current_generation: int = 0

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
            spawned_at = getattr(evt, "spawned_at", None)
            # Don't treat 0.0 as falsy — it's a real (boot-time) reading.
            if spawned_at is None:
                spawned_at = time.monotonic()
            self.workers[wid] = WorkerView(
                id=wid,
                strategy=getattr(evt, "strategy", ""),
                status="queued",
                phase="queued",
                spawned_at=spawned_at,
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
        elif kind == "MutationProposal":
            wid = evt.worker_id  # type: ignore[attr-defined]
            w = self.workers.setdefault(wid, WorkerView(id=wid))
            w.last_proposal = evt.proposal  # type: ignore[attr-defined]
        elif kind == "GenerationStarted":
            # Snapshot current workers as a generation in the lineage tree
            # before clearing for the next round. The first gen (gen=0) has
            # nothing to snapshot; subsequent gens preserve the prior round.
            new_gen = evt.gen  # type: ignore[attr-defined]
            parent = evt.parent  # type: ignore[attr-defined]
            if self.workers:
                # Freeze a copy of every worker so later mutations don't
                # mutate the snapshot.
                snap = [
                    WorkerView(
                        id=w.id, strategy=w.strategy, status=w.status,
                        phase=w.phase, tests=w.tests, delta_pass=w.delta_pass,
                        merged=w.merged, spawned_at=w.spawned_at,
                        last_proposal=w.last_proposal,
                    )
                    for w in self.workers.values()
                ]
                self.lineage_history.append(GenerationSnapshot(
                    gen=self.current_generation, parent=self.parent_label,
                    workers=snap,
                ))
            self.current_generation = new_gen
            self.parent_label = parent
            self.workers.clear()
        elif kind == "FrontierUpdated":
            existing = {fe.id: fe for fe in self.frontier}
            existing[evt.admitted_id] = FrontierEntryView(  # type: ignore[attr-defined]
                id=evt.admitted_id,  # type: ignore[attr-defined]
                score=evt.admitted_score,  # type: ignore[attr-defined]
                parent=self.parent_label,
                active=True,
            )
            evicted = getattr(evt, "evicted_id", None)
            if evicted and evicted in existing:
                del existing[evicted]
            # Demote prior actives so only the new admit pulses
            for fe_id, fe in existing.items():
                if fe_id != evt.admitted_id and fe.active:  # type: ignore[attr-defined]
                    existing[fe_id] = FrontierEntryView(
                        id=fe.id, score=fe.score, parent=fe.parent, active=False,
                    )
            self.frontier = sorted(existing.values(), key=lambda e: e.id)
        elif kind == "SparklineSample":
            self.sparkline.append(SparklinePoint(
                t=evt.t, score=evt.score,  # type: ignore[attr-defined]
            ))

    # ---- read side ---------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            elapsed_secs = self._elapsed_secs_locked()
            elapsed = _format_elapsed(elapsed_secs)
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
                elapsed_secs=elapsed_secs,
            )
            now = time.monotonic()
            workers = [_worker_view_for_render(w, now) for w in _sorted_workers(self.workers)]
            # v0.7.1 Mission Control fields. Templates render gracefully
            # on empty state (lineage strip shows "no generations yet",
            # frontier shows "frontier is empty", etc).
            current_workers = list(self.workers.values())
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
                "parent_label": self.parent_label,
                # v0.7.1
                "generations": list(self.generations),
                "frontier": list(self.frontier),
                "sparkline": list(self.sparkline),
                "lineage_history": list(self.lineage_history),
                "current_workers": current_workers,
            }

    def _elapsed_secs_locked(self) -> int:
        if self.started_at is None:
            return 0
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0, int(end - self.started_at))

    def _elapsed_locked(self) -> str:
        return _format_elapsed(self._elapsed_secs_locked())

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


def resolve_parent_label(output_root: Path, skill: str) -> str:
    """Return the highest existing version label under
    `<output_root>/history/<skill>/` (e.g. 'v2'), else 'baseline'.

    Used by `forge optimize`/`forge improve` at run start to label the
    parent node in the dashboard bracket. Read-only — never writes.
    """
    history = output_root / "history" / skill
    if not history.is_dir():
        return "baseline"
    versions: list[int] = []
    for p in history.iterdir():
        m = re.match(r"v(\d+)_evidence\.md$", p.name)
        if m:
            versions.append(int(m.group(1)))
    if not versions:
        return "baseline"
    return f"v{max(versions)}"


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


def _format_elapsed(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _worker_view_for_render(w: WorkerView, now: float | None = None) -> dict:
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
    if w.spawned_at is not None and now is not None:
        elapsed = _format_elapsed(max(0, int(now - w.spawned_at)))
    else:
        elapsed = "—"
    return {
        "id": w.id,
        "strategy": w.strategy or "",
        "strategy_tag": _strategy_tag(w.strategy),
        "status": w.status,
        "phase": w.phase,
        "tests": w.tests,
        "delta": w.delta_pass,
        "merged": w.merged,
        "dot_class": dot,
        "status_label": label,
        "elapsed": elapsed,
    }


def _strategy_tag(strategy: str | None) -> str:
    """Short single-word tag for the bracket node — first word of the
    strategy text, lowercased, max 14 chars. Empty if no strategy set."""
    if not strategy:
        return ""
    parts = strategy.strip().split()
    if not parts:
        return ""
    return parts[0].lower().strip(".,;:")[:14]


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
