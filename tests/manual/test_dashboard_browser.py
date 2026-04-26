"""Browser-driven verification loop for the live dashboard.

This is the *single* gate that proves the dashboard actually works
end-to-end: SSE delivers events to the browser, the browser applies
them to the live DOM, click handlers fire on both table rows and
bracket SVG nodes, and the elapsed clock advances on the heartbeat.

Run after any change to:
  - src/skill_forge/dashboard/static/*
  - src/skill_forge/dashboard/templates/*
  - src/skill_forge/dashboard/routes.py
  - any code path that emits events

Setup (one-time):
    uv sync --extra ui --extra ui-test
    uv run playwright install chromium

Run:
    uv run pytest tests/manual/test_dashboard_browser.py -m manual -v

Marked `manual` so it stays out of the default suite — Playwright is
heavy and not every CI shape can run a browser.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402

from skill_forge.dashboard import events as ev  # noqa: E402
from skill_forge.dashboard import server as srv  # noqa: E402
from skill_forge.dashboard import state as state_mod  # noqa: E402


@pytest.fixture
def live_dashboard():
    """Boots a real DashboardServer on a free port; yields (port, bus, state).
    Tears the server down on exit so the test is hermetic."""
    ev.reset_global_bus()
    state_mod.reset_state()
    state = state_mod.get_state()
    state.parent_label = "baseline"

    server = srv.DashboardServer(port=srv.pick_free_port(start=8200, end=8299))
    server.start()
    # Tiny grace so uvicorn finishes binding before the browser navigates.
    time.sleep(0.3)
    try:
        yield server.port, ev.get_global_bus(), state
    finally:
        server.stop()


@pytest.fixture
def page():
    """Headless Chromium page. Per-test fresh browser context."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


@pytest.mark.manual
def test_sse_mutates_live_dom(live_dashboard, page: Page) -> None:
    """The big regression: an event emitted on the bus must mutate the
    DOM in the live browser without a manual reload. This is the test
    that catches "OOB swap not actually applied" bugs."""
    port, bus, _state = live_dashboard
    page.goto(f"http://127.0.0.1:{port}/")

    # Initial state — no workers in the table.
    expect(page.locator("#workers-empty")).to_be_visible()

    # Drive a worker through the bus.
    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=3))
    bus.emit(ev.BaselineCaptured(passed=0, failed=2, errors=0))
    for i, strat in enumerate(("strict", "concise", "schema")):
        bus.emit(ev.WorkerSpawned(worker_id=f"w{i}", strategy=strat, spawned_at=0.0))

    # The browser MUST pick up these events without a reload. Use
    # auto-retrying assertions so we don't race the 5s heartbeat.
    expect(page.locator("#worker-w0")).to_be_visible(timeout=10_000)
    expect(page.locator("#worker-w1")).to_be_visible(timeout=5_000)
    expect(page.locator("#worker-w2")).to_be_visible(timeout=5_000)
    # Stats reflect the new baseline.
    expect(page.locator("#stat-baseline")).to_contain_text("0/2/0", timeout=5_000)


@pytest.mark.manual
def test_status_transition_updates_row_class(live_dashboard, page: Page) -> None:
    """A WorkerStatus(merged) must give the corresponding row the
    `kept-row` class. Catches "OOB swap targets the wrong attribute"
    or "fragments don't carry the merged flag" regressions."""
    port, bus, _state = live_dashboard
    page.goto(f"http://127.0.0.1:{port}/")
    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=2))
    bus.emit(ev.WorkerSpawned(worker_id="w0", strategy="x", spawned_at=0.0))
    bus.emit(ev.WorkerSpawned(worker_id="w1", strategy="y", spawned_at=0.0))
    expect(page.locator("#worker-w0")).to_be_visible(timeout=10_000)

    bus.emit(ev.WorkerStatus(worker_id="w0", status="merged"))
    bus.emit(ev.WorkerStatus(worker_id="w1", status="discarded"))
    # kept-row applied to merged worker
    expect(page.locator("#worker-w0.kept-row")).to_be_visible(timeout=5_000)
    # discarded worker keeps a plain row
    expect(page.locator("#worker-w1")).to_be_visible(timeout=5_000)
    expect(page.locator("#worker-w1.kept-row")).to_have_count(0)


@pytest.mark.manual
def test_clicking_worker_row_opens_slide_over(live_dashboard, page: Page) -> None:
    """Click a `<tr>` worker row → dialog#slide opens with the worker
    id in its title."""
    port, bus, _state = live_dashboard
    page.goto(f"http://127.0.0.1:{port}/")
    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=1))
    bus.emit(ev.WorkerSpawned(worker_id="w0", strategy="x", spawned_at=0.0))
    expect(page.locator("#worker-w0")).to_be_visible(timeout=10_000)

    page.locator("#worker-w0").click()
    expect(page.locator("dialog#slide[open]")).to_be_visible(timeout=2_000)
    expect(page.locator("#slide-title")).to_contain_text("w0", timeout=2_000)


@pytest.mark.manual
def test_clicking_bracket_node_opens_slide_over(live_dashboard, page: Page) -> None:
    """Click an SVG `<circle data-worker-id>` in the bracket → dialog
    opens. This is the bug the user reported on screen — the existing
    click handler only matched `tr.worker-row`, not SVG nodes."""
    port, bus, _state = live_dashboard
    page.goto(f"http://127.0.0.1:{port}/")
    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=2))
    bus.emit(ev.WorkerSpawned(worker_id="w0", strategy="x", spawned_at=0.0))
    bus.emit(ev.WorkerSpawned(worker_id="w1", strategy="y", spawned_at=0.0))
    # Wait until the bracket has both child node groups. data-worker-id
    # lives on the <g> wrapper so a click on either the circle or its
    # text label resolves to the same worker.
    expect(page.locator('g[data-worker-id="w0"]')).to_be_visible(timeout=10_000)
    expect(page.locator('g[data-worker-id="w1"]')).to_be_visible(timeout=5_000)

    page.locator('g[data-worker-id="w1"]').click()
    expect(page.locator("dialog#slide[open]")).to_be_visible(timeout=2_000)
    expect(page.locator("#slide-title")).to_contain_text("w1", timeout=2_000)


@pytest.mark.manual
def test_elapsed_clock_advances(live_dashboard, page: Page) -> None:
    """The elapsed cell on a worker row must change between two
    snapshots. The page should self-update without a reload."""
    port, bus, _state = live_dashboard
    page.goto(f"http://127.0.0.1:{port}/")
    # Spawn at a small offset from "now" so we see it tick visibly.
    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=1))
    import time as _t
    bus.emit(ev.WorkerSpawned(worker_id="w0", strategy="x", spawned_at=_t.monotonic() - 1))
    expect(page.locator("#worker-w0")).to_be_visible(timeout=10_000)

    initial = page.locator("#worker-w0 td:last-child").inner_text()
    # Wait for the 5s heartbeat to fire at least once. Allow a safety margin.
    page.wait_for_timeout(7_000)
    after = page.locator("#worker-w0 td:last-child").inner_text()
    assert after != initial, (
        f"elapsed didn't advance — initial={initial!r} after={after!r}. "
        "Heartbeat or DOM-update path is broken."
    )
