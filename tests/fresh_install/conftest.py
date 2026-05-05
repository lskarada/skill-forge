"""Fresh-install E2E tier fixtures.

Each test gets a fresh `git clone --local` of the repo HEAD into
`tmp_path`. The session shares one `UV_CACHE_DIR` so cold uvx
resolution (~30s) is paid once.

Gated behind `-m fresh_install` (registered in pyproject.toml) so
`pytest tests/ -q` ignores this tier. Run via `bin/verify-fresh-install`
or `pytest tests/fresh_install/ -m fresh_install -v`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class FreshClone:
    """One per test. `forge` is the path to bin/forge in the clone."""

    clone_dir: Path
    forge: Path
    env: dict[str, str]


@pytest.fixture(scope="session")
def uv_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped uvx cache. First live test pays cold-resolve cost
    (~30s); subsequent tests reuse the cache. Doesn't touch the user's
    global cache.

    Checks BOTH `uvx` and `uv` because they can be packaged
    independently. Some Linux distro packages of uv (apt, dnf, pacman)
    install only the `uv` binary; `uvx` must then be invoked as
    `uv tool run`. `bin/forge` directly invokes `uvx`, so without
    this check the fixture would pass but every test that calls
    `bin/forge` would fail with rc=127 and a misleading error.
    """
    if shutil.which("uvx") is None:
        pytest.fail(
            "fresh_install tier requires `uvx` on PATH (used by bin/forge). "
            "Install with one of:\n"
            "    brew install uv\n"
            "    curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "If you have `uv` but not `uvx` (some Linux distro packages "
            "split them), install via the curl command or `pip install uv`."
        )
    if shutil.which("uv") is None:
        pytest.fail(
            "fresh_install tier requires `uv` on PATH (used by `uv sync` "
            "in the dev env). Install with `brew install uv` or "
            "`curl -LsSf https://astral.sh/uv/install.sh | sh`."
        )
    if shutil.which("git") is None:
        pytest.fail("fresh_install tier requires `git` on PATH.")
    return tmp_path_factory.mktemp("uv-cache")


@pytest.fixture
def fresh_clone(tmp_path: Path, uv_cache: Path) -> Iterator[FreshClone]:
    """Per-test git clone of the repo HEAD. `git clone --local`
    reflects committed state only — uncommitted changes are not
    visible. To verify uncommitted changes against this tier, commit
    first."""
    clone_dir = tmp_path / "checkout"
    result = subprocess.run(
        ["git", "clone", "--local", "--quiet", str(REPO_ROOT), str(clone_dir)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(
            f"git clone --local failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    forge = clone_dir / "bin" / "forge"
    if not forge.exists():
        pytest.fail(f"bin/forge missing in fresh clone at {forge}")

    env = {**os.environ, "UV_CACHE_DIR": str(uv_cache)}
    yield FreshClone(clone_dir=clone_dir, forge=forge, env=env)


def pytest_collection_modifyitems(config, items) -> None:
    """Auto-tag every test under tests/fresh_install/ with the
    `fresh_install` marker, so the addopts exclusion works without
    requiring `@pytest.mark.fresh_install` on every test.

    Path-separator normalization: pytest's `item.fspath` produces
    backslash-separated paths on Windows. A bare substring check for
    `tests/fresh_install/` would silently miss every test there, the
    marker would never be applied, and the addopts exclusion would
    not exclude the tier from the default suite. Normalize to forward
    slashes before the substring check.
    """
    for item in items:
        normalized = str(item.fspath).replace("\\", "/")
        if "tests/fresh_install/" in normalized:
            item.add_marker(pytest.mark.fresh_install)
