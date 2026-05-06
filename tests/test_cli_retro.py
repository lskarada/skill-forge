"""Task 8.9 — `forge retro` CLI smoke tests."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from skill_forge import cli, retro as retro_mod
from skill_forge.campaign import Portfolio, PortfolioEntry


def test_forge_retro_dispatches_with_expected_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(*, transcripts_dir, git_diff_path, skills_inventory,
                 generations, frontier_size, workers_per_skill, patience,
                 min_confidence, **kw):
        captured.update(
            transcripts_dir=transcripts_dir,
            generations=generations, workers_per_skill=workers_per_skill,
            min_confidence=min_confidence,
        )
        return Portfolio(entries=[
            PortfolioEntry("greeter", True, "high", 0.85, "merged"),
            PortfolioEntry("scribe", True, "high", 0.78, "merged"),
        ])

    monkeypatch.setattr(retro_mod, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["retro", "--pain-from", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert captured["generations"] == 2
    assert captured["workers_per_skill"] == 3
    assert captured["min_confidence"] == "low"
    assert "greeter" in result.output
    assert "scribe" in result.output


def test_forge_retro_kill_on_no_pidfile_reports_no_run(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["retro", "--kill"])
    assert result.exit_code == 0
    assert "no background run" in result.output
