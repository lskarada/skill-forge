"""Tests for src/skill_forge/capture.py.

Covers the full Milestone 1 orchestration pipeline: transcript → excerpt →
capture agent → approval gate → disk. The dispatcher is injected, so these
tests never spawn a real subagent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from skill_forge.capture import (
    ESCAPE_HATCH_WARNING,
    CaptureConfig,
    CaptureIO,
    run_capture,
)


# --- fixtures -------------------------------------------------------------


FIXED_NOW = datetime(2026, 4, 18, 7, 30, 0, tzinfo=timezone.utc)
FIXED_TIMESTAMP = "20260418_073000"


def _write_transcript(path: Path) -> Path:
    """Write a minimal valid JSONL transcript with a handful of turns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
            },
        },
        {"type": "user", "message": {"role": "user", "content": "summarize the doc"}},
        {
            "type": "assistant",
            "message": {
                "id": "m2",
                "role": "assistant",
                "content": [{"type": "text", "text": "I'm sorry, as an AI…"}],
            },
        },
    ]
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def _base_config(tmp_path: Path, transcript: Path, **overrides: Any) -> CaptureConfig:
    return CaptureConfig(
        projects_dir=tmp_path / "projects",
        cwd=tmp_path / "work",
        output_root=tmp_path / ".skill-forge",
        target=overrides.get("target"),
        assume_yes=overrides.get("assume_yes", False),
        transcript_path=transcript,
        now=lambda: FIXED_NOW,
    )


def _good_draft() -> dict[str, Any]:
    return {
        "skill_name": "summarizer",
        "failure_note": "refused a benign summarization request",
        "source_turn_index": 3,
        "conversation": [
            {"role": "user", "content": "summarize the doc"},
        ],
        "trigger_turn_index": 0,
        "test_code": (
            'from skill_forge.harness.v1 import run_skill, assert_not_contains\n'
            'def test_no_refusal() -> None:\n'
            '    out = run_skill(skill="summarizer", replay="replays/whatever.json")\n'
            '    assert_not_contains(out, "I\'m sorry")\n'
        ),
        "cannot_express_in_dsl": False,
        "reason": "",
        "escape_hatch_test_code": "",
    }


class _IOCapture:
    """Collects printed output; answers prompts from a scripted queue."""

    def __init__(self, answers: list[str] | None = None) -> None:
        self.lines: list[str] = []
        self.answers = list(answers or [])
        self.prompts: list[str] = []

    def printer(self, s: str) -> None:
        self.lines.append(s)

    def prompter(self, msg: str) -> str:
        self.prompts.append(msg)
        return self.answers.pop(0) if self.answers else ""


# --- happy path -----------------------------------------------------------


