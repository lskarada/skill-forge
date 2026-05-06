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
from skill_forge.improve import ImproveConfig, ImproveIO, run_improve
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
    ui: bool = typer.Option(
        False,
        "--ui",
        help="Boot a localhost web dashboard that streams the run. Requires "
        "the [ui] extras: pip install 'skill-forge[ui]'.",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="With --ui, open the dashboard in the default browser. Off by "
        "default to avoid stealing focus on macOS.",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="With --ui, bind to this port instead of auto-picking 7777-7799.",
    ),
    ui_grace: int = typer.Option(
        300,
        "--ui-grace",
        min=0,
        help="With --ui --yes, keep the dashboard alive for this many seconds "
        "after RunFinished so you can inspect drilldowns. Default 300s.",
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

    server = None
    if ui:
        server = _start_dashboard_or_exit(output_root, port)
        typer.echo(f"dashboard: http://127.0.0.1:{server.port}")
        if open_browser:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{server.port}")
        # State knows where to find sidecar artifacts for drilldowns.
        from skill_forge.dashboard import state as state_mod
        state_mod.get_state().sidecar_root = output_root  # type: ignore[attr-defined]

    try:
        result = run_optimize(config, io)
    finally:
        if server is not None:
            _shutdown_dashboard(server, assume_yes=yes, grace=ui_grace)

    if result.outcome in {"regression", "aborted"}:
        raise typer.Exit(code=1)


def _start_dashboard_or_exit(output_root: Path, port: int | None):
    """Boot the dashboard, exit cleanly with a friendly error on missing
    extras or an exhausted port range. Never let a traceback leak."""
    from skill_forge.dashboard import DashboardExtrasMissing, require_web_extras
    try:
        require_web_extras()
    except DashboardExtrasMissing as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    from skill_forge.dashboard import server as srv
    try:
        chosen = port if port is not None else srv.pick_free_port()
    except srv.PortRangeExhausted as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2)

    s = srv.DashboardServer(port=chosen)
    s.start()
    srv.write_port_file(output_root, s.port)
    return s


def _shutdown_dashboard(server, *, assume_yes: bool, grace: int) -> None:
    """In --yes mode, hold the server alive for `grace` seconds so the
    user can drill into a finished run. Without --yes, the foreground
    `forge optimize` call already blocked on a prompt — the run is
    interactive, so just stop the server and exit."""
    import time
    if assume_yes and grace > 0:
        typer.echo(
            f"dashboard alive for {grace}s; Ctrl-C to exit immediately."
        )
        try:
            time.sleep(grace)
        except KeyboardInterrupt:
            pass
    server.stop()


@app.command()
def improve(
    target: str | None = typer.Option(
        None,
        "--target",
        help="Path to the SUT markdown file (e.g., .claude/skills/<name>/SKILL.md). "
        "If omitted, the capture agent infers the skill from the transcript.",
    ),
    workers: int = typer.Option(
        3,
        "--workers",
        "-w",
        min=1,
        max=16,
        help="Number of parallel mutation workers. Default 3.",
    ),
    output_root: Path = typer.Option(
        Path.cwd() / ".skill-forge",
        "--output-root",
        help="Root for runs/, history/, learnings.md (default: ./.skill-forge).",
    ),
    yes: bool = typer.Option(
        True,
        "--yes/--no-yes",
        "-y",
        help="Auto-confirm both capture-approval and mutation prompts. "
        "Default ON for friction-free runs; pass --no-yes to confirm interactively.",
    ),
    ui: bool = typer.Option(
        True,
        "--ui/--no-ui",
        help="Boot the live web dashboard. Default ON. Pass --no-ui for headless.",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="With --ui, open the dashboard in the default browser. Default ON.",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="With --ui, bind to this port instead of auto-picking 7777-7799.",
    ),
    ui_grace: int = typer.Option(
        300,
        "--ui-grace",
        min=0,
        help="Seconds to keep the dashboard alive after RunFinished. Default 300s.",
    ),
    projects_dir: Path = typer.Option(
        tx.DEFAULT_PROJECTS_DIR,
        "--projects-dir",
        help="Override the Claude Code projects directory.",
    ),
    transcript: Path | None = typer.Option(
        None,
        "--transcript",
        help="Use this specific transcript JSONL instead of auto-selecting the latest.",
    ),
) -> None:
    """One-call workflow: capture the latest failure, then mutate-tournament the inferred skill."""
    config = ImproveConfig(
        target=target,
        repo_path=Path.cwd(),
        output_root=output_root,
        num_workers=workers,
        assume_yes=yes,
        ui=ui,
        open_browser=open_browser,
        ui_grace=ui_grace,
        port=port,
        projects_dir=projects_dir,
        cwd=Path.cwd(),
        transcript_path=transcript,
    )

    server = None
    if ui:
        server = _start_dashboard_or_exit(output_root, port)
        typer.echo(f"dashboard: http://127.0.0.1:{server.port}")
        if open_browser:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{server.port}")
        from skill_forge.dashboard import state as state_mod
        state_mod.get_state().sidecar_root = output_root  # type: ignore[attr-defined]

    io = ImproveIO(
        printer=typer.echo,
        prompter=lambda msg: typer.prompt(msg.rstrip(), default="", show_default=False),
    )
    try:
        result = run_improve(config, io)
    finally:
        if server is not None:
            _shutdown_dashboard(server, assume_yes=yes, grace=ui_grace)

    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)


@app.command()
def evolve(
    skill: str = typer.Argument(
        ...,
        help="Skill name (looked up in .claude/skills/<skill>/SKILL.md).",
    ),
    generations: int = typer.Option(
        3, "--generations", "-g", min=1, max=20,
        help="Number of evolution generations (default: 3).",
    ),
    frontier_size: int = typer.Option(
        3, "--frontier-size", min=1, max=10,
        help="Top-K Pareto frontier size (default: 3, paper §D).",
    ),
    workers: int = typer.Option(
        3, "--workers", "-w", min=1, max=16,
        help="Mutation workers per generation (default: 3).",
    ),
    patience: int = typer.Option(
        2, "--patience", min=1, max=10,
        help="Stop after this many stagnant generations (default: 2).",
    ),
) -> None:
    """v0.5: Run a multi-generation Pareto-frontier evolution against `skill`.

    Wraps the v0.4 single-gen mutation loop. Frontier is persisted as
    git tags `frontier/<skill>/g<N>-w<W>` (see git_tags.py); each entry
    has a sibling program.yaml. Use `git tag -l 'frontier/<skill>/*'`
    after the run to inspect surviving programs.
    """
    from skill_forge import evolve as evolve_mod

    def _no_op_one_gen(*, skill, gen_index, parent, k, workers_per_gen, repo_lock):
        # v0.5 default: real mutation dispatch lands when the optimize.py
        # extraction is wired (Task 5.7 staging tier). For now the CLI is
        # exercisable end-to-end with stubbed dispatch via monkeypatch.
        return []

    result = evolve_mod.run_evolution(
        skill=skill,
        generations=generations,
        frontier_size=frontier_size,
        workers_per_gen=workers,
        patience=patience,
        run_one_generation=_no_op_one_gen,
    )
    typer.echo(
        f"evolve: gens={result.generations_run} "
        f"early_stopped={result.early_stopped} "
        f"winner={result.winner.id if result.winner else None}"
    )


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
