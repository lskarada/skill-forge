"""Git worktree management for the mutation loop.

Mutations are run in isolated worktrees so the subagent's file edits cannot
clobber the user's working tree. When the mutation wins the gate, we merge
the worktree's branch into main; when it loses, we remove the worktree and
delete the branch. Either way, the user's HEAD is untouched.

We shell out to `git worktree` directly rather than using GitPython here —
`git worktree add` and `remove` are the stable surface, and keeping the CLI
layer thin means tests can fake the whole module by monkeypatching
`create_worktree` rather than mocking GitPython internals.
"""

from __future__ import annotations

import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class WorktreeError(RuntimeError):
    """Raised when git worktree operations fail."""


@dataclass(frozen=True)
class WorktreeHandle:
    path: Path
    branch: str
    base_ref: str


def _run_git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    git_bin = shutil.which("git")
    if not git_bin:
        raise WorktreeError("git not found on PATH")
    proc = subprocess.run(
        [git_bin, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise WorktreeError(
            f"git {' '.join(args)} failed: rc={proc.returncode}\n"
            f"stdout: {proc.stdout[:400]}\nstderr: {proc.stderr[:400]}"
        )
    return proc


@contextmanager
def create_worktree(
    repo_path: Path,
    branch_name: str,
    *,
    base_ref: str = "HEAD",
    worktree_parent: Path | None = None,
) -> Iterator[WorktreeHandle]:
    """Create a detached worktree on a new branch and yield its path.

    The worktree is always removed on exit (even on exception). The branch
    is only deleted if the caller did not explicitly keep it — that's done
    via `finalize_worktree`, which the orchestrator uses to decide whether
    to merge or discard. This context manager's job is just lifecycle.
    """
    repo_path = repo_path.resolve()
    parent = (worktree_parent or (repo_path / ".skill-forge" / "runs")).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    worktree_path = parent / branch_name

    if worktree_path.exists():
        raise WorktreeError(
            f"worktree path already exists: {worktree_path}. Clean up stale "
            "runs or choose a different branch name."
        )

    _run_git(
        ["worktree", "add", "-b", branch_name, str(worktree_path), base_ref],
        cwd=repo_path,
    )

    handle = WorktreeHandle(path=worktree_path, branch=branch_name, base_ref=base_ref)
    try:
        yield handle
    finally:
        _cleanup_worktree(repo_path, worktree_path)


def _cleanup_worktree(repo_path: Path, worktree_path: Path) -> None:
    """Remove the worktree directory; best-effort, swallow cleanup errors.

    If `git worktree remove --force` fails (orphaned, moved, etc.) we fall
    back to filesystem rm + `git worktree prune` so stale entries don't pile
    up in `.git/worktrees/`. The branch itself is left alone here — caller
    decides whether to delete it via `discard_branch`.
    """
    if worktree_path.exists():
        proc = _run_git(
            ["worktree", "remove", "--force", str(worktree_path)],
            cwd=repo_path,
            check=False,
        )
        if proc.returncode != 0 and worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
    _run_git(["worktree", "prune"], cwd=repo_path, check=False)


def commit_all(
    worktree_path: Path,
    message: str,
) -> str | None:
    """Stage and commit every change in the worktree. Returns commit SHA or None.

    If the worktree is clean (mutation agent produced no diff), returns None
    instead of creating an empty commit. Caller treats that as a discard.
    """
    _run_git(["add", "-A"], cwd=worktree_path)
    status = _run_git(["status", "--porcelain"], cwd=worktree_path)
    if not status.stdout.strip():
        return None
    _run_git(["commit", "-m", message, "--no-verify"], cwd=worktree_path)
    sha = _run_git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()
    return sha


def merge_branch(repo_path: Path, branch: str, *, message: str) -> None:
    """Merge `branch` into the current HEAD of `repo_path`.

    Uses --no-ff so the merge commit is visible in history. Conflicts are
    surfaced as WorktreeError — M2 does not attempt resolution (see
    KNOWN_ISSUES.md). The caller has already confirmed this mutation touches
    only the SUT markdown, which reduces conflict surface to near zero.
    """
    _run_git(
        ["merge", "--no-ff", "-m", message, branch],
        cwd=repo_path,
    )


def discard_branch(repo_path: Path, branch: str) -> None:
    """Delete `branch` from `repo_path` regardless of merge status."""
    _run_git(["branch", "-D", branch], cwd=repo_path, check=False)
