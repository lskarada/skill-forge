from pathlib import Path
import json

from skill_forge.feedback_history import append, read_recent, FeedbackEntry


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
