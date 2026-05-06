"""Tasks 7.2–7.6 — v0.7 Mission Control template render tests.

Renders each new fragment with stubbed snapshot data and asserts the
DOM contains the expected anchors (data attributes, ids, labels).
Drives the SSE OOB-swap pipeline shape from above.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# jinja2 is in the [ui] extras; skip gracefully when not installed.
jinja2 = pytest.importorskip("jinja2")
Environment = jinja2.Environment
FileSystemLoader = jinja2.FileSystemLoader
select_autoescape = jinja2.select_autoescape

from skill_forge.dashboard.state import (
    FrontierEntryView,
    LineageView,
    SparklinePoint,
    WorkerView,
)


def _env() -> Environment:
    templates = Path(__file__).resolve().parents[1] / "src" / "skill_forge" / "dashboard" / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True, lstrip_blocks=True,
    )


def test_lineage_renders_baseline_and_versions() -> None:
    env = _env()
    out = env.get_template("_lineage.html").render(
        generations=[
            LineageView(label="baseline", score=0.0, parent=""),
            LineageView(label="v1", score=0.55, parent="baseline"),
            LineageView(label="v2", score=0.72, parent="v1"),
            LineageView(label="v3", score=0.81, parent="v2"),
        ],
    )
    assert 'id="lineage"' in out
    assert 'data-lineage-label="baseline"' in out
    assert 'data-lineage-label="v3"' in out
    assert "0.81" in out
    assert "lineage-current" in out  # last node marked


def test_frontier_renders_top_k_cards_with_parent_arrow() -> None:
    env = _env()
    out = env.get_template("_frontier.html").render(
        frontier=[
            FrontierEntryView(id="g0-w0", score=0.50, parent="baseline", active=False),
            FrontierEntryView(id="g1-w0", score=0.62, parent="g0-w0", active=True),
            FrontierEntryView(id="g2-w1", score=0.78, parent="g1-w0", active=False),
        ],
    )
    assert 'id="frontier"' in out
    assert 'data-frontier-id="g2-w1"' in out
    assert 'data-frontier-parent="g1-w0"' in out
    assert "frontier-active-pulse" in out
    assert "0.780" in out


def test_frontier_empty_state() -> None:
    env = _env()
    out = env.get_template("_frontier.html").render(frontier=[])
    assert "frontier is empty" in out


def test_sparkline_renders_polyline_when_2_plus_points() -> None:
    env = _env()
    out = env.get_template("_sparkline.html").render(
        sparkline=[SparklinePoint(t=0, score=0.4), SparklinePoint(t=1, score=0.55),
                   SparklinePoint(t=2, score=0.72)],
    )
    assert "<polyline" in out
    assert 'data-spark-t="2"' in out
    assert 'data-spark-score="0.720"' in out


def test_sparkline_empty_when_under_2_points() -> None:
    env = _env()
    out = env.get_template("_sparkline.html").render(sparkline=[SparklinePoint(t=0, score=0.4)])
    assert "needs 2+ generations" in out


def test_strategy_chips_take_first_word_of_proposed_skill() -> None:
    env = _env()
    workers = [
        WorkerView(id="w0", last_proposal={
            "action": "edit", "target_skill": "greeter",
            "proposed_skill": "Tighten JSON envelope schema",
            "justification": "x"}),
        WorkerView(id="w1"),  # no last_proposal
    ]
    out = env.get_template("_strategy_chips.html").render(workers=workers)
    assert 'data-worker-id="w0"' in out
    assert "Tighten" in out
    # w1 has no proposal — empty chip
    assert "strategy-chip-empty" in out


def test_why_rail_renders_per_worker_panels_with_data_anchors() -> None:
    env = _env()
    workers = [
        WorkerView(id="w0", last_proposal={
            "action": "edit", "target_skill": "greeter",
            "proposed_skill": "Add explicit envelope spec",
            "justification": "Test asserts schema match."}),
        WorkerView(id="w1"),
    ]
    out = env.get_template("_why_rail.html").render(workers=workers)
    assert 'id="why-rail"' in out
    assert 'data-worker-id="w0"' in out
    assert "Add explicit envelope spec" in out
    assert "Test asserts schema match." in out
    # Worker without proposal
    assert 'data-worker-id="w1"' in out
    assert "no proposal yet" in out
