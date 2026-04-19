"""Tests for Milestone 3 — parallel fork-and-pick in optimize.py.

These tests reuse the same injectable-I/O pattern as test_optimize.py but
vary fake behaviour *per worker* so we exercise:

  * winner selection by passing-test count
  * PRD §3 Phase 4 tiebreak on shorter mutated SUT
  * graceful loss path (no worker beats baseline → no merge, learnings logged)
  * per-worker strategy distribution from DEFAULT_STRATEGIES
  * empty-mutation workers handled without crashing neighbours
  * worker-level exception isolation (one crash doesn't abort the run)
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from skill_forge import baseline as baseline_mod
from skill_forge import optimize as opt_mod
from skill_forge import worktree as wt_mod


FROZEN_TIME = datetime(2026, 4, 18, 2, 0, 0, tzinfo=timezone.utc)


@dataclass
class _Calls:
    mutator: list[dict] = field(default_factory=list)
    pytest_runner: list[dict] = field(default_factory=list)
    merges: list[dict] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    branch_discards: list[str] = field(default_factory=list)
    printed: list[str] = field(default_factory=list)
    worktree_enters: list[str] = field(default_factory=list)


def _baseline(passed: int, failed: int = 0, errors: int = 0, *, path: Path) -> baseline_mod.BaselineResult:
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


def _setup(tmp_path: Path, *, skill: str = "demo", num_workers: int = 3) -> tuple[opt_mod.OptimizeConfig, _Calls, Path]:
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
        strategy="tighten",
        assume_yes=True,
        num_workers=num_workers,
        now=lambda: FROZEN_TIME,
    )
    return config, _Calls(), sut_path


def _make_io(
    calls: _Calls,
    *,
    sut_path: Path,
    baseline_counts: tuple[int, int, int],
    worker_plans: list[dict],
) -> opt_mod.OptimizeIO:
    """Construct an OptimizeIO where per-worker behaviour is plan-driven.

    Each entry of `worker_plans` is keyed by worker index {0..N-1}:
        post_counts:  (passed, failed, errors) from pytest after mutation
        body:         str body to write when this worker mutates (len → tiebreak)
        writes:       bool; False skips the mutation edit so committer returns None
        raises:       optional str; if set, the mutator raises RuntimeError
    """
    plan_by_idx = {p["index"]: p for p in worker_plans}
    pytest_lock = threading.Lock()

    def fake_pytest(tests_dir, *, cwd, junit_xml, timeout=600, extra_args=None):
        with pytest_lock:
            calls.pytest_runner.append({"cwd": cwd, "junit_xml": junit_xml})
        junit_xml.parent.mkdir(parents=True, exist_ok=True)
        junit_xml.write_text("<testsuite tests='0'/>")
        # Baseline runs first on the main repo; every later call is a worker.
        if "mutated" not in junit_xml.name:
            return _baseline(*baseline_counts, path=junit_xml)
        # Identify the worker by the junit filename suffix (_w<idx>).
        idx = int(junit_xml.stem.rsplit("_w", 1)[-1])
        plan = plan_by_idx[idx]
        return _baseline(*plan["post_counts"], path=junit_xml)

    def fake_resolver(skill, *, search_root=None):
        return sut_path

    @contextmanager
    def fake_worktree(repo_path, branch_name, *, base_ref="HEAD", worktree_parent=None):
        calls.worktree_enters.append(branch_name)
        wt_path = repo_path / ".skill-forge" / "runs" / branch_name
        wt_path.mkdir(parents=True, exist_ok=True)
        wt_sut = wt_path / sut_path.relative_to(repo_path)
        wt_sut.parent.mkdir(parents=True, exist_ok=True)
        wt_sut.write_text(sut_path.read_text())
        yield wt_mod.WorktreeHandle(path=wt_path, branch=branch_name, base_ref=base_ref)

    def fake_mutator(*, sut_path, tests_preview, learnings, strategy, cwd):
        # Worker index is encoded in the branch suffix of the cwd path.
        idx = int(str(cwd).rsplit("/w", 1)[-1])
        plan = plan_by_idx[idx]
        calls.mutator.append({
            "index": idx,
            "strategy": strategy,
            "learnings": learnings,
        })
        if plan.get("raises"):
            raise RuntimeError(plan["raises"])
        if plan.get("writes", True):
            sut_path.write_text(plan["body"])
        return f"w{idx}: mutated"

    def fake_committer(worktree_path, message):
        calls.commits.append({"cwd": worktree_path, "message": message})
        for p in worktree_path.rglob("SKILL.md"):
            if p.read_text() != "initial skill body\n":
                return "a" * 40
        return None

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


# --- Tests ---------------------------------------------------------------


def test_parallel_merge_picks_highest_passing(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    plans = [
        {"index": 0, "post_counts": (1, 1, 0), "body": "medium body text\n"},
        {"index": 1, "post_counts": (2, 0, 0), "body": "longer winning body for worker 1\n"},
        {"index": 2, "post_counts": (1, 1, 0), "body": "another medium body text\n"},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)
    result = opt_mod.run_optimize(config, io)

    assert result.outcome == "merged"
    assert len(calls.merges) == 1
    # Worker 1 had the highest passing count → its branch was merged.
    assert calls.merges[0]["branch"].endswith("/w1")
    assert result.worker_results
    assert {r.index for r in result.worker_results} == {0, 1, 2}
    # Every worker branch was discarded (including the winner post-merge).
    assert set(calls.branch_discards) == {r.branch for r in result.worker_results}


def test_parallel_tiebreak_on_shorter_sut(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    # All three tie on passing count; index 1 has the shortest mutated SUT.
    plans = [
        {"index": 0, "post_counts": (2, 0, 0), "body": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"},  # 32
        {"index": 1, "post_counts": (2, 0, 0), "body": "short\n"},  # 6 — shortest
        {"index": 2, "post_counts": (2, 0, 0), "body": "medium sized mutated body\n"},  # 26
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)
    result = opt_mod.run_optimize(config, io)

    assert result.outcome == "merged"
    assert calls.merges[0]["branch"].endswith("/w1")
    winner = next(r for r in result.worker_results if r.branch == calls.merges[0]["branch"])
    assert winner.mutated_sut_length == len("short\n")


def test_parallel_no_winner_writes_learnings(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    # Nobody improves on baseline — all tie.
    plans = [
        {"index": 0, "post_counts": (1, 1, 0), "body": "body-a\n"},
        {"index": 1, "post_counts": (1, 1, 0), "body": "body-b\n"},
        {"index": 2, "post_counts": (1, 1, 0), "body": "body-c\n"},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)
    result = opt_mod.run_optimize(config, io)

    assert result.outcome == "tie"
    assert calls.merges == []
    learnings = (config.output_root / "learnings.md").read_text()
    # One learning per worker.
    assert learnings.count("[w0]") == 1
    assert learnings.count("[w1]") == 1
    assert learnings.count("[w2]") == 1
    # Evidence file exists for a full loss too (SOUL: no silent losses).
    assert result.evidence_path is not None
    assert result.evidence_path.is_file()
    assert "no merge" in result.evidence_path.read_text()


def test_parallel_strategies_distributed_per_worker(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    plans = [
        {"index": 0, "post_counts": (2, 0, 0), "body": "body-0\n"},
        {"index": 1, "post_counts": (1, 1, 0), "body": "body-1\n"},
        {"index": 2, "post_counts": (1, 1, 0), "body": "body-2\n"},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)
    opt_mod.run_optimize(config, io)

    strategies_seen = {c["index"]: c["strategy"] for c in calls.mutator}
    # 3 workers = 3 distinct strategies from the default lineup.
    assert len(set(strategies_seen.values())) == 3


def test_parallel_empty_mutation_does_not_block_others(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    plans = [
        {"index": 0, "post_counts": (0, 0, 0), "body": "", "writes": False},
        {"index": 1, "post_counts": (2, 0, 0), "body": "winning body w1\n"},
        {"index": 2, "post_counts": (0, 0, 0), "body": "", "writes": False},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)
    result = opt_mod.run_optimize(config, io)

    assert result.outcome == "merged"
    assert calls.merges[0]["branch"].endswith("/w1")
    # Two "no_change" outcomes plus one "won".
    outcomes = [r.outcome for r in sorted(result.worker_results, key=lambda r: r.index)]
    assert outcomes == ["no_change", "won", "no_change"]


def test_parallel_worker_exception_is_isolated(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path, num_workers=3)
    plans = [
        {"index": 0, "post_counts": (2, 0, 0), "body": "w0 winning body\n"},
        {"index": 1, "post_counts": (0, 0, 0), "body": "", "raises": "subagent kaboom"},
        {"index": 2, "post_counts": (1, 1, 0), "body": "w2 body\n"},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)
    result = opt_mod.run_optimize(config, io)

    # Winner is still w0 even though w1 blew up.
    assert result.outcome == "merged"
    assert calls.merges[0]["branch"].endswith("/w0")
    errored = next(r for r in result.worker_results if r.index == 1)
    assert errored.outcome == "error"
    assert errored.error is not None
    assert "subagent kaboom" in errored.error


def test_parallel_all_regress_returns_regression(tmp_path: Path) -> None:
    config, calls, sut_path = _setup(tmp_path, num_workers=2)
    plans = [
        {"index": 0, "post_counts": (0, 2, 0), "body": "w0 body\n"},
        {"index": 1, "post_counts": (0, 2, 0), "body": "w1 body\n"},
    ]
    io = _make_io(calls, sut_path=sut_path, baseline_counts=(1, 1, 0), worker_plans=plans)
    result = opt_mod.run_optimize(config, io)

    assert result.outcome == "regression"
    assert calls.merges == []


def test_strategies_for_cycles_default_lineup() -> None:
    from skill_forge.prompts import DEFAULT_STRATEGIES, strategies_for

    n = len(DEFAULT_STRATEGIES) + 2
    picked = strategies_for(n)
    assert len(picked) == n
    # First len(DEFAULT_STRATEGIES) should match the lineup in order, then wrap.
    assert picked[: len(DEFAULT_STRATEGIES)] == list(DEFAULT_STRATEGIES)
    assert picked[len(DEFAULT_STRATEGIES)] == DEFAULT_STRATEGIES[0]


def test_strategies_for_override_wins() -> None:
    from skill_forge.prompts import strategies_for

    override = ["custom-a", "custom-b"]
    picked = strategies_for(5, override=override)
    assert picked == ["custom-a", "custom-b", "custom-a", "custom-b", "custom-a"]
