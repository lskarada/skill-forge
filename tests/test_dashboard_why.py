"""Phase-B gates B.1 + B.2 — slide-over 'Why' tab plumbing."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from skill_forge.dashboard import events as ev  # noqa: E402
from skill_forge.dashboard import server as srv  # noqa: E402
from skill_forge.dashboard import state as state_mod  # noqa: E402


def _client_with_seeded_state(tmp_path: Path) -> tuple[TestClient, state_mod.RunState]:
    bus = ev.EventBus()
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="g", run_id="run_x", num_workers=1))
    state.apply(ev.WorkerSpawned(worker_id="wfix", strategy="x", spawned_at=0.0))
    state.apply(ev.WorkerStatus(worker_id="wfix", status="merged"))
    state.sidecar_root = tmp_path  # type: ignore[attr-defined]
    app = srv.create_app(bus=bus, state=state)
    return TestClient(app), state


def test_why_endpoint_reads_persisted_why(tmp_path: Path) -> None:
    """B.1 — given runs/<run>/wfix/why.txt on disk, GET /workers/wfix/why
    returns 200 with the content wrapped in <pre>."""
    sidecar = tmp_path / "runs" / "run_x" / "wfix"
    sidecar.mkdir(parents=True)
    (sidecar / "why.txt").write_text(
        "Merged: 2/0/0 — beat baseline by +1 pass and won the SUT-length tiebreak."
    )
    client, _ = _client_with_seeded_state(tmp_path)
    with client:
        r = client.get("/workers/wfix/why")
        assert r.status_code == 200
        assert "<pre>" in r.text
        assert "Merged" in r.text
        assert "+1 pass" in r.text or "by 1" in r.text


def test_why_endpoint_awaiting_when_missing(tmp_path: Path) -> None:
    """Pre-pick state has no why.txt yet — return a friendly fragment."""
    client, _ = _client_with_seeded_state(tmp_path)
    with client:
        r = client.get("/workers/wfix/why")
        assert r.status_code == 200
        assert "awaiting" in r.text


def test_why_endpoints_after_scripted_run(tmp_path: Path) -> None:
    """B.2 automation — drive the scripted demo state, write fake
    why.txt files, and confirm GET /workers/<wid>/why for every worker
    returns 200 + non-empty body that mentions the worker's pass count."""
    bus = ev.EventBus()
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="g", run_id="run_demo", num_workers=3))
    state.apply(ev.BaselineCaptured(passed=0, failed=2, errors=0))
    for i, strat in enumerate(("strict", "concise", "schema")):
        state.apply(ev.WorkerSpawned(worker_id=f"w{i}", strategy=strat, spawned_at=0.0))
    state.apply(ev.WorkerTested(worker_id="w0", passed=2, failed=0, errors=0))
    state.apply(ev.WorkerStatus(worker_id="w0", status="merged"))
    state.apply(ev.WorkerStatus(worker_id="w1", status="discarded"))
    state.apply(ev.WorkerStatus(worker_id="w2", status="discarded"))
    state.sidecar_root = tmp_path  # type: ignore[attr-defined]

    runs = tmp_path / "runs" / "run_demo"
    for wid in ("w0", "w1", "w2"):
        wdir = runs / wid
        wdir.mkdir(parents=True)
        (wdir / "why.txt").write_text(f"{wid}: passed=2 failed=0 errors=0\n")

    app = srv.create_app(bus=bus, state=state)
    with TestClient(app) as c:
        for wid in ("w0", "w1", "w2"):
            r = c.get(f"/workers/{wid}/why")
            assert r.status_code == 200, f"{wid}: {r.status_code}"
            assert "passed=2" in r.text


def test_elapsed_advances_under_heartbeat(monkeypatch) -> None:
    """B.2 — drive sse_stream with a real heartbeat and a swap-able
    monotonic clock localized to state.py; assert the workers fragment
    between heartbeats contains different elapsed strings as time
    advances, with no new events emitted."""
    import asyncio
    from skill_forge.dashboard import routes as routes_mod
    from skill_forge.dashboard import state as state_module

    bus = ev.EventBus()
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="g", run_id="r", num_workers=1))
    state.apply(ev.WorkerSpawned(worker_id="w0", strategy="x", spawned_at=1000.0))

    # Patch ONLY state.time.monotonic, leaving asyncio's internal clock alone.
    clock = {"now": 1000.0}

    class _FakeTime:
        @staticmethod
        def monotonic() -> float:
            return clock["now"]
    monkeypatch.setattr(state_module, "time", _FakeTime)

    async def drive():
        env = routes_mod._make_env()
        stop = asyncio.Event()
        gen = routes_mod.sse_stream(
            env, bus, state, stop_event=stop, heartbeat_interval=0.1
        )
        # v0.7.1: initial snapshot is 11 frames: topbar, stats, counts,
        # workers, bracket, then six Mission Control panels (_lineage,
        # _frontier, _sparkline, _evo_tree, _strategy_chips, _why_rail).
        await gen.__anext__()  # topbar
        await gen.__anext__()  # stats
        await gen.__anext__()  # counts
        first = await gen.__anext__()  # workers OOB at clock=1000
        for _ in range(7):  # bracket + 6 mission control panels
            await gen.__anext__()

        clock["now"] = 1075.0
        # Heartbeat path is the same 11 frames in the same order.
        await asyncio.wait_for(gen.__anext__(), timeout=2)  # heartbeat topbar
        await asyncio.wait_for(gen.__anext__(), timeout=2)  # heartbeat stats
        await asyncio.wait_for(gen.__anext__(), timeout=2)  # heartbeat counts
        second = await asyncio.wait_for(gen.__anext__(), timeout=2)  # heartbeat workers
        for _ in range(7):
            await asyncio.wait_for(gen.__anext__(), timeout=2)
        stop.set()
        return first, second

    first, second = asyncio.run(drive())
    assert "0s" in first
    assert "1m15s" in second
