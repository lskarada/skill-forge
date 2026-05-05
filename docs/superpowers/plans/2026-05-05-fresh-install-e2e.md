# Fresh-Install E2E Test Tier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an automated `tests/fresh_install/` tier + `bin/verify-fresh-install` entrypoint that catches marketplace-install-path regressions in under ~3.5 min, automating CLAUDE.md Gate 2 and pinning 8 other SkillForge contracts.

**Architecture:** New pytest tier gated by marker `fresh_install` (excluded from default `pytest tests/ -q`). Tests run against a per-test `git clone --local` of the repo HEAD into `tmp_path`, with a session-scoped `UV_CACHE_DIR` so cold uvx resolution is paid once. Live tests drive the real `bin/forge` via subprocess. Static tests parse manifests / grep `src/`.

**Tech Stack:** Python 3.12 stdlib (`subprocess`, `tomllib`, `pathlib`, `json`, `re`), pytest, real `git` and `uv` CLIs (no mocks).

**Spec:** `docs/design/2026-05-05-fresh-install-e2e.md`

---

## File Structure

| Path | Purpose |
|---|---|
| `tests/fresh_install/__init__.py` | Empty marker file. |
| `tests/fresh_install/conftest.py` | `uv_cache` (session) + `fresh_clone` (function) fixtures; auto-tags items with `fresh_install` marker (mirrors `tests/verify/conftest.py` pattern). |
| `tests/fresh_install/test_manifest_contracts.py` | Tests #1, #2 — manifest version agreement + pytest in runtime deps. |
| `tests/fresh_install/test_static_contracts.py` | Tests #7, #8, #9 — `MUTATION_TARGET.md` staging, terse-dispatch string, no-anthropic-import. |
| `tests/fresh_install/test_uvx_install.py` | Tests #3, #4 — `bin/forge --help` and `forge status` from cold uvx. |
| `tests/fresh_install/test_demo_fixture.py` | Tests #5, #6 — 5x red baseline + `.skill-forge/tests/greeter/` emits. |
| `bin/verify-fresh-install` | Shell entrypoint, mirrors `bin/verify-dashboard`. |
| `pyproject.toml` (modify) | Register `fresh_install` marker; extend `addopts` to exclude. |
| `CLAUDE.md` (modify) | Add command in "Commands you will actually run"; note Gate 2 automation in "Shipping a new version". |
| `README.md` (modify) | One line in testing section. |

---

## Task 1: Register the `fresh_install` pytest marker

**Files:**
- Modify: `pyproject.toml` (the `[tool.pytest.ini_options]` block)

The marker must be registered AND included in `addopts` exclusion before any test file lands, so the unit suite (`pytest tests/ -q`) keeps ignoring the new tier.

- [ ] **Step 1: Open the current pytest section**

Run: `grep -n "tool.pytest\|markers\|addopts" pyproject.toml`
Expected: shows current `addopts = "-m 'not manual and not verify'"` and `markers = [ ... ]` with two entries.

- [ ] **Step 2: Update `addopts` and add the marker**

Edit `pyproject.toml`. Change:
```toml
addopts = "-m 'not manual and not verify'"
markers = [
    "manual: tests requiring real subprocesses or browsers, excluded from default CI",
    "verify: real-browser dashboard verification loop (Playwright, headless Chromium)",
]
```
to:
```toml
addopts = "-m 'not manual and not verify and not fresh_install'"
markers = [
    "manual: tests requiring real subprocesses or browsers, excluded from default CI",
    "verify: real-browser dashboard verification loop (Playwright, headless Chromium)",
    "fresh_install: cold uvx-install simulation against a fresh git clone, excluded from default CI",
]
```

- [ ] **Step 3: Confirm the existing unit suite still passes**

