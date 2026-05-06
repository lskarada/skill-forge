"""Task 4.6 — generalized SUT staging handles single files AND directories."""
from __future__ import annotations

from pathlib import Path

from skill_forge.optimize import _stage_sut, _unstage_sut


def test_stage_sut_for_file_creates_mutation_target_md(tmp_path: Path) -> None:
    sut = tmp_path / ".claude" / "skills" / "x" / "SKILL.md"
    sut.parent.mkdir(parents=True)
    sut.write_text("hello")

    worktree = tmp_path / "wt"
    worktree.mkdir()

    scratch = _stage_sut(sut, worktree)

    assert scratch == worktree / "MUTATION_TARGET.md"
    assert scratch.read_text() == "hello"


def test_stage_sut_for_directory_creates_mutation_target_dir(tmp_path: Path) -> None:
    sut_dir = tmp_path / ".claude" / "skills" / "sample"
    (sut_dir / "scripts").mkdir(parents=True)
    (sut_dir / "SKILL.md").write_text("# sample\n")
    (sut_dir / "scripts" / "foo.py").write_text("print('hi')\n")

    worktree = tmp_path / "wt"
    worktree.mkdir()

    scratch = _stage_sut(sut_dir, worktree)

    assert scratch == worktree / "MUTATION_TARGET"
    assert scratch.is_dir()
    assert (scratch / "SKILL.md").read_text() == "# sample\n"
    assert (scratch / "scripts" / "foo.py").read_text() == "print('hi')\n"


def test_unstage_sut_copies_directory_back(tmp_path: Path) -> None:
    sut_dir = tmp_path / ".claude" / "skills" / "sample"
    (sut_dir / "scripts").mkdir(parents=True)
    (sut_dir / "SKILL.md").write_text("original\n")
    (sut_dir / "scripts" / "foo.py").write_text("original\n")

    worktree = tmp_path / "wt"
    worktree.mkdir()
    scratch = _stage_sut(sut_dir, worktree)

    (scratch / "SKILL.md").write_text("mutated SKILL\n")
    (scratch / "scripts" / "foo.py").write_text("mutated foo\n")
    (scratch / "scripts" / "new.py").write_text("added file\n")

    _unstage_sut(scratch, sut_dir)

    assert (sut_dir / "SKILL.md").read_text() == "mutated SKILL\n"
    assert (sut_dir / "scripts" / "foo.py").read_text() == "mutated foo\n"
    assert (sut_dir / "scripts" / "new.py").read_text() == "added file\n"


def test_unstage_sut_copies_file_back(tmp_path: Path) -> None:
    sut = tmp_path / ".claude" / "skills" / "x" / "SKILL.md"
    sut.parent.mkdir(parents=True)
    sut.write_text("orig")

    worktree = tmp_path / "wt"
    worktree.mkdir()
    scratch = _stage_sut(sut, worktree)
    scratch.write_text("mutated")

    _unstage_sut(scratch, sut)

    assert sut.read_text() == "mutated"
