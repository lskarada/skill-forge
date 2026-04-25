"""Phase-4 manual gate — boot a real DashboardServer + drive a fake-run
through the global bus + assert the live SSE feed and drilldown HTTP
endpoints reflect the run. Marked `manual` so it doesn't run in default
CI but is one `pytest -m manual` away.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
import urllib.request

pytest.importorskip("fastapi")

from skill_forge.dashboard import events as ev
from skill_forge.dashboard import server as srv
from skill_forge.dashboard import state as state_mod


@pytest.mark.manual
def test_real_server_streams_a_scripted_run(tmp_path: Path) -> None:
    """Boots uvicorn in a daemon thread, drives the global bus through
    a scripted lifecycle, hits / and /workers/<wid>/diff, and stops the
    server cleanly."""
    ev.reset_global_bus()
    state_mod.reset_state()
    state = state_mod.get_state()
    state.sidecar_root = tmp_path  # type: ignore[attr-defined]

    port = srv.pick_free_port(start=7900, end=7999)
    server = srv.DashboardServer(port=port)
    server.start()
    try:
        # Drive the bus.
        bus = ev.get_global_bus()
        bus.emit(ev.RunStarted(skill="greeter", run_id="run_smoke", num_workers=2))
        bus.emit(ev.BaselineCaptured(passed=0, failed=2, errors=0))
        bus.emit(ev.WorkerSpawned(worker_id="w0", strategy="A"))
        bus.emit(ev.WorkerSpawned(worker_id="w1", strategy="B"))
        bus.emit(ev.WorkerStatus(worker_id="w0", status="mutating"))
        bus.emit(ev.WorkerStatus(worker_id="w0", status="testing"))
        bus.emit(ev.WorkerTested(worker_id="w0", passed=2, failed=0, errors=0))
        bus.emit(ev.WorkerStatus(worker_id="w0", status="merged"))
        bus.emit(ev.WorkerMerged(worker_id="w0", new_generation=1))
        bus.emit(ev.WorkerStatus(worker_id="w1", status="discarded"))
        bus.emit(ev.RunFinished(outcome="merged"))

        # Sidecar for w0 so the drilldown returns content.
        wdir = tmp_path / "runs" / "run_smoke" / "w0"
        wdir.mkdir(parents=True)
        (wdir / "diff.patch").write_text("--- a\n+++ b\n+ok\n")
        (wdir / "tests.txt").write_text("passed=2 failed=0 errors=0\n")

        # Allow the loop to drain queued events.
        time.sleep(0.3)

        body = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=5
        ).read().decode()
        assert "w0" in body
        assert "kept-row" in body
        assert "0/2/0" in body  # baseline counts visible

        diff = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/workers/w0/diff", timeout=5
        ).read().decode()
        assert "+ok" in diff
    finally:
        server.stop()
