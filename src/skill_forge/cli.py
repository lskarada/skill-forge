"""Typer entry point for the `forge` binary.

Registered as `forge = "skill_forge.cli:app"` in pyproject.toml.
Subcommands shipped so far:
  - `capture`  (M1)   — turn the last failure into a regression test.
  - `optimize` (M2+M3) — baseline → mutate → gate → merge winner.
  - `status`   (M4)   — read-only summary of tracked skills and runs.
"""

from __future__ import annotations

from pathlib import Path

import typer

from skill_forge.capture import CaptureConfig, CaptureIO, run_capture
from skill_forge.optimize import OptimizeConfig, OptimizeIO, run_optimize
from skill_forge.prompts import DEFAULT_MUTATION_STRATEGY
from skill_forge.status import StatusConfig, StatusIO, run_status
from skill_forge import dispatch, transcript as tx

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Skill-Forge — test, mutate, and merge improvements to Claude Code skills.",
)


@app.callback()
def _root() -> None:
    # Presence of a callback forces Typer to keep subcommands as subcommands
    # even when there's only one, so `forge capture` stays the public spelling.
    pass


@app.command()
def capture(
    target: str | None = typer.Option(
        None,
        "--target",
        help="Path to the SUT markdown file (e.g., .claude/skills/<name>/SKILL.md). "
        "If omitted, the capture agent infers the skill from the transcript.",
    ),
    projects_dir: Path = typer.Option(
        tx.DEFAULT_PROJECTS_DIR,
        "--projects-dir",
        help="Override the Claude Code projects directory (default: ~/.claude/projects).",
    ),
    transcript: Path | None = typer.Option(
        None,
        "--transcript",
        help="Use this specific transcript JSONL instead of auto-selecting the latest.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Auto-approve the drafted test. Intended for dogfooding / scripted runs.",
    ),
) -> None:
    """Capture the most recent failure and write a regression test."""
    config = CaptureConfig(
        projects_dir=projects_dir,
        cwd=Path.cwd(),
        output_root=Path.cwd() / ".skill-forge",
        target=target,
        assume_yes=yes,
        transcript_path=transcript,
    )
    io = CaptureIO(
        printer=typer.echo,
        prompter=lambda msg: typer.prompt(msg.rstrip(), default="", show_default=False),
        dispatcher=dispatch.draft_capture,
    )
    result = run_capture(config, io)
    if not result.approved and result.outcome in {"rejected", "skipped"}:
        raise typer.Exit(code=1)


@app.command()
def optimize(
    skill: str = typer.Argument(
        ...,
        help="Skill name (looked up in .claude/skills/<skill>/SKILL.md).",
    ),
    strategy: str = typer.Option(
        DEFAULT_MUTATION_STRATEGY,
        "--strategy",
        help="Strategy directive passed to the mutation subagent.",
    ),
    tests_dir: Path | None = typer.Option(
        None,
        "--tests-dir",
        help="Override test directory (default: .skill-forge/tests/<skill>).",
    ),
    output_root: Path = typer.Option(
        Path.cwd() / ".skill-forge",
        "--output-root",
        help="Root for runs/, history/, learnings.md (default: ./.skill-forge).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Auto-confirm mutation prompts.",
    ),
    workers: int = typer.Option(
        1,
        "--workers",
        "-w",
        min=1,
        max=16,
        help="Number of parallel mutation workers (M3). Default 1 = serial.",
    ),
    strategies: list[str] | None = typer.Option(
        None,
        "--strategies",
        help="Explicit strategy directive per worker. Repeat the flag once per "
        "strategy. If fewer strategies than workers, the list is cycled. "
        "If omitted, Skill-Forge uses the built-in default rotation.",
    ),
) -> None:
    """Run one baseline → mutate → gate → merge/discard cycle on a skill."""
    config = OptimizeConfig(
        skill=skill,
        repo_path=Path.cwd(),
        output_root=output_root,
        tests_dir=tests_dir,
        strategy=strategy,
        assume_yes=yes,
        num_workers=workers,
        strategies=list(strategies) if strategies else None,
    )
    io = OptimizeIO(
        printer=typer.echo,
        prompter=lambda msg: typer.prompt(msg.rstrip(), default="", show_default=False),
    )
    result = run_optimize(config, io)
    if result.outcome in {"regression", "aborted"}:
        raise typer.Exit(code=1)


@app.command()
def status(
    skill: str | None = typer.Option(
        None,
        "--skill",
        help="Limit the report to one skill. If omitted, all tracked skills are listed.",
    ),
    output_root: Path = typer.Option(
        Path.cwd() / ".skill-forge",
        "--output-root",
        help="Root that contains tests/, history/, learnings.md (default: ./.skill-forge).",
    ),
) -> None:
    """Show tracked skills, test counts, merged runs, and learnings."""
    config = StatusConfig(output_root=output_root, skill=skill)
    io = StatusIO(printer=typer.echo)
    run_status(config, io)


if __name__ == "__main__":
    app()
