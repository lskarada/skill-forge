"""Wiring test for forge retro — NOT a product test.

Every subagent dispatch is stubbed. This test proves the
pain.ingest → attribution.attribute → synthesis.synthesize_test →
campaign.run_campaign pipeline is wired correctly and emits a
Portfolio with the right shape. It does NOT prove that real
subagent responses produce useful skill mutations — that gate
lives in Task 8.11 / v0.8 Gate 4 (real-API).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from skill_forge import campaign as campaign_mod
from skill_forge import retro
from skill_forge.attribution import SkillAttribution
from skill_forge.evolve import EvolutionResult
from skill_forge.frontier import FrontierEntry

pytestmark = pytest.mark.fresh_install

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "rough_session"


def test_retro_pipeline_emits_two_entry_portfolio(monkeypatch) -> None:
    # Inventory contains greeter + scribe (the two fixture-attributed skills).
    inventory = {"greeter", "scribe", "data-extraction"}

    # Stub run_evolution to return a winning entry per skill.
    def fake_run_evolution(*, skill, **_kw):
        winner = FrontierEntry(id=f"g0-{skill}", score=0.85, skill_len=120)
        return EvolutionResult(
            skill=skill,
            frontier=[winner],
            winner=winner,
            generations_run=1,
            early_stopped=False,
        )
    monkeypatch.setattr(campaign_mod.evolve_mod, "run_evolution", fake_run_evolution)

    portfolio = retro.run(
        transcripts_dir=FIXTURE,
        git_diff_path=FIXTURE / "git.diff",
        skills_inventory=inventory,
        generations=1,
        frontier_size=1,
        workers_per_skill=1,
        patience=1,
        min_confidence="high",  # both fixture skills are literal-invocation = high
    )

    # Plumbing assertions.
    assert len(portfolio.entries) == 2
    assert {e.skill for e in portfolio.entries} == {"greeter", "scribe"}
    assert all(e.accepted for e in portfolio.entries)
    assert all(e.confidence == "high" for e in portfolio.entries)
