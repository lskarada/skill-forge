"""v0.8.2-S1 — synthesis.synthesize_test driver tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skill_forge.attribution import SkillAttribution
from skill_forge.pain import PainSession, Turn
from skill_forge.synthesis import SynthesisResult, synthesize_test


@dataclass
class _FakeIO:
    responses: list[str]
    calls: list[dict] = field(default_factory=list)

    def run(self, *, prompt: str, kind: str, forbid_writes: bool) -> str:
        self.calls.append({"kind": kind, "prompt": prompt})
        return self.responses.pop(0)


def _pain_for(skill: str) -> PainSession:
    return PainSession(
        turns=[
            Turn(role="user", text=f"the {skill} is broken"),
            Turn(role="assistant", text="Using skill", tool_calls=(f"Skill: {skill}",)),
            Turn(role="user", text="no, the output isn't tagged with _schema"),
        ],
        error_signatures={"TypeError"},
        changed_files=set(),
        user_complaint_phrases=["no, the output isn't tagged"],
    )


def _valid_response(replay_filename_hint: str) -> str:
    """Returns a response whose test_code uses the replay filename the
    prompt told the subagent to use. We grep the prompt to extract it
    when constructing the test in the harness — but for tests we just
    pass any path; the validator's harness-only contract is what matters."""
    test_code = (
        "from skill_forge.harness.v1 import run_skill, assert_contains\n"
        "\n"
        f"def test_envelope_includes_schema():\n"
        f"    output = run_skill('greeter', replay='replays/{replay_filename_hint}')\n"
        f"    assert_contains(output, '_schema')\n"
    )
    return (
        '```json\n'
        '{\n'
        f'  "test_code": {test_code!r},\n'
        '  "replay_user_input": "format these as a JSON envelope: foo, bar",\n'
        '  "rationale": "user complained the output isn\'t tagged with _schema"\n'
        '}\n'
        '```'
    )


def test_synthesize_admits_when_validator_passes_and_runner_red(tmp_path: Path) -> None:
    output_root = tmp_path / ".skill-forge"
    pain = _pain_for("greeter")
    attr = SkillAttribution(skill="greeter", confidence="high", evidence="ev")

    fake_io = _FakeIO(responses=[_valid_response("ANY.json")])

    def loader(_skill: str) -> str:
        return "# greeter\n\nRespond to greetings.\n"

    # Baseline runner returns False (test fails) for every call → admitted
    runs_seen: list[Path] = []

    def runner(p: Path) -> bool:
        runs_seen.append(p)
        return False

    result = synthesize_test(
        pain=pain, attribution=attr, io=fake_io,
        output_root=output_root, skill_loader=loader,
        baseline_runner=runner, n_runs=5,
    )

    assert isinstance(result, SynthesisResult)
    assert result.admitted_path is not None
    assert result.admitted_path.exists()
    assert result.admitted_path.parent == output_root / "tests" / "greeter"
    # Replay file written
    replays = list((output_root / "tests" / "greeter" / "replays").glob("*.json"))
    assert len(replays) == 1
    # Baseline runner invoked exactly n_runs times
    assert len(runs_seen) == 5
    assert result.rejected_paths == []


def test_synthesize_rejects_unparseable_response(tmp_path: Path) -> None:
    output_root = tmp_path / ".skill-forge"
    pain = _pain_for("greeter")
    attr = SkillAttribution(skill="greeter", confidence="high", evidence="ev")
    fake_io = _FakeIO(responses=["not json at all"])

    result = synthesize_test(
        pain=pain, attribution=attr, io=fake_io,
        output_root=output_root, skill_loader=lambda _s: "# greeter",
    )

    assert result.admitted_path is None
    assert result.reason == "parse_failed"
    rejects = list((output_root / "synthesis_rejects" / "greeter").glob("*"))
    assert any("parse_failed" in p.name for p in rejects)


def test_synthesize_rejects_when_validator_fails(tmp_path: Path) -> None:
    output_root = tmp_path / ".skill-forge"
    pain = _pain_for("greeter")
    attr = SkillAttribution(skill="greeter", confidence="high", evidence="ev")

    # Test code uses `import pytest` → AST validator rejects.
    bad_test_code = (
        "import pytest\n"
        "from skill_forge.harness.v1 import run_skill\n"
        "\n"
        "def test_x():\n"
        "    run_skill('greeter', replay='x.json')\n"
    )
    fake_io = _FakeIO(responses=[
        '```json\n{"test_code": ' + repr(bad_test_code) + ', '
        '"replay_user_input": "hi", "rationale": "x"}\n```',
    ])

    result = synthesize_test(
        pain=pain, attribution=attr, io=fake_io,
        output_root=output_root, skill_loader=lambda _s: "# greeter",
    )

    assert result.admitted_path is None
    assert result.reason == "validator_rejected"
    rejects = list((output_root / "synthesis_rejects" / "greeter").glob("*"))
    assert any("validator_rejected" in p.name for p in rejects)
    # Test should NOT be left in the tests dir.
    tests = list((output_root / "tests" / "greeter").glob("test_*.py"))
    assert tests == []


def test_synthesize_rejects_flaky_baseline(tmp_path: Path) -> None:
    output_root = tmp_path / ".skill-forge"
    pain = _pain_for("greeter")
    attr = SkillAttribution(skill="greeter", confidence="high", evidence="ev")
    fake_io = _FakeIO(responses=[_valid_response("ANY.json")])

    # Runner returns True (passed) on first call → flaky → reject
    def runner(_p: Path) -> bool:
        return True

    result = synthesize_test(
        pain=pain, attribution=attr, io=fake_io,
        output_root=output_root, skill_loader=lambda _s: "# greeter",
        baseline_runner=runner, n_runs=5,
    )

    assert result.admitted_path is None
    assert result.reason == "baseline_passed"
    rejects = list((output_root / "synthesis_rejects" / "greeter").glob("*"))
    assert any("baseline_passed" in p.name for p in rejects)


def test_synthesize_skips_baseline_when_runner_is_none(tmp_path: Path) -> None:
    """Unit-test mode: caller signals 'trust the AST validator only'."""
    output_root = tmp_path / ".skill-forge"
    pain = _pain_for("greeter")
    attr = SkillAttribution(skill="greeter", confidence="high", evidence="ev")
    fake_io = _FakeIO(responses=[_valid_response("ANY.json")])

    result = synthesize_test(
        pain=pain, attribution=attr, io=fake_io,
        output_root=output_root, skill_loader=lambda _s: "# greeter",
        baseline_runner=None,
    )
    assert result.admitted_path is not None