Run: `uv run pytest tests/ -q`
Expected: same green count as before this change (no new tests collected; the marker rule excludes anything we add later).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "skill-forge: register fresh_install pytest marker"
```

---

## Task 2: Skeleton — `__init__.py` and `conftest.py`

**Files:**
- Create: `tests/fresh_install/__init__.py`
- Create: `tests/fresh_install/conftest.py`

The conftest holds two fixtures and the auto-marker. No tests yet — Task 2 ends with the dir collected by pytest but empty.

- [ ] **Step 1: Create the empty `__init__.py`**

Write `tests/fresh_install/__init__.py` as an empty file.

- [ ] **Step 2: Create `tests/fresh_install/conftest.py`**

```python
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
    global cache."""
    if shutil.which("uv") is None:
        pytest.fail(
            "fresh_install tier requires `uv` on PATH. Install with "
            "`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`."
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
    requiring `@pytest.mark.fresh_install` on every test."""
    for item in items:
        if "tests/fresh_install/" in str(item.fspath):
            item.add_marker(pytest.mark.fresh_install)
```

- [ ] **Step 3: Verify pytest collects the dir without errors**

Run: `uv run pytest tests/fresh_install/ -m fresh_install --collect-only -q`
Expected: exit 0, "no tests ran" (or "no tests collected"). No import errors. The conftest module loads cleanly.

- [ ] **Step 4: Confirm default suite is unaffected**

Run: `uv run pytest tests/ -q`
Expected: same green count as before; no fresh_install tests collected.

- [ ] **Step 5: Commit**

```bash
git add tests/fresh_install/__init__.py tests/fresh_install/conftest.py
git commit -m "skill-forge: scaffold fresh_install tier conftest + fixtures"
```

---

## Task 3: Static manifest tests (#1, #2)

**Files:**
- Create: `tests/fresh_install/test_manifest_contracts.py`

Static parses of `pyproject.toml`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`. No subprocess, no clone — these tests run against `REPO_ROOT` (the live working tree) directly because manifest contracts are about source files, not about install behavior. Sub-second.

- [ ] **Step 1: Write `test_manifest_contracts.py`**

```python
"""Static manifest contract tests.

These tests parse repo source files directly (no clone). They guard
the version-agreement and pytest-in-deps rules from CLAUDE.md.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_versions_agree() -> None:
    """All three manifests (pyproject.toml, plugin.json, marketplace.json)
    agree on the version string. CLAUDE.md "three places the version
    string lives; bump together"; SOUL.md "version bumped in all three
    manifests."

    Note: marketplace.json has TWO version fields — `metadata.version`
    AND `plugins[0].version`. Both must match.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    plugin = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    marketplace = json.loads(
        (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text()
    )

    py_version = pyproject["project"]["version"]
    plugin_version = plugin["version"]
    marketplace_metadata = marketplace["metadata"]["version"]
    plugins_list = marketplace["plugins"]
    skill_forge_entry = next(
        (p for p in plugins_list if p["name"] == "skill-forge"), None
    )
    assert skill_forge_entry is not None, (
        "marketplace.json plugins[] missing skill-forge entry"
    )
    marketplace_plugin = skill_forge_entry["version"]

    versions = {
        "pyproject.toml [project].version": py_version,
        ".claude-plugin/plugin.json .version": plugin_version,
        ".claude-plugin/marketplace.json .metadata.version": marketplace_metadata,
        ".claude-plugin/marketplace.json .plugins[skill-forge].version": (
            marketplace_plugin
        ),
    }
    unique = set(versions.values())
    assert len(unique) == 1, (
        "Manifest version drift detected — bump all four together:\n"
        + "\n".join(f"  {k}: {v}" for k, v in versions.items())
    )


def test_pytest_in_runtime_deps_not_dev() -> None:
    """Pytest must be in `[project].dependencies`, NOT in a dev-only
    group. Phase 1 (baseline) runs pytest inside a uvx-installed
    marketplace copy; if pytest is dev-only, that install won't have
    it and baseline blows up. CLAUDE.md non-obvious rule."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    runtime_deps = pyproject["project"]["dependencies"]
    runtime_pkgs = {dep.split(">=")[0].split("==")[0].split("<")[0].strip()
                    for dep in runtime_deps}
    assert "pytest" in runtime_pkgs, (
        "pytest is missing from [project].dependencies. CLAUDE.md: "
        "'pytest belongs in [project].dependencies, not a dev group.' "
        "Phase 1 baseline runs pytest inside the uvx env; this regression "
        "would silently break the loop."
    )

    # Belt-and-suspenders: if a dependency-groups.dev exists, it must
    # not contain pytest as a separate entry (which could shadow runtime).
    dep_groups = pyproject.get("dependency-groups", {})
    dev_group = dep_groups.get("dev", [])
    dev_pkgs = {dep.split(">=")[0].split("==")[0].split("<")[0].strip()
                for dep in dev_group}
    assert "pytest" not in dev_pkgs, (
        "pytest appears in [dependency-groups].dev — remove it; "
        "the runtime entry is canonical."
    )
```

