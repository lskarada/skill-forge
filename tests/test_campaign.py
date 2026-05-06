"""Tasks 8.7a–e — campaign orchestrator + lock + cap + min-confidence + 0-tests."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from skill_forge import campaign
from skill_forge.attribution import SkillAttribution
from skill_forge.evolve import EvolutionResult
from skill_forge.frontier import FrontierEntry


# 8.7a: orchestrator + repo_lock plumbing
def test_run_campaign_calls_run_evolution_once_per_attribution(monkeypatch) -> None:
    captured_skills = []
    captured_locks = []

    def fake_run_evolution(*, skill, repo_lock=None, **_kw):
        captured_skills.append(skill)
        captured_locks.append(repo_lock)
        return EvolutionResult(skill=skill, frontier=[], winner=None,
                               generations_run=1, early_stopped=False)

    monkeypatch.setattr(campaign.evolve_mod, "run_evolution", fake_run_evolution)
    attributions = [SkillAttribution(s, "high", "ev") for s in ("greeter", "scribe", "data-extraction")]

    portfolio = campaign.run_campaign(
        attributions, generations=1, frontier_size=1,
        workers_per_skill=1, patience=1,
    )

    assert sorted(captured_skills) == ["data-extraction", "greeter", "scribe"]
    # All three calls share the same lock instance (8.7a contract).
    assert len(set(id(l) for l in captured_locks)) == 1
    assert all(l is not None for l in captured_locks)
    assert len(portfolio.entries) == 3


# 8.7c: concurrency cap rejects M*N > 16
def test_run_campaign_rejects_concurrency_above_16(monkeypatch) -> None:
    monkeypatch.setattr(campaign.evolve_mod, "run_evolution",
                        lambda **_kw: EvolutionResult("x", [], None, 0, False))
    attrs = [SkillAttribution(f"s{i}", "high", "") for i in range(5)]
    with pytest.raises(ValueError, match="exceeds concurrency cap"):
        campaign.run_campaign(attrs, generations=2, frontier_size=2,
                              workers_per_skill=4, patience=1)


# 8.7d: min_confidence filters out lower-rank attributions
def test_min_confidence_filters_attributions(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(campaign.evolve_mod, "run_evolution",
                        lambda *, skill, **_kw: (
                            captured.append(skill) or
                            EvolutionResult(skill, [], None, 0, False)
                        ))
    attrs = [
        SkillAttribution("greeter", "high", "literal"),
        SkillAttribution("scribe", "medium", "complaint"),
        SkillAttribution("dim", "low", "weak"),
    ]
    portfolio = campaign.run_campaign(
        attrs, generations=1, frontier_size=1, workers_per_skill=1,
        patience=1, min_confidence="medium",
    )
    assert sorted(captured) == ["greeter", "scribe"]
    assert {e.skill for e in portfolio.entries} == {"greeter", "scribe"}


# 8.7e: zero synthesizable tests admitted → skip run_evolution, mark non-accepted
def test_zero_admitted_tests_skips_run_evolution(monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(campaign.evolve_mod, "run_evolution",
                        lambda *, skill, **_kw: (
                            called.append(skill) or
                            EvolutionResult(skill, [FrontierEntry("g0-w0", 1.0, 100)],
                                            FrontierEntry("g0-w0", 1.0, 100), 1, False)
                        ))

    attrs = [SkillAttribution("greeter", "high", ""), SkillAttribution("scribe", "high", "")]
    portfolio = campaign.run_campaign(
        attrs, generations=1, frontier_size=1, workers_per_skill=1, patience=1,
        synthesize_test=lambda *_a, **_kw: None,  # synthesis rejects every test
    )

    assert called == []
    assert len(portfolio.entries) == 2
    assert all(not e.accepted for e in portfolio.entries)
    assert all("no synthesizable tests admitted" in e.reason for e in portfolio.entries)


# 8.7b: shared-lock concurrency stress test (real git, real threads)
def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
             "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )


def test_two_concurrent_worktree_creations_succeed_under_shared_lock(tmp_path: Path) -> None:
    """Two threads create worktrees against the same repo with the shared
    lock — both succeed. Without the lock, git races on
    .git/worktrees/.lock and one would crash with `fatal: cannot lock ref`."""
    from skill_forge import optimize, worktree

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _git(repo_path, "init", "-q", "-b", "main")
    (repo_path / "a.txt").write_text("a\n")
    _git(repo_path, "add", "a.txt")
    _git(repo_path, "commit", "-q", "-m", "init")

    shared_lock = threading.Lock()
    results: dict[str, Path] = {}
    errors: dict[str, BaseException] = {}

    class _RealIO:
        @staticmethod
        def worktree_factory(repo_path, branch, base_ref="HEAD"):
            return worktree.create_worktree(repo_path, branch, base_ref=base_ref)

    def make(name: str) -> None:
        try:
            with optimize._locked_worktree(
                _RealIO(), repo_path, f"stress/{name}", shared_lock,
            ) as handle:
                results[name] = handle.path
        except BaseException as e:  # noqa: BLE001
            errors[name] = e

    t1 = threading.Thread(target=make, args=("a",))
    t2 = threading.Thread(target=make, args=("b",))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert errors == {}, f"shared-lock contract failed: {errors}"
    assert set(results.keys()) == {"a", "b"}
    assert results["a"] != results["b"]
