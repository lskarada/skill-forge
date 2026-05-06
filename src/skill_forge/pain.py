"""Ingest a rough Claude Code session into a structured PainSession.

Reads ~/.claude/projects/<cwd-encoded>/*.jsonl transcripts and the recent
git log/diff. Pure-Python — no LLM calls, no Anthropic API. The Attribution
and Synthesis subagents downstream are the ones that interpret pain;
this module just gathers the raw signal.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


@dataclass(frozen=True)
class Turn:
    role: str          # "user" | "assistant" | "tool_result"
    text: str
    tool_calls: tuple[str, ...] = ()


@dataclass(frozen=True)
class PainSession:
    turns: list[Turn]
    error_signatures: set[str]      # extracted from tool_result text
    changed_files: set[str]         # from git diff
    user_complaint_phrases: list[str]   # heuristic complaint detection


_ERROR_RE = re.compile(r"\b(\w*Error|\w*Exception|Traceback)\b")
# English-only complaint heuristic. Non-English complaint phrasing falls
# through to error-signature attribution. Multilingual ingestion is a
# v0.9 candidate (S12 in the plan, documented in CLAUDE.md).
_COMPLAINT_PREFIXES = (
    "no ", "wrong", "that's not", "doesn't",
    "still broken", "ugh", "this is wrong",
)


DEFAULT_RECENCY = timedelta(hours=24)


def ingest(
    *,
    transcripts_dir: Path,
    git_diff_path: Path | None,
    since: timedelta | None = DEFAULT_RECENCY,
) -> PainSession:
    """Ingest transcripts modified within `since` of now.

    `since=None` disables the recency filter (read everything). The
    default of 24 hours stops a fresh `forge retro` from re-reading
    months of historical transcripts on a long-lived project — the
    user's "rough session" is almost always within the last day.
    """
    turns: list[Turn] = []
    cutoff = (time.time() - since.total_seconds()) if since is not None else None

    files = sorted(transcripts_dir.glob("*.jsonl"))
    if cutoff is not None:
        files = [p for p in files if p.stat().st_mtime >= cutoff]

    for jsonl in files:
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            turns.append(Turn(
                role=data.get("role", "unknown"),
                text=str(data.get("text", "")),
                tool_calls=tuple(data.get("tool_calls", ())),
            ))

    errors: set[str] = set()
    complaints: list[str] = []
    for t in turns:
        errors.update(_ERROR_RE.findall(t.text))
        if t.role == "user" and any(t.text.lower().startswith(p) for p in _COMPLAINT_PREFIXES):
            complaints.append(t.text)

    changed: set[str] = set()
    if git_diff_path and git_diff_path.exists():
        for line in git_diff_path.read_text().splitlines():
            if line.startswith("+++ b/") or line.startswith("--- a/"):
                changed.add(line[6:])

    return PainSession(
        turns=turns,
        error_signatures=errors,
        changed_files=changed,
        user_complaint_phrases=complaints,
    )


# --- Task 8.1.5: cwd → ~/.claude/projects/<encoded> resolver --------------


class TranscriptsNotFoundError(FileNotFoundError):
    """Raised when no Claude Code transcripts exist for the requested cwd."""


def _encode_cwd(cwd: Path) -> str:
    """Claude Code's encoding: every '/' (including the leading one) becomes '-'."""
    return str(cwd).replace("/", "-")


def resolve_transcripts_dir(
    cwd: Path,
    *,
    projects_root: Path | None = None,
) -> Path:
    """Map a cwd Path to its encoded `~/.claude/projects/<encoded>` directory.

    Verified empirically: `/Users/lskarada/Documents/SkillForge` →
    `-Users-lskarada-Documents-SkillForge`. The encoding replaces every
    `/` with `-`, including the leading slash.
    """
    root = projects_root or (Path.home() / ".claude" / "projects")
    candidate = root / _encode_cwd(cwd)
    if not candidate.is_dir():
        raise TranscriptsNotFoundError(
            f"no transcripts found for {cwd} at {candidate} — "
            f"is Claude Code installed and have you used this project?"
        )
    return candidate
