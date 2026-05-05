"""Phase-C gates C.1 + C.2 — bracket diagram (NOT a multi-gen tree).

Within one forge optimize run, all workers spawn from a single parent
generation: that's a 1-deep fan, not a tree. The bracket renders the
parent label at top, N child workers below, with edges colored by
status. Click a node → existing slide-over handler opens (uses
`data-worker-id`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from skill_forge.dashboard import events as ev  # noqa: E402
from skill_forge.dashboard import server as srv  # noqa: E402
from skill_forge.dashboard import state as state_mod  # noqa: E402


def _state_with_workers() -> state_mod.RunState:
    state = state_mod.RunState()
    state.apply(ev.RunStarted(skill="g", run_id="r", num_workers=3))
    state.apply(ev.BaselineCaptured(passed=0, failed=2, errors=0))
    for i, strat in enumerate(("strict", "concise", "schema")):
        state.apply(ev.WorkerSpawned(worker_id=f"w{i}", strategy=strat, spawned_at=0.0))
    return state


def test_parent_label_resolves_from_history(tmp_path: Path) -> None:
    """C.1 — when history/<skill>/v2_evidence.md exists on disk and the
    state has been told the skill, snapshot.parent_label == 'v2'."""
    (tmp_path / "history" / "g").mkdir(parents=True)
    (tmp_path / "history" / "g" / "v2_evidence.md").write_text("# v2\n")
    state = _state_with_workers()
    # Tell the state where to look up history.
    state.parent_label = state_mod.resolve_parent_label(tmp_path, "g")
    snap = state.snapshot()
    assert snap["parent_label"] == "v2"


def test_parent_label_defaults_to_baseline(tmp_path: Path) -> None:
    """No history dir → parent_label == 'baseline'."""
    state = _state_with_workers()
    state.parent_label = state_mod.resolve_parent_label(tmp_path, "g")
    snap = state.snapshot()
    assert snap["parent_label"] == "baseline"


def test_bracket_renders_one_node_per_worker() -> None:
    """C.1 — given a state with 3 workers, GET / returns SVG with
    1 parent + 3 child <circle> elements; each child carries
    data-worker-id. Bezier `<path>` edges connect parent to each child."""
    state = _state_with_workers()
    state.parent_label = "baseline"
    bus = ev.EventBus()
    app = srv.create_app(bus=bus, state=state)
    with TestClient(app) as c:
        body = c.get("/").text
    assert 'id="bracket"' in body
    # One parent + three children = four circles
    assert body.count("<circle") >= 4
    # Edge paths
    assert body.count("<path") >= 3
    for wid in ("w0", "w1", "w2"):
        assert f'data-worker-id="{wid}"' in body


def test_node_class_matches_status() -> None:
    """C.1 — merged worker → bracket-node-merged; discarded → -discarded;
    errored → -errored; in-flight → -active."""
    state = state_mod.RunState()
    state.parent_label = "baseline"
    state.apply(ev.RunStarted(skill="g", run_id="r", num_workers=4))
    state.apply(ev.WorkerSpawned(worker_id="w0", strategy="a", spawned_at=0.0))
    state.apply(ev.WorkerSpawned(worker_id="w1", strategy="b", spawned_at=0.0))
    state.apply(ev.WorkerSpawned(worker_id="w2", strategy="c", spawned_at=0.0))
    state.apply(ev.WorkerSpawned(worker_id="w3", strategy="d", spawned_at=0.0))
    state.apply(ev.WorkerStatus(worker_id="w0", status="merged"))
    state.apply(ev.WorkerStatus(worker_id="w1", status="discarded"))
    state.apply(ev.WorkerStatus(worker_id="w2", status="errored"))
    # w3 stays in-flight (mutating)
    state.apply(ev.WorkerStatus(worker_id="w3", status="mutating"))

    bus = ev.EventBus()
    app = srv.create_app(bus=bus, state=state)
    with TestClient(app) as c:
        body = c.get("/").text
    assert "bracket-node-merged" in body
    assert "bracket-node-discarded" in body
    assert "bracket-node-errored" in body
    assert "bracket-node-active" in body


def test_bracket_renders_after_scripted_run() -> None:
    """C.2 automation — after the scripted lifecycle, GET /; assert
    response HTML contains id='bracket', exactly 4 SVG <circle>
    (1 parent + 3 workers), and the merged winner's <circle> carries
    data-worker-id='w0'."""
    state = _state_with_workers()
    state.parent_label = "baseline"
    state.apply(ev.WorkerTested(worker_id="w0", passed=2, failed=0, errors=0))
    state.apply(ev.WorkerStatus(worker_id="w0", status="merged"))
    state.apply(ev.WorkerStatus(worker_id="w1", status="discarded"))
    state.apply(ev.WorkerStatus(worker_id="w2", status="discarded"))
    bus = ev.EventBus()
    app = srv.create_app(bus=bus, state=state)
    with TestClient(app) as c:
        body = c.get("/").text
    assert 'id="bracket"' in body
    # Count circles inside the bracket SVG only — the bracket card may
    # also contain a sparkline SVG with its own dots, which are not part
    # of the tournament bracket itself.
    import re as _re
    bracket_svg = _re.search(r'class="bracket-svg".*?</svg>', body, _re.DOTALL)
    assert bracket_svg, "bracket SVG not found"
    assert bracket_svg.group(0).count("<circle") == 4
    # The merged-winner circle has data-worker-id="w0"
    import re
    merged_circle = re.search(
        r'<circle[^>]*class="[^"]*bracket-node-merged[^"]*"[^>]*data-worker-id="w0"',
        body,
    ) or re.search(
        r'<circle[^>]*data-worker-id="w0"[^>]*class="[^"]*bracket-node-merged[^"]*"',
        body,
    )
    assert merged_circle, "merged-winner circle missing data-worker-id=w0"


def test_bracket_oob_swap_on_worker_status_change() -> None:
    """C.2 automation — events emitted on WorkerStatus, WorkerMerged,
    and the heartbeat all include a _bracket.html OOB-swap fragment."""
    import asyncio
    from skill_forge.dashboard import routes as routes_mod

    bus = ev.EventBus()
    state = _state_with_workers()
    state.parent_label = "baseline"

    async def drive():
        env = routes_mod._make_env()
        stop = asyncio.Event()
        gen = routes_mod.sse_stream(env, bus, state, stop_event=stop)
        # Drain the two snapshot frames first.
        await gen.__anext__()
        await gen.__anext__()

        # Bind so emit can land on this loop.
        bus.bind_loop(asyncio.get_running_loop())

        bus.emit(ev.WorkerStatus(worker_id="w0", status="testing"))
        await asyncio.sleep(0)
        # Fragments per status change: stats + worker_row + bracket
        frames = []
        for _ in range(3):
            frames.append(await asyncio.wait_for(gen.__anext__(), timeout=1))
        stop.set()
        return frames

    frames = asyncio.run(drive())
    joined = "".join(frames)
    assert 'id="bracket"' in joined
    assert 'hx-swap-oob="true"' in joined
