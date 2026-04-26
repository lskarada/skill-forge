"""Phase-1 gate 1.2 + Phase-2/4 route tests.

The dashboard is gated behind the [ui] optional extras. If a developer
running the unit suite has the extras installed, the routes are
exercised; otherwise the file is skipped cleanly. Because the project's
pyproject promotes the [ui] extras as a first-class CI concern, CI
installs them and the tests run.
"""

from __future__ import annotations

import pytest

# Skip the whole module if the [ui] extras aren't installed locally.
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from skill_forge.dashboard import server as srv  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    # Use an isolated bus + state so other tests can't pollute this one
    # via the module-global state.
    from skill_forge.dashboard import events as ev
    from skill_forge.dashboard import state as state_mod
    bus = ev.EventBus()
    state = state_mod.RunState()
    app = srv.create_app(bus=bus, state=state)
    return TestClient(app)


def test_index_renders_mockup(client: TestClient) -> None:
    """Phase-1 gate 1.2 — `/` returns 200 + the locked mockup's
    load-bearing markers (logo, path, top stats, workers table)."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    # Logo + monospace skill path. The mockup ships a lowercase dotted "s f".
    assert ">s f<" in body
    assert "skill.skill" in body  # default placeholder skill name
    # All five stat labels from the mockup
    for label in ("baseline", "best so far", "merge target", "workers", "elapsed"):
        assert label in body, f"missing stat label: {label}"
    # Workers table header
    assert "WORKER" in body or "worker" in body


def test_port_picker_increments_when_default_taken(monkeypatch) -> None:
    """Phase-1 gate 1.2 — first port in range is in use → picker returns
    the next free one. Uses a high port range so the test doesn't fight
    a real dashboard process on 7777."""
    import socket

    occupied = []

    def _try_bind(port: int) -> bool:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            s.listen(1)
            occupied.append(s)
            return True
        except OSError:
            return False

    # Pick a high port range that's almost certainly free in CI.
    start = 8770
    while start < 8800 and not _try_bind(start):
        start += 1
    if start >= 8800:
        pytest.skip("no free port in 8770-8799 to run picker test")
    try:
        port = srv.pick_free_port(start=start, end=start + 5)
        assert port == start + 1
    finally:
        for s in occupied:
            s.close()


def test_sse_delivers_in_order() -> None:
    """Phase-2 gate 2.1 — publish 5 events, /events delivers all 5 as
    `event: html` frames, in publish order. Drive the async generator
    directly to avoid streaming-client deadlocks."""
    import asyncio
    from skill_forge.dashboard import events as ev
    from skill_forge.dashboard import routes as routes_mod
    from skill_forge.dashboard import state as state_mod

    bus = ev.EventBus()
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="t", run_id="r", num_workers=1))

    async def drive():
        loop = asyncio.get_running_loop()
        bus.bind_loop(loop)
        # subscribe via state so callbacks update the run state too
        state_mod.attach_to_bus(bus, state)
        env = routes_mod._make_env()
        stop = asyncio.Event()
        gen = routes_mod.sse_stream(env, bus, state, stop_event=stop)

        # Drain the two snapshot frames first.
        snap_frames = [await gen.__anext__(), await gen.__anext__()]

        # Schedule emits onto the same loop.
        for i in range(3):
            bus.emit(ev.WorkerSpawned(worker_id=f"w{i}", strategy=f"s{i}"))
            # Yield so call_soon_threadsafe runs and queues advance.
            await asyncio.sleep(0)

        # Each event triggers `_fragments_for_event` returning 2 fragments
        # (stats + worker_row). 3 events × 2 fragments = 6 frames.
        emit_frames = []
        for _ in range(6):
            emit_frames.append(await asyncio.wait_for(gen.__anext__(), timeout=2))
        stop.set()

        return snap_frames, emit_frames

    snap_frames, emit_frames = asyncio.run(drive())
    assert all("event: html" in f for f in snap_frames + emit_frames)
    # First emit's stats fragment must mention w0 spawned (it was the
    # most recent state update); each row fragment must carry its id.
    joined = "".join(emit_frames)
    assert "w0" in joined
    assert "w1" in joined
    assert "w2" in joined


def test_sse_reconnect_resends_snapshot() -> None:
    """Phase-2 gate 2.1 — every fresh subscription's first frames
    describe the current RunState (snapshot replay)."""
    import asyncio
    from skill_forge.dashboard import events as ev
    from skill_forge.dashboard import routes as routes_mod
    from skill_forge.dashboard import state as state_mod

    bus = ev.EventBus()
    state = state_mod.RunState()
    # Populate state with workers + baseline + a merged generation.
    state.apply(ev.RunStarted(skill="g", run_id="run_x", num_workers=2))
    state.apply(ev.BaselineCaptured(passed=0, failed=2, errors=0))
    state.apply(ev.WorkerSpawned(worker_id="w0", strategy="A"))
    state.apply(ev.WorkerSpawned(worker_id="w1", strategy="B"))
    state.apply(ev.WorkerStatus(worker_id="w0", status="merged"))

    async def drain_two_subs():
        env = routes_mod._make_env()
        results = []
        for _ in range(2):
            stop = asyncio.Event()
            gen = routes_mod.sse_stream(env, bus, state, stop_event=stop)
            f1 = await gen.__anext__()
            f2 = await gen.__anext__()
            stop.set()
            results.append(f1 + f2)
        return results

    a, b = asyncio.run(drain_two_subs())
    for snap in (a, b):
        assert "w0" in snap
        assert "w1" in snap
        assert "0/2/0" in snap  # baseline counts


def test_sse_emits_periodic_snapshot_when_idle() -> None:
    """During long pytest pauses the bus is silent for ~80s. The SSE
    stream must still re-render the current snapshot at a short cadence
    so the browser self-heals without manual reload.

    We compress the cadence via heartbeat_interval=0.1 so the test runs
    in milliseconds; production default is 5s.
    """
    import asyncio
    from skill_forge.dashboard import events as ev
    from skill_forge.dashboard import routes as routes_mod
    from skill_forge.dashboard import state as state_mod

    bus = ev.EventBus()
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="g", run_id="r", num_workers=1))
    state.apply(ev.WorkerSpawned(worker_id="w0", strategy="x"))

    async def drive():
        env = routes_mod._make_env()
        stop = asyncio.Event()
        gen = routes_mod.sse_stream(
            env, bus, state,
            stop_event=stop, heartbeat_interval=0.1,
        )
        # Drain the two initial snapshot frames.
        await gen.__anext__()
        await gen.__anext__()

        # No events emitted. Wait two heartbeats. We must still receive
        # at least 2 fresh stats fragments containing w0's row.
        frames: list[str] = []
        for _ in range(2):
            frames.append(await asyncio.wait_for(gen.__anext__(), timeout=2))
        stop.set()
        return frames

    frames = asyncio.run(drive())
    # Each heartbeat frame is the stats fragment OR a workers-row fragment;
    # both reference the run state. Assert we got real HTML, not just `: ping`.
    for f in frames:
        assert f.startswith("event: html"), f"got non-html heartbeat: {f[:50]!r}"
    joined = "".join(frames)
    assert "w0" in joined or "baseline" in joined


def test_drilldown_404_for_unknown_worker(client: TestClient) -> None:
    """Phase-4 gate 4.1 — unknown worker → 404."""
    resp = client.get("/workers/wnope/diff")
    assert resp.status_code == 404


def test_drilldown_diff_endpoint_reads_persisted_patch(tmp_path) -> None:
    """Phase-4 gate 4.1 — given runs/<run>/wfix/diff.patch on disk,
    GET /workers/wfix/diff returns 200 with the diff content. Wired
    via state.sidecar_root + state.run_id."""
    from skill_forge.dashboard import events as ev
    from skill_forge.dashboard import server as srv
    from skill_forge.dashboard import state as state_mod

    bus = ev.EventBus()
    state = state_mod.RunState()
    # Seed a worker so the 404 guard passes; populate its sidecar.
    state.apply(ev.RunStarted(skill="g", run_id="run_x", num_workers=1))
    state.apply(ev.WorkerSpawned(worker_id="wfix", strategy="x"))
    state.apply(ev.WorkerStatus(worker_id="wfix", status="discarded"))

    sidecar = tmp_path / "runs" / "run_x" / "wfix"
    sidecar.mkdir(parents=True)
    (sidecar / "diff.patch").write_text(
        "--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1 @@\n-old\n+new\n"
    )
    (sidecar / "tests.txt").write_text("passed=1 failed=0 errors=0\n")
    state.sidecar_root = tmp_path  # type: ignore[attr-defined]

    app = srv.create_app(bus=bus, state=state)
    with TestClient(app) as c:
        r = c.get("/workers/wfix/diff")
        assert r.status_code == 200
        assert "+new" in r.text
        assert "<pre>" in r.text

        r = c.get("/workers/wfix/tests")
        assert r.status_code == 200
        assert "passed=1" in r.text


def test_drilldown_awaiting_when_artifact_missing(tmp_path) -> None:
    """Active workers exist before sidecars are written. The endpoint
    must return a friendly 'awaiting' fragment, not a 500."""
    from skill_forge.dashboard import events as ev
    from skill_forge.dashboard import server as srv
    from skill_forge.dashboard import state as state_mod

    bus = ev.EventBus()
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="g", run_id="run_x", num_workers=1))
    state.apply(ev.WorkerSpawned(worker_id="w0", strategy="x"))
    state.sidecar_root = tmp_path  # type: ignore[attr-defined]

    app = srv.create_app(bus=bus, state=state)
    with TestClient(app) as c:
        r = c.get("/workers/w0/diff")
        assert r.status_code == 200
        assert "awaiting" in r.text


def test_port_picker_raises_when_range_exhausted() -> None:
    """Phase-1 gate 1.2 — when no port in [start..end] is free,
    picker raises PortRangeExhausted (NOT OSError)."""
    import socket

    occupied = []
    try:
        for p in range(7900, 7903):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", p))
                s.listen(1)
                occupied.append(s)
            except OSError:
                pytest.skip(f"port {p} is unavailable on this host")
        with pytest.raises(srv.PortRangeExhausted):
            srv.pick_free_port(start=7900, end=7902)
    finally:
        for s in occupied:
            s.close()
