"""Read-only status report over a `.skill-forge/` tree.

Invoked from the CLI as `forge status`. Inspects the filesystem only —
never spawns pytest, never spawns a subagent, never writes. The goal is
"tell me what's going on" at a glance, not re-run the regression gate.

Layout assumed (matches optimize.py + capture.py writers):

    .skill-forge/
      tests/<skill>/test_*.py
      history/<skill>/v<N>_evidence.md
      history/<skill>/loss_<ts>_evidence.md
      learnings.md

All paths are treated as optional: a brand-new repo with zero skills
should still print something useful (and exit 0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_OUTPUT_ROOT = ".skill-forge"
_V_EVIDENCE_RE = re.compile(r"^v(\d+)_evidence\.md$")
_LOSS_EVIDENCE_RE = re.compile(r"^loss_.*_evidence\.md$")


@dataclass
class StatusConfig:
    output_root: Path = field(default_factory=lambda: Path.cwd() / DEFAULT_OUTPUT_ROOT)
    skill: str | None = None


@dataclass
class StatusIO:
    printer: Callable[[str], None]


@dataclass(frozen=True)
class SkillStatus:
    name: str
    test_count: int
    test_files: tuple[str, ...]
    version_count: int
    latest_version: int | None
    latest_evidence: Path | None
    latest_evidence_mtime: datetime | None
    loss_run_count: int


@dataclass(frozen=True)
class ForgeStatus:
    output_root: Path
    root_exists: bool
    skills: tuple[SkillStatus, ...]
    learnings_entries: int
    learnings_last_mtime: datetime | None


def collect_status(config: StatusConfig) -> ForgeStatus:
    """Walk the `.skill-forge/` tree and summarize per skill."""
    root = config.output_root
    if not root.is_dir():
        return ForgeStatus(
            output_root=root,
            root_exists=False,
            skills=(),
            learnings_entries=0,
            learnings_last_mtime=None,
        )

    names = _discover_skill_names(root, only=config.skill)
    skills = tuple(_skill_status(root, name) for name in names)

    learnings = root / "learnings.md"
    if learnings.is_file():
        lines = [
            line
            for line in learnings.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        learnings_entries = len(lines)
        learnings_mtime = datetime.fromtimestamp(learnings.stat().st_mtime)
    else:
        learnings_entries = 0
        learnings_mtime = None

    return ForgeStatus(
        output_root=root,
        root_exists=True,
        skills=skills,
        learnings_entries=learnings_entries,
        learnings_last_mtime=learnings_mtime,
    )


def render_status(status: ForgeStatus) -> str:
    """Human-readable status block. Stable enough for tests to grep."""
    lines: list[str] = []
    lines.append(f"Skill-Forge status (root: {status.output_root})")
    if not status.root_exists:
        lines.append("  (no .skill-forge directory yet — run `forge capture` to start.)")
        return "\n".join(lines)

    if not status.skills:
        lines.append("  No skills tracked yet.")
    else:
        lines.append("")
        for s in status.skills:
            lines.append(f"  {s.name}")
            lines.append(f"    tests:    {s.test_count}")
            if s.test_files:
                preview = ", ".join(s.test_files[:5])
                suffix = f", …(+{len(s.test_files) - 5} more)" if len(s.test_files) > 5 else ""
                lines.append(f"              {preview}{suffix}")
            lines.append(f"    history:  {s.version_count} merged, {s.loss_run_count} loss run(s)")
            if s.latest_version is not None and s.latest_evidence_mtime is not None:
                stamp = s.latest_evidence_mtime.strftime("%Y-%m-%d %H:%M")
                lines.append(f"    latest:   v{s.latest_version} ({stamp})")
            else:
                lines.append("    latest:   no merged runs yet")

    lines.append("")
    if status.learnings_last_mtime is not None:
        stamp = status.learnings_last_mtime.strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"Learnings: {status.learnings_entries} entries (last {stamp})"
        )
    else:
        lines.append("Learnings: none yet")

    return "\n".join(lines)


def run_status(config: StatusConfig, io: StatusIO) -> ForgeStatus:
    status = collect_status(config)
    io.printer(render_status(status))
    return status


def _discover_skill_names(root: Path, *, only: str | None) -> list[str]:
    candidates: set[str] = set()
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        candidates.update(p.name for p in tests_dir.iterdir() if p.is_dir())
    history_dir = root / "history"
    if history_dir.is_dir():
        candidates.update(p.name for p in history_dir.iterdir() if p.is_dir())

    if only is not None:
        return [only] if only in candidates else []
    return sorted(candidates)


def _skill_status(root: Path, skill: str) -> SkillStatus:
    tests_dir = root / "tests" / skill
    test_files: list[str] = []
    if tests_dir.is_dir():
        test_files = sorted(p.name for p in tests_dir.glob("test_*.py"))

    history_dir = root / "history" / skill
    versions: list[int] = []
    latest_path: Path | None = None
    loss_runs = 0
    if history_dir.is_dir():
        for p in history_dir.iterdir():
            if not p.is_file():
                continue
            m = _V_EVIDENCE_RE.match(p.name)
            if m:
                versions.append(int(m.group(1)))
                continue
            if _LOSS_EVIDENCE_RE.match(p.name):
                loss_runs += 1

    latest_version: int | None = None
    latest_mtime: datetime | None = None
    if versions:
        latest_version = max(versions)
        latest_path = history_dir / f"v{latest_version}_evidence.md"
        if latest_path.is_file():
            latest_mtime = datetime.fromtimestamp(latest_path.stat().st_mtime)
        else:
            latest_path = None

    return SkillStatus(
        name=skill,
        test_count=len(test_files),
        test_files=tuple(test_files),
        version_count=len(versions),
        latest_version=latest_version,
        latest_evidence=latest_path,
        latest_evidence_mtime=latest_mtime,
        loss_run_count=loss_runs,
    )