- [ ] **Step 2: Run the new tests; expect green**

Run: `uv run pytest tests/fresh_install/test_manifest_contracts.py -m fresh_install -v`
Expected: 2 passed. (Manifest versions are all `0.3.1` and pytest is in runtime deps as of HEAD — these contracts already hold.)

- [ ] **Step 3: Sanity-check the test bites — temporarily corrupt and confirm RED**

Edit `.claude-plugin/plugin.json` and change `"version": "0.3.1"` to `"version": "9.9.9"`.
Run: `uv run pytest tests/fresh_install/test_manifest_contracts.py::test_manifest_versions_agree -m fresh_install -v`
Expected: FAIL with the four-line drift message naming all four versions.
**Revert the change** before continuing: `git checkout .claude-plugin/plugin.json`.

- [ ] **Step 4: Final green check**

Run: `uv run pytest tests/fresh_install/test_manifest_contracts.py -m fresh_install -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/fresh_install/test_manifest_contracts.py
git commit -m "skill-forge: pin manifest version + pytest-in-runtime contracts"
```

---

## Task 4: Static grep tests (#7, #8, #9)

**Files:**
- Create: `tests/fresh_install/test_static_contracts.py`

Three tests guarding load-bearing string constants in `src/`. These are the cheapest tests in the suite and the most direct guards against "simplification" regressions.

- [ ] **Step 1: Write `test_static_contracts.py`**

```python
"""Static contract tests — grep src/ for load-bearing strings.

These tests pin contracts from CLAUDE.md and SOUL.md non-negotiables.
If they fail, the test was right and the contract changed. The fix:
update the test string AND the citation comment, OR update the source
to restore the contract. The test never gets deleted to make a build
green.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mutation_target_staging_contract_intact() -> None:
    """`MUTATION_TARGET.md` is the staging path the harness uses to
    work around Claude Code's block on subagent writes under .claude/.
    CLAUDE.md: 'Skill-Forge works around this by staging the SUT at
    MUTATION_TARGET.md at the worktree root ... Don't simplify this
    into a direct edit.'

    Verified at spec time: the literal lives in src/skill_forge/optimize.py.
    If the staging mechanism moves, update this test to grep the new
    location, not delete it.
    """
    optimize_py = (REPO_ROOT / "src" / "skill_forge" / "optimize.py").read_text()
    assert "MUTATION_TARGET.md" in optimize_py, (
        "MUTATION_TARGET.md staging path missing from optimize.py. "
        "CLAUDE.md forbids simplifying this into a direct edit — the "
        "harness needs an out-of-tree staging path because Claude Code "
        "blocks subagent writes anywhere under .claude/."
    )


def test_terse_dispatch_constraint_intact() -> None:
    """The dispatch wrapper constrains the final assistant turn to
    'Produce only the final assistant response... No commentary.'
    CLAUDE.md: 'load-bearing for test determinism — do not soften it.'

    Verified at spec time: lives in src/skill_forge/dispatch.py.
    """
    dispatch_py = (REPO_ROOT / "src" / "skill_forge" / "dispatch.py").read_text()
    needle = "Produce only the final assistant response"
    assert needle in dispatch_py, (
        f"Terse-dispatch constraint string missing from dispatch.py. "
        f"Looked for: {needle!r}. CLAUDE.md: 'load-bearing for test "
        f"determinism — do not soften it.'"
    )


def test_no_anthropic_sdk_imports_in_src() -> None:
    """SOUL.md non-negotiable #4: 'Mutations go through Claude Code
    subagents. The user pays what they were going to pay anyway.' No
    direct Anthropic SDK calls anywhere in src/.
    """
    src_root = REPO_ROOT / "src"
    bad_pattern = re.compile(r"^\s*(from\s+anthropic\b|import\s+anthropic\b)", re.M)

    offenders: list[tuple[Path, int, str]] = []
    for py_file in src_root.rglob("*.py"):
        text = py_file.read_text()
        for m in bad_pattern.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append((py_file, line_no, m.group(0).strip()))

    assert not offenders, (
        "anthropic SDK import found in src/. SOUL.md non-negotiable #4: "
        "'Mutations go through Claude Code subagents.' Offenders:\n"
        + "\n".join(f"  {p.relative_to(REPO_ROOT)}:{n}: {line}"
                    for p, n, line in offenders)
    )
```

