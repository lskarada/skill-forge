"""Regression test for the greeter demo skill.

Failure captured: the loose "You respond to greetings." SKILL.md makes the
model hedge — it says "Hello!" but then offers help / asks a follow-up.
The expected post-optimize behavior is a bare greeting with no assistance
offer. See docs/DEMO.md for the full narrative.
"""

from skill_forge.harness.v1 import (
    assert_contains,
    assert_not_contains,
    run_skill,
)


def test_greeter_says_hello() -> None:
    out = run_skill(skill="greeter", replay="replays/20260419_154000.json")
    assert_contains(out, "Hello")


def test_greeter_does_not_hedge_or_offer_help() -> None:
    out = run_skill(skill="greeter", replay="replays/20260419_154000.json")
    assert_not_contains(out, "help you")
    assert_not_contains(out, "assist you")
    assert_not_contains(out, "How can I")
