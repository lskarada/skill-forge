"""Task 7.1 — Mission Control state types: LineageView, FrontierEntryView, SparklinePoint."""
from __future__ import annotations

from skill_forge.dashboard.state import (
    FrontierEntryView,
    LineageView,
    RunState,
    SparklinePoint,
)


def test_lineage_view_has_required_fields() -> None:
    lv = LineageView(label="v3", score=0.82, parent="v2")
    assert lv.label == "v3"
    assert lv.score == 0.82
    assert lv.parent == "v2"


def test_frontier_entry_view_has_required_fields() -> None:
    fe = FrontierEntryView(id="g1-w0", score=0.75, parent="g0-w0", active=True)
    assert fe.id == "g1-w0"
    assert fe.score == 0.75
    assert fe.parent == "g0-w0"
    assert fe.active is True


def test_sparkline_point_has_required_fields() -> None:
    sp = SparklinePoint(t=3, score=0.6)
    assert sp.t == 3
    assert sp.score == 0.6


def test_run_state_has_generations_and_frontier_lists() -> None:
    state = RunState()
    assert hasattr(state, "generations")
    assert state.generations == []
    assert hasattr(state, "frontier")
    assert state.frontier == []
