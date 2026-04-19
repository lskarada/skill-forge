"""Milestone 1 capture flow.

Pipeline:
    transcript → excerpt → capture subagent → approval gate → disk

All side effects (stdout, stdin, disk, subagent dispatch) are injected so
the orchestration is directly testable. `run_capture` is the one entry point
the CLI and tests both call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from skill_forge import transcript as tx

REPLAY_VERSION = "1"
NUM_CONTEXT_TURNS = 12
ESCAPE_HATCH_WARNING = "# SKILL-FORGE: unreviewed surface area — escape hatch test.\n"


@dataclass
class CaptureConfig:
    projects_dir: Path = field(default_factory=lambda: tx.DEFAULT_PROJECTS_DIR)
    cwd: Path = field(default_factory=Path.cwd)
    output_root: Path = field(default_factory=lambda: Path.cwd() / ".skill-forge")
    target: str | None = None
    assume_yes: bool = False
    transcript_path: Path | None = None
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(timezone.utc)
    )


@dataclass
class CaptureIO:
    printer: Callable[[str], None]
    prompter: Callable[[str], str]
    dispatcher: Callable[[str, str | None], dict[str, Any]]


@dataclass
class CaptureResult:
    approved: bool
    outcome: str  # "approved" | "rejected" | "skipped" | "escape_hatch" | "dsl_gap_noted"
    test_path: Path | None = None
    replay_path: Path | None = None
    skill_name: str | None = None


# --- public entry ---------------------------------------------------------


def run_capture(config: CaptureConfig, io: CaptureIO) -> CaptureResult:
    transcript_path = config.transcript_path or tx.find_latest_transcript(
        projects_dir=config.projects_dir,
        cwd=config.cwd,
    )
    entries = tx.load_entries(transcript_path)
    turns = tx.group_turns(entries)
    if not turns:
        raise SystemExit(f"transcript {transcript_path} has no conversational turns")

    excerpt = _build_excerpt(turns, NUM_CONTEXT_TURNS)
    io.printer(f"transcript: {transcript_path}")
    io.printer(f"turns: {len(turns)} total, sending last {min(len(turns), NUM_CONTEXT_TURNS)} to capture agent")

    draft = io.dispatcher(excerpt, config.target)
    _validate_draft(draft)

    skill_name = draft["skill_name"]
    timestamp_dt = config.now()
    timestamp = timestamp_dt.strftime("%Y%m%d_%H%M%S")

    if draft.get("cannot_express_in_dsl"):
        return _handle_dsl_gap(
            draft=draft,
            skill_name=skill_name,
            timestamp=timestamp,
            timestamp_dt=timestamp_dt,
            transcript_path=transcript_path,
            config=config,
            io=io,
        )

    return _handle_dsl_draft(
        draft=draft,
        skill_name=skill_name,
        timestamp=timestamp,
        timestamp_dt=timestamp_dt,
        transcript_path=transcript_path,
        config=config,
        io=io,
    )


# --- branches -------------------------------------------------------------


def _handle_dsl_draft(
    *,
    draft: dict[str, Any],
    skill_name: str,
    timestamp: str,
    timestamp_dt: datetime,
    transcript_path: Path,
    config: CaptureConfig,
    io: CaptureIO,
) -> CaptureResult:
    test_code = _rewrite_replay_path(draft["test_code"], timestamp)
    io.printer("")
    io.printer("=" * 72)
    io.printer(f"Drafted test for skill: {skill_name}")
    io.printer(f"Why it failed: {draft['failure_note']}")
    io.printer("=" * 72)
    io.printer(test_code)
    io.printer("=" * 72)

    if not _confirm(io, config, "Approve this test? [y/N] "):
        io.printer("rejected — nothing written")
        return CaptureResult(approved=False, outcome="rejected", skill_name=skill_name)

    test_path, replay_path = _write_artifacts(
        skill_name=skill_name,
        timestamp=timestamp,
        timestamp_dt=timestamp_dt,
        transcript_path=transcript_path,
        draft=draft,
        test_code=test_code,
        config=config,
        flag_as_escape_hatch=False,
    )
    _append_learnings(config.output_root, skill_name, timestamp_dt, draft, transcript_path)

    io.printer(f"wrote test:   {test_path}")
    io.printer(f"wrote replay: {replay_path}")
    return CaptureResult(
        approved=True,
        outcome="approved",
        test_path=test_path,
        replay_path=replay_path,
        skill_name=skill_name,
    )


def _handle_dsl_gap(
    *,
    draft: dict[str, Any],
    skill_name: str,
    timestamp: str,
    timestamp_dt: datetime,
    transcript_path: Path,
    config: CaptureConfig,
    io: CaptureIO,
) -> CaptureResult:
    reason = draft.get("reason", "(no reason given)")
    io.printer("")
    io.printer("=" * 72)
    io.printer(f"Capture agent could NOT express this failure in harness.v1 DSL.")
    io.printer(f"Reason: {reason}")
    io.printer("=" * 72)
    io.printer("Options:")
    io.printer("  (a) skip     — discard this capture, write nothing")
    io.printer("  (b) hatch    — write as escape-hatch free-form pytest (flagged)")
    io.printer("  (c) note     — log missing helper, discard test for now")
    io.printer("=" * 72)

    choice = _prompt_dsl_gap(io, config)

    if choice == "a":
        io.printer("skipped — nothing written")
        return CaptureResult(approved=False, outcome="skipped", skill_name=skill_name)

    if choice == "c":
        notes_path = config.output_root / "history" / skill_name / "dsl_gaps.md"
        _append_file(
            notes_path,
            f"## {timestamp_dt.isoformat()}\n- transcript: {transcript_path}\n- reason: {reason}\n\n",
        )
        io.printer(f"logged DSL gap at {notes_path}")
        return CaptureResult(approved=False, outcome="dsl_gap_noted", skill_name=skill_name)

    escape_code = draft.get("escape_hatch_test_code", "").strip()
    if not escape_code:
        io.printer("capture agent did not provide an escape-hatch draft; nothing written")
        return CaptureResult(approved=False, outcome="skipped", skill_name=skill_name)

    escape_code_flagged = ESCAPE_HATCH_WARNING + escape_code
    escape_code_flagged = _rewrite_replay_path(escape_code_flagged, timestamp)
    test_path, replay_path = _write_artifacts(
        skill_name=skill_name,
        timestamp=timestamp,
        timestamp_dt=timestamp_dt,
        transcript_path=transcript_path,
        draft=draft,
        test_code=escape_code_flagged,
        config=config,
        flag_as_escape_hatch=True,
    )
    _append_learnings(config.output_root, skill_name, timestamp_dt, draft, transcript_path)
    _append_file(
        config.output_root / "history" / skill_name / "escape_hatches.md",
        f"## {timestamp_dt.isoformat()}\n- test: {test_path}\n- reason: {draft.get('reason', '')}\n\n",
    )
    io.printer(f"wrote escape-hatch test: {test_path}")
    io.printer(f"wrote replay:           {replay_path}")
    return CaptureResult(
        approved=True,
        outcome="escape_hatch",
        test_path=test_path,
        replay_path=replay_path,
        skill_name=skill_name,
    )


# --- I/O plumbing ---------------------------------------------------------


def _confirm(io: CaptureIO, config: CaptureConfig, prompt: str) -> bool:
    if config.assume_yes:
        io.printer(f"{prompt}[y (auto)]")
        return True
    answer = io.prompter(prompt).strip().lower()
    return answer in {"y", "yes"}


def _prompt_dsl_gap(io: CaptureIO, config: CaptureConfig) -> str:
    if config.assume_yes:
        # without an interactive user we can't pick between skip/hatch/note;
        # treat --yes here as "skip", matching (a) which is the no-op choice
        io.printer("Choice? [a/b/c] [a (auto)]")
        return "a"
    raw = io.prompter("Choice? [a/b/c] ").strip().lower()
    return raw[0] if raw and raw[0] in {"a", "b", "c"} else "a"


# --- transcript excerpt ---------------------------------------------------


def _build_excerpt(turns: list[dict[str, Any]], n: int) -> str:
    slice_ = turns[-n:]
    start_index = len(turns) - len(slice_)
    parts: list[str] = []
    for offset, turn in enumerate(slice_):
        parts.append(tx.render_turn(turn, start_index + offset))
    return "\n".join(parts)


# --- validation -----------------------------------------------------------


_REQUIRED_DRAFT_KEYS = (
    "skill_name",
    "failure_note",
    "source_turn_index",
    "conversation",
    "trigger_turn_index",
)


def _validate_draft(draft: dict[str, Any]) -> None:
    missing = [k for k in _REQUIRED_DRAFT_KEYS if k not in draft]
    if missing:
        raise SystemExit(
            f"capture subagent response missing required keys: {missing}. Got keys: {list(draft)}"
        )

    if not isinstance(draft["conversation"], list) or not draft["conversation"]:
        raise SystemExit("capture subagent returned empty `conversation`")

    trigger = draft["trigger_turn_index"]
    if not isinstance(trigger, int) or not 0 <= trigger < len(draft["conversation"]):
        raise SystemExit(
            f"trigger_turn_index {trigger!r} out of range for conversation of length {len(draft['conversation'])}"
        )
    if draft["conversation"][trigger].get("role") != "user":
        raise SystemExit("trigger_turn_index must point at a user turn")

    cannot_express = draft.get("cannot_express_in_dsl", False)
    if cannot_express and not draft.get("escape_hatch_test_code", "").strip():
        # acceptable — user may still choose (a) skip or (c) note — but warn
        pass
    elif not cannot_express and not draft.get("test_code", "").strip():
        raise SystemExit("capture subagent returned empty test_code with cannot_express_in_dsl=false")


# --- disk writers ---------------------------------------------------------


def _write_artifacts(
    *,
    skill_name: str,
    timestamp: str,
    timestamp_dt: datetime,
    transcript_path: Path,
    draft: dict[str, Any],
    test_code: str,
    config: CaptureConfig,
    flag_as_escape_hatch: bool,
) -> tuple[Path, Path]:
    tests_dir = config.output_root / "tests" / skill_name
    replays_dir = tests_dir / "replays"
    tests_dir.mkdir(parents=True, exist_ok=True)
    replays_dir.mkdir(parents=True, exist_ok=True)

    test_path = tests_dir / f"test_{timestamp}.py"
    replay_path = replays_dir / f"{timestamp}.json"

    replay_payload = {
        "replay_version": REPLAY_VERSION,
        "captured_at": timestamp_dt.isoformat(),
        "source_transcript": str(transcript_path),
        "source_turn_index": draft["source_turn_index"],
        "replay_mode": draft.get("replay_mode", "full_conversation"),
        "conversation": draft["conversation"],
        "trigger_turn_index": draft["trigger_turn_index"],
    }
    if flag_as_escape_hatch:
        replay_payload["escape_hatch"] = True

    if not test_code.endswith("\n"):
        test_code += "\n"
    test_path.write_text(test_code, encoding="utf-8")
    replay_path.write_text(json.dumps(replay_payload, indent=2) + "\n", encoding="utf-8")
    return test_path, replay_path


def _append_learnings(
    output_root: Path,
    skill_name: str,
    timestamp_dt: datetime,
    draft: dict[str, Any],
    transcript_path: Path,
) -> None:
    learnings = output_root / "learnings.md"
    entry = (
        f"## {timestamp_dt.isoformat()} — {skill_name}\n"
        f"- transcript: {transcript_path}\n"
        f"- turn: {draft['source_turn_index']}\n"
        f"- note: {draft['failure_note']}\n\n"
    )
    _append_file(learnings, entry)


def _append_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(content)


# --- test-code rewriter ---------------------------------------------------

_REPLAY_PATTERN = re.compile(r"""replay\s*=\s*["']([^"']+)["']""")


def _rewrite_replay_path(code: str, timestamp: str) -> str:
    """Force any `replay=...` call site in the drafted test to point at the
    canonical `replays/<timestamp>.json` path we're about to write.

    The subagent is instructed to emit a relative replay path but may choose
    any basename. Rewriting here keeps the on-disk layout predictable.
    """
    target = f'replay="replays/{timestamp}.json"'
    return _REPLAY_PATTERN.sub(target, code)
