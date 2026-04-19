"""Prompt templates used by the capture and mutation subagents.

Kept separate from dispatch.py so the prompts can be edited and diffed
without touching the orchestration plumbing. A skill-forge "fat skill":
all the intelligence is in these templates, not in the Python.
"""

from __future__ import annotations

CAPTURE_SCHEMA_DESCRIPTION = """\
Return a single JSON object with EXACTLY these keys:

- "skill_name" (string): the skill or subagent that misbehaved. Lowercase,
  kebab-case. If you cannot identify it, use "unknown".
- "failure_note" (string): a short human-readable explanation of what went
  wrong. Under 300 characters.
- "source_turn_index" (integer): the 0-indexed position of the failing turn
  in the FULL transcript excerpt below.
- "conversation" (array of objects): the ordered list of turns to replay.
  Each element has "role" ("user" or "assistant") and "content" (string).
  Include every turn up to and including the user message that triggered
  the failure. Do not include tool_use / tool_result plumbing — just the
  spoken turns a fresh subagent needs to recreate the situation.
- "trigger_turn_index" (integer): 0-indexed position within
  `conversation` of the final user message that triggered the failure.
  MUST point at a role:"user" entry.
- "test_code" (string): a complete Python file that imports ONLY from
  `skill_forge.harness.v1` and uses ONLY these helpers:
    run_skill, assert_contains, assert_not_contains, assert_regex,
    assert_json_has_field, assert_matches_schema, assert_min_sources
  The test MUST call run_skill(skill=<skill_name>, replay="replays/<basename>.json")
  using a relative replay path — Skill-Forge rewrites this at write time.
  Include a docstring at the top of the file summarizing why this test exists.
- "cannot_express_in_dsl" (boolean): true ONLY if the correct assertion
  genuinely cannot be written with the v1 helpers. Default false.
- "reason" (string): if cannot_express_in_dsl is true, explain why. Otherwise "".
- "escape_hatch_test_code" (string): if cannot_express_in_dsl is true,
  provide a best-effort free-form pytest file (no harness import restriction)
  for the user to accept as an escape hatch. Otherwise "".

Output ONLY the JSON. No commentary before or after. No markdown fences.
"""


CAPTURE_PROMPT_TEMPLATE = """\
You are the capture agent for Skill-Forge.

## Your job

Read the Claude Code transcript excerpt below. Identify (1) which skill or
subagent was invoked, (2) what went wrong in the last assistant turn, and
(3) draft a pytest regression test that would have caught the failure.

## The Assertion DSL (the ONLY helpers you may use in the default test)

| Helper | Purpose |
|---|---|
| run_skill(skill, replay) | Spawns a fresh subagent with the SUT loaded and replay fed in; returns its final assistant output. |
| assert_contains(output, phrase) | `phrase in output` |
| assert_not_contains(output, phrase) | `phrase not in output` |
| assert_regex(output, pattern) | `re.search(pattern, output) is not None` |
| assert_json_has_field(output, field, parent=None) | Parses JSON, asserts field present. |
| assert_matches_schema(output, schema) | Validates parsed JSON against jsonschema Draft 2020-12. |
| assert_min_sources(output, n) | Asserts at least n distinct sources in JSON output. |

The test should import ONLY from `skill_forge.harness.v1`. No fixtures. No
conftest. No class-based tests. One replay, one or more helper calls.

## Output format

{schema}

## Hint (optional)

{hint}

## Transcript excerpt

{excerpt}
"""


def build_capture_prompt(transcript_excerpt: str, target_hint: str | None) -> str:
    hint = (
        f"The user has pointed Skill-Forge at this target file: {target_hint}.\n"
        "Prefer this as the misbehaving skill unless the transcript clearly says otherwise."
        if target_hint
        else "(no --target flag supplied; infer the skill from the transcript)"
    )
    return CAPTURE_PROMPT_TEMPLATE.format(
        schema=CAPTURE_SCHEMA_DESCRIPTION,
        hint=hint,
        excerpt=transcript_excerpt,
    )


