from pathlib import Path
import json

from skill_forge.feedback_history import (
    FeedbackEntry,
    append,
    project_to_learnings,
    read_recent,
)


def test_append_writes_one_jsonl_line(tmp_path: Path):
    log = tmp_path / "feedback_history.jsonl"
    entry = FeedbackEntry(
        iter=1,
        skill="greeter",
        parent="baseline",
        action="create",
        proposal_summary="numbered checklist",
        verdict="discarded",
        score_delta=-0.0,
        reason="tied on length",
        ts="2026-05-05T11:39:00Z",
    )

    append(log, entry)

    lines = log.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["iter"] == 1
    assert json.loads(lines[0])["proposal_summary"] == "numbered checklist"


def test_read_recent_returns_last_n_in_order(tmp_path: Path):
    log = tmp_path / "feedback_history.jsonl"
    for i in range(5):
        append(log, FeedbackEntry(
            iter=i, skill="greeter", parent="baseline",
            action="create", proposal_summary=f"p{i}",
            verdict="admitted", score_delta=0.1, reason="",
            ts="2026-05-05T11:39:00Z",
        ))

    recent = read_recent(log, n=3)

    assert [e.iter for e in recent] == [2, 3, 4]


def test_project_to_learnings_emits_one_line_per_discard(tmp_path: Path):
    log = tmp_path / "feedback_history.jsonl"
    learnings = tmp_path / "learnings.md"
    for i, verdict in enumerate(["admitted", "discarded", "discarded"]):
        append(log, FeedbackEntry(
            iter=i, skill="greeter", parent="baseline",
            action="create", proposal_summary=f"p{i}",
            verdict=verdict, score_delta=0.0, reason=f"r{i}",
            ts="2026-05-05T11:39:00Z",
        ))

    project_to_learnings(log, learnings)

    body = learnings.read_text()
    assert body.count("\n") == 2  # two discarded entries
    assert "r1" in body and "r2" in body
    assert "r0" not in body  # admitted, not a loss
