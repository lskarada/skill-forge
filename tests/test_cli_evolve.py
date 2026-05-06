"""Task 5.6 — `forge evolve <skill>` CLI subcommand."""
from __future__ import annotations

from typer.testing import CliRunner

from skill_forge import cli, evolve as evolve_mod
from skill_forge.evolve import EvolutionResult
from skill_forge.frontier import FrontierEntry


def test_forge_evolve_dispatches_with_expected_defaults(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_evolution(*, skill, generations, frontier_size, workers_per_gen, patience, **kwargs):
        captured["skill"] = skill
        captured["generations"] = generations
        captured["frontier_size"] = frontier_size
        captured["workers_per_gen"] = workers_per_gen
        captured["patience"] = patience
        return EvolutionResult(
            skill=skill,
            frontier=[FrontierEntry(id="g0-w0", score=0.7, skill_len=100)],
            winner=FrontierEntry(id="g0-w0", score=0.7, skill_len=100),
            generations_run=generations,
            early_stopped=False,
        )

    monkeypatch.setattr(evolve_mod, "run_evolution", fake_run_evolution)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["evolve", "greeter"])

    assert result.exit_code == 0, result.output
    assert captured["skill"] == "greeter"
    assert captured["generations"] == 3
    assert captured["frontier_size"] == 3
    assert captured["workers_per_gen"] == 3
    assert captured["patience"] == 2


def test_forge_evolve_overrides_defaults_via_flags(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_evolution(*, skill, generations, frontier_size, workers_per_gen, patience, **kwargs):
        captured.update(skill=skill, generations=generations,
                        frontier_size=frontier_size, workers_per_gen=workers_per_gen,
                        patience=patience)
        return EvolutionResult(skill=skill, frontier=[], winner=None,
                               generations_run=0, early_stopped=False)

    monkeypatch.setattr(evolve_mod, "run_evolution", fake_run_evolution)

    runner = CliRunner()
    result = runner.invoke(cli.app, [
        "evolve", "greeter",
        "--generations", "5",
        "--frontier-size", "2",
        "--workers", "4",
        "--patience", "1",
    ])

    assert result.exit_code == 0, result.output
    assert captured["generations"] == 5
    assert captured["frontier_size"] == 2
    assert captured["workers_per_gen"] == 4
    assert captured["patience"] == 1