- [ ] **Step 2: Run the new tests; expect green**

Run: `uv run pytest tests/fresh_install/test_static_contracts.py -m fresh_install -v`
Expected: 3 passed.

- [ ] **Step 3: Sanity-check #1 — corrupt MUTATION_TARGET reference, expect RED**

Run: `sed -i.bak 's/MUTATION_TARGET.md/MUTATION_TGT.md/' src/skill_forge/optimize.py`
Run: `uv run pytest tests/fresh_install/test_static_contracts.py::test_mutation_target_staging_contract_intact -m fresh_install -v`
Expected: FAIL.
Restore: `mv src/skill_forge/optimize.py.bak src/skill_forge/optimize.py`

- [ ] **Step 4: Final green check**

Run: `uv run pytest tests/fresh_install/test_static_contracts.py -m fresh_install -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/fresh_install/test_static_contracts.py
git commit -m "skill-forge: pin load-bearing string contracts (MUTATION_TARGET, terse dispatch, no-anthropic)"
```

---

## Task 5: Live uvx tests (#3, #4)

**Files:**
- Create: `tests/fresh_install/test_uvx_install.py`

These are the first tests that actually use the `fresh_clone` fixture and pay the cold-uvx cost.

- [ ] **Step 1: Write `test_uvx_install.py`**

```python
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


def _run_forge(fresh: FreshClone, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
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
    result = _run_forge(fresh_clone, ["--help"], timeout=60)
    assert result.returncode == 0, (
        f"bin/forge --help exited rc={result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Usage" in result.stdout or "usage" in result.stdout, (
        f"bin/forge --help did not print Typer usage. stdout:\n{result.stdout}"
    )
    assert "forge" in result.stdout.lower(), (
        f"bin/forge --help output did not mention 'forge'. stdout:\n{result.stdout}"
    )


def test_forge_status_clean_repo_no_crash(fresh_clone: FreshClone) -> None:
    """`bin/forge status` exits 0 against a clone with no .skill-forge/
    state. New users hit this immediately after cloning; crashing on
    missing sidecar would be a poor first impression."""
    result = _run_forge(fresh_clone, ["status"], timeout=30)
    assert result.returncode == 0, (
        f"bin/forge status exited rc={result.returncode} on a clean clone "
        f"(no .skill-forge/ state).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
```

- [ ] **Step 2: Run the new tests; expect green (cold cache, ~30-40s)**

Run: `uv run pytest tests/fresh_install/test_uvx_install.py -m fresh_install -v`
Expected: 2 passed. First run takes ~30-40s as uvx resolves the package into the new cache. **Note:** if `bin/forge --help` fails here, it is a real bug in `bin/forge` or the manifest — fix the wrapper or the dependency declaration, not the test.

- [ ] **Step 3: Re-run; expect fast (warm cache, ~5s total)**

Run: `uv run pytest tests/fresh_install/test_uvx_install.py -m fresh_install -v`
Expected: 2 passed in <10s.

- [ ] **Step 4: Commit**

```bash
git add tests/fresh_install/test_uvx_install.py
git commit -m "skill-forge: live uvx-install tests (bin/forge --help, forge status)"
```

---

## Task 6: Demo fixture tests (#5, #6) — the 5x red baseline

**Files:**
- Create: `tests/fresh_install/test_demo_fixture.py`

This is the tier's most expensive task — ~2.5 minutes wall-clock. It automates `CLAUDE.md` Gate 2 verbatim ("5 consecutive red baselines on a fresh `git clone`") and verifies that capture emits the regression-test directory.

