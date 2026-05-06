"""Top-level retro flow: session pain → portfolio of merged skill updates.

Glues `pain.ingest` → `attribution.attribute` → `campaign.run_campaign`.
Synthesis is invoked inside `campaign.run_campaign` (per Task 8.7e:
campaign skips run_evolution when synthesis admits zero tests).

This module is intentionally thin (≤ 80 LOC). Heavy lifting lives in
the composed primitives — pain, attribution, synthesis, campaign.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from skill_forge import attribution as attribution_mod
from skill_forge import campaign as campaign_mod
from skill_forge import pain as pain_mod


def run(
    *,
    transcripts_dir: Path,
    git_diff_path: Path | None,
    skills_inventory: Iterable[str],
    generations: int = 2,
    frontier_size: int = 2,
    workers_per_skill: int = 3,
    patience: int = 2,
    min_confidence: str = "low",
    io: object | None = None,
    synthesize_test=None,
    run_one_generation=None,
) -> campaign_mod.Portfolio:
    """Run the full retro flow against `transcripts_dir`. Returns a Portfolio.

    `io` is the dispatch IO injected into the Attribution subagent pass.
    `synthesize_test(skill, attribution) -> path | None` is the synthesizer
    used by Campaign for the per-skill test admission gate (Task 8.7e).
    """
    # since=None for fixture-driven runs (rough_session/) — production
    # `forge retro` already passes a real cwd-resolved transcripts dir
    # whose recent jsonl files satisfy the default 24h slice.
    pain = pain_mod.ingest(
        transcripts_dir=transcripts_dir, git_diff_path=git_diff_path,
        since=None,
    )
    inventory_set = set(skills_inventory)
    attributions = attribution_mod.attribute(pain, inventory_set, io=io)

    portfolio = campaign_mod.run_campaign(
        attributions,
        generations=generations,
        frontier_size=frontier_size,
        workers_per_skill=workers_per_skill,
        patience=patience,
        min_confidence=min_confidence,
        synthesize_test=synthesize_test,
        run_one_generation=run_one_generation,
    )
    return portfolio
