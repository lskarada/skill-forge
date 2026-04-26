"""Sync→async event bridge for the dashboard.

Worker threads in optimize.py call `emit_event(evt)` (sync). The bridge
hops onto the asyncio loop running uvicorn via
`loop.call_soon_threadsafe`, then dispatches to subscribers. Without a
bound loop the bridge is a no-op so optimize.py can call emit_event
unconditionally — core installs without the [ui] extras still work.

Only stdlib imports here. No FastAPI / no jinja2.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

# Per-subscriber bounded queue. If a slow client falls behind, we drop
# the oldest event and re-emit a StateSnapshot so the UI re-syncs (Phase 2).
SUBSCRIBER_QUEUE_MAX = 256


# ---- Event dataclasses --------------------------------------------------
#
# Frozen so subscribers cannot mutate them after dispatch. All events
# carry a `kind` field so consumers can switch on a string tag without
# isinstance() chains.


@dataclass(frozen=True)
class RunStarted:
    skill: str
    run_id: str
    num_workers: int
    kind: str = "RunStarted"


@dataclass(frozen=True)
class PhaseChanged:
    phase: int  # 1..5
    kind: str = "PhaseChanged"


@dataclass(frozen=True)
class BaselineCaptured:
    passed: int
    failed: int
    errors: int
    kind: str = "BaselineCaptured"


@dataclass(frozen=True)
class WorkerSpawned:
    worker_id: str
    strategy: str
    spawned_at: float = 0.0  # time.monotonic() snapshot for elapsed-clock
    kind: str = "WorkerSpawned"


@dataclass(frozen=True)
class WorkerStatus:
    worker_id: str
    # queued|mutating|testing|done|errored|merged|discarded
    status: str
    kind: str = "WorkerStatus"


@dataclass(frozen=True)
class WorkerTested:
    worker_id: str
    passed: int
    failed: int
    errors: int
    kind: str = "WorkerTested"


@dataclass(frozen=True)
class WorkerMerged:
    worker_id: str
    new_generation: int
    kind: str = "WorkerMerged"


@dataclass(frozen=True)
class RunFinished:
    outcome: str  # merged|regression|tie|no_change|aborted
    kind: str = "RunFinished"


@dataclass
class EventBus:
    """Thread-safe event bus.

    Producers call `emit(evt)` from any thread. Consumers `subscribe()`
    on the asyncio loop thread; each subscriber gets its own bounded
    asyncio.Queue.
    """

    loop: asyncio.AbstractEventLoop | None = None
    _subscribers_q: list[asyncio.Queue] = field(default_factory=list)
    _subscribers_cb: list[Callable[[Any], None]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---- producer side (any thread) -----------------------------------

    def emit(self, evt: Any) -> None:
        """Sync, thread-safe. No-op if no loop bound."""
        loop = self.loop
        if loop is None:
            return
        # call_soon_threadsafe is the contract — DO NOT replace with
        # queue.put_nowait, which is not safe across threads.
        try:
            loop.call_soon_threadsafe(self._dispatch_threadsafe, evt)
        except RuntimeError:
            # Loop closed mid-emit. Treat as benign no-op.
            pass

    # ---- subscription side (loop thread) ------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Subscribe a new SSE client. Must be called from the loop thread."""
        q: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
        with self._lock:
            self._subscribers_q.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            try:
                self._subscribers_q.remove(q)
            except ValueError:
                pass

    def subscribe_callback(self, fn: Callable[[Any], None]) -> None:
        """Subscribe a plain callback. Used by tests + state aggregator."""
        with self._lock:
            self._subscribers_cb.append(fn)

    # ---- lifecycle ----------------------------------------------------

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def unbind_loop(self) -> None:
        self.loop = None

    # ---- internal -----------------------------------------------------

    def _dispatch_threadsafe(self, evt: Any) -> None:
        """Runs on the loop thread (scheduled via call_soon_threadsafe)."""
        with self._lock:
            queues = list(self._subscribers_q)
            callbacks = list(self._subscribers_cb)
        for cb in callbacks:
            try:
                cb(evt)
            except Exception:  # noqa: BLE001
                log.exception("dashboard subscribe_callback raised")
        for q in queues:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                # Drop oldest, push newest, then signal a snapshot resync.
                try:
                    _ = q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(evt)
                except asyncio.QueueFull:
                    pass
                log.warning("dashboard subscriber queue overflowed; oldest dropped")


# ---- module-global bus (the API optimize.py uses) -----------------------

_global_bus: EventBus = EventBus()


def get_global_bus() -> EventBus:
    return _global_bus


def reset_global_bus() -> None:
    """Test helper — fresh bus, no bound loop, no subscribers."""
    global _global_bus
    _global_bus = EventBus()


def emit_event(evt: Any, *, bus: EventBus | None = None) -> None:
    """Sync emit. Called from worker threads in optimize.py.

    No-op if no loop bound — core CLI users (no `--ui`, no [ui] extras)
    pay only a single attribute lookup per call.
    """
    (bus or _global_bus).emit(evt)
