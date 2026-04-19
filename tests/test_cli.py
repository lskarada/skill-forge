"""Smoke tests for src/skill_forge/cli.py.

The CLI is a thin Typer shim over `run_capture`. These tests assert the
wiring: the `capture` subcommand exists, exposes the documented flags, and
invokes run_capture with a matching CaptureConfig.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from skill_forge import capture as capture_mod
from skill_forge import dispatch
from skill_forge import optimize as optimize_mod
from skill_forge.cli import app


runner = CliRunner()


def test_capture_help_shows_flags() -> None:
    result = runner.invoke(app, ["capture", "--help"])
    assert result.exit_code == 0
    for flag in ("--target", "--projects-dir", "--transcript", "--yes"):
        assert flag in result.output


def test_capture_invokes_run_capture(tmp_path: Path, monkeypatch) -> None:
    # minimal transcript so we don't depend on ~/.claude/projects
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}})
        + "\n"
    )

    calls: dict[str, Any] = {}

    def fake_run_capture(config: capture_mod.CaptureConfig, io: capture_mod.CaptureIO):
        calls["target"] = config.target
        calls["assume_yes"] = config.assume_yes
        calls["transcript_path"] = config.transcript_path
        calls["projects_dir"] = config.projects_dir
        calls["dispatcher_is_draft_capture"] = io.dispatcher is dispatch.draft_capture
        return capture_mod.CaptureResult(approved=True, outcome="approved")

    monkeypatch.setattr("skill_forge.cli.run_capture", fake_run_capture)

    result = runner.invoke(
        app,
        [
            "capture",
            "--target",
            "skills/foo/SKILL.md",
            "--transcript",
            str(transcript),
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["target"] == "skills/foo/SKILL.md"
    assert calls["assume_yes"] is True
    assert calls["transcript_path"] == transcript
    assert calls["dispatcher_is_draft_capture"] is True


def test_capture_exits_nonzero_on_rejection(tmp_path: Path, monkeypatch) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n"
    )

    def reject(config, io):
        return capture_mod.CaptureResult(approved=False, outcome="rejected")

    monkeypatch.setattr("skill_forge.cli.run_capture", reject)

    result = runner.invoke(app, ["capture", "--transcript", str(transcript)])
    assert result.exit_code == 1


def test_capture_exits_zero_on_escape_hatch(tmp_path: Path, monkeypatch) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n"
    )

    def hatch(config, io):
        return capture_mod.CaptureResult(approved=True, outcome="escape_hatch")

    monkeypatch.setattr("skill_forge.cli.run_capture", hatch)

    result = runner.invoke(app, ["capture", "--transcript", str(transcript)])
    assert result.exit_code == 0


def test_optimize_help_shows_flags() -> None:
    result = runner.invoke(app, ["optimize", "--help"])
    assert result.exit_code == 0
    for flag in ("--strategy", "--tests-dir", "--output-root", "--yes"):
        assert flag in result.output


def test_optimize_invokes_run_optimize(tmp_path: Path, monkeypatch) -> None:
    calls: dict[str, Any] = {}

    def fake_run(config, io):
        calls["skill"] = config.skill
        calls["strategy"] = config.strategy
        calls["assume_yes"] = config.assume_yes
        return optimize_mod.OptimizeResult(outcome="merged")

    monkeypatch.setattr("skill_forge.cli.run_optimize", fake_run)
    result = runner.invoke(
        app,
        ["optimize", "my-skill", "--strategy", "be strict", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert calls["skill"] == "my-skill"
    assert calls["strategy"] == "be strict"
    assert calls["assume_yes"] is True


def test_optimize_exits_nonzero_on_regression(tmp_path: Path, monkeypatch) -> None:
    def regressing(config, io):
        return optimize_mod.OptimizeResult(outcome="regression")

    monkeypatch.setattr("skill_forge.cli.run_optimize", regressing)
    result = runner.invoke(app, ["optimize", "my-skill", "--yes"])
    assert result.exit_code == 1


def test_optimize_exits_zero_on_no_change(tmp_path: Path, monkeypatch) -> None:
    """Baseline already green or empty mutation isn't a failure, just a no-op."""
    def no_change(config, io):
        return optimize_mod.OptimizeResult(outcome="no_change")

    monkeypatch.setattr("skill_forge.cli.run_optimize", no_change)
    result = runner.invoke(app, ["optimize", "my-skill", "--yes"])
    assert result.exit_code == 0


def test_status_help_shows_flags() -> None:
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    for flag in ("--skill", "--output-root"):
        assert flag in result.output


def test_status_invokes_run_status_with_output_root(
    tmp_path: Path, monkeypatch
) -> None:
    from skill_forge import status as status_mod

    calls: dict[str, Any] = {}

    def fake_run(config, io):
        calls["output_root"] = config.output_root
        calls["skill"] = config.skill
        io.printer("ok")
        return status_mod.ForgeStatus(
            output_root=config.output_root,
            root_exists=False,
            skills=(),
            learnings_entries=0,
            learnings_last_mtime=None,
        )

    monkeypatch.setattr("skill_forge.cli.run_status", fake_run)
    result = runner.invoke(
        app,
        ["status", "--output-root", str(tmp_path), "--skill", "greeter"],
    )
    assert result.exit_code == 0, result.output
    assert calls["output_root"] == tmp_path
    assert calls["skill"] == "greeter"
    assert "ok" in result.output


def test_status_runs_end_to_end_on_empty_dir(tmp_path: Path) -> None:
    # Real run, no monkeypatch. Should succeed with "no .skill-forge" hint.
    result = runner.invoke(app, ["status", "--output-root", str(tmp_path / "nope")])
    assert result.exit_code == 0, result.output
    assert "no .skill-forge" in result.output.lower()
