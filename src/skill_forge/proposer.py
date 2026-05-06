"""Proposer subagent — analyzes failures, proposes a skill change.

Paper reference: EvoSkill §B.1 (proposer prompt header lifted into prompts.py).
This module ONLY builds the prompt and parses the JSON response;
subagent dispatch lives in dispatch.py.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from skill_forge.feedback_history import FeedbackEntry
from skill_forge.prompts import PROPOSER_PROMPT_HEADER


@dataclass(frozen=True)
class Proposal:
    action: str          # "create" | "edit"
    target_skill: str | None
    proposed_skill: str
    justification: str


def build_prompt(
    *,
    sut_relative_path: Path,
    existing_skill_text: str,
    failures_summary: str,
    recent_history: list[FeedbackEntry],
    tests_preview: str,
) -> str:
    history_block = "\n".join(
        f"- iter={e.iter} verdict={e.verdict} delta={e.score_delta:+.3f}: {e.proposal_summary}"
        for e in recent_history[-20:]
    ) or "(no prior iterations)"

    return f"""{PROPOSER_PROMPT_HEADER}

## Failures observed (training set)

{failures_summary}

## Existing skill at {sut_relative_path}

```
{existing_skill_text}
```

## Tests preview

{tests_preview}

## Feedback history (most recent first)

{history_block}

## Output

Respond with EXACTLY ONE fenced ```json block containing:
{{"action": "create"|"edit",
  "target_skill": str|null,
  "proposed_skill": str,
  "justification": str}}

Do NOT edit any file in this turn. Output JSON only.
"""


_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def parse_response(raw: str) -> Proposal:
    m = _JSON_BLOCK.search(raw)
    if not m:
        raise ValueError(f"no ```json block in response: {raw[:200]!r}")
    data = json.loads(m.group(1))
    return Proposal(
        action=data["action"],
        target_skill=data.get("target_skill"),
        proposed_skill=data["proposed_skill"],
        justification=data["justification"],
    )
