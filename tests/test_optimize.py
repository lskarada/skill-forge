"""Tests for optimize.py — the full Milestone 2 orchestration loop.

Every side effect (pytest, mutation subagent, git worktree, merge, branch
delete) is stubbed so these tests exercise ONLY the orchestrator's logic:
phase ordering, strictly-better gate, evidence write, learnings append, and
the merge/discard branch selection.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from skill_forge import baseline as baseline_mod
from skill_forge import optimize as opt_mod
from skill_forge import worktree as wt_mod


FROZEN_TIME = datetime(2026, 4, 18, 1, 30, 0, tzinfo=timezone.utc)


@dataclass
class _Calls:
    mutator: list[dict] = field(default_factory=list)
    pytest_runner: list[dict] = field(default_factory=list)
    merges: list[dict] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    branch_discards: list[str] = field(default_factory=list)
    printed: list[str] = field(default_factory=list)


def _make_baseline(passed: int, failed: int = 0, errors: int = 0, *, path: Path) -> baseline_mod.BaselineResult:
    total = passed + failed + errors
    return baseline_mod.BaselineResult(
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=0,
        total=total,
        returncode=0 if failed + errors == 0 else 1,
        junit_xml_path=path,
    )


def _setup(tmp_path: Path, *, skill: str = "demo") -> tuple[opt_mod.OptimizeConfig, _Calls, Path]:
    # Create a real SUT and a test file so the orchestrator's preflight passes.
    repo = tmp_path / "repo"
    repo.mkdir()
    sut_dir = repo / ".claude" / "skills" / skill
    sut_dir.mkdir(parents=True)
    sut_path = sut_dir / "SKILL.md"
    sut_path.write_text("initial skill body\n")

    tests_dir = repo / ".skill-forge" / "tests" / skill
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_demo.py").write_text("def test_ok(): assert True\n")

    config = opt_mod.OptimizeConfig(
        skill=skill,
        repo_path=repo,
        output_root=repo / ".skill-forge",
        strategy="tighten the contract",
        assume_yes=True,
        now=lambda: FROZEN_TIME,
    )
    calls = _Calls()
    return config, calls, sut_path


def _make_io(
    calls: _Calls,
    *,
    sut_path: Path,
    baseline_counts: tuple[int, int, int],
    post_counts: tuple[int, int, int],
    mutation_writes_file: bool = True,
    mutation_summary: str = "tightened the contract",
) -> opt_mod.OptimizeIO:
    """Construct an OptimizeIO with fakes that record every call."""

    def fake_pytest(tests_dir, *, cwd, junit_xml, timeout=600, extra_args=None):
        calls.pytest_runner.append({
            "tests_dir": tests_dir, "cwd": cwd, "junit_xml": junit_xml,
        })
        junit_xml.parent.mkdir(parents=True, exist_ok=True)
        junit_xml.write_text("<testsuite tests='0'/>")
        counts = baseline_counts if len(calls.pytest_runner) == 1 else post_counts
        return _make_baseline(*counts, path=junit_xml)

    def fake_resolver(skill, *, search_root=None):
        return sut_path

    @contextmanager
    def fake_worktree(repo_path, branch_name, *, base_ref="HEAD", worktree_parent=None):
        wt_path = repo_path / ".skill-forge" / "runs" / branch_name
        wt_path.mkdir(parents=True, exist_ok=True)
        (wt_path / ".claude" / "skills" / sut_path.parent.name).mkdir(parents=True, exist_ok=True)
        wt_sut = wt_path / sut_path.relative_to(repo_path)
        wt_sut.parent.mkdir(parents=True, exist_ok=True)
        wt_sut.write_text(sut_path.read_text())
        yield wt_mod.WorktreeHandle(path=wt_path, branch=branch_name, base_ref=base_ref)

    def fake_mutator(*, sut_path, tests_preview, learnings, strategy, cwd):
        calls.mutator.append({
            "sut_path": sut_path,
            "tests_preview_len": len(tests_preview),
            "learnings": learnings,
            "strategy": strategy,
            "cwd": cwd,
        })
        if mutation_writes_file:
            sut_path.write_text("mutated skill body\n")
        return mutation_summary

    def fake_committer(worktree_path, message):
        calls.commits.append({"cwd": worktree_path, "message": message})
        # Return a fake SHA when the SUT changed; None if clean.
        wt_sut = list(worktree_path.rglob("SKILL.md"))
        if wt_sut and wt_sut[0].read_text() == "initial skill body\n":
            return None
        return "a" * 40

    def fake_merger(repo_path, branch, *, message):
        calls.merges.append({"repo": repo_path, "branch": branch, "message": message})

    def fake_discarder(repo_path, branch):
        calls.branch_discards.append(branch)

    return opt_mod.OptimizeIO(
        printer=lambda m: calls.printed.append(m),
        prompter=lambda _m: "y",
        mutator=fake_mutator,
        pytest_runner=fake_pytest,
        sut_resolver=fake_resolver,
        worktree_factory=fake_worktree,
        committer=fake_committer,
        merger=fake_merger,
        branch_discarder=fake_discarder,
    )


# --- Tests ----------------------------------------------------------------


def test_baseline_all_green_is_no_op(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path)
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(2, 0, 0), post_counts=(2, 0, 0))
    result = opt_mod.run_optimize(config, io)
    assert result.outcome == "no_change"
    assert len(calls.pytest_runner) == 1  # only baseline ran
    assert calls.mutator == []


def test_mutation_wins_triggers_merge_and_evidence(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path)
    io = _make_io(
        calls,
        sut_path=sut_path,
        baseline_counts=(1, 1, 0),  # 1 failing test
        post_counts=(2, 0, 0),      # fully green after mutation
    )
    result = opt_mod.run_optimize(config, io)

    assert result.outcome == "merged"
    assert len(calls.merges) == 1
    assert calls.merges[0]["branch"].startswith("skill-forge/demo/")
    assert result.evidence_path is not None
    assert result.evidence_path.is_file()
    evidence = result.evidence_path.read_text()
    assert "merged" in evidence
    assert "## Baseline" in evidence
    assert "## Post-mutation" in evidence
    # No learning entry written on a win.
    assert not (config.output_root / "learnings.md").exists()


def test_mutation_loss_discards_and_writes_learning(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path)
    io = _make_io(
        calls,
        sut_path=sut_path,
        baseline_counts=(3, 2, 0),
        post_counts=(3, 2, 0),  # exactly the same — a tie is not a win
    )
    result = opt_mod.run_optimize(config, io)

    assert result.outcome == "tie"
    assert calls.merges == []
    # Branch got discarded (both after worktree cleanup AND at end of discard path).
    assert result.branch is not None
    assert calls.branch_discards == [result.branch]
    learnings = (config.output_root / "learnings.md").read_text()
    assert "tie" in learnings
    assert "demo" in learnings
    assert result.evidence_path is not None
    assert "tie" in result.evidence_path.read_text()


def test_mutation_regression_discards(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path)
    io = _make_io(
        calls,
        sut_path=sut_path,
        baseline_counts=(3, 1, 0),
        post_counts=(2, 2, 0),  # fewer passing — regression
    )
    result = opt_mod.run_optimize(config, io)
    assert result.outcome == "regression"
    assert calls.merges == []


def test_empty_mutation_is_no_change(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path)
    io = _make_io(
        calls,
        sut_path=sut_path,
        baseline_counts=(1, 1, 0),
        post_counts=(2, 0, 0),
        mutation_writes_file=False,  # subagent produced no diff
    )
    result = opt_mod.run_optimize(config, io)
    assert result.outcome == "no_change"
    assert calls.merges == []
    # No evidence file on empty mutations, but a learning is logged.
    assert (config.output_root / "learnings.md").exists()


def test_no_tests_aborts(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path)
    # Wipe the tests that _setup created.
    for t in (config.output_root / "tests" / config.skill).glob("test_*.py"):
        t.unlink()
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(0, 0, 0), post_counts=(0, 0, 0))
    result = opt_mod.run_optimize(config, io)
    assert result.outcome == "aborted"
    assert calls.pytest_runner == []


def test_mutation_prompt_receives_learnings(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path)
    # Pre-seed a learning so the orchestrator forwards it to the mutator.
    (config.output_root).mkdir(parents=True, exist_ok=True)
    (config.output_root / "learnings.md").write_text("- prior attempt failed: x\n")

    io = _make_io(
        calls,
        sut_path=sut_path,
        baseline_counts=(0, 1, 0),
        post_counts=(1, 0, 0),
    )
    opt_mod.run_optimize(config, io)
    assert "prior attempt failed" in calls.mutator[0]["learnings"]


def test_evidence_version_increments(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path)
    # Pre-create v1 and v2 evidence so the next write should pick v3.
    history = config.output_root / "history" / config.skill
    history.mkdir(parents=True, exist_ok=True)
    (history / "v1_evidence.md").write_text("old\n")
    (history / "v2_evidence.md").write_text("old\n")

    io = _make_io(
        calls,
        sut_path=sut_path,
        baseline_counts=(0, 1, 0),
        post_counts=(1, 0, 0),
    )
    result = opt_mod.run_optimize(config, io)
    assert result.evidence_path is not None
    assert result.evidence_path.name == "v3_evidence.md"