- [ ] **Step 1: Write `test_demo_fixture.py`**

```python
"""Greeter demo fixture tests — the load-bearing first-run proof.

SOUL.md: 'The shipped greeter fixture is the first-run proof a user
sees. It is not a toy. ... Fixture breakage is demo breakage is
launch breakage.'

Test 5 is the inverse of sampling-based verification SOUL.md forbids:
the assertion is `all 5 red`. A single green run fails the test —
that is the deterministic kill criterion CLAUDE.md Gate 2 names.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from .conftest import FreshClone

# Regex that pulls failed/passed counts from a pytest summary line like:
#   "===== 2 failed, 0 passed in 0.05s ====="
#   "===== 2 failed in 0.05s ====="
#   "===== 2 passed in 0.05s ====="
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_PASSED_RE = re.compile(r"(\d+)\s+passed")


@dataclass(frozen=True)
class BaselineResult:
    failed: int
    passed: int
    raw_stdout: str


def _run_optimize_baseline(fresh: FreshClone, timeout: int = 60) -> BaselineResult:
    """Run `bin/forge optimize greeter --workers 1` with stdin='n\\n' so
    the user prompt to start mutations is declined. The Phase 1
    baseline still runs — that's all this test cares about.

    Parses pytest's summary line out of stdout. Hard-kills on timeout
    and surfaces captured output."""
    proc = subprocess.run(
        [str(fresh.forge), "optimize", "greeter", "--workers", "1"],
        cwd=str(fresh.clone_dir),
        env=fresh.env,
        input="n\n",
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    failed_match = _FAILED_RE.search(combined)
    passed_match = _PASSED_RE.search(combined)
    return BaselineResult(
        failed=int(failed_match.group(1)) if failed_match else 0,
        passed=int(passed_match.group(1)) if passed_match else 0,
        raw_stdout=combined,
    )


def test_greeter_baseline_red_by_construction_5x(fresh_clone: FreshClone) -> None:
    """SOUL.md non-negotiable #1: 'Red baselines must be red by
    construction.' This test runs the Phase 1 baseline 5 consecutive
    times and asserts ALL are red (failed > 0). Any single green run
    fails this test — that is the deterministic kill criterion CLAUDE.md
    Gate 2 names ('5 consecutive red baselines on a fresh git clone').
    """
    results: list[BaselineResult] = []
    for i in range(5):
        results.append(_run_optimize_baseline(fresh_clone, timeout=60))

    all_red = all(r.failed > 0 for r in results)
    if not all_red:
        # Identify the green run (the regression). Print all 5 counts +
        # the green run's stdout so the operator can diagnose
        # "SKILL accidentally satisfied" vs "pytest never ran".
        lines = ["Greeter baseline failed SOUL.md non-negotiable #1 (red by construction):"]
        green_idx = -1
        for idx, r in enumerate(results):
            tag = "" if r.failed > 0 else "  ← GREEN, broke determinism"
            lines.append(f"  run {idx + 1}/5: failed={r.failed} passed={r.passed}{tag}")
            if r.failed == 0 and green_idx < 0:
                green_idx = idx
        lines.append("")
        lines.append("Green-run stdout (truncated to 400 chars):")
        lines.append("  " + results[green_idx].raw_stdout[:400].replace("\n", "\n  "))
        lines.append("")
        lines.append(
            "Diagnose: did the SKILL accidentally satisfy the assertion "
            "(real bug) or did pytest never run (env issue)?"
        )
        raise AssertionError("\n".join(lines))


def test_capture_emits_test_dir_under_skill_forge(fresh_clone: FreshClone) -> None:
    """After running optimize-baseline against the greeter, the
    captured regression tests live at .skill-forge/tests/greeter/.
    Independent run — does NOT rely on test 5's iteration order."""
    _run_optimize_baseline(fresh_clone, timeout=60)

    test_dir = fresh_clone.clone_dir / ".skill-forge" / "tests" / "greeter"
    assert test_dir.is_dir(), (
        f"Expected .skill-forge/tests/greeter/ after optimize-baseline; "
        f"got nothing at {test_dir}. CLAUDE.md: 'regression tests for "
        f"tracked skills ... separate tree.'"
    )
    test_files = list(test_dir.glob("test_*.py"))
    assert test_files, (
        f"No test_*.py files under {test_dir}. The greeter capture "
        f"flow should produce at least one regression test."
    )
```

