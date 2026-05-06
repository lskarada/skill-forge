"""Program metadata for the v0.5 multi-generation frontier.

Each frontier entry has a sibling `program.yaml` under
`.skill-forge/programs/<skill>/<id>/program.yaml`, recording the
parent program id, generation, score, and timestamps. We hand-roll
a flat-YAML reader/writer instead of pulling in PyYAML — pyyaml
isn't a runtime dep and the CLAUDE.md "no environment changes"
rule is in force. The format is JSON-compatible YAML (a subset
both formats accept), so a future migration to PyYAML or json is
a one-line swap.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

BASELINE_SENTINEL = "baseline"


@dataclass(frozen=True)
class Program:
    id: str           # e.g. "g0-w0"
    parent: str       # parent id, or "baseline"
    gen: int
    score: float
    skill_len: int
    created_at: str   # ISO 8601 UTC, e.g. "2026-05-05T18:00:00Z"


_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$")


def _parse_value(raw: str) -> str | int | float:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return json.loads(raw)
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def write_program(path: Path, program: Program) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for k, v in asdict(program).items():
        if isinstance(v, str):
            # JSON-quote so embedded colons / newlines survive the round-trip.
            lines.append(f"{k}: {json.dumps(v)}")
        else:
            lines.append(f"{k}: {v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_program(path: Path) -> Program:
    fields: dict[str, object] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _LINE_RE.match(raw)
        if not m:
            raise ValueError(f"unparseable program.yaml line: {raw!r}")
        fields[m.group(1)] = _parse_value(m.group(2))

    return Program(
        id=str(fields["id"]),
        parent=str(fields["parent"]),
        gen=int(fields["gen"]),  # type: ignore[arg-type]
        score=float(fields["score"]),  # type: ignore[arg-type]
        skill_len=int(fields["skill_len"]),  # type: ignore[arg-type]
        created_at=str(fields["created_at"]),
    )


def lineage_chain(*, programs_root: Path, leaf_id: str) -> list[Program]:
    """Walk parent pointers from `leaf_id` back to `baseline`, return chain
    in oldest-first order. Each program is read from
    `programs_root/<id>/program.yaml`.
    """
    chain: list[Program] = []
    current = leaf_id
    while current != BASELINE_SENTINEL:
        path = programs_root / current / "program.yaml"
        if not path.is_file():
            raise FileNotFoundError(
                f"lineage broken — program.yaml missing for {current!r} at {path}"
            )
        prog = read_program(path)
        chain.append(prog)
        current = prog.parent
    chain.reverse()
    return chain
