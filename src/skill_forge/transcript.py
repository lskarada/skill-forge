"""Find the most recent Claude Code session transcript and print the last N turns.

Run with no arguments:
    python src/skill_forge/transcript.py

--- What is a "turn"? -----------------------------------------------------------

A Claude Code JSONL transcript interleaves three kinds of entries:

1. **user typed-text.** `type:"user"`, content is a string, `message.id` is
   empty. The human typed something into the chat. This marks a boundary.

2. **assistant response blocks.** `type:"assistant"`. One API response splits
   into multiple JSONL entries (thinking, text, tool_use), all sharing the
   same `message.id`. A single user message often triggers several API calls
   in a tool-use loop.

3. **tool_result.** `type:"user"`, content is a list containing a
   `tool_result` block, `message.id` is empty. This is plumbing — the output
   of a tool Claude called. It was not typed by the human.

We collapse (2) and (3) together, because they're all work that Claude did in
response to one human message. So a "turn" here is:

- A **user turn**: one typed-text entry. One turn, stands alone.
- An **assistant turn**: every entry from just after a user-typed-text up to
  (but not including) the next user-typed-text. All of Claude's API responses
  plus the tool_results they consumed, rendered in chronological order.

This matches the human mental model of "what did the user say, and what did
Claude do about it." "Last 10 turns" is roughly 5 full back-and-forths.

Metadata entries (`permission-mode`, `attachment`, `file-history-snapshot`,
`system`, `queue-operation`, `last-prompt`) are dropped entirely — they're
not conversation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
NUM_TURNS = 10
MAX_TEXT_CHARS = 800


def _project_dir_name(cwd: Path) -> str:
    """Claude Code encodes an absolute project path as `/` → `-`.

    e.g. /Users/lskarada/Documents/SkillForge → -Users-lskarada-Documents-SkillForge
    """
    return str(cwd.resolve()).replace("/", "-")


def find_latest_transcript(
    projects_dir: Path = DEFAULT_PROJECTS_DIR,
    cwd: Path | None = None,
) -> Path:
    """Pick the most recent JSONL under `projects_dir`.

    Preference order (per PRD §10 open question on multi-project handling):
      1. If `cwd` is given, restrict to the subdir whose name matches cwd's
         Claude-Code-encoded path. Among those, take newest mtime.
      2. Otherwise (or if no match), fall back to newest mtime across all
         project subdirs.

    This makes `forge capture` deterministic when the user runs it inside a
    specific project, while still working in ad-hoc contexts.
    """
    if cwd is not None:
        scoped = projects_dir / _project_dir_name(cwd)
        if scoped.is_dir():
            scoped_jsonls = list(scoped.glob("*.jsonl"))
            if scoped_jsonls:
                return max(scoped_jsonls, key=lambda p: p.stat().st_mtime)

    jsonls = list(projects_dir.glob("*/*.jsonl"))
    if not jsonls:
        sys.exit(f"no transcripts found under {projects_dir}")
    return max(jsonls, key=lambda p: p.stat().st_mtime)


def load_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _is_user_typed(entry: dict[str, Any]) -> bool:
    if entry.get("type") != "user":
        return False
    msg = entry.get("message") or {}
    content = msg.get("content")
    return isinstance(content, str)


def group_turns(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse entries into alternating user / assistant turns.

    Returns a list of {"role": "user"|"assistant", "entries": [...]}.
    An assistant turn bundles every user+assistant entry between two
    user-typed messages (so tool_results and tool_uses stay together).
    """
    turns: list[dict[str, Any]] = []
    bucket: list[dict[str, Any]] = []

    for entry in entries:
        if entry.get("type") not in ("user", "assistant"):
            continue
        if _is_user_typed(entry):
            if bucket:
                turns.append({"role": "assistant", "entries": bucket})
                bucket = []
            turns.append({"role": "user", "entries": [entry]})
        else:
            bucket.append(entry)

    if bucket:
        turns.append({"role": "assistant", "entries": bucket})

    return turns


def _truncate(s: str, limit: int = MAX_TEXT_CHARS) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n… [truncated, {len(s) - limit} more chars]"


def _render_block(block: Any) -> str | None:
    if not isinstance(block, dict):
        return _truncate(repr(block))
    btype = block.get("type", "?")
    if btype == "text":
        text = block.get("text", "").strip()
        return _truncate(text) if text else None
    if btype == "thinking":
        thinking = block.get("thinking", "").strip()
        return f"[thinking] {_truncate(thinking, 300)}" if thinking else None
    if btype == "tool_use":
        name = block.get("name", "?")
        tool_input = block.get("input", {})
        input_str = json.dumps(tool_input, ensure_ascii=False)
        return f"[tool_use] {name}({_truncate(input_str, 400)})"
    if btype == "tool_result":
        tool_id = block.get("tool_use_id", "?")
        result = block.get("content", "")
        if isinstance(result, list):
            result = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in result
            )
        return f"[tool_result {tool_id[-8:]}] {_truncate(str(result), 500)}"
    return f"[{btype}] {_truncate(json.dumps(block, ensure_ascii=False), 300)}"


def _render_entry_body(entry: dict[str, Any]) -> list[str]:
    msg = entry.get("message") or {}
    content = msg.get("content", "")
    if isinstance(content, str):
        return [_truncate(content.strip())] if content.strip() else []
    if isinstance(content, list):
        return [s for s in (_render_block(b) for b in content) if s]
    return [_truncate(repr(content))]


def render_turn(turn: dict[str, Any], index: int) -> str:
    role = turn["role"]
    entries = turn["entries"]
    first_ts = entries[0].get("timestamp", "")
    body_parts: list[str] = []
    for e in entries:
        body_parts.extend(_render_entry_body(e))
    body = "\n\n".join(body_parts) if body_parts else "(empty)"

    sep = "=" * 72
    rule = "-" * 72
    header = f"Turn {index} | {role} | {first_ts}"
    if role == "assistant" and len(entries) > 1:
        header += f" | {len(entries)} entries"
    return f"{sep}\n{header}\n{rule}\n{body}\n"


def main() -> None:
    path = find_latest_transcript()
    entries = load_entries(path)
    turns = group_turns(entries)
    total = len(turns)
    last = turns[-NUM_TURNS:]
    start_index = total - len(last) + 1

    print(f"transcript: {path}")
    print(f"turns: {total} total, showing last {len(last)}\n")

    for offset, turn in enumerate(last):
        print(render_turn(turn, start_index + offset))


if __name__ == "__main__":
    main()
