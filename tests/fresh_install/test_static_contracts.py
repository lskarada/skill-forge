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
    """The PARALLEL path (`workers > 1`) stages the SUT at
    `MUTATION_TARGET.md` at the worktree root, copies the SUT in,
    invokes the mutator against the staged copy, then copies back.
    CLAUDE.md: 'Skill-Forge works around this by staging the SUT at
    MUTATION_TARGET.md at the worktree root ... Don't simplify this
    into a direct edit.'

    Scope: this test pins the parallel-path staging only. The serial
    path (`workers = 1`) routes through `worktree_sut` directly inside
    a worktree (verified separately by
    test_serial_path_uses_worktree_sut_contract_intact). The two-test
    split was prompted by code review feedback that the original single
    grep under-specified what the test actually pinned.

    Lives inside `_run_parallel` in src/skill_forge/optimize.py.
    If the staging mechanism moves, update this test to grep the new
    location, not delete it. (Function name cited rather than line
    number — line numbers drift on every nearby edit.)
    """
    optimize_py = (REPO_ROOT / "src" / "skill_forge" / "optimize.py").read_text()
    assert "MUTATION_TARGET.md" in optimize_py, (
        "MUTATION_TARGET.md staging path missing from optimize.py "
        "(parallel-path SUT staging). CLAUDE.md forbids simplifying "
        "this into a direct edit — the parallel-path mutator needs an "
        "out-of-tree staging path because Claude Code blocks subagent "
        "writes anywhere under .claude/."
    )


def test_serial_path_uses_worktree_sut_contract_intact() -> None:
    """The SERIAL path (`workers = 1`) hands the mutator a path inside
    a worktree (`worktree_sut`), not the main-repo .claude/ path. The
    worktree IS the .claude/-write workaround for the serial flow:
    mutating `<worktree>/.claude/...` is fine because Claude Code's
    block applies to the source-of-truth tree, not detached worktrees.

    This test pins the contract that the serial path passes
    `worktree_sut` (not `sut_path`) to the mutator. If someone
    "simplifies" the serial path to write the main-repo .claude/
    directly — which is what CLAUDE.md forbids — this assertion
    fails.

    Lives inside `_run_optimize_inner` in src/skill_forge/optimize.py.
    """
    optimize_py = (REPO_ROOT / "src" / "skill_forge" / "optimize.py").read_text()
    needle = "sut_path=worktree_sut"
    assert needle in optimize_py, (
        f"Serial-path worktree-staging contract missing from "
        f"optimize.py. Looked for: {needle!r}. CLAUDE.md: 'Claude Code "
        f"blocks subagent writes anywhere under .claude/.' The serial "
        f"path's workaround is to mutate inside a worktree, not the "
        f"main repo's .claude/ tree."
    )


def test_terse_dispatch_constraint_intact() -> None:
    """The dispatch wrapper constrains the final assistant turn to
    'Produce only the final assistant response... No commentary.'
    CLAUDE.md: 'load-bearing for test determinism — do not soften it.'

    Lives in src/skill_forge/dispatch.py inside `run_skill()`.
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