- [ ] **Step 2: Run the new tests; expect green (~2.5 min wall-clock, warm cache)**

Run: `uv run pytest tests/fresh_install/test_demo_fixture.py -m fresh_install -v`
Expected: 2 passed in ~2-3 min. **If this fails, do NOT mute the test.** Diagnose:
- All 5 runs red but `failed=0 passed=0`? → Phase 1 didn't run pytest (env/install issue). Look at the captured stdout.
- 4 red 1 green? → Demo fixture's red-baseline contract is broken (SOUL.md non-negotiable #1). Fix the SKILL.md or the test — see CLAUDE.md "Demo fixture is load-bearing" rules.
- `test_capture_emits_test_dir_under_skill_forge` fails? → Capture phase isn't writing to the expected path.

- [ ] **Step 3: Commit**

```bash
git add tests/fresh_install/test_demo_fixture.py
git commit -m "skill-forge: automate Gate 2 (5x red baseline) + capture-emits-test-dir"
```

---

## Task 7: Shell entrypoint `bin/verify-fresh-install`

**Files:**
- Create: `bin/verify-fresh-install`

Mirrors `bin/verify-dashboard`. The only thing it does that `pytest tests/fresh_install/ -m fresh_install` doesn't: pre-flight `uv sync` so the tier's pytest invocation has its deps.

- [ ] **Step 1: Write `bin/verify-fresh-install`**

```bash
#!/usr/bin/env bash
# Local-dev verify loop for the fresh-install (marketplace) flow.
#
# Boots a per-test `git clone --local` of the repo HEAD into tmp_path
# and drives bin/forge through cold uvx, asserting overfitted-to-
# SkillForge contracts (CLAUDE.md non-obvious rules + SOUL.md
# non-negotiables). Run after any change to:
#   - pyproject.toml / .claude-plugin/*
#   - bin/forge
#   - src/skill_forge/optimize.py / dispatch.py / capture.py
#   - .claude/skills/greeter/ / .skill-forge/tests/greeter/
#
# First run pays ~30s for cold uvx resolution into a session-scoped
# UV_CACHE_DIR (the test's tmp); subsequent runs reuse it for ~30s
# total wall-clock.
#
# Usage:
#   bin/verify-fresh-install              # full suite
#   bin/verify-fresh-install <test-name>  # single test, e.g. manifest_versions
#
# This automates CLAUDE.md Gate 2 (5 consecutive red baselines).
# Gate 3 (full Phase 1→5 mutation loop) stays manual before tagging.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$REPO_ROOT"

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<EOF
verify-fresh-install: requires \`uv\` on PATH.
Install with one of:
    brew install uv
    curl -LsSf https://astral.sh/uv/install.sh | sh
EOF
  exit 127
fi

if ! command -v git >/dev/null 2>&1; then
  echo "verify-fresh-install: requires \`git\` on PATH." >&2
  exit 127
fi

# Make sure the dev env has pytest. No --extra needed; this tier uses
# stdlib + pytest + real subprocesses.
uv sync > /dev/null

# Run the suite. -m fresh_install overrides the default exclusion. -x
# stops on first failure to keep the loop tight.
if [ -n "$1" ]; then
  exec uv run pytest tests/fresh_install/ -m fresh_install -k "$1" -x -v
else
  exec uv run pytest tests/fresh_install/ -m fresh_install -x -v
fi
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x bin/verify-fresh-install`

- [ ] **Step 3: Run it end-to-end**

Run: `bin/verify-fresh-install`
Expected: 9 passed (2 manifest + 3 static + 2 uvx + 2 demo) in ~3 min cold or ~3 min warm. The script should exit 0.

- [ ] **Step 4: Run a single test by name**

Run: `bin/verify-fresh-install manifest_versions`
Expected: 1 passed (just `test_manifest_versions_agree`).

- [ ] **Step 5: Commit**

