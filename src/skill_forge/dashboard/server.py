"""FastAPI app + uvicorn launcher.

Importing this module REQUIRES the [ui] extras. The CLI guards with
`require_web_extras()` before importing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI

from skill_forge.dashboard import events as ev
from skill_forge.dashboard import routes as routes_mod
from skill_forge.dashboard import state as state_mod

log = logging.getLogger(__name__)


class PortRangeExhausted(RuntimeError):
    """No free port in the requested range."""


DEFAULT_PORT_START = 7777
DEFAULT_PORT_END = 7799


def pick_free_port(start: int = DEFAULT_PORT_START, end: int = DEFAULT_PORT_END) -> int:
    """Return the first free port in [start, end] on 127.0.0.1."""
    for port in range(start, end + 1):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        finally:
            s.close()
        return port
    raise PortRangeExhausted(
        f"no free port in {start}-{end}; pass --port <N>"
    )


def create_app(*, bus: Optional[ev.EventBus] = None,
               state: Optional[state_mod.RunState] = None) -> FastAPI:
    """Build the FastAPI app, wired to the supplied bus + state.

    Defaults to the module-global bus + state — the production CLI
    always uses globals so optimize.py's emit_event() lands here. Tests
    inject their own.
    """
    bus = bus or ev.get_global_bus()
    state = state or state_mod.get_state()

    # Subscribe the state aggregator to the bus exactly once for this app.
    state_mod.attach_to_bus(bus, state)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        bus.bind_loop(asyncio.get_running_loop())
        try:
            yield
        finally:
            bus.unbind_loop()

    app = FastAPI(title="skill-forge-dashboard", openapi_url=None, docs_url=None,
                  lifespan=lifespan)
    routes_mod.register(app, bus=bus, state=state)
    return app


# ---- daemon-thread uvicorn lifecycle (used from CLI) --------------------

class DashboardServer:
    """Run uvicorn in a daemon thread bound to 127.0.0.1.

    The CLI uses this to serve the dashboard for the duration of one
    `forge optimize --ui` run. Daemon thread = process exits when the
    main thread exits, so a Ctrl-C in the CLI immediately ends serving.
    """

    def __init__(self, *, port: int, host: str = "127.0.0.1",
                 app: Optional[FastAPI] = None) -> None:
        self.host = host
        self.port = port
        self.app = app or create_app()
        self._server: Optional[object] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def start(self) -> None:
        import uvicorn  # local import keeps core CLI light
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port,
            log_level="warning", access_log=False, lifespan="on",
        )
        server = uvicorn.Server(config)
        self._server = server

        def _run() -> None:
            try:
                # Server.run() creates its own loop and blocks.
                server.run()
            except Exception:  # noqa: BLE001
                log.exception("dashboard uvicorn server crashed")

        thread = threading.Thread(target=_run, daemon=True, name="forge-ui")
        thread.start()
        self._thread = thread
        # Wait briefly for the server to come up before returning.
        for _ in range(50):
            if getattr(server, "started", False):
                self._ready.set()
                return
            threading.Event().wait(0.05)

    def stop(self, timeout: float = 5.0) -> None:
        server = self._server
        if server is None:
            return
        with contextlib.suppress(Exception):
            server.should_exit = True  # type: ignore[attr-defined]
        if self._thread is not None:
            self._thread.join(timeout=timeout)


def write_port_file(output_root: Path, port: int) -> Path:
    """Write the chosen port to .skill-forge/dashboard.port for tooling."""
    output_root.mkdir(parents=True, exist_ok=True)
    p = output_root / "dashboard.port"
    p.write_text(str(port), encoding="utf-8")
    return p
