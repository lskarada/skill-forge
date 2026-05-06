"""Skill-Builder subagent — materializes a proposal into edited skill files.

Paper reference: EvoSkill §B.2. The builder dispatches AFTER the proposer
returns its JSON proposal. It edits MUTATION_TARGET/ in place and returns
a single-line summary; it does NOT run tests (the harness owns that).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skill_forge.proposer import Proposal


def build_prompt(
    *,
    proposal: Proposal,
    sut_relative_path: Path,
    existing_skill_text: str,
    tests_preview: str,
) -> str:
    return f"""You are a Skill-Builder subagent. The Proposer has analyzed a failure
and produced the proposal below. Materialize it by editing the skill at
{sut_relative_path} (relative to the worktree root).

## Proposer's proposal

action: {proposal.action}
target_skill: {proposal.target_skill}
proposed_skill:
{proposal.proposed_skill}

justification:
{proposal.justification}

## Current contents of {sut_relative_path}

```
{existing_skill_text}
```

## Tests preview

{tests_preview}

## Rules

- Edit ONLY {sut_relative_path} (or files inside its parent directory).
- Do NOT run tests, do NOT execute pytest, do NOT spawn subprocesses.
- After editing, output exactly ONE single-line summary describing the
  change (no preamble, no JSON, no commentary).
"""


def parse_summary(raw: str) -> str:
    for line in reversed(raw.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