```bash
git add bin/verify-fresh-install
git commit -m "skill-forge: bin/verify-fresh-install entrypoint for the new tier"
```

---

## Task 8: Documentation updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

CLAUDE.md needs the new command surfaced and the Gate 2 paragraph updated to note automation. README.md gets one line in whatever testing section it has.

- [ ] **Step 1: Update CLAUDE.md "Commands you will actually run"**

Open `CLAUDE.md`. Find the section starting `## Commands you will actually run`. Add a line in the bash block after the existing commands:

```bash
bin/verify-fresh-install         # automated Gate 2 + 8 contract tests
```

- [ ] **Step 2: Update CLAUDE.md "Shipping a new version"**

In the same file, find `## Shipping a new version`. The current Gate 2 line reads:

```
3. Gate 2 (if demo touched): 5 consecutive red baselines on a fresh
   `git clone` of the repo, using `echo n | uv run forge optimize greeter --workers 1`.
```

Replace with:

```
3. Gate 2 (if demo touched): `bin/verify-fresh-install` (~3 min) — automates
   the 5 consecutive red baselines on a fresh `git clone` plus 8 other
   overfitted contract tests. Hand-run only if the script can't be used.
```

- [ ] **Step 3: Update README.md**

Find the README.md testing section (search for `pytest` or `Testing`). Add one line near the existing test commands:

```
- `bin/verify-fresh-install` — fresh-clone marketplace-install simulation (~3 min). Automates the 5x red-baseline ship gate.
```

If there's no existing testing section, add a small one near the bottom — but match the README's voice; don't introduce a new heading style.

- [ ] **Step 4: Verify CLAUDE.md and README.md still render cleanly**

Run: `head -100 CLAUDE.md | grep -A2 "verify-fresh-install"`
Expected: shows the new line under the right section.

Run: `grep -c "verify-fresh-install" README.md`
Expected: at least 1.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "skill-forge: document fresh_install tier in CLAUDE.md + README"
```

---

## Task 9: Final gate — full suite green

**Files:** none modified; this is a verification task.

- [ ] **Step 1: Default unit suite — confirm unchanged**

Run: `uv run pytest tests/ -q`
Expected: same green count as before this branch began (the new tier is excluded by `-m 'not manual and not verify and not fresh_install'`).

- [ ] **Step 2: Fresh-install tier — confirm all 9 pass**

Run: `bin/verify-fresh-install`
Expected: 9 passed, exit 0, ~3 min wall-clock.

- [ ] **Step 3: Verify the marker actually excludes by default**

Run: `uv run pytest tests/fresh_install/ -q`
Expected: "no tests ran" (because the addopts excludes the marker).

Run: `uv run pytest tests/fresh_install/ -m fresh_install -q`
Expected: 9 passed.

- [ ] **Step 4: Confirm no orphan changes**

Run: `git status`
Expected: clean working tree (all 8 prior tasks committed).

- [ ] **Step 5: Quick log check**

Run: `git log --oneline -10`
Expected: 8 task commits visible in order, plus the spec commits earlier in the branch.

---

## Self-review checklist (run before declaring done)

- [ ] Spec coverage: every test in §"Test list" of the spec corresponds to a `def test_*` in this plan. (1→Task 3; 2→Task 3; 3→Task 5; 4→Task 5; 5→Task 6; 6→Task 6; 7→Task 4; 8→Task 4; 9→Task 4.) ✓
- [ ] Failure-mode rules from spec §"Failure-mode handling" honored: no `time.sleep` polling, no `pytest.skip`, no `try/except: pass`, no mocks of `git`/`uv`/`pytest`, no retries. Subprocess timeouts are hard-kills with captured output in the assertion message. ✓
- [ ] Type/name consistency: `FreshClone` dataclass fields used identically across Tasks 5 and 6 (`clone_dir`, `forge`, `env`). `BaselineResult` and `_FAILED_RE` only used inside Task 6. ✓
- [ ] No placeholders: every step has the actual code or command. No "TBD", no "implement appropriately." ✓
- [ ] Imports check: Task 5 and Task 6 import `FreshClone` from `.conftest`. The conftest defines it with `@dataclass(frozen=True)` in Task 2. ✓
