"""Tasks 8.1 + 8.1.5 — pain.ingest + resolve_transcripts_dir."""
from __future__ import annotations

from pathlib import Path

import pytest

from skill_forge.pain import (
    PainSession,
    TranscriptsNotFoundError,
    ingest,
    resolve_transcripts_dir,
)

FIXTURE = Path(__file__).parent / "fixtures" / "rough_session"


def test_ingest_combines_transcripts_and_git() -> None:
    # since=None to make this test independent of fixture file mtime
    # (default recency is 24h; fixtures don't update).
    pain = ingest(transcripts_dir=FIXTURE, git_diff_path=FIXTURE / "git.diff", since=None)

    assert isinstance(pain, PainSession)
    assert len(pain.turns) == 5  # 3 + 2
    assert "TypeError" in pain.error_signatures
    assert "src/foo.py" in pain.changed_files
    assert "src/bar.py" in pain.changed_files
    assert pain.user_complaint_phrases  # at least one


def test_resolve_encodes_slashes_to_dashes(tmp_path: Path) -> None:
    fake_projects = tmp_path / "projects"
    encoded = "-Users-x-Documents-Foo"
    (fake_projects / encoded).mkdir(parents=True)

    resolved = resolve_transcripts_dir(
        Path("/Users/x/Documents/Foo"), projects_root=fake_projects,
    )
    assert resolved == fake_projects / encoded


def test_resolve_raises_when_no_match(tmp_path: Path) -> None:
    fake_projects = tmp_path / "projects"
    fake_projects.mkdir()
    with pytest.raises(TranscriptsNotFoundError, match="no transcripts found for"):
        resolve_transcripts_dir(
            Path("/nowhere/in/particular"), projects_root=fake_projects,
        )


def test_resolve_handles_non_ascii_path(tmp_path: Path) -> None:
    fake_projects = tmp_path / "projects"
    encoded = "-Users-x-Documents-プロジェクト"
    (fake_projects / encoded).mkdir(parents=True)
    resolved = resolve_transcripts_dir(
        Path("/Users/x/Documents/プロジェクト"), projects_root=fake_projects,
    )
    assert resolved == fake_projects / encoded
