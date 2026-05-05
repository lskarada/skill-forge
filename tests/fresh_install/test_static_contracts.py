"""Static contract tests — grep src/ for load-bearing strings.

These tests pin contracts from CLAUDE.md and SOUL.md non-negotiables.
If they fail, the test was right and the contract changed. The fix:
update the test string AND the citation comment, OR update the source
to restore the contract. The test never gets deleted to make a build
green.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mutation_target_staging_contract_intact() -> None:
    """`MUTATION_TARGET.md` is the staging path the harness uses to
    work around Claude Code's block on subagent writes under .claude/.
    CLAUDE.md: 'Skill-Forge works around this by staging the SUT at
    MUTATION_TARGET.md at the worktree root ... Don't simplify this
    into a direct edit.'

    Verified at spec time: the literal lives in src/skill_forge/optimize.py.
    If the staging mechanism moves, update this test to grep the new
    location, not delete it.
    """
    optimize_py = (REPO_ROOT / "src" / "skill_forge" / "optimize.py").read_text()
    assert "MUTATION_TARGET.md" in optimize_py, (
        "MUTATION_TARGET.md staging path missing from optimize.py. "
        "CLAUDE.md forbids simplifying this into a direct edit — the "
        "harness needs an out-of-tree staging path because Claude Code "
        "blocks subagent writes anywhere under .claude/."
    )


def test_terse_dispatch_constraint_intact() -> None:
    """The dispatch wrapper constrains the final assistant turn to
    'Produce only the final assistant response... No commentary.'
    CLAUDE.md: 'load-bearing for test determinism — do not soften it.'

    Verified at spec time: lives in src/skill_forge/dispatch.py.
    """
    dispatch_py = (REPO_ROOT / "src" / "skill_forge" / "dispatch.py").read_text()
    needle = "Produce only the final assistant response"
    assert needle in dispatch_py, (
        f"Terse-dispatch constraint string missing from dispatch.py. "
        f"Looked for: {needle!r}. CLAUDE.md: 'load-bearing for test "
        f"determinism — do not soften it.'"
    )


def test_no_anthropic_sdk_imports_in_src() -> None:
    """SOUL.md non-negotiable #4: 'Mutations go through Claude Code
    subagents. The user pays what they were going to pay anyway.' No
    direct Anthropic SDK calls anywhere in src/.
    """
    src_root = REPO_ROOT / "src"
    bad_pattern = re.compile(r"^\s*(from\s+anthropic\b|import\s+anthropic\b)", re.M)

    offenders: list[tuple[Path, int, str]] = []
    for py_file in src_root.rglob("*.py"):
        text = py_file.read_text()
        for m in bad_pattern.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append((py_file, line_no, m.group(0).strip()))

    assert not offenders, (
        "anthropic SDK import found in src/. SOUL.md non-negotiable #4: "
        "'Mutations go through Claude Code subagents.' Offenders:\n"
        + "\n".join(
            f"  {p.relative_to(REPO_ROOT)}:{n}: {line}"
            for p, n, line in offenders
        )
    )
