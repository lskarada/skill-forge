"""Skill-Forge live dashboard.

Opt-in only — `forge optimize --ui` runs a local FastAPI server that
streams the tournament. Requires the `[ui]` extras (FastAPI, uvicorn,
jinja2). Core users don't pay the dependency cost.

`events` is import-safe without the extras — it only depends on the
stdlib. The web layer (server.py / routes.py) is gated behind a
try-import so `from skill_forge.dashboard import events` keeps working
in core installs (this matters because optimize.py wants to call
emit_event() unconditionally; a missing import would break core).
"""

from __future__ import annotations

from skill_forge.dashboard import events  # noqa: F401  (intentional re-export)


class DashboardExtrasMissing(RuntimeError):
    """Raised when --ui is used without the [ui] optional dependency installed."""


def require_web_extras() -> None:
    """Import-time gate. Raises a friendly error if [ui] isn't installed."""
    try:
        import fastapi  # noqa: F401
        import jinja2  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:
        missing = exc.name or "fastapi/jinja2/uvicorn"
        raise DashboardExtrasMissing(
            f"--ui requires the [ui] extras. Install with:\n"
            f"    pip install 'skill-forge[ui]'\n"
            f"(missing: {missing})"
        ) from exc
