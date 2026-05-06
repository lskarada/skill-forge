"""Regression: scribe must emit a markdown bullet list, not prose.

Failure captured: vague "Format the input nicely." baseline emits "Here
are the items: foo, bar, baz" — prose, no bullet markers. Downstream
markdown renderers expect `- ` line prefixes.
"""
from skill_forge.harness.v1 import (
    assert_not_contains,
    assert_regex,
    run_skill,
)


def test_scribe_emits_markdown_bullets():
    output = run_skill(
        "scribe",
        replay="replays/20260505_171500.json",
    )
    # Every non-empty line must start with "- " (markdown bullet).
    assert_regex(output, r"(?m)^- \S")
    # Forbid prose runs that betray the failure mode.
    assert_not_contains(output, "Here are the items")
    assert_not_contains(output, ", ")  # comma-separated prose smell