# --- mutation prompt ------------------------------------------------------

MUTATION_PROMPT_TEMPLATE = """\
You are the mutation agent for Skill-Forge.

## Your job

Edit the skill definition at `{sut_relative_path}` so that the existing
regression test suite passes. You are running inside a fresh git worktree.
You may edit only this one file. Do not touch tests, code, or config.

## Rules

1. Edit the markdown at `{sut_relative_path}` in place. After editing, save
   the file and stop — Skill-Forge will commit and run tests.
2. Do NOT run tests yourself. Do NOT create new files. Do NOT delete files.
3. Keep the skill's intent intact — you are *improving* the instructions,
   not replacing the skill's purpose.
4. Avoid edits that have already been tried and failed (see Learnings).
5. Follow the Strategy directive below — it's the specific lens to optimize
   through on this attempt.

## Strategy directive for this mutation

{strategy}

## Current skill definition

```markdown
{sut_content}
```

## Regression tests the mutated skill must satisfy

```
{tests_preview}
```

## Learnings (mutations that already failed — do not repeat)

{learnings}

## Final instructions

Read the tests carefully. Think about what assertions they make about the
skill's output. Rewrite the markdown at `{sut_relative_path}` to satisfy
those assertions while applying the strategy directive.

When you are done editing the file, reply with a single line summarizing
what you changed and why. Nothing else.
"""


DEFAULT_MUTATION_STRATEGY = (
    "Tighten the output contract. If tests assert structure (JSON fields, "
    "schema), add an explicit output-format section. If tests assert absent "
    "phrases, add a forbidden-phrases list. Keep the skill concise."
)


# The PRD (§3, Phase 3) calls for a *strategy directive that varies per
# subagent* so parallel mutations explore different lenses instead of
# converging on the same edit. Each string below is self-contained — the
# mutation agent reads exactly one of them per worker.
DEFAULT_STRATEGIES: tuple[str, ...] = (
    DEFAULT_MUTATION_STRATEGY,
    (
        "Restructure the skill as a numbered checklist. Each step must be "
        "imperative and testable. Collapse prose paragraphs into bullets. "
        "If the skill has an output contract, promote it to step 1."
    ),
    (
        "Add a stricter output schema block. State required fields, allowed "
        "types, and forbidden values explicitly. Prefer a JSON-schema-like "
        "fenced block the model can pattern-match against at output time."
    ),
    (
        "Rewrite the skill's description and activation heuristics so the "
        "right trigger conditions are unambiguous. Clarify when the skill "
        "applies vs. when it should defer. Leave the body alone unless it "
        "contradicts the new description."
    ),
    (
        "Tighten the examples. Remove examples that contradict the tests, "
        "add one minimal example that demonstrates the exact contract the "
        "tests assert, and make sure every example's output would pass the "
        "assertions verbatim."
    ),
)


def strategies_for(n: int, override: list[str] | None = None) -> list[str]:
    """Return `n` strategy directives, cycling DEFAULT_STRATEGIES if needed.

    If `override` is supplied, it wins — pad by cycling the override list
    itself if fewer strategies than workers were provided.
    """
    if n <= 0:
        return []
    source = override if override else list(DEFAULT_STRATEGIES)
    if not source:
        source = [DEFAULT_MUTATION_STRATEGY]
    return [source[i % len(source)] for i in range(n)]


def build_mutation_prompt(
    *,
    sut_relative_path: str,
    sut_content: str,
    tests_preview: str,
    learnings: str,
    strategy: str,
) -> str:
    return MUTATION_PROMPT_TEMPLATE.format(
        sut_relative_path=sut_relative_path,
        sut_content=sut_content,
        tests_preview=tests_preview,
        learnings=learnings or "(none yet)",
        strategy=strategy or DEFAULT_MUTATION_STRATEGY,
    )
