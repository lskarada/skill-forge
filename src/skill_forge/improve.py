"""One-call orchestrator: capture → optimize.

Threads `run_capture` and `run_optimize` together with friction-free
defaults so `forge improve` is the daily happy path. The orchestrator
itself is small — all real logic lives in capture.py and optimize.py;
this file is glue + sane defaults.

State machine:
    capture.outcome == "approved"     → optimize runs
    capture.outcome == "escape_hatch" → optimize runs (escape-hatch test
                                        is still a real regression test)
    capture.outcome == "rejected"     → exit 1, optimize NOT called
    capture.outcome == "skipped"      → exit 1, optimize NOT called
    capture.outcome == "dsl_gap_noted"→ exit 1, optimize NOT called
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from skill_forge import capture as cap_mod
from skill_forge import dispatch
from skill_forge import optimize as opt_mod
from skill_forge import transcript as tx
from skill_forge.prompts import DEFAULT_MUTATION_STRATEGY


PROCEED_OUTCOMES = {"approved", "escape_hatch"}


@dataclass
class ImproveConfig:
    """Composes CaptureConfig + OptimizeConfig. Friction-free defaults
    apply unless the caller explicitly disables them."""

    target: str | None = None
    repo_path: Path = field(default_factory=Path.cwd)
    output_root: Path = field(default_factory=lambda: Path.cwd() / ".skill-forge")
    num_workers: int = 3
    assume_yes: bool = True
    ui: bool = True
    open_browser: bool = True
    ui_grace: int = 300
    port: int | None = None
    strategy: str = DEFAULT_MUTATION_STRATEGY
    strategies: list[str] | None = None
    tests_dir: Path | None = None
    # Capture-side knobs:
    projects_dir: Path = field(default_factory=lambda: tx.DEFAULT_PROJECTS_DIR)
    cwd: Path = field(default_factory=Path.cwd)
    transcript_path: Path | None = None
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(timezone.utc)
    )


@dataclass
class ImproveIO:
    printer: Callable[[str], None]
    prompter: Callable[[str], str]
    # Injectable seams: tests pass fakes; CLI passes the real funcs.
    run_capture: Callable[..., cap_mod.CaptureResult] = cap_mod.run_capture
    run_optimize: Callable[..., opt_mod.OptimizeResult] = opt_mod.run_optimize


@dataclass
class ImproveResult:
    capture_outcome: str
    optimize_outcome: str | None = None
    skill: str | None = None
    test_path: Path | None = None
    evidence_path: Path | None = None
    merge_sha: str | None = None
    exit_code: int = 0


def run_improve(config: ImproveConfig, io: ImproveIO) -> ImproveResult:
    """Drive capture, then optimize on the captured skill."""
    # ---- Phase 1: capture -------------------------------------------------
    cap_config = cap_mod.CaptureConfig(
        projects_dir=config.projects_dir,
        cwd=config.cwd,
        output_root=config.output_root,
        target=config.target,
        assume_yes=config.assume_yes,
        transcript_path=config.transcript_path,
        now=config.now,
    )
    cap_io = cap_mod.CaptureIO(
        printer=io.printer,
        prompter=io.prompter,
        dispatcher=dispatch.draft_capture,
    )
    cap_result = io.run_capture(cap_config, cap_io)

    if cap_result.outcome not in PROCEED_OUTCOMES:
        io.printer(
            f"capture {cap_result.outcome!r} — not running optimize. "
            f"Re-run `forge improve` once the failure is captured."
        )
        return ImproveResult(
            capture_outcome=cap_result.outcome,
            skill=cap_result.skill_name,
            test_path=cap_result.test_path,
            exit_code=1,
        )

    skill = cap_result.skill_name
    if not skill:
        io.printer("capture returned no skill name — cannot run optimize.")
        return ImproveResult(
            capture_outcome=cap_result.outcome,
            test_path=cap_result.test_path,
            exit_code=1,
        )

    # ---- Phase 2: optimize ------------------------------------------------
    opt_config = opt_mod.OptimizeConfig(
        skill=skill,
        repo_path=config.repo_path,
        output_root=config.output_root,
        tests_dir=config.tests_dir,
        strategy=config.strategy,
        assume_yes=config.assume_yes,
        num_workers=config.num_workers,
        strategies=config.strategies,
        now=config.now,
    )
    opt_io = opt_mod.OptimizeIO(
        printer=io.printer,
        prompter=io.prompter,
    )
    opt_result = io.run_optimize(opt_config, opt_io)

    return ImproveResult(
        capture_outcome=cap_result.outcome,
        optimize_outcome=opt_result.outcome,
        skill=skill,
        test_path=cap_result.test_path,
        evidence_path=opt_result.evidence_path,
        merge_sha=opt_result.merge_sha,
        exit_code=0 if opt_result.outcome in {"merged", "no_change"} else 1,
    )
