"""HTTP routes — the index, SSE stream, and per-worker drilldown
fragments. All routes are read-only.

Phase-1 ships `/` only. Phase 2 adds `/events`. Phase 4 adds the
`/workers/{wid}/{kind}` fragment trio.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from skill_forge.dashboard import events as ev
from skill_forge.dashboard import state as state_mod

log = logging.getLogger(__name__)

THIS_DIR = Path(__file__).parent
TEMPLATES_DIR = THIS_DIR / "templates"
STATIC_DIR = THIS_DIR / "static"


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def register(app: FastAPI, *, bus: ev.EventBus, state: state_mod.RunState) -> None:
    env = _make_env()

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---- index ---------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        snap = state.snapshot()
        html = env.get_template("base.html").render(**snap)
        return HTMLResponse(content=html)

    # ---- SSE stream ----------------------------------------------------

    @app.get("/events")
    async def sse(request: Request) -> StreamingResponse:
        return StreamingResponse(
            sse_stream(env, bus, state, disconnected=request.is_disconnected),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # ---- drilldown fragments (Phase 4) --------------------------------

    @app.get("/workers/{worker_id}/diff", response_class=HTMLResponse)
    def diff(worker_id: str) -> HTMLResponse:
        return _drilldown_fragment(state, worker_id, "diff.patch")

    @app.get("/workers/{worker_id}/transcript", response_class=HTMLResponse)
    def transcript(worker_id: str) -> HTMLResponse:
        return _drilldown_fragment(state, worker_id, "transcript.txt")

    @app.get("/workers/{worker_id}/tests", response_class=HTMLResponse)
    def tests(worker_id: str) -> HTMLResponse:
        return _drilldown_fragment(state, worker_id, "tests.txt")


async def sse_stream(env: Environment, bus: ev.EventBus,
                     state: state_mod.RunState,
                     *,
                     disconnected=None,
                     stop_event: Optional[asyncio.Event] = None,
                     heartbeat_interval: float = 5.0):
    """Async generator backing /events. Exposed so tests can iterate it
    without going through HTTPX/TestClient's streaming layer.

    Self-healing heartbeat: when the bus is silent (e.g. an 80s pytest
    pause inside a worker thread), the stream still emits a fresh full-
    state snapshot every `heartbeat_interval` seconds. The browser's
    OOB swaps are idempotent, so re-sending the same state is cheap and
    the UI re-syncs even after a missed event.
    """
    queue: asyncio.Queue = bus.subscribe()
    snap = state.snapshot()
    yield _format_sse("html", env.get_template("_stats.html").render(**snap))
    yield _format_sse("html", _render_workers_oob(env, snap))
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            if disconnected is not None:
                try:
                    if await disconnected():
                        return
                except Exception:
                    pass
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                # Idle heartbeat — re-render the current snapshot so the
                # browser stays in sync even after a missed event.
                snap = state.snapshot()
                yield _format_sse(
                    "html", env.get_template("_stats.html").render(**snap)
                )
                yield _format_sse("html", _render_workers_oob(env, snap))
                continue
            snap = state.snapshot()
            fragments = _fragments_for_event(env, evt, snap)
            for frag in fragments:
                yield _format_sse("html", frag)
    finally:
        bus.unsubscribe(queue)


# ---- helpers --------------------------------------------------------------

def _format_sse(event: str, data: str) -> str:
    payload = data.replace("\n", "\ndata: ")
    return f"event: {event}\ndata: {payload}\n\n"


def _render_workers_oob(env: Environment, snap: dict) -> str:
    """Render the workers tbody as OOB-swap fragments. Used on reconnect
    so the table re-syncs without flicker."""
    parts = []
    for w in snap["workers"]:
        parts.append(
            env.get_template("_worker_row.html").render(w=w, hx_oob=True)
        )
    return "".join(parts)


def _fragments_for_event(env: Environment, evt: object, snap: dict) -> list[str]:
    """Translate one event into the HTML fragments to OOB-swap.

    Idempotent: each fragment fully describes its target's new state, so
    re-applying a snapshot rebuilds the UI safely.
    """
    out: list[str] = []
    # Stats and counts always update — small, cheap.
    out.append(env.get_template("_stats.html").render(**snap))
    kind = getattr(evt, "kind", None)
    if kind in {"WorkerSpawned", "WorkerStatus", "WorkerTested", "WorkerMerged"}:
        wid = getattr(evt, "worker_id", None)
        if wid is not None:
            view = next((w for w in snap["workers"] if w["id"] == wid), None)
            if view is not None:
                out.append(
                    env.get_template("_worker_row.html").render(w=view, hx_oob=True)
                )
    elif kind == "BaselineCaptured" or kind == "RunStarted" or kind == "RunFinished":
        # Stats already covers it.
        pass
    return out


def _drilldown_fragment(state: state_mod.RunState, worker_id: str,
                        sidecar: str) -> HTMLResponse:
    """Read the persisted sidecar artifact for `worker_id` and wrap in <pre>.
    404 if the worker is unknown. Empty/missing artifact renders an
    'awaiting' message rather than 404 — workers are visible the moment
    they spawn but sidecars arrive at cleanup time."""
    snap = state.snapshot()
    if not any(w["id"] == worker_id for w in snap["workers"]):
        raise HTTPException(status_code=404,
                            detail=f"unknown worker {worker_id!r}")
    path = _sidecar_path(state, worker_id, sidecar)
    if path is None or not path.is_file():
        return HTMLResponse(
            content='<div class="empty">awaiting artifact…</div>'
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return HTMLResponse(content='<div class="empty">empty</div>')
    # Plain text → <pre>. The browser context is trusted (loopback only).
    import html as _html
    return HTMLResponse(content=f"<pre>{_html.escape(text)}</pre>")


def _sidecar_path(state: state_mod.RunState, worker_id: str,
                  filename: str) -> Optional[Path]:
    """Locate the sidecar file for a worker. The state object knows the
    `output_root` and `run_id`; if either is missing (tests, very early
    runs), return None."""
    output_root = getattr(state, "sidecar_root", None)
    run_id = state.run_id or None
    if output_root is None or not run_id:
        return None
    return Path(output_root) / "runs" / run_id / worker_id / filename
