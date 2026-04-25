"""Phase-2 gate 2.2 — scripted demo drives the live UI.

Replaces the v1 plan's hidden CLI command with a pytest-driven scenario
so the demo data path can't rot. Runs the canonical event sequence
through the bus + state + SSE generator, verifies every event reaches
an SSE subscriber, and that the final HTML at `/` shows the merged
worker highlighted with baseline counts populated.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from skill_forge.dashboard import events as ev  # noqa: E402
from skill_forge.dashboard import routes as routes_mod  # noqa: E402
from skill_forge.dashboard import server as srv  # noqa: E402
from skill_forge.dashboard import state as state_mod  # noqa: E402


def _scripted_sequence() -> list[object]:
    return [
        ev.RunStarted(skill="greeter", run_id="run_demo_42", num_workers=3),
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


def test_scripted_run_drives_ui() -> None:
    """Phase-2 gate 2.2 — every scripted event reaches an SSE subscriber;
    final HTML at `/` shows winner highlighted, baseline populated."""
    bus = ev.EventBus()
    state = state_mod.RunState()
    sequence = _scripted_sequence()

    received: list[object] = []

    async def drive():
        loop = asyncio.get_running_loop()
        bus.bind_loop(loop)
        # Two subscribers: the state aggregator (callback) and an SSE
        # client (queue). We assert both see every event.
        state_mod.attach_to_bus(bus, state)
        bus.subscribe_callback(received.append)

        env = routes_mod._make_env()
        stop = asyncio.Event()
        gen = routes_mod.sse_stream(env, bus, state, stop_event=stop)
        # Drain the two initial snapshot frames so we don't conflate
        # them with event-driven frames.
        await gen.__anext__()
        await gen.__anext__()

        for evt in sequence:
            bus.emit(evt)
            # Each event yields at least one fragment (stats), and
            # worker-targeted ones yield two (stats + row).
            await asyncio.sleep(0)
        # Drain the per-event frames; we know each event produces ≥1.
        # Use a generous deadline.
        seen_frames = 0
        try:
            while seen_frames < len(sequence):
                _ = await asyncio.wait_for(gen.__anext__(), timeout=1)
                seen_frames += 1
        except asyncio.TimeoutError:
            pass
        stop.set()
        return seen_frames

    seen_frames = asyncio.run(drive())

    # The callback subscriber must see every event.
    assert len(received) == len(sequence), (
        f"got {len(received)} of {len(sequence)} events"
    )
    # SSE generator must have yielded at least one frame per event.
    assert seen_frames >= len(sequence)

    # Final state: w0 merged, w1/w2 discarded, baseline populated.
    snap = state.snapshot()
    assert snap["counts"]["merged"] == 1
    assert snap["counts"]["discarded"] == 2
    assert snap["stats"].baseline.passed == 0
    assert snap["stats"].best.passed == 2
    assert snap["counts"]["total"] == 3

    # Render `/` — must mark w0 as the kept-row.
    app = srv.create_app(bus=bus, state=state)
    with TestClient(app) as c:
        body = c.get("/").text
        assert "w0" in body
        assert "kept-row" in body
        # baseline counts visible in stats
        assert "0/2/0" in body
        # winner counts visible (best so far)
        assert "2/0/0" in body


def test_drilldown_after_demo(tmp_path: Path) -> None:
    """Phase-4 gate 4.2 — after the scripted demo, write fake sidecars
    for each worker and GET each fragment endpoint. All return 200 with
    non-empty bodies, including for discarded workers."""
    bus = ev.EventBus()
    state = state_mod.RunState()
    for evt in _scripted_sequence():
        state.apply(evt)

    state.sidecar_root = tmp_path  # type: ignore[attr-defined]
    run_dir = tmp_path / "runs" / state.run_id
    for wid in ("w0", "w1", "w2"):
        wdir = run_dir / wid
        wdir.mkdir(parents=True)
        (wdir / "diff.patch").write_text(
            f"--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1 @@\n-old\n+{wid}-mutation\n"
        )
        (wdir / "transcript.txt").write_text(f"{wid} subagent transcript\n")
        (wdir / "tests.txt").write_text(f"{wid}: passed=2 failed=0 errors=0\n")

    app = srv.create_app(bus=bus, state=state)
    with TestClient(app) as c:
        for wid in ("w0", "w1", "w2"):
            for kind in ("diff", "transcript", "tests"):
                r = c.get(f"/workers/{wid}/{kind}")
                assert r.status_code == 200, f"{wid}/{kind}: {r.status_code}"
                assert r.text.strip(), f"{wid}/{kind}: empty body"
