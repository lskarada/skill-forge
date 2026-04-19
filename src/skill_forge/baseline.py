"""Pytest runner for Skill-Forge's regression gate.

The optimize loop needs a deterministic way to ask "did this run pass more
tests than baseline?" We shell out to pytest with --junit-xml so we can count
pass/fail/error without parsing human-readable stdout.

The runner is intentionally small: it does not know about strategies, worktrees,
or merging. It takes a directory of tests and a cwd, returns a BaselineResult.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class BaselineError(RuntimeError):
    """Raised when pytest cannot be invoked (missing binary, unreadable XML)."""


@dataclass(frozen=True)
class BaselineResult:
    passed: int
    failed: int
    errors: int
    skipped: int
    total: int
    returncode: int
    junit_xml_path: Path

    @property
    def score(self) -> int:
        """Higher is better. Baseline is ranked by passing-test count."""
        return self.passed

    def strictly_better_than(self, other: "BaselineResult") -> bool:
        """Improvement means MORE passing AND NO NEW failures.

        A mutation that flips a previously-failing test to passing is a win.
        A mutation that also breaks a previously-passing test is a regression
        even if total pass count went up.
        """
        if self.passed <= other.passed:
            return False
        return (self.failed + self.errors) <= (other.failed + other.errors)


def run_pytest(
    tests_dir: Path,
    *,
    cwd: Path,
    junit_xml: Path,
    timeout: int = 600,
    extra_args: list[str] | None = None,
) -> BaselineResult:
    """Run pytest against `tests_dir` from `cwd`, writing JUnit XML to `junit_xml`.

    Returns a BaselineResult even on test failures — a failing test run is a
    *signal*, not an error. Only surfaces BaselineError when pytest itself
    cannot be located or its XML is malformed.
    """
    pytest_cmd = _resolve_pytest_bin()
    junit_xml.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        *pytest_cmd,
        str(tests_dir),
        f"--junit-xml={junit_xml}",
        "-q",
        "--no-header",
    ]
    if extra_args:
        cmd.extend(extra_args)

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise BaselineError(f"pytest timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise BaselineError(f"pytest binary not invokable: {pytest_cmd}") from e

    if not junit_xml.is_file():
        raise BaselineError(
            f"pytest exited {proc.returncode} but wrote no JUnit XML.\n"
            f"stdout: {proc.stdout[:400]}\nstderr: {proc.stderr[:400]}"
        )

    counts = _parse_junit_xml(junit_xml)
    return BaselineResult(
        passed=counts["passed"],
        failed=counts["failed"],
        errors=counts["errors"],
        skipped=counts["skipped"],
        total=counts["total"],
        returncode=proc.returncode,
        junit_xml_path=junit_xml,
    )


def _resolve_pytest_bin() -> list[str]:
    """Return an argv prefix that invokes pytest.

    Default is `[sys.executable, "-m", "pytest"]` — this guarantees workers
    inherit the same interpreter (and therefore the same site-packages) as
    the Skill-Forge process, which matters inside a venv where
    `shutil.which("pytest")` might resolve to a system binary that can't
    import the project under test.

    Override with SKILL_FORGE_PYTEST_BIN. The value is parsed with shlex
    so multi-token overrides like "uv run pytest" are supported.
    """
    override = os.environ.get("SKILL_FORGE_PYTEST_BIN")
    if override:
        parts = shlex.split(override)
        if not parts:
            raise BaselineError("SKILL_FORGE_PYTEST_BIN is set but empty.")
        resolved = shutil.which(parts[0])
        if resolved is None:
            raise BaselineError(
                f"SKILL_FORGE_PYTEST_BIN points at {parts[0]!r}, which is not "
                "on PATH."
            )
        return [resolved, *parts[1:]]
    return [sys.executable, "-m", "pytest"]


def _parse_junit_xml(path: Path) -> dict[str, int]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise BaselineError(f"could not parse JUnit XML at {path}: {e}") from e

    root = tree.getroot()
    # Accept both <testsuite ...> and <testsuites><testsuite ...>.
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    total = failed = errors = skipped = 0
    for suite in suites:
        total += int(suite.attrib.get("tests", "0") or "0")
        failed += int(suite.attrib.get("failures", "0") or "0")
        errors += int(suite.attrib.get("errors", "0") or "0")
        skipped += int(suite.attrib.get("skipped", "0") or "0")

    passed = max(0, total - failed - errors - skipped)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
    }
