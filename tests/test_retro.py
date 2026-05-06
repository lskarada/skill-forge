"""Task 8.8 — retro.run orchestrator (pain → attribution → synthesis → campaign)."""
from __future__ import annotations

from pathlib import Path

from skill_forge import retro
from skill_forge.attribution import SkillAttribution
from skill_forge.campaign import Portfolio, PortfolioEntry
from skill_forge.pain import PainSession


def test_retro_pipes_pain_through_attribution_synthesis_campaign(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    fake_pain = PainSession(turns=[], error_signatures=set(),
                            changed_files=set(), user_complaint_phrases=[])
    monkeypatch.setattr(retro.pain_mod, "ingest",
                        lambda *_a, **_kw: (calls.append("ingest") or fake_pain))

    fake_attrs = [SkillAttribution("greeter", "high", "ev"),
                  SkillAttribution("scribe", "high", "ev")]
    monkeypatch.setattr(retro.attribution_mod, "attribute",
                        lambda *_a, **_kw: (calls.append("attribute") or fake_attrs))

    fake_portfolio = Portfolio(entries=[
        PortfolioEntry("greeter", True, "high", 0.85, "merged"),
        PortfolioEntry("scribe", True, "high", 0.78, "merged"),
    ])
    monkeypatch.setattr(retro.campaign_mod, "run_campaign",
                        lambda *_a, **_kw: (calls.append("campaign") or fake_portfolio))

    inventory = {"greeter", "scribe", "data-extraction"}
    portfolio = retro.run(
        transcripts_dir=tmp_path,
        git_diff_path=None,
        skills_inventory=inventory,
        generations=2,
        frontier_size=2,
        workers_per_skill=1,
        patience=2,
        min_confidence="medium",
    )

    assert calls == ["ingest", "attribute", "campaign"]
    assert portfolio is fake_portfolio


def test_retro_short_circuits_on_empty_attribution(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(retro.pain_mod, "ingest",
                        lambda *_a, **_kw: PainSession([], set(), set(), []))
    monkeypatch.setattr(retro.attribution_mod, "attribute", lambda *_a, **_kw: [])
    called = []
    monkeypatch.setattr(retro.campaign_mod, "run_campaign",
                        lambda *_a, **_kw: called.append(1) or Portfolio([]))

    portfolio = retro.run(
        transcripts_dir=tmp_path, git_diff_path=None,
        skills_inventory={"greeter"},
        generations=1, frontier_size=1, workers_per_skill=1, patience=1,
    )
    # Empty attribution → still call campaign with []; portfolio has no entries.
    assert portfolio.entries == []
