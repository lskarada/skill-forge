"""Phase-1 gate 1.1: sync→async event bridge.

The riskiest unknown in the dashboard is delivering events from worker
*threads* (ThreadPoolExecutor in optimize.py) into an asyncio loop running
uvicorn. asyncio.Queue.put_nowait is NOT thread-safe; the bridge must use
loop.call_soon_threadsafe with a captured loop reference.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

# Module under test (created next).
from skill_forge.dashboard import events as ev


def _start_loop_in_thread() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    # Wait a beat for the thread to actually be running the loop.
    while not loop.is_running():
        time.sleep(0.001)
    return loop, t


def _stop_loop(loop: asyncio.AbstractEventLoop, t: threading.Thread) -> None:
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)
    loop.close()


def test_emit_from_worker_thread_preserves_per_thread_order() -> None:
    """3 worker threads × 50 events each — 150 events all arrive, each
    thread's events arrive in that thread's emit order. No assertion on
    cross-thread interleaving (call_soon_threadsafe preserves per-thread
    order, not global order)."""
    loop, t = _start_loop_in_thread()
    bus = ev.EventBus()

    received: list[tuple[str, int]] = []
    received_lock = threading.Lock()

    async def _consume() -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()

        def on_event(evt: object) -> None:
            # Dispatched on the loop thread; safe to mutate plain list under lock.
            with received_lock:
                received.append(evt)  # type: ignore[arg-type]

        bus.subscribe_callback(on_event)
        return q

    asyncio.run_coroutine_threadsafe(_consume(), loop).result(timeout=1)
    bus.bind_loop(loop)

    def worker(name: str) -> None:
        for i in range(50):
            ev.emit_event((name, i), bus=bus)

    workers = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(3)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    # Drain: give the loop a moment to dispatch all queued call_soon_threadsafe.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with received_lock:
            if len(received) == 150:
                break
        time.sleep(0.01)

    try:
        with received_lock:
            assert len(received) == 150, f"expected 150 events, got {len(received)}"
            for thread_name in ("w0", "w1", "w2"):
                indexes = [i for (n, i) in received if n == thread_name]
                assert indexes == list(range(50)), (
                    f"events from {thread_name} arrived out of order: {indexes[:10]}..."
                )
    finally:
        _stop_loop(loop, t)


def test_emit_noop_when_loop_not_bound() -> None:
    """A bus with no bound loop must drop events silently — no exception,
    no measurable cost. Lets `emit_event` live unconditionally in the
    optimize loop without forcing all CLI users to install [ui]."""
    bus = ev.EventBus()
    # No bind_loop call.
    t0 = time.perf_counter()
    for i in range(10_000):
        ev.emit_event(("noop", i), bus=bus)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"no-op path too slow: {elapsed:.3f}s for 10k calls"


def test_emit_event_module_default_bus_is_noop_until_bound() -> None:
    """The module-level emit_event() with no `bus=` must use the global
    bus; if nobody bound a loop, it's a no-op. This is the API call sites
    in optimize.py will use."""
    # Reset module-global bus to a clean state.
    ev.reset_global_bus()
    # No exception, no error.
    ev.emit_event(("smoke", 1))
    assert ev.get_global_bus() is not None
