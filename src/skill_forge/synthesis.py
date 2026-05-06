"""Synthesis pipeline: subagent + AST validator + N-red baseline gate.

Tasks 8.4 / 8.5:
  - `validate_harness_only(path)` enforces the v1 DSL surface (no `import
    pytest`, no star imports, no bare-assert tests, no helper functions).
  - `admit_synthesized_test(path, runner, runs=N)` runs the candidate
    against the unmutated baseline N times and admits only if all N runs
    fail (SOUL §1: "deterministic-by-construction red baseline").

Synthesized files admit-only when BOTH gates pass; rejects are written
under `.skill-forge/synthesis_rejects/<skill>/` (driver in
`campaign.py`/`retro.py`) so the user can audit the rejected outputs.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# Allowlist of harness functions that synthesized tests may call.
# Mirrors `harness.v1.__all__` plus future additions (assert_pain_resolved
# from Task 8.6 lands in v1's __all__ when 8.6 commits).
_HARNESS_ALLOWLIST = {
    "run_skill",
    "assert_contains",
    "assert_not_contains",
    "assert_regex",
    "assert_json_has_field",
    "assert_matches_schema",
    "assert_min_sources",
    "assert_answer_matches",
    "assert_pain_resolved",
}

_HARNESS_MODULE = "skill_forge.harness.v1"

_LITERAL_NODE_TYPES = (
    ast.Constant, ast.Dict, ast.List, ast.Tuple, ast.Set,
    ast.FormattedValue, ast.JoinedStr,
)


@dataclass
class ValidationResult:
    ok: bool
    reasons: list[str]


def _check_module_scope_node(node: ast.stmt, reasons: list[str]) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            reasons.append(f"forbidden top-level `import {alias.name}` (no `import pytest` etc.)")
    elif isinstance(node, ast.ImportFrom):
        if node.module != _HARNESS_MODULE:
            reasons.append(
                f"forbidden top-level `from {node.module} import ...`; "
                f"only `from {_HARNESS_MODULE} import <names>` is allowed"
            )
        for alias in node.names:
            if alias.name == "*":
                reasons.append(f"forbidden star import from {node.module}")
    elif isinstance(node, ast.Assign):
        if not isinstance(node.value, _LITERAL_NODE_TYPES):
            reasons.append(
                "module-level assign must have a literal RHS (constant/dict/list/tuple/set)"
            )
    elif isinstance(node, ast.FunctionDef):
        if not node.name.startswith("test_"):
            reasons.append(
                f"forbidden helper function `def {node.name}`; "
                f"only `def test_*` is allowed at module scope"
            )
    else:
        reasons.append(
            f"forbidden module-level node `{type(node).__name__}` "
            f"(only Import/ImportFrom/Assign/FunctionDef permitted)"
        )


def _validate_test_body(fn: ast.FunctionDef, reasons: list[str]) -> None:
    harness_calls = 0
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in _HARNESS_ALLOWLIST:
                    harness_calls += 1
                else:
                    reasons.append(
                        f"`def {fn.name}`: forbidden call to `{func.id}` "
                        f"(not in harness allowlist)"
                    )
            elif isinstance(func, ast.Attribute):
                reasons.append(
                    f"`def {fn.name}`: forbidden method call `.{func.attr}(...)` "
                    f"(use a harness assertion instead)"
                )
    if harness_calls == 0:
        reasons.append(
            f"`def {fn.name}`: no harness Call detected — "
            f"each test_* must invoke at least one harness function"
        )


def validate_harness_only(test_path: Path) -> ValidationResult:
    text = test_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(test_path))
    except SyntaxError as e:
        return ValidationResult(ok=False, reasons=[f"syntax error: {e.msg}"])

    reasons: list[str] = []
    for node in tree.body:
        _check_module_scope_node(node, reasons)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            _validate_test_body(node, reasons)

    return ValidationResult(ok=not reasons, reasons=reasons)


# --- Task 8.5: N-consecutive-red baseline gate ----------------------------

DEFAULT_BASELINE_RUNS = 5
MIN_BASELINE_RUNS = 3


def admit_synthesized_test(
    test_path: Path,
    *,
    baseline_runner: Callable[[Path], bool],
    runs: int = DEFAULT_BASELINE_RUNS,
) -> bool:
    """Admit `test_path` only if `baseline_runner` returns False on every
    run (deterministic-red, SOUL §1). `True` from the runner means the
    baseline accidentally passed — the test is rejected as flaky.

    Raises ValueError if `runs < MIN_BASELINE_RUNS` (development-tier
    cheapness has a floor).
    """
    if runs < MIN_BASELINE_RUNS:
        raise ValueError(
            f"runs={runs} < MIN_BASELINE_RUNS={MIN_BASELINE_RUNS} — "
            f"the deterministic-red gate cannot be cheapened below 3 runs"
        )
    for _ in range(runs):
        if baseline_runner(test_path):  # baseline passed — flaky
            return False
    return True
