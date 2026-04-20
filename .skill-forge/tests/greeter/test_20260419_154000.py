"""Regression test for the greeter demo skill.

Failure captured: the vague "You respond to greetings." SKILL.md does
not specify any output contract. A downstream consumer expecting a
schema-tagged JSON envelope (common when a parser validates a
version/schema discriminator before extracting fields) cannot use the
reply. Expected post-optimize behavior: SKILL mandates a JSON object
with both a `_schema` tag and a `greeting` field. See docs/DEMO.md.
"""

from skill_forge.harness.v1 import (
    assert_matches_schema,
    run_skill,
)

GREETER_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["_schema", "greeting"],
    "properties": {
        "_schema": {"const": "skill-forge/greeter/v1"},
        "greeting": {"type": "string"},
    },
}


def test_greeter_returns_tagged_json_envelope() -> None:
    out = run_skill(skill="greeter", replay="replays/20260419_154000.json")
    assert_matches_schema(out, GREETER_ENVELOPE_SCHEMA)
