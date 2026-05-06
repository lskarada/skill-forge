"""Structured per-iteration log fed back to the Proposer subagent."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class FeedbackEntry:
    iter: int
    skill: str
    parent: str
    action: str            # "create" | "edit"
    proposal_summary: str
    verdict: str           # "admitted" | "discarded"
    score_delta: float
    reason: str
    ts: str


def append(log: Path, entry: FeedbackEntry) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def read_recent(log: Path, n: int) -> list[FeedbackEntry]:
    if not log.exists():
        return []
    lines = log.read_text(encoding="utf-8").splitlines()[-n:]
    return [FeedbackEntry(**json.loads(line)) for line in lines]
