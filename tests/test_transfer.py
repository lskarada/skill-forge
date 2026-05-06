"""Task 6.3 — forge transfer primitive (copy skill folder, run target tests, report delta)."""
from __future__ import annotations

from pathlib import Path

from skill_forge.transfer import TransferReport, run_transfer


def test_transfer_copies_source_into_target_slot(tmp_path: Path) -> None:
    skills_root = tmp_path / ".claude" / "skills"
    src = skills_root / "src-skill"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("# src skill\nplus extras\n")
    (src / "scripts").mkdir()
    (src / "scripts" / "helper.py").write_text("print('hi')\n")

    target_slot = skills_root / "tgt-slot"
    target_slot.mkdir(parents=True)
    (target_slot / "SKILL.md").write_text("# old target\n")

    def fake_runner(slot: Path) -> tuple[int, int]:
        # passes is 0 before, 1 after the copy lands SKILL.md content
        if (slot / "scripts" / "helper.py").exists():
            return (1, 1)
        return (0, 1)

    report = run_transfer(
        source_skill_dir=src,
        target_slot_dir=target_slot,
        run_target_tests=fake_runner,
    )

    assert isinstance(report, TransferReport)
    assert (target_slot / "SKILL.md").read_text() == "# src skill\nplus extras\n"
    assert (target_slot / "scripts" / "helper.py").exists()
    assert report.pass_before == 0
    assert report.pass_after == 1
    assert report.delta == 1
    assert report.total == 1


def test_transfer_handles_single_file_source(tmp_path: Path) -> None:
    src = tmp_path / "src-SKILL.md"
    src.write_text("# new\n")

    target_slot = tmp_path / "tgt"
    target_slot.mkdir()
    (target_slot / "SKILL.md").write_text("# old\n")

    def fake_runner(slot: Path) -> tuple[int, int]:
        passed = 1 if (slot / "SKILL.md").read_text() == "# new\n" else 0
        return (passed, 2)

    report = run_transfer(
        source_skill_dir=src,
        target_slot_dir=target_slot,
        run_target_tests=fake_runner,
    )

    assert (target_slot / "SKILL.md").read_text() == "# new\n"
    assert report.pass_before == 0
    assert report.pass_after == 1
    assert report.total == 2
    assert report.delta == 1
