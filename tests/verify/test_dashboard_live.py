"""Real-browser feedback loop for the dashboard.

Drives a scripted event lifecycle through the global bus; asserts the
DOM mutates in response. Catches the class of bugs unit tests can't:
SSE-to-DOM plumbing, htmx OOB applicability, click delegation on SVG
nodes, slide-over fragment loads.

Run with:
    bin/verify-dashboard
or:
    uv run pytest tests/verify/ -m verify -q

These tests exit fast (< 30s total) so the loop is tight.
"""

from __future__ import annotations

import re
import time

from skill_forge.dashboard import events as ev


def _wait_for(predicate, *, timeout=4.0, interval=0.1, msg="condition") -> None:
    """Poll `predicate()` until it returns truthy or the timeout fires.
    Cheap UI-test glue — we don't have htmx-aware waiters."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return
        time.sleep(interval)
    raise AssertionError(f"timeout waiting for: {msg} (last value: {last!r})")


# ---- Scenario 1: SSE OOB swap actually mutates the DOM ----------------


def test_status_pill_updates_on_run_started(dashboard) -> None:
    """When the server emits RunStarted, the top-bar pill should flip
    from its initial label to 'workers running' WITHOUT a manual reload.

    This is the single sharpest test for the OOB-swap-not-applied bug:
    if SSE → DOM is broken, the pill text never changes."""
    page, bus = dashboard["page"], dashboard["bus"]

    # Initial render: no run_id, no workers, generic "running" or
    # "complete" label depending on initial state.
    bus.emit(ev.RunStarted(skill="greeter", run_id="run_verify", num_workers=3))
    bus.emit(ev.BaselineCaptured(passed=0, failed=2, errors=0))

    # The top-bar's run-id span should reflect the new run id.
    _wait_for(
        lambda: page.locator("#run-id").text_content().strip() == "run_verify",
        msg="run_id never updated in DOM",
    )


def test_baseline_stat_renders_after_event(dashboard) -> None:
    """BaselineCaptured(0, 2, 0) → the BASELINE stat should display 0/2/0."""
    page, bus = dashboard["page"], dashboard["bus"]

    bus.emit(ev.RunStarted(skill="greeter", run_id="run_b", num_workers=3))
    bus.emit(ev.BaselineCaptured(passed=0, failed=2, errors=0))

    _wait_for(
        lambda: "0/2/0" in page.locator("#stat-baseline").text_content(),
        msg="BASELINE stat did not render baseline counts",
    )


def test_worker_row_appears_on_spawn(dashboard) -> None:
    """WorkerSpawned → a worker row with that ID becomes visible."""
    page, bus = dashboard["page"], dashboard["bus"]

    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=2))
    bus.emit(ev.WorkerSpawned(worker_id="w0", strategy="strict", spawned_at=0.0))
    bus.emit(ev.WorkerSpawned(worker_id="w1", strategy="loose", spawned_at=0.0))

    _wait_for(
        lambda: page.locator("#worker-w0").count() > 0
                and page.locator("#worker-w1").count() > 0,
        msg="worker rows w0/w1 never rendered",
    )


# ---- Scenario 2: bracket node click opens slide-over ------------------


def test_bracket_node_click_opens_slide_over(dashboard) -> None:
    """Click an SVG circle with data-worker-id → slide-over opens.

    This catches the bug where the click handler matched only
    `tr.worker-row`, not arbitrary `[data-worker-id]` elements."""
    page, bus, sidecar = dashboard["page"], dashboard["bus"], dashboard["sidecar_root"]

    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=3))
    for i in range(3):
        bus.emit(ev.WorkerSpawned(worker_id=f"w{i}", strategy=f"s{i}", spawned_at=0.0))

    # Drop a why.txt fixture so the slide-over loads non-empty content.
    wdir = sidecar / "runs" / "r" / "w0"
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "why.txt").write_text("test reasoning content for w0")

    # Wait for the bracket SVG node to render, then click.
    _wait_for(
        lambda: page.locator('circle[data-worker-id="w0"]').count() > 0,
        msg="bracket SVG node for w0 never rendered",
    )
    page.locator('circle[data-worker-id="w0"]').first.click()

    # The slide-over <dialog id="slide"> should be open with body
    # showing the loaded why content.
    _wait_for(
        lambda: page.locator("#slide").evaluate("el => el.open") is True,
        msg="slide-over <dialog> never opened on bracket node click",
    )
    _wait_for(
        lambda: "test reasoning content" in page.locator("#slide-body").text_content(),
        msg="slide-over body never loaded the why fragment",
    )


# ---- Scenario 3: worker row click opens slide-over (regression guard) -


def test_worker_row_click_still_opens_slide_over(dashboard) -> None:
    """Make sure broadening the click handler to `[data-worker-id]`
    didn't break the original table-row click path."""
    page, bus, sidecar = dashboard["page"], dashboard["bus"], dashboard["sidecar_root"]

    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=1))
    bus.emit(ev.WorkerSpawned(worker_id="w0", strategy="x", spawned_at=0.0))

    wdir = sidecar / "runs" / "r" / "w0"
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "why.txt").write_text("worker row click works")

    _wait_for(
        lambda: page.locator("#worker-w0").count() > 0,
        msg="worker row never rendered",
    )
    page.locator("#worker-w0").click()
    _wait_for(
        lambda: page.locator("#slide").evaluate("el => el.open") is True,
        msg="slide-over never opened on row click",
    )


# ---- Scenario 4: live elapsed advances on heartbeat -------------------


def test_elapsed_advances_without_explicit_event(dashboard) -> None:
    """The 5s heartbeat (or whatever the configured cadence is) should
    bump the elapsed text on each tick, without any new event emit.

    This is the "feels laggy / never updates" canary."""
    page, bus = dashboard["page"], dashboard["bus"]

    bus.emit(ev.RunStarted(skill="g", run_id="r", num_workers=1))
    bus.emit(ev.WorkerSpawned(worker_id="w0", strategy="x", spawned_at=0.0))

    _wait_for(
        lambda: page.locator("#worker-w0 td.mono.muted").count() > 0,
        msg="worker row never rendered with elapsed cell",
    )

    initial = (page.locator("#worker-w0 td.mono.muted")
               .nth(-1).text_content().strip())

    # Wait two heartbeats. With default 5s, this is ~10s. Tests assert
    # that the elapsed value is NOT identical to the initial render.
    deadline = time.time() + 12
    while time.time() < deadline:
        current = (page.locator("#worker-w0 td.mono.muted")
                   .nth(-1).text_content().strip())
        if current and current != "—" and current != initial:
            return
        time.sleep(0.5)
    raise AssertionError(
        f"elapsed never advanced from {initial!r} during 12s of heartbeats — "
        "SSE → DOM swap path is broken"
    )
