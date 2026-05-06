"""v0.8.1-B2 — _evo_tree.html render test."""
from __future__ import annotations

from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")
Environment = jinja2.Environment
FileSystemLoader = jinja2.FileSystemLoader
select_autoescape = jinja2.select_autoescape

from skill_forge.dashboard.state import (
    GenerationSnapshot,
    WorkerView,
)


def _env() -> Environment:
    templates = Path(__file__).resolve().parents[1] / "src" / "skill_forge" / "dashboard" / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True, lstrip_blocks=True,
    )


def test_evo_tree_renders_three_generations_with_winners_and_siblings() -> None:
    env = _env()
    history = [
        GenerationSnapshot(gen=0, parent="baseline", workers=[
            WorkerView(id="w0", strategy="checklist", status="merged", merged=True),
            WorkerView(id="w1", strategy="bullet", status="discarded"),
            WorkerView(id="w2", strategy="explicit", status="errored"),
        ]),
        GenerationSnapshot(gen=1, parent="v1", workers=[
            WorkerView(id="w0", strategy="enum tighten", status="merged", merged=True),
            WorkerView(id="w1", strategy="schema mig", status="discarded"),
        ]),
    ]
    out = env.get_template("_evo_tree.html").render(
        lineage_history=history, current_workers=[],
    )
    assert 'id="evo-tree"' in out
    assert "evo-node-merged" in out
    assert "evo-node-discarded" in out
    assert "evo-node-errored" in out
    assert "evo-edge-merged" in out
    assert "evo-edge-discarded" in out
    # Trunk labels
    assert ">baseline<" in out
    assert ">v1<" in out
    assert ">v2<" in out


def test_evo_tree_handles_in_flight_current_generation() -> None:
    env = _env()
    history = [
        GenerationSnapshot(gen=0, parent="baseline", workers=[
            WorkerView(id="w0", strategy="x", status="merged", merged=True),
        ]),
    ]
    current = [
        WorkerView(id="g1-w0", strategy="active1", status="mutating"),
        WorkerView(id="g1-w1", strategy="active2", status="testing"),
    ]
    out = env.get_template("_evo_tree.html").render(
        lineage_history=history, current_workers=current,
    )
    assert "evo-node-active" in out
    assert "current round in progress" in out


def test_evo_tree_empty_history() -> None:
    env = _env()
    out = env.get_template("_evo_tree.html").render(
        lineage_history=[], current_workers=[],
    )
    assert "0 generations rendered" in out
    assert ">baseline<" in out  # trunk root always shown
