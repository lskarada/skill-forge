from pathlib import Path

from skill_forge.feedback_history import FeedbackEntry
from skill_forge.proposer import Proposal, build_prompt, parse_response


def test_build_prompt_includes_required_sections():
    prompt = build_prompt(
        sut_relative_path=Path(".claude/skills/greeter/SKILL.md"),
        existing_skill_text="You respond to greetings.",
        failures_summary="test_greeter_returns_tagged_json_envelope: AssertionError",
        recent_history=[],
        tests_preview="test_greeter_returns_tagged_json_envelope.py",
    )

    assert "Brainstorming skill" in prompt or "performance analyst" in prompt
    assert "DISCARDED" in prompt
    assert "test_greeter_returns_tagged_json_envelope" in prompt
    assert "You respond to greetings." in prompt
    assert "do not edit any file" in prompt.lower()


def test_parse_response_extracts_action_and_proposal():
    raw = """
    Some preamble.
    ```json
    {"action": "edit",
     "target_skill": "greeter",
     "proposed_skill": "Add explicit JSON envelope spec.",
     "justification": "Test asserts schema match."}
    ```
    Trailing junk.
    """
    proposal = parse_response(raw)
    assert isinstance(proposal, Proposal)
    assert proposal.action == "edit"
    assert proposal.target_skill == "greeter"
    assert "envelope" in proposal.proposed_skill
    assert proposal.justification.startswith("Test")
