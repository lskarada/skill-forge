"""Verify-loop fixtures — real-browser dashboard testing.

Boots a real DashboardServer in a daemon thread, opens a Playwright
Chromium page against it, and yields (page, bus, state, sidecar_root)
for the test to drive. Cleans everything up in teardown.

These tests are gated behind `-m verify` (excluded by default in
addopts) so the standard `pytest tests/ -q` run isn't affected.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

import pytest

# Skip the whole suite unless [verify] is installed.
playwright_sync = pytest.importorskip("playwright.sync_api")
fastapi = pytest.importorskip("fastapi")

from skill_forge.dashboard import events as ev  # noqa: E402
from skill_forge.dashboard import server as srv  # noqa: E402
from skill_forge.dashboard import state as state_mod  # noqa: E402


@pytest.fixture
def dashboard(tmp_path: Path) -> Iterator[dict]:
    """Boot a real DashboardServer + Chromium page bound to it.

    Yields a dict with `page`, `bus`, `state`, `sidecar_root`, `url`.
    The page navigates to `/` before the test body runs; tests just
    drive `bus.emit(...)` and assert on `page.locator(...)`.
    """
    ev.reset_global_bus()
    state_mod.reset_state()
    state = state_mod.get_state()
    state.sidecar_root = tmp_path  # type: ignore[attr-defined]
    state.parent_label = "baseline"

    server = srv.DashboardServer(port=srv.pick_free_port(start=8800, end=8899))
    server.start()
    # Wait for the loop bind so emits aren't dropped.
    deadline = time.time() + 2
    while time.time() < deadline and ev.get_global_bus().loop is None:
        time.sleep(0.02)

    # Wait for the TCP listener to actually accept — first run sometimes
    # races page.goto before uvicorn has finished binding.
    import socket as _socket
    deadline = time.time() + 5
    while time.time() < deadline:
        s = _socket.socket()
        s.settimeout(0.2)
        try:
            s.connect(("127.0.0.1", server.port))
            s.close()
            break
        except OSError:
            time.sleep(0.1)
        finally:
            try:
                s.close()
            except Exception:
                pass

    url = f"http://127.0.0.1:{server.port}"

    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        try:
            yield {
                "page": page,
                "bus": ev.get_global_bus(),
                "state": state,
                "sidecar_root": tmp_path,
                "url": url,
            }
        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass
            server.stop()


def pytest_collection_modifyitems(config, items) -> None:
    """Auto-tag every test in tests/verify/ with the `verify` marker so
    the addopts `-m 'not verify and not manual'` filter excludes them
    by default. Runs at collection time so `-m verify` selects them."""
    for item in items:
        if "tests/verify/" in str(item.fspath):
            item.add_marker(pytest.mark.verify)
