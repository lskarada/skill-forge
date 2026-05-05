"""Live uvx-install tests against a fresh clone.

The first test in the session pays ~30s for cold uvx resolution; the
session-scoped `uv_cache` fixture amortizes that across subsequent
tests. Each test gets its own clone for filesystem isolation.

These tests catch the bug class where the marketplace install path
silently broke (e.g., bug 963: bin/forge wrapper missing [ui] extras).
"""

from __future__ import annotations

import subprocess

from .conftest import FreshClone


def _run_forge(
    fresh: FreshClone, args: list[str], timeout: int
) -> subprocess.CompletedProcess[str]:
    """Invoke bin/forge in a fresh clone with the session uvx cache.
    Returns CompletedProcess; assertions live in the calling test
    so failure messages stay specific."""
    return subprocess.run(
        [str(fresh.forge), *args],
        cwd=str(fresh.clone_dir),
        env=fresh.env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_uvx_cold_install_help_works(fresh_clone: FreshClone) -> None:
    """`bin/forge --help` exits 0 from a fresh clone with cold
    UV_CACHE_DIR. Pins the contract that uvx can resolve the package
    + extras and dispatch the Typer entry point. Catches bug-963-class
    regressions in bin/forge."""
    result = _run_forge(fresh_clone, ["--help"], timeout=120)
    assert result.returncode == 0, (
        f"bin/forge --help exited rc={result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Usage" in result.stdout or "usage" in result.stdout, (
        f"bin/forge --help did not print Typer usage. stdout:\n{result.stdout}"
    )
    assert "forge" in result.stdout.lower(), (
        f"bin/forge --help output did not mention 'forge'. "
        f"stdout:\n{result.stdout}"
    )


def test_forge_status_clean_repo_no_crash(fresh_clone: FreshClone) -> None:
    """`bin/forge status` exits 0 against a clone with no .skill-forge/
    state. New users hit this immediately after cloning; crashing on
    missing sidecar would be a poor first impression."""
    result = _run_forge(fresh_clone, ["status"], timeout=60)
    assert result.returncode == 0, (
        f"bin/forge status exited rc={result.returncode} on a clean clone "
        f"(no .skill-forge/ state).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
