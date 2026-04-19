"""Tests for M2-era dispatch.py additions: resolve_sut_path, run_skill SUT
loading, and mutate_skill.

run_claude is stubbed via SKILL_FORGE_CLAUDE_BIN pointing at a shell script
that echoes a canned response — same trick the M1 tests use.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from skill_forge import dispatch


def _write_fake_claude(tmp_path: Path, stdout_payload: str) -> Path:
    """Write a shell script that prints a fixed payload and exits 0."""
    script = tmp_path / "fake_claude.sh"
    script.write_text(
        "#!/bin/sh\n"
        "# Echo back whatever prompt came in on argv to stderr for debug; "
        "# emit stdout_payload as the 'response'.\n"
        f"cat <<'EOF'\n{stdout_payload}\nEOF\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def test_resolve_sut_path_finds_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    sut = skill_dir / "SKILL.md"
    sut.write_text("# my skill\n")

    result = dispatch.resolve_sut_path("my-skill", search_root=tmp_path)
    assert result == sut


def test_resolve_sut_path_finds_agent_fallback(tmp_path: Path) -> None:
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    sut = agents / "helper.md"
    sut.write_text("# helper agent\n")

    result = dispatch.resolve_sut_path("helper", search_root=tmp_path)
    assert result == sut


def test_resolve_sut_path_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(dispatch.DispatchError, match="SUT markdown not found"):
        dispatch.resolve_sut_path("nope", search_root=tmp_path)


def test_run_skill_loads_sut_and_replay(tmp_path: Path, monkeypatch) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "echoer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("be a good echoer")

    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps({
        "conversation": [
            {"role": "user", "content": "say hi"},
        ]
    }))

    fake = _write_fake_claude(tmp_path, "hi!")
    monkeypatch.setenv("SKILL_FORGE_CLAUDE_BIN", str(fake))

    out = dispatch.run_skill("echoer", str(replay), search_root=tmp_path)
    assert out == "hi!"


def test_mutate_skill_invokes_subagent(tmp_path: Path, monkeypatch) -> None:
    sut = tmp_path / "SKILL.md"
    sut.write_text("# current skill\n")

    fake = _write_fake_claude(tmp_path, "rewrote the skill")
    monkeypatch.setenv("SKILL_FORGE_CLAUDE_BIN", str(fake))

    stdout = dispatch.mutate_skill(
        sut_path=sut,
        tests_preview="def test_x(): ...",
        learnings="",
        strategy="tighten contract",
        cwd=tmp_path,
    )
    assert "rewrote the skill" in stdout


def test_mutate_skill_raises_on_nonzero_exit(tmp_path: Path, monkeypatch) -> None:
    sut = tmp_path / "SKILL.md"
    sut.write_text("body\n")

    script = tmp_path / "claude_fail.sh"
    script.write_text("#!/bin/sh\necho boom >&2\nexit 2\n")
    script.chmod(0o755)
    monkeypatch.setenv("SKILL_FORGE_CLAUDE_BIN", str(script))

    with pytest.raises(dispatch.DispatchError, match="mutation subagent exited 2"):
        dispatch.mutate_skill(
            sut_path=sut,
            tests_preview="",
            learnings="",
            strategy="",
            cwd=tmp_path,
        )
