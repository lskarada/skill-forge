"""Pain attribution — link rough-session signal to specific skills.

Two-pass design (paper §B.1 spirit, SkillForge S13 plan extension):
  1. Deterministic pass — pure-Python scans over PainSession:
       a) literal tool-call invocations of an inventory skill (confidence=high)
       b) word-boundary skill mentions in user-complaint turns (confidence=medium)
     The two scans are deduped per-skill, keeping the higher confidence.
  2. Subagent pass — Claude Code subagent reads PainSession + inventory and
     returns "should-have-triggered" skills the deterministic pass missed
     (confidence=medium).

`attribute(pain, inventory, io)` orchestrates both passes and returns a
unified list with high>medium>low precedence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from skill_forge.pain import PainSession

CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class SkillAttribution:
    skill: str
    confidence: str   # "high" | "medium" | "low"
    evidence: str


# --- Task 8.2: deterministic two-scan -------------------------------------


def _scan_literal_invocations(pain: PainSession, inventory: set[str]) -> dict[str, str]:
    """{skill -> evidence} for skills literally called via `Skill: <name>`."""
    found: dict[str, str] = {}
    for turn in pain.turns:
        for call in turn.tool_calls:
            m = re.match(r"\s*Skill:\s*([\w-]+)", call)
            if m and m.group(1) in inventory:
                found.setdefault(
                    m.group(1),
                    f"literal tool call '{call}'; "
                    f"errors={sorted(pain.error_signatures)[:3]}",
                )
    return found


def _scan_complaint_mentions(pain: PainSession, inventory: set[str]) -> dict[str, str]:
    """{skill -> evidence} for skills word-boundary-mentioned in complaint turns."""
    found: dict[str, str] = {}
    for phrase in pain.user_complaint_phrases:
        for skill in inventory:
            if re.search(rf"\b{re.escape(skill)}\b", phrase):
                found.setdefault(skill, f"complaint mention: {phrase!r}")
    return found


def attribute_deterministic(
    pain: PainSession, inventory: set[str],
) -> list[SkillAttribution]:
    high = _scan_literal_invocations(pain, inventory)
    medium = _scan_complaint_mentions(pain, inventory)

    out: list[SkillAttribution] = []
    for skill, evidence in high.items():
        out.append(SkillAttribution(skill=skill, confidence="high", evidence=evidence))
    for skill, evidence in medium.items():
        if skill in high:
            continue
        out.append(SkillAttribution(skill=skill, confidence="medium", evidence=evidence))
    return out


# --- Task 8.3: subagent pass ----------------------------------------------


_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _build_subagent_prompt(
    pain: PainSession, inventory: set[str], deterministic: list[SkillAttribution],
) -> str:
    return f"""You are an Attribution agent. Given a rough Claude Code session
and the local skills inventory, return any skills that SHOULD HAVE triggered
to prevent the observed pain but did not.

Anti-patterns:
- Don't propose a skill already in `already_attributed`.
- Don't propose a skill not in the `inventory`.
- Provide a one-line `reason` per missing skill.

## Pain summary
- turns: {len(pain.turns)}
- error_signatures: {sorted(pain.error_signatures)[:5]}
- user_complaints: {pain.user_complaint_phrases[:3]}

## Inventory
{sorted(inventory)}

## Already attributed (don't repeat these)
{[a.skill for a in deterministic]}

## Output

Respond with EXACTLY ONE fenced ```json block:
{{"missing_skills": [{{"skill": str, "reason": str}}, ...]}}

Do NOT edit any file. Output JSON only.
"""


def attribute_subagent(
    pain: PainSession, inventory: set[str],
    deterministic: list[SkillAttribution], *, io: object,
) -> list[SkillAttribution]:
    prompt = _build_subagent_prompt(pain, inventory, deterministic)
    raw = io.run(prompt=prompt, kind="propose", forbid_writes=True)  # type: ignore[attr-defined]

    m = _JSON_BLOCK.search(raw)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    out: list[SkillAttribution] = []
    for entry in data.get("missing_skills", []):
        skill = entry.get("skill")
        if skill in inventory:
            out.append(SkillAttribution(
                skill=skill, confidence="medium",
                evidence=f"subagent: {entry.get('reason', '')}",
            ))
    return out


def attribute(
    pain: PainSession, inventory: set[str], *, io: object | None = None,
) -> list[SkillAttribution]:
    """Orchestrate deterministic + subagent passes; dedupe by skill, keep
    the highest-confidence attribution per skill.
    """
    det = attribute_deterministic(pain, inventory)
    sub = attribute_subagent(pain, inventory, det, io=io) if io is not None else []

    by_skill: dict[str, SkillAttribution] = {}
    for a in det + sub:
        prior = by_skill.get(a.skill)
        if prior is None or CONFIDENCE_RANK[a.confidence] > CONFIDENCE_RANK[prior.confidence]:
            by_skill[a.skill] = a
    return list(by_skill.values())
