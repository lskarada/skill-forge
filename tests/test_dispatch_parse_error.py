"""v0.8.1-D1 — dispatch.mutate_skill resilience to non-JSON Proposer output."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skill_forge import dispatch


@dataclass
class _FakeIO:
    responses: list[str]
    calls: list[dict] = field(default_factory=list)

    def run(self, *, prompt: str, kind: str, forbid_writes: bool) -> str:
        self.calls.append({"kind": kind})
        return self.responses.pop(0)


def test_unparseable_proposer_response_returns_sentinel(tmp_path: Path) -> None:
    sut = tmp_path / "SKILL.md"
    sut.write_text("hello")

    fake_io = _FakeIO(responses=["this is not JSON, just prose"])

    summary = dispatch.mutate_skill(
        sut_path=sut, cwd=tmp_path,
        tests_preview="def test_x(): ...",
        learnings="", strategy="",
        io=fake_io,
    )

    assert "proposer JSON unparseable" in summary
    # Builder must NOT have been called — propose failed first.
    assert len(fake_io.calls) == 1
    assert fake_io.calls[0]["kind"] == "propose"


def test_propose_response_missing_field_returns_sentinel(tmp_path: Path) -> None:
    """A well-formed JSON block but missing required fields hits KeyError;
    same fallback as a non-JSON response."""
    sut = tmp_path / "SKILL.md"
    sut.write_text("hello")

    # Valid JSON, but no `action` field — proposer.parse_response raises KeyError
    fake_io = _FakeIO(responses=['```json\n{"foo": "bar"}\n```'])

    summary = dispatch.mutate_skill(
        sut_path=sut, cwd=tmp_path,
        tests_preview="", learnings="", strategy="",
        io=fake_io,
    )
    assert "proposer JSON unparseable" in summary
