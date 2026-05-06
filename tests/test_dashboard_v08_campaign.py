"""Task 8.9 — _campaign.html + _synthesis_rejects.html render tests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")
Environment = jinja2.Environment
FileSystemLoader = jinja2.FileSystemLoader
select_autoescape = jinja2.select_autoescape


def _env() -> Environment:
    templates = Path(__file__).resolve().parents[1] / "src" / "skill_forge" / "dashboard" / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True, lstrip_blocks=True,
    )


@dataclass
class _Reject:
    reason: str
    path: str


@dataclass
class _Entry:
    skill: str
    accepted: bool
    confidence: str
    score: float
    reason: str
    synthesis_rejects: list[_Reject] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.synthesis_rejects is None:
            self.synthesis_rejects = []


@dataclass
class _Campaign:
    entries: list[_Entry]


def test_campaign_view_renders_one_panel_per_skill() -> None:
    env = _env()
    campaign = _Campaign(entries=[
        _Entry("greeter", True, "high", 0.85, "winner=g1-w0"),
        _Entry("scribe", True, "medium", 0.78, "winner=g1-w0"),
    ])
    out = env.get_template("_campaign.html").render(campaign=campaign)
    assert 'id="campaign"' in out
    assert 'data-skill="greeter"' in out
    assert 'data-skill="scribe"' in out
    assert "campaign-conf-high" in out
    assert "campaign-conf-medium" in out


def test_campaign_panel_shows_rejection_reason() -> None:
    env = _env()
    campaign = _Campaign(entries=[
        _Entry("dim", False, "low", 0.0, "no synthesizable tests admitted"),
    ])
    out = env.get_template("_campaign.html").render(campaign=campaign)
    assert "no synthesizable tests admitted" in out


def test_synthesis_rejects_pane_renders_count_and_links() -> None:
    env = _env()
    entry = _Entry(
        "scribe", True, "high", 0.7, "merged",
        synthesis_rejects=[
            _Reject("failed validator", ".skill-forge/synthesis_rejects/scribe/x_validator.py"),
            _Reject("passed baseline 2/5", ".skill-forge/synthesis_rejects/scribe/x_flaky.py"),
        ],
    )
    out = env.get_template("_synthesis_rejects.html").render(entry=entry)
    assert "2 synthesis rejects" in out
    assert "failed validator" in out
    assert "passed baseline 2/5" in out


def test_synthesis_rejects_pane_empty_state() -> None:
    env = _env()
    entry = _Entry("greeter", True, "high", 0.7, "merged", synthesis_rejects=[])
    out = env.get_template("_synthesis_rejects.html").render(entry=entry)
    assert "All synthesized tests admitted." in out
