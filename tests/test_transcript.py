"""Tests for src/skill_forge/transcript.py."""

from __future__ import annotations

import json
import os
from pathlib import Path

from skill_forge.transcript import (
    _project_dir_name,
    find_latest_transcript,
    group_turns,
    load_entries,
)


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _user_typed(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant_text(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": "msg_test",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def test_find_latest_picks_newest_across_projects(tmp_path: Path) -> None:
    old = tmp_path / "projA" / "old.jsonl"
    new = tmp_path / "projB" / "new.jsonl"
    _write_jsonl(old, [_user_typed("old")])
    _write_jsonl(new, [_user_typed("new")])

    old_time = 1_700_000_000
    new_time = 1_800_000_000
    os.utime(old, (old_time, old_time))
    os.utime(new, (new_time, new_time))

    assert find_latest_transcript(tmp_path) == new


def test_find_latest_prefers_cwd_project_dir(tmp_path: Path) -> None:
    # Two projects, two transcripts. The non-cwd one is newer by mtime, but
    # we expect the cwd-matching one to win when cwd is passed.
    cwd = tmp_path / "work" / "my-proj"
    cwd.mkdir(parents=True)

    mine = tmp_path / "projects" / _project_dir_name(cwd) / "mine.jsonl"
    other = tmp_path / "projects" / "-some-other-proj" / "other.jsonl"
    _write_jsonl(mine, [_user_typed("mine")])
    _write_jsonl(other, [_user_typed("other")])

    old_time = 1_700_000_000
    new_time = 1_800_000_000
    os.utime(mine, (old_time, old_time))
    os.utime(other, (new_time, new_time))

    assert find_latest_transcript(tmp_path / "projects", cwd=cwd) == mine


def test_find_latest_falls_back_when_cwd_project_missing(tmp_path: Path) -> None:
    cwd = tmp_path / "unmapped"
    cwd.mkdir()

    only = tmp_path / "projects" / "-some-project" / "only.jsonl"
    _write_jsonl(only, [_user_typed("only")])

    assert find_latest_transcript(tmp_path / "projects", cwd=cwd) == only


def test_empty_jsonl_is_handled(tmp_path: Path) -> None:
    empty = tmp_path / "proj" / "empty.jsonl"
    empty.parent.mkdir(parents=True)
    empty.touch()

    assert load_entries(empty) == []
    assert group_turns(load_entries(empty)) == []


def test_midwrite_partial_line_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "proj" / "live.jsonl"
    path.parent.mkdir(parents=True)
    good_a = json.dumps(_user_typed("hello"))
    good_b = json.dumps(_assistant_text("hi back"))
    truncated = '{"type":"user","message":{"role":"user","content":"half-wri'
    path.write_text(good_a + "\n" + good_b + "\n" + truncated)

    entries = load_entries(path)
    assert len(entries) == 2
    turns = group_turns(entries)
    assert [t["role"] for t in turns] == ["user", "assistant"]


def test_project_dir_name_encodes_absolute_path() -> None:
    got = _project_dir_name(Path("/Users/lskarada/Documents/SkillForge"))
    assert got == "-Users-lskarada-Documents-SkillForge"
