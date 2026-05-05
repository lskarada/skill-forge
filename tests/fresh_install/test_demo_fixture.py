"""Greeter demo fixture tests — the load-bearing first-run proof.

SOUL.md: 'The shipped greeter fixture is the first-run proof a user
sees. It is not a toy. ... Fixture breakage is demo breakage is
launch breakage.'

test_greeter_baseline_red_by_construction_5x is the inverse of
sampling-based verification SOUL.md forbids: the assertion is
`all 5 red`. A single green run fails the test — that is the
deterministic kill criterion CLAUDE.md Gate 2 names.
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


def _run_optimize_baseline(
    fresh: FreshClone, timeout: int = 300
) -> BaselineResult:
    """Run `bin/forge optimize greeter --workers 1` with stdin='n\\n' so
    the user prompt to start mutations is declined. The Phase 1
    baseline still runs — that's all this test cares about.

    Parses pytest's summary line out of stdout. Hard-kills on timeout
    and surfaces captured output.

    Default timeout is 300s — Phase 1 baseline runs the harness DSL,
    which dispatches real Claude Code subagents (one per `run_skill`
    call). On a fresh clone with cold UV_CACHE_DIR, the inner uvx
    invocation also pays wheel-build cost. Empirically: 60-180s per
    call. 300s gives headroom without masking a genuine hang."""
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


def test_greeter_baseline_red_by_construction_5x(
    fresh_clone: FreshClone,
) -> None:
    """SOUL.md non-negotiable #1: 'Red baselines must be red by
    construction.' This test runs the Phase 1 baseline 5 consecutive
    times and asserts ALL are red (failed > 0). Any single green run
    fails this test — that is the deterministic kill criterion CLAUDE.md
    Gate 2 names ('5 consecutive red baselines on a fresh git clone').
    """
    results: list[BaselineResult] = []
    for _ in range(5):
        r = _run_optimize_baseline(fresh_clone, timeout=300)
        results.append(r)
        # Short-circuit: if any baseline goes green, the contract is
        # already violated. No need to wait for the remaining
        # iterations — fail fast with the diagnostic. (This is not
        # softening the 5x rule — the rule is `all 5 red`, and a
        # single green already disproves that.)
        if r.failed == 0:
            break

    all_red = all(r.failed > 0 for r in results) and len(results) == 5
    if not all_red:
        # Identify the green run (the regression). Print all 5 counts +
        # the green run's stdout so the operator can diagnose
        # "SKILL accidentally satisfied" vs "pytest never ran".
        lines = [
            "Greeter baseline failed SOUL.md non-negotiable #1 "
            "(red by construction):"
        ]
        green_idx = -1
        for idx, r in enumerate(results):
            tag = "" if r.failed > 0 else "  ← GREEN, broke determinism"
            lines.append(
                f"  run {idx + 1}/{len(results)}: "
                f"failed={r.failed} passed={r.passed}{tag}"
            )
            if r.failed == 0 and green_idx < 0:
                green_idx = idx
        lines.append("")
        if green_idx >= 0:
            lines.append("Green-run stdout (truncated to 400 chars):")
            lines.append(
                "  "
                + results[green_idx].raw_stdout[:400].replace("\n", "\n  ")
            )
        lines.append("")
        lines.append(
            "Diagnose: did the SKILL accidentally satisfy the assertion "
            "(real bug) or did pytest never run (env issue)?"
        )
        raise AssertionError("\n".join(lines))


def test_capture_emits_test_dir_under_skill_forge(
    fresh_clone: FreshClone,
) -> None:
    """After running optimize-baseline against the greeter, the
    captured regression tests live at .skill-forge/tests/greeter/.
    Independent run — does NOT rely on test 5's iteration order."""
    _run_optimize_baseline(fresh_clone, timeout=300)

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
