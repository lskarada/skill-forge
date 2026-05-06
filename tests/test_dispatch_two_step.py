"""Task 4.5 — propose → build orchestration in dispatch.mutate_skill."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from skill_forge import dispatch


@dataclass
class _Call:
    kind: str
    forbid_writes: bool
    prompt: str


@dataclass
class _Event:
    kind: str
    payload: object


@dataclass
class FakeSubagentIO:
    responses: list[str]
    calls: list[_Call] = field(default_factory=list)

    def run(self, *, prompt: str, kind: str, forbid_writes: bool) -> str:
        self.calls.append(_Call(kind=kind, forbid_writes=forbid_writes, prompt=prompt))
        if not self.responses:
            raise AssertionError(f"FakeSubagentIO ran out of responses on call {kind!r}")
        return self.responses.pop(0)


@dataclass
class FakeStateBus:
    events: list[_Event] = field(default_factory=list)

    def emit(self, kind: str, payload: object) -> None:
        self.events.append(_Event(kind=kind, payload=payload))


def test_mutate_skill_calls_propose_then_build(tmp_path: Path) -> None:
    sut = tmp_path / "MUTATION_TARGET.md"
    sut.write_text("You respond to greetings.\n")

    fake_io = FakeSubagentIO(responses=[
        '```json\n{"action":"edit","target_skill":"greeter","proposed_skill":"add schema","justification":"x"}\n```',
        "Added explicit JSON envelope spec to SKILL.md.",
    ])
    fake_state = FakeStateBus()

    summary = dispatch.mutate_skill(
        sut_path=sut,
        cwd=tmp_path,
        tests_preview="def test_x(): ...",
        learnings="",
        strategy="",
        io=fake_io,
        state=fake_state,
    )

    assert len(fake_io.calls) == 2
    assert fake_io.calls[0].kind == "propose"
    assert fake_io.calls[0].forbid_writes is True
    assert fake_io.calls[1].kind == "build"
    assert fake_io.calls[1].forbid_writes is False
    assert "Added explicit JSON envelope" in summary
    assert any(ev.kind == "MutationProposal" for ev in fake_state.events)
