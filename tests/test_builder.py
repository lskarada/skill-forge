from pathlib import Path

from skill_forge.builder import build_prompt, parse_summary
from skill_forge.proposer import Proposal


def test_build_prompt_includes_proposal_and_sut_path():
    proposal = Proposal(
        action="edit",
        target_skill="greeter",
        proposed_skill="Add explicit JSON envelope spec to SKILL.md.",
        justification="Test asserts schema match.",
    )
    prompt = build_prompt(
        proposal=proposal,
        sut_relative_path=Path("MUTATION_TARGET/SKILL.md"),
        existing_skill_text="You respond to greetings.",
        tests_preview="test_greeter_returns_tagged_json_envelope.py",
    )

    assert "MUTATION_TARGET/SKILL.md" in prompt
    assert "Add explicit JSON envelope spec" in prompt
    assert "do not run" in prompt.lower() or "do not execute" in prompt.lower()
    assert "single" in prompt.lower() and "summary" in prompt.lower()


def test_parse_summary_returns_last_non_empty_line():
    raw = """
    Edited MUTATION_TARGET/SKILL.md.

    Added explicit JSON envelope spec to SKILL.md.

    """
    assert parse_summary(raw) == "Added explicit JSON envelope spec to SKILL.md."


def test_parse_summary_handles_single_line():
    assert parse_summary("Wrote schema.\n") == "Wrote schema."
