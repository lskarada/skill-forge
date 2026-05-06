"""Task 5.3 — frontier/<skill>/<id> git tag wrapper (real git, no mocks)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skill_forge.git_tags import (
    create_frontier_tag,
    delete_frontier_tag,
    list_frontier_tags,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
             "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("a\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_create_and_list_frontier_tag(repo: Path) -> None:
    create_frontier_tag(repo, skill="greeter", program_id="g0-w0")

    tags = list_frontier_tags(repo, skill="greeter")
    assert tags == ["frontier/greeter/g0-w0"]


def test_list_filters_by_skill(repo: Path) -> None:
    create_frontier_tag(repo, skill="greeter", program_id="g0-w0")
    create_frontier_tag(repo, skill="scribe", program_id="g0-w0")
    create_frontier_tag(repo, skill="greeter", program_id="g1-w1")

    greeter_tags = list_frontier_tags(repo, skill="greeter")
    assert sorted(greeter_tags) == ["frontier/greeter/g0-w0", "frontier/greeter/g1-w1"]

    scribe_tags = list_frontier_tags(repo, skill="scribe")
    assert scribe_tags == ["frontier/scribe/g0-w0"]


def test_delete_frontier_tag(repo: Path) -> None:
    create_frontier_tag(repo, skill="greeter", program_id="g0-w0")
    delete_frontier_tag(repo, skill="greeter", program_id="g0-w0")

    assert list_frontier_tags(repo, skill="greeter") == []


def test_create_is_idempotent(repo: Path) -> None:
    create_frontier_tag(repo, skill="greeter", program_id="g0-w0")
    # Second create on same id should not raise (idempotent for retry/loop semantics).
    create_frontier_tag(repo, skill="greeter", program_id="g0-w0")
    assert list_frontier_tags(repo, skill="greeter") == ["frontier/greeter/g0-w0"]
