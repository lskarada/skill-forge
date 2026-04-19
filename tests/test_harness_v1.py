"""Tests for skill_forge.harness.v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_forge.harness import v1
from skill_forge.harness.v1 import (
    assert_contains,
    assert_json_has_field,
    assert_matches_schema,
    assert_min_sources,
    assert_not_contains,
    assert_regex,
    run_skill,
)


# --- assert_contains / not_contains ---------------------------------------


def test_assert_contains_passes() -> None:
    assert_contains("hello world", "world")


def test_assert_contains_raises_on_miss() -> None:
    with pytest.raises(AssertionError, match="expected output to contain"):
        assert_contains("hello world", "planet")


def test_assert_not_contains_passes() -> None:
    assert_not_contains("hello world", "planet")


def test_assert_not_contains_raises_on_hit() -> None:
    with pytest.raises(AssertionError, match="NOT to contain"):
        assert_not_contains("I'm sorry, as an AI", "I'm sorry")


# --- assert_regex ---------------------------------------------------------


def test_assert_regex_passes() -> None:
    assert_regex("token: abc123", r"token:\s*\w+")


def test_assert_regex_raises_on_miss() -> None:
    with pytest.raises(AssertionError, match="to match"):
        assert_regex("no match here", r"^\d+$")


# --- assert_json_has_field ------------------------------------------------


def test_assert_json_has_field_root_direct_json() -> None:
    assert_json_has_field('{"sources": []}', "sources")


def test_assert_json_has_field_embedded_in_prose() -> None:
    output = "Here's the answer: {\"sources\": [\"a\"], \"answer\": 42}. Hope that helps."
    assert_json_has_field(output, "answer")


def test_assert_json_has_field_with_parent() -> None:
    assert_json_has_field('{"data": {"ok": true}}', "ok", parent="data")


def test_assert_json_has_field_missing_field_raises() -> None:
    with pytest.raises(AssertionError, match="expected field"):
        assert_json_has_field('{"sources": []}', "missing")


def test_assert_json_has_field_no_json_raises() -> None:
    with pytest.raises(AssertionError, match="parseable JSON"):
        assert_json_has_field("just prose", "field")


# --- assert_matches_schema ------------------------------------------------


def test_assert_matches_schema_passes() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }
    assert_matches_schema('{"name": "Lance", "age": 21}', schema)


def test_assert_matches_schema_fails_with_path() -> None:
    schema = {
        "type": "object",
        "properties": {"age": {"type": "integer"}},
        "required": ["age"],
    }
    with pytest.raises(AssertionError, match="schema validation"):
        assert_matches_schema('{"age": "old"}', schema)


# --- assert_min_sources ---------------------------------------------------


def test_assert_min_sources_with_strings() -> None:
    assert_min_sources('{"sources": ["a", "b", "c"]}', 3)


def test_assert_min_sources_with_objects_dedups_on_id() -> None:
    data = json.dumps({"sources": [{"id": "x"}, {"id": "y"}, {"id": "x"}]})
    assert_min_sources(data, 2)
    with pytest.raises(AssertionError, match="at least 3 distinct sources"):
        assert_min_sources(data, 3)


def test_assert_min_sources_missing_field_raises() -> None:
    with pytest.raises(AssertionError, match="`sources` field"):
        assert_min_sources('{"answer": 42}', 1)


def test_assert_min_sources_non_list_raises() -> None:
    with pytest.raises(AssertionError, match="list"):
        assert_min_sources('{"sources": "not a list"}', 1)


# --- run_skill ------------------------------------------------------------


def test_run_skill_delegates_to_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    replay = tmp_path / "replay.json"
    replay.write_text("{}")

    called: dict[str, str] = {}

    def fake(skill: str, replay: str) -> str:
        called["skill"] = skill
        called["replay"] = replay
        return "FAKE OUTPUT"

    from skill_forge import dispatch

    monkeypatch.setattr(dispatch, "run_skill", fake)

    out = run_skill(skill="demo", replay=str(replay))
    assert out == "FAKE OUTPUT"
    assert called["skill"] == "demo"
    assert called["replay"] == str(replay.resolve())


def test_run_skill_exports_match_prd_v1() -> None:
    # Guardrail: the v1 surface is locked (PRD §4.1). If someone adds or
    # removes a helper, they must bump to v2 — this catches accidental churn.
    assert set(v1.__all__) == {
        "run_skill",
        "assert_contains",
        "assert_not_contains",
        "assert_regex",
        "assert_json_has_field",
        "assert_matches_schema",
        "assert_min_sources",
    }
