"""Tests for baseline.py — the pytest runner and JUnit XML parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from skill_forge import baseline as baseline_mod


def _write_junit(path: Path, *, tests: int, failures: int = 0, errors: int = 0, skipped: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<?xml version="1.0"?>
<testsuites>
  <testsuite name="s" tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"/>
</testsuites>
"""
    )


def test_parse_counts_all_passing(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    _write_junit(xml, tests=5)
    counts = baseline_mod._parse_junit_xml(xml)
    assert counts == {"total": 5, "passed": 5, "failed": 0, "errors": 0, "skipped": 0}


def test_parse_counts_with_failures(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    _write_junit(xml, tests=10, failures=2, errors=1, skipped=1)
    counts = baseline_mod._parse_junit_xml(xml)
    assert counts == {"total": 10, "passed": 6, "failed": 2, "errors": 1, "skipped": 1}


def test_parse_handles_single_testsuite_root(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text('<testsuite name="s" tests="3" failures="1"/>')
    counts = baseline_mod._parse_junit_xml(xml)
    assert counts["total"] == 3
    assert counts["failed"] == 1
    assert counts["passed"] == 2


def test_parse_raises_on_malformed_xml(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text("<not xml")
    with pytest.raises(baseline_mod.BaselineError):
        baseline_mod._parse_junit_xml(xml)


def test_strictly_better_requires_more_passing(tmp_path: Path) -> None:
    xml = tmp_path / "j.xml"
    xml.write_text('<testsuite tests="0"/>')
    base = baseline_mod.BaselineResult(
        passed=3, failed=1, errors=0, skipped=0, total=4, returncode=1, junit_xml_path=xml
    )
    same = baseline_mod.BaselineResult(
        passed=3, failed=1, errors=0, skipped=0, total=4, returncode=1, junit_xml_path=xml
    )
    better = baseline_mod.BaselineResult(
        passed=4, failed=0, errors=0, skipped=0, total=4, returncode=0, junit_xml_path=xml
    )
    # More passing but also strictly MORE total failures/errors → not better.
    regressed = baseline_mod.BaselineResult(
        passed=6, failed=0, errors=2, skipped=0, total=8, returncode=1, junit_xml_path=xml
    )
    base_stable = baseline_mod.BaselineResult(
        passed=5, failed=1, errors=0, skipped=0, total=6, returncode=1, junit_xml_path=xml
    )

    assert not same.strictly_better_than(base)
    assert better.strictly_better_than(base)
    # Passed went up by 1 but errors went up by 2 → net new broken tests. Not a win.
    assert not regressed.strictly_better_than(base_stable)


def test_run_pytest_returns_result_even_on_failures(tmp_path: Path) -> None:
    """A failing pytest run should produce a BaselineResult, not raise."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fail.py").write_text("def test_x(): assert False\n")

    junit = tmp_path / "junit.xml"
    result = baseline_mod.run_pytest(tests_dir, cwd=tmp_path, junit_xml=junit, timeout=60)

    assert result.total == 1
    assert result.failed == 1
    assert result.passed == 0
    assert result.returncode != 0
    assert junit.is_file()


def test_run_pytest_success(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text("def test_x(): assert True\n")

    junit = tmp_path / "junit.xml"
    result = baseline_mod.run_pytest(tests_dir, cwd=tmp_path, junit_xml=junit, timeout=60)

    assert result.total == 1
    assert result.passed == 1
    assert result.failed == 0
    assert result.returncode == 0


def test_run_pytest_missing_binary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SKILL_FORGE_PYTEST_BIN", "/nonexistent/pytest")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    junit = tmp_path / "junit.xml"
    with pytest.raises(baseline_mod.BaselineError):
        baseline_mod.run_pytest(tests_dir, cwd=tmp_path, junit_xml=junit, timeout=10)
