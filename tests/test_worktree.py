"""Tests for worktree.py — git worktree lifecycle helpers.

These tests create a real temp git repo (cheap; `git init` + one commit) so
we exercise the actual git CLI, not a mock. That way we catch things like
argument-order changes between git versions, which a mock would miss.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from skill_forge import worktree as wt_mod

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not on PATH",
)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init", "--no-verify"], cwd=path, check=True)


def test_create_worktree_yields_path_and_cleans_up(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    captured: dict = {}
    with wt_mod.create_worktree(repo, "skill-forge/test/branch-a") as handle:
        assert handle.path.is_dir()
        assert (handle.path / "README.md").is_file()
        captured["path"] = handle.path
        captured["branch"] = handle.branch

    # After context exits, worktree path is removed but branch survives.
    assert not captured["path"].exists()
    branches = subprocess.run(
        ["git", "branch", "--list", captured["branch"]],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "skill-forge/test/branch-a" in branches


def test_create_worktree_cleans_up_on_exception(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    with pytest.raises(RuntimeError):
        with wt_mod.create_worktree(repo, "skill-forge/test/err") as handle:
            raise RuntimeError("boom")

    # Worktree dir should be gone even though we raised.
    assert not (repo / ".skill-forge" / "runs" / "skill-forge/test/err").exists()


def test_commit_all_returns_none_for_clean_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    with wt_mod.create_worktree(repo, "skill-forge/test/clean") as handle:
        sha = wt_mod.commit_all(handle.path, "no-op")
        assert sha is None


def test_commit_all_returns_sha_for_dirty_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    with wt_mod.create_worktree(repo, "skill-forge/test/dirty") as handle:
        (handle.path / "SKILL.md").write_text("mutated skill body\n")
        sha = wt_mod.commit_all(handle.path, "skill-forge: mutate")
        assert sha is not None
        assert len(sha) == 40


def test_merge_branch_brings_changes_into_main(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    branch = "skill-forge/test/merge"
    with wt_mod.create_worktree(repo, branch) as handle:
        (handle.path / "SKILL.md").write_text("mutated\n")
        wt_mod.commit_all(handle.path, "mutate")

    wt_mod.merge_branch(repo, branch, message="merge mutation")
    assert (repo / "SKILL.md").read_text() == "mutated\n"


def test_discard_branch_is_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    # Deleting a nonexistent branch should not raise (check=False in impl).
    wt_mod.discard_branch(repo, "skill-forge/test/nope")


def test_duplicate_worktree_name_raises(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    branch = "skill-forge/test/dup"
    with wt_mod.create_worktree(repo, branch) as handle:
        # Pre-create the path for a second identical worktree attempt.
        conflicting = tmp_path / "outside"
        conflicting.mkdir()
        with pytest.raises(wt_mod.WorktreeError):
            with wt_mod.create_worktree(repo, branch):
                pass
