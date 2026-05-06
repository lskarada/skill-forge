"""Tasks 8.2 + 8.3 — attribution: deterministic two-scan + subagent pass."""
from __future__ import annotations

from dataclasses import dataclass, field

from skill_forge.attribution import (
    SkillAttribution,
    attribute,
    attribute_deterministic,
    attribute_subagent,
)
from skill_forge.pain import PainSession, Turn


@dataclass
class FakeIO:
    responses: list[str]
    calls: list[dict] = field(default_factory=list)

    def run(self, *, prompt: str, kind: str, forbid_writes: bool) -> str:
        self.calls.append({"kind": kind, "forbid_writes": forbid_writes})
        return self.responses.pop(0)


def test_literal_tool_call_yields_high_confidence() -> None:
    pain = PainSession(
        turns=[
            Turn(role="assistant", text="Using greeter", tool_calls=("Skill: greeter",)),
            Turn(role="tool_result", text="TypeError on greeter output"),
        ],
        error_signatures={"TypeError"},
        changed_files=set(),
        user_complaint_phrases=[],
    )
    attributions = attribute_deterministic(pain, inventory={"greeter", "scribe"})

    assert len(attributions) == 1
    assert attributions[0].skill == "greeter"
    assert attributions[0].confidence == "high"


def test_complaint_text_mention_yields_medium_confidence() -> None:
    pain = PainSession(
        turns=[Turn(role="user", text="the greeter is broken", tool_calls=())],
        error_signatures=set(),
        changed_files=set(),
        user_complaint_phrases=["the greeter is broken"],
    )
    attributions = attribute_deterministic(pain, inventory={"greeter", "scribe"})

    assert len(attributions) == 1
    assert attributions[0].skill == "greeter"
    assert attributions[0].confidence == "medium"


def test_literal_invocation_dedupes_with_complaint_mention() -> None:
    pain = PainSession(
        turns=[
            Turn(role="assistant", text="Using greeter", tool_calls=("Skill: greeter",)),
            Turn(role="user", text="the greeter is broken", tool_calls=()),
        ],
        error_signatures={"TypeError"},
        changed_files=set(),
        user_complaint_phrases=["the greeter is broken"],
    )
    attributions = attribute_deterministic(pain, inventory={"greeter", "scribe"})

    assert len(attributions) == 1
    assert attributions[0].confidence == "high"


def test_subagent_pass_finds_missing_skills_via_stub() -> None:
    pain = PainSession(turns=[], error_signatures={"TypeError"},
                       changed_files=set(), user_complaint_phrases=[])
    inventory = {"greeter", "data-extraction"}
    deterministic: list[SkillAttribution] = []
    fake_io = FakeIO(responses=[
        '```json\n{"missing_skills":[{"skill":"data-extraction","reason":"TypeError on tabular parse"}]}\n```',
    ])

    additional = attribute_subagent(pain, inventory, deterministic, io=fake_io)

    assert len(additional) == 1
    assert additional[0].skill == "data-extraction"
    assert additional[0].confidence == "medium"
    assert fake_io.calls[0]["forbid_writes"] is True


def test_attribute_combines_deterministic_and_subagent_dedup() -> None:
    pain = PainSession(
        turns=[Turn(role="assistant", text="Using greeter", tool_calls=("Skill: greeter",))],
        error_signatures={"TypeError"},
        changed_files=set(),
        user_complaint_phrases=[],
    )
    inventory = {"greeter", "data-extraction"}
    fake_io = FakeIO(responses=[
        # Subagent re-suggests greeter (already deterministically high) — should dedupe to high
        '```json\n{"missing_skills":[{"skill":"greeter","reason":"x"},{"skill":"data-extraction","reason":"y"}]}\n```',
    ])

    out = attribute(pain, inventory, io=fake_io)

    by_skill = {a.skill: a for a in out}
    assert by_skill["greeter"].confidence == "high"   # deterministic wins
    assert by_skill["data-extraction"].confidence == "medium"  # subagent only