def test_approved_writes_test_and_replay(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    draft = _good_draft()
    cap = _IOCapture(answers=["y"])
    io = CaptureIO(
        printer=cap.printer,
        prompter=cap.prompter,
        dispatcher=lambda excerpt, target: draft,
    )

    result = run_capture(config, io)

    assert result.approved is True
    assert result.outcome == "approved"
    assert result.skill_name == "summarizer"
    assert result.test_path is not None and result.test_path.exists()
    assert result.replay_path is not None and result.replay_path.exists()

    # layout: .skill-forge/tests/<skill>/test_<ts>.py and replays/<ts>.json
    assert result.test_path.parent.name == "summarizer"
    assert result.test_path.name == f"test_{FIXED_TIMESTAMP}.py"
    assert result.replay_path.parent.name == "replays"
    assert result.replay_path.name == f"{FIXED_TIMESTAMP}.json"

    # replay path in the test code was normalized to the canonical basename
    test_contents = result.test_path.read_text()
    assert f'replay="replays/{FIXED_TIMESTAMP}.json"' in test_contents
    assert "whatever.json" not in test_contents

    # replay payload shape matches PRD §4.4
    replay = json.loads(result.replay_path.read_text())
    assert replay["replay_version"] == "1"
    assert replay["captured_at"] == FIXED_NOW.isoformat()
    assert replay["source_transcript"] == str(transcript)
    assert replay["source_turn_index"] == 3
    assert replay["trigger_turn_index"] == 0
    assert replay["conversation"][0]["role"] == "user"
    assert "escape_hatch" not in replay

    # learnings.md appended
    learnings = (tmp_path / ".skill-forge" / "learnings.md").read_text()
    assert "summarizer" in learnings
    assert "refused a benign summarization" in learnings


def test_rejected_writes_nothing(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    cap = _IOCapture(answers=["n"])
    io = CaptureIO(
        printer=cap.printer,
        prompter=cap.prompter,
        dispatcher=lambda excerpt, target: _good_draft(),
    )

    result = run_capture(config, io)

    assert result.approved is False
    assert result.outcome == "rejected"
    assert result.test_path is None
    assert not (tmp_path / ".skill-forge" / "tests").exists()
    assert not (tmp_path / ".skill-forge" / "learnings.md").exists()


def test_yes_flag_auto_approves(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript, assume_yes=True)
    cap = _IOCapture()  # no answers — prompter must NOT be called
    io = CaptureIO(
        printer=cap.printer,
        prompter=cap.prompter,
        dispatcher=lambda excerpt, target: _good_draft(),
    )

    result = run_capture(config, io)

    assert result.approved is True
    assert result.outcome == "approved"
    assert cap.prompts == []


def test_dispatcher_receives_excerpt_and_target(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript, target=".claude/skills/foo/SKILL.md")
    seen: dict[str, Any] = {}

    def spy(excerpt: str, target: str | None) -> dict[str, Any]:
        seen["excerpt"] = excerpt
        seen["target"] = target
        return _good_draft()

    io = CaptureIO(
        printer=lambda _: None,
        prompter=lambda _: "y",
        dispatcher=spy,
    )

    run_capture(config, io)

    assert seen["target"] == ".claude/skills/foo/SKILL.md"
    # excerpt should contain user + assistant turn markers rendered by transcript.render_turn
    assert "summarize the doc" in seen["excerpt"]
    assert "Turn" in seen["excerpt"]


# --- validation guards ----------------------------------------------------


def test_missing_required_key_errors(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    bad = _good_draft()
    del bad["skill_name"]
    io = CaptureIO(
        printer=lambda _: None,
        prompter=lambda _: "y",
        dispatcher=lambda e, t: bad,
    )

    with pytest.raises(SystemExit, match="missing required keys"):
        run_capture(config, io)


def test_trigger_index_must_point_at_user_turn(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    bad = _good_draft()
    bad["conversation"] = [{"role": "assistant", "content": "nope"}]
    bad["trigger_turn_index"] = 0
    io = CaptureIO(
        printer=lambda _: None,
        prompter=lambda _: "y",
        dispatcher=lambda e, t: bad,
    )

    with pytest.raises(SystemExit, match="user turn"):
        run_capture(config, io)


def test_trigger_index_out_of_range(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    bad = _good_draft()
    bad["trigger_turn_index"] = 5  # conversation has 1 entry
    io = CaptureIO(
        printer=lambda _: None,
        prompter=lambda _: "y",
        dispatcher=lambda e, t: bad,
    )

    with pytest.raises(SystemExit, match="out of range"):
        run_capture(config, io)


def test_empty_transcript_raises(tmp_path: Path) -> None:
    empty = tmp_path / "projects" / "proj" / "empty.jsonl"
    empty.parent.mkdir(parents=True)
    empty.touch()
    config = _base_config(tmp_path, empty)
    io = CaptureIO(
        printer=lambda _: None,
        prompter=lambda _: "y",
        dispatcher=lambda e, t: _good_draft(),
    )

    with pytest.raises(SystemExit, match="no conversational turns"):
        run_capture(config, io)


# --- DSL-gap branch -------------------------------------------------------


def _dsl_gap_draft(*, with_escape: bool = True) -> dict[str, Any]:
    draft = _good_draft()
    draft["cannot_express_in_dsl"] = True
    draft["reason"] = "needs cosine similarity between two outputs"
    draft["test_code"] = ""
    draft["escape_hatch_test_code"] = (
        'def test_freeform() -> None:\n'
        '    assert 1 == 1  # free-form escape hatch\n'
        if with_escape
        else ""
    )
    return draft


def test_dsl_gap_skip_choice_writes_nothing(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    cap = _IOCapture(answers=["a"])
    io = CaptureIO(
        printer=cap.printer,
        prompter=cap.prompter,
        dispatcher=lambda e, t: _dsl_gap_draft(),
    )

    result = run_capture(config, io)

    assert result.approved is False
    assert result.outcome == "skipped"
    assert not (tmp_path / ".skill-forge" / "tests").exists()


def test_dsl_gap_hatch_writes_flagged_test(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    cap = _IOCapture(answers=["b"])
    io = CaptureIO(
        printer=cap.printer,
        prompter=cap.prompter,
        dispatcher=lambda e, t: _dsl_gap_draft(),
    )

    result = run_capture(config, io)

    assert result.approved is True
    assert result.outcome == "escape_hatch"
    assert result.test_path is not None
    contents = result.test_path.read_text()
    assert contents.startswith(ESCAPE_HATCH_WARNING)
    assert "free-form escape hatch" in contents

    # escape_hatches.md logged
    log = tmp_path / ".skill-forge" / "history" / "summarizer" / "escape_hatches.md"
    assert log.exists()
    assert "cosine similarity" in log.read_text()

    # replay file marked
    replay = json.loads(result.replay_path.read_text())
    assert replay["escape_hatch"] is True


def test_dsl_gap_hatch_without_escape_code_skips(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    cap = _IOCapture(answers=["b"])
    io = CaptureIO(
        printer=cap.printer,
        prompter=cap.prompter,
        dispatcher=lambda e, t: _dsl_gap_draft(with_escape=False),
    )

    result = run_capture(config, io)

    assert result.approved is False
    assert result.outcome == "skipped"


def test_dsl_gap_note_choice_logs_gap(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript)
    cap = _IOCapture(answers=["c"])
    io = CaptureIO(
        printer=cap.printer,
        prompter=cap.prompter,
        dispatcher=lambda e, t: _dsl_gap_draft(),
    )

    result = run_capture(config, io)

    assert result.approved is False
    assert result.outcome == "dsl_gap_noted"
    gap_log = tmp_path / ".skill-forge" / "history" / "summarizer" / "dsl_gaps.md"
    assert gap_log.exists()
    assert "cosine similarity" in gap_log.read_text()


def test_dsl_gap_yes_flag_defaults_to_skip(tmp_path: Path) -> None:
    """--yes on a DSL-gap draft picks (a) skip since interactive choice is unavailable."""
    transcript = _write_transcript(tmp_path / "projects" / "proj" / "session.jsonl")
    config = _base_config(tmp_path, transcript, assume_yes=True)
    cap = _IOCapture()
    io = CaptureIO(
        printer=cap.printer,
        prompter=cap.prompter,
        dispatcher=lambda e, t: _dsl_gap_draft(),
    )

    result = run_capture(config, io)

    assert result.outcome == "skipped"
    assert cap.prompts == []
