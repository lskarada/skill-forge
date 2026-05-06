"""`forge transfer` primitive — copy a skill folder into a sibling slot
and report the pre/post pass-rate delta.

Used by:
  - v0.6 demo (substrate primitive only).
  - v0.8 retro Mission Control: `forge retro` calls this to surface
    transfer deltas in the campaign panel for skills that share tests.

Pure-Python plumbing. The actual test invocation is injected via the
`run_target_tests` callable so this module stays test-runner-agnostic.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class TransferReport:
    pass_before: int
    pass_after: int
    total: int
    delta: int   # pass_after - pass_before


PassCounts = tuple[int, int]   # (passed, total)
TestRunner = Callable[[Path], PassCounts]


def _copy_source_into_slot(source_skill_dir: Path, target_slot_dir: Path) -> None:
    target_slot_dir.mkdir(parents=True, exist_ok=True)
    if source_skill_dir.is_dir():
        for child in source_skill_dir.iterdir():
            dest = target_slot_dir / child.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            if child.is_dir():
                shutil.copytree(child, dest)
            else:
                shutil.copy(child, dest)
    else:
        # Single-file source: replace the slot's SKILL.md with it.
        dest = target_slot_dir / "SKILL.md"
        shutil.copy(source_skill_dir, dest)


def run_transfer(
    *,
    source_skill_dir: Path,
    target_slot_dir: Path,
    run_target_tests: TestRunner,
) -> TransferReport:
    """Run target tests once for the baseline, copy source over, run again,
    return TransferReport.
    """
    passed_before, total_before = run_target_tests(target_slot_dir)
    _copy_source_into_slot(source_skill_dir, target_slot_dir)
    passed_after, total_after = run_target_tests(target_slot_dir)

    # Use the post-copy total as the canonical denominator.
    return TransferReport(
        pass_before=passed_before,
        pass_after=passed_after,
        total=total_after,
        delta=passed_after - passed_before,
    )
