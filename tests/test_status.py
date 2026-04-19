"""Tests for skill_forge.status — the `forge status` read-only report.

Coverage targets:
- Missing `.skill-forge/` root prints a hint and exits clean.
- Empty root (exists, no skills) prints a "no skills tracked yet" message.
- A fully populated tree (tests + history + learnings) is summarized
  per-skill with test counts, merged version counts, and latest evidence.
- `--skill` filters the report to one skill.
"""

from __future__ import annotations

from pathlib import Path

from skill_forge.status import (
    StatusConfig,
    StatusIO,
    collect_status,
    render_status,
    run_status,
)


def _mk_skill_tree(
    root: Path,
    skill: str,
    *,
    n_tests: int = 0,
    versions: tuple[int, ...] = (),
    loss_runs: int = 0,
) -> None:
    tests_dir = root / "tests" / skill
    tests_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n_tests):
        (tests_dir / f"test_{skill}_{i}.py").write_text("def test_ok(): pass\n")

    history_dir = root / "history" / skill
    history_dir.mkdir(parents=True, exist_ok=True)
    for v in versions:
        (history_dir / f"v{v}_evidence.md").write_text(f"# v{v} evidence\n")
    for i in range(loss_runs):
        (history_dir / f"loss_2026-04-19T00-0{i}_evidence.md").write_text(
            "# loss evidence\n"
        )


def test_missing_root_does_not_crash(tmp_path: Path) -> None:
    config = StatusConfig(output_root=tmp_path / "nope")
    status = collect_status(config)
    assert status.root_exists is False
    assert status.skills == ()
    text = render_status(status)
    assert "no .skill-forge directory" in text.lower()


def test_empty_root_reports_no_skills(tmp_path: Path) -> None:
    (tmp_path / ".skill-forge").mkdir()
    status = collect_status(StatusConfig(output_root=tmp_path / ".skill-forge"))
    assert status.root_exists is True
    assert status.skills == ()
    text = render_status(status)
    assert "no skills tracked" in text.lower()


def test_populated_tree_is_summarized(tmp_path: Path) -> None:
    root = tmp_path / ".skill-forge"
    root.mkdir()
    _mk_skill_tree(root, "greeter", n_tests=2, versions=(1, 2), loss_runs=1)
    _mk_skill_tree(root, "extractor", n_tests=1, versions=(), loss_runs=0)
    (root / "learnings.md").write_text("one loss\ntwo loss\n")

    status = collect_status(StatusConfig(output_root=root))
    names = [s.name for s in status.skills]
    assert names == ["extractor", "greeter"]  # alphabetically sorted

    greeter = next(s for s in status.skills if s.name == "greeter")
    assert greeter.test_count == 2
    assert greeter.version_count == 2
    assert greeter.latest_version == 2
    assert greeter.loss_run_count == 1

    extractor = next(s for s in status.skills if s.name == "extractor")
    assert extractor.test_count == 1
    assert extractor.version_count == 0
    assert extractor.latest_version is None

    assert status.learnings_entries == 2
    assert status.learnings_last_mtime is not None

    text = render_status(status)
    assert "greeter" in text
    assert "extractor" in text
    assert "v2" in text  # latest merged version surfaces
    assert "Learnings: 2 entries" in text


def test_skill_filter_narrows_report(tmp_path: Path) -> None:
    root = tmp_path / ".skill-forge"
    root.mkdir()
    _mk_skill_tree(root, "greeter", n_tests=1)
    _mk_skill_tree(root, "extractor", n_tests=3)

    status = collect_status(StatusConfig(output_root=root, skill="greeter"))
    assert [s.name for s in status.skills] == ["greeter"]

    unknown = collect_status(StatusConfig(output_root=root, skill="does-not-exist"))
    assert unknown.skills == ()


def test_run_status_prints_via_io(tmp_path: Path) -> None:
    root = tmp_path / ".skill-forge"
    root.mkdir()
    _mk_skill_tree(root, "greeter", n_tests=1, versions=(1,))

    lines: list[str] = []
    run_status(StatusConfig(output_root=root), StatusIO(printer=lines.append))

    assert any("greeter" in line for line in lines)
    assert any("v1" in line for line in lines)
