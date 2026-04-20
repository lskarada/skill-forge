"""Subagent dispatch boundary.

Everything LLM-facing goes through here so the rest of the harness stays
deterministic and unit-testable. Default dispatch shells out to the `claude`
CLI in non-interactive print mode, which uses the user's existing Claude Code
subscription — no API key, zero cost (PRD §2.3, §8: no direct Anthropic API).

Tests monkeypatch `run_claude` (for prompt plumbing), `run_skill`
(for Assertion DSL execution), or `mutate_skill` (for the optimize loop)
to avoid spawning real subagents.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CLAUDE_BIN_ENV = "SKILL_FORGE_CLAUDE_BIN"
DEFAULT_TIMEOUT_SECONDS = 300
MUTATION_TIMEOUT_SECONDS = 900


class DispatchError(RuntimeError):
    """Raised when the subagent call itself fails (missing binary, nonzero exit, timeout)."""


@dataclass
class ClaudeResult:
    stdout: str
    stderr: str
    returncode: int


def _resolve_claude_bin() -> str:
    override = os.environ.get(CLAUDE_BIN_ENV)
    if override:
        return override
    found = shutil.which("claude")
    if not found:
        raise DispatchError(
            "claude CLI not found on PATH. Install Claude Code "
            f"(https://claude.com/claude-code) or set {CLAUDE_BIN_ENV}."
        )
    return found


def run_claude(
    prompt: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    cwd: Path | None = None,
) -> ClaudeResult:
    """Invoke `claude -p <prompt>` and return stdout/stderr/returncode.

    `cwd` controls the subprocess working directory — essential for the
    mutation loop, where the subagent must be rooted in a git worktree so
    its edits land on that worktree's branch.
    """
    claude_bin = _resolve_claude_bin()
    try:
        proc = subprocess.run(
            [claude_bin, "--dangerously-skip-permissions", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired as e:
        raise DispatchError(
            f"claude subagent timed out after {timeout}s"
        ) from e

    return ClaudeResult(
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
    )


# --- SUT resolution -------------------------------------------------------


def resolve_sut_path(skill: str, *, search_root: Path | None = None) -> Path:
    """Return the path to the SUT markdown for `skill`.

    Conventional locations (checked in order):
      1. .claude/skills/<skill>/SKILL.md
      2. .claude/agents/<skill>.md
    Search from `search_root` (defaults to cwd).
    """
    root = search_root or Path.cwd()
    candidates = [
        root / ".claude" / "skills" / skill / "SKILL.md",
        root / ".claude" / "agents" / f"{skill}.md",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise DispatchError(
        f"SUT markdown not found for skill {skill!r}. Tried: "
        + ", ".join(str(p) for p in candidates)
    )


# --- skill runner (harness.v1.run_skill calls this) -----------------------


def run_skill(
    skill: str,
    replay: str,
    *,
    search_root: Path | None = None,
    cwd: Path | None = None,
) -> str:
    """Re-run a captured replay against the current SUT.

    Loads the SUT markdown, stitches it with the replay conversation, and
    shells out to `claude -p`. The SUT content is injected as a system-style
    preamble so the subagent behaves as the skill. Tests in worktrees pass
    `search_root=worktree` so the *mutated* SUT is exercised, not main's.
    """
    with open(replay, encoding="utf-8") as f:
        payload = json.load(f)

    sut_path = resolve_sut_path(skill, search_root=search_root)
    sut_content = sut_path.read_text(encoding="utf-8")

    conversation = payload.get("conversation", [])
    transcript_lines = [
        f"[{turn.get('role', '?')}] {turn.get('content', '')}"
        for turn in conversation
    ]

    prompt = (
        f"You are the '{skill}' skill. The markdown below is your instruction "
        f"set — follow it exactly. After the instructions, a conversation "
        f"transcript is replayed. Produce only the final assistant response "
        f"that the skill would produce for the last user turn. No commentary.\n\n"
        f"---BEGIN SKILL INSTRUCTIONS---\n"
        f"{sut_content}\n"
        f"---END SKILL INSTRUCTIONS---\n\n"
        f"---BEGIN CONVERSATION REPLAY---\n"
        + "\n".join(transcript_lines)
        + "\n---END CONVERSATION REPLAY---\n"
    )

    result = run_claude(prompt, cwd=cwd)
    if result.returncode != 0:
        raise DispatchError(
            f"run_skill failed for {skill}: rc={result.returncode}\n{result.stderr[:500]}"
        )
    return result.stdout.strip()


# --- capture subagent -----------------------------------------------------


def draft_capture(transcript_excerpt: str, target_hint: str | None) -> dict[str, Any]:
    """Ask a subagent to identify the failed skill and draft a regression test.

    Returns a dict matching the schema documented in prompts.CAPTURE_SCHEMA.
    Raises DispatchError on subagent failure or unparseable response.
    """
    from skill_forge import prompts

    prompt = prompts.build_capture_prompt(
        transcript_excerpt=transcript_excerpt,
        target_hint=target_hint,
    )
    result = run_claude(prompt)
    if result.returncode != 0:
        raise DispatchError(
            f"capture subagent exited {result.returncode}:\n{result.stderr[:500]}"
        )

    parsed = _extract_first_json_object(result.stdout)
    if parsed is None:
        raise DispatchError(
            "capture subagent did not return parseable JSON. First 400 chars:\n"
            f"{result.stdout[:400]}"
        )
    return parsed


# --- mutation subagent ----------------------------------------------------


def mutate_skill(
    *,
    sut_path: Path,
    tests_preview: str,
    learnings: str,
    strategy: str,
    cwd: Path,
) -> str:
    """Spawn a Claude Code subagent to rewrite the SUT at `sut_path`.

    The subagent is expected to edit `sut_path` in place (it's a file inside
    `cwd`, which is a git worktree). We return the subagent's stdout for
    audit logging — the actual mutation is observed by re-reading the file.
    Raises DispatchError on subagent failure.
    """
    from skill_forge import prompts

    sut_content = sut_path.read_text(encoding="utf-8")
    relative_sut = sut_path.relative_to(cwd) if sut_path.is_absolute() else sut_path

    prompt = prompts.build_mutation_prompt(
        sut_relative_path=str(relative_sut),
        sut_content=sut_content,
        tests_preview=tests_preview,
        learnings=learnings,
        strategy=strategy,
    )
    result = run_claude(prompt, cwd=cwd, timeout=MUTATION_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise DispatchError(
            f"mutation subagent exited {result.returncode}:\n{result.stderr[:500]}"
        )
    return result.stdout


# --- JSON extraction ------------------------------------------------------


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    s = text.strip()
    if s.startswith("```"):
        # strip triple-backtick fences regardless of language tag
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -len("```")]
        s = s.strip()

    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = s.find("{", start + 1)
    return None
