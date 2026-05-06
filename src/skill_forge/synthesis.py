"""Synthesis pipeline: subagent + AST validator + N-red baseline gate.

Tasks 8.4 / 8.5 / v0.8.2:
  - `validate_harness_only(path)` enforces the v1 DSL surface (no `import
    pytest`, no star imports, no bare-assert tests, no helper functions).
  - `admit_synthesized_test(path, runner, runs=N)` runs the candidate
    against the unmutated baseline N times and admits only if all N runs
    fail (SOUL §1: "deterministic-by-construction red baseline").
  - `synthesize_test(pain, attribution, *, io, ...)` (v0.8.2) drives the
    Synthesis subagent, writes the proposed test + replay JSON, runs both
    gates above, and returns the admitted path (or None on rejection).

Synthesized files admit-only when BOTH gates pass; rejects are written
under `.skill-forge/synthesis_rejects/<skill>/` (driver in
`campaign.py`/`retro.py`) so the user can audit the rejected outputs.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
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


# --- v0.8.2: real baseline runner ----------------------------------------


def make_real_baseline_runner(
    *, repo_path: Path, skill: str,
) -> Callable[[Path], bool]:
    """Return a runner that pytest-executes a single synthesized test
    against the unmutated SKILL.md in `repo_path`. Returns True if the
    test PASSED (which means the baseline accidentally passed — the
    test is flaky from a deterministic-red perspective).

    Intended for the v0.8.2 retro flow: the campaign synthesizer needs
    to gate admitted tests on N consecutive baseline reds (SOUL §1).
    """
    import subprocess
    import sys

    def runner(test_path: Path) -> bool:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q",
             str(test_path)],
            cwd=str(repo_path),
            capture_output=True, text=True, check=False,
        )
        return proc.returncode == 0

    return runner


# --- v0.8.2: Synthesis subagent driver -----------------------------------


@dataclass(frozen=True)
class SynthesisResult:
    """Outcome of a single synthesize_test call."""
    admitted_path: Path | None
    rejected_paths: list[Path]
    reason: str   # "" if admitted, else why rejected


_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_synthesis_response(raw: str) -> dict | None:
    m = _JSON_BLOCK_RE.search(raw)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _build_synthesis_prompt(
    *, pain_turns: list, skill_name: str, sut_text: str,
    replay_filename: str,
) -> str:
    from skill_forge.prompts import SYNTHESIS_PROMPT_HEADER

    turns_block = "\n".join(
        f"  - role={t.role!r} text={t.text!r} tool_calls={list(t.tool_calls)}"
        for t in pain_turns
    ) or "  (no turns)"

    return f"""{SYNTHESIS_PROMPT_HEADER}

## Skill in question

`.claude/skills/{skill_name}/SKILL.md`:

```
{sut_text}
```

## Rough-session turns implicated

{turns_block}

## Replay file you must reference

The harness will place a replay JSON at:

  `.skill-forge/tests/{skill_name}/replays/{replay_filename}`

Your test must call `run_skill("{skill_name}", replay="replays/{replay_filename}")`.
You will SUPPLY the replay content via the `replay_user_input` field; the
harness writes the file. The replay user turn is the failing turn from the
rough session (or a trimmed equivalent) so the regression captures the
actual contract that should hold.

## Output

Respond with EXACTLY ONE fenced ```json block:

{{
  "test_code": "<full python source for the test file (string)>",
  "replay_user_input": "<single string, the user's turn the test replays>",
  "rationale": "<one-sentence why this test catches the failure>"
}}

Do NOT edit any file. Output JSON only.
"""


def _write_replay_file(
    *, replay_path: Path, user_input: str, source: str,
) -> None:
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(json.dumps({
        "replay_version": "1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_transcript": source,
        "source_turn_index": 0,
        "replay_mode": "full_conversation",
        "conversation": [{"role": "user", "content": user_input}],
        "trigger_turn_index": 0,
    }, indent=2), encoding="utf-8")


def _write_reject(
    *, rejects_root: Path, skill: str, ts: str,
    suffix: str, body: str, reason: str,
) -> Path:
    rejects_dir = rejects_root / skill
    rejects_dir.mkdir(parents=True, exist_ok=True)
    rej_path = rejects_dir / f"{ts}_{suffix}.py"
    rej_path.write_text(body, encoding="utf-8")
    why_path = rejects_dir / f"{ts}_{suffix}.why.md"
    why_path.write_text(reason, encoding="utf-8")
    return rej_path


def synthesize_test(
    *,
    pain,
    attribution,
    io,
    output_root: Path,
    skill_loader: Callable[[str], str],
    baseline_runner: Callable[[Path], bool] | None = None,
    n_runs: int = DEFAULT_BASELINE_RUNS,
) -> SynthesisResult:
    """Drive the Synthesis subagent for one attributed skill.

    Steps:
      1. Filter pain turns to those mentioning this skill (heuristic: any
         turn whose tool_calls include the skill, or whose text mentions
         it word-bounded).
      2. Dispatch the subagent with the harness DSL constraints.
      3. Parse JSON response → write replay JSON + test_*.py.
      4. Run `validate_harness_only` (AST allowlist).
      5. If a `baseline_runner` is supplied, run `admit_synthesized_test`
         (N-red gate). If `None`, skip — caller is signalling unit-test
         mode where we trust the supplied gates.
      6. Return SynthesisResult(admitted_path, rejected_paths, reason).

    Rejected tests + their why.md sit under
    `.skill-forge/synthesis_rejects/<skill>/`.
    """
    skill = attribution.skill
    sut_text = skill_loader(skill)
    rejects_root = output_root / "synthesis_rejects"

    # Filter pain turns to those implicating this skill.
    relevant_turns = []
    name_re = re.compile(rf"\b{re.escape(skill)}\b")
    for t in pain.turns:
        if any(skill in call for call in t.tool_calls):
            relevant_turns.append(t)
        elif t.role == "user" and name_re.search(t.text):
            relevant_turns.append(t)
    if not relevant_turns:
        relevant_turns = list(pain.turns)  # fallback: use everything

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    replay_filename = f"{ts}.json"

    prompt = _build_synthesis_prompt(
        pain_turns=relevant_turns,
        skill_name=skill,
        sut_text=sut_text,
        replay_filename=replay_filename,
    )
    raw = io.run(prompt=prompt, kind="propose", forbid_writes=True)

    parsed = _parse_synthesis_response(raw)
    if parsed is None:
        rej = _write_reject(
            rejects_root=rejects_root, skill=skill, ts=ts,
            suffix="parse_failed",
            body=f"# raw response (truncated):\n# {raw[:800]!r}\n",
            reason="Synthesis subagent returned no parseable ```json block.",
        )
        return SynthesisResult(
            admitted_path=None, rejected_paths=[rej],
            reason="parse_failed",
        )

    test_code = parsed.get("test_code")
    replay_user_input = parsed.get("replay_user_input")
    if not test_code or not replay_user_input:
        rej = _write_reject(
            rejects_root=rejects_root, skill=skill, ts=ts,
            suffix="missing_field",
            body=f"# parsed: {parsed!r}\n",
            reason="Synthesis JSON lacked test_code or replay_user_input.",
        )
        return SynthesisResult(
            admitted_path=None, rejected_paths=[rej],
            reason="missing_field",
        )

    # Materialize replay + test under .skill-forge/tests/<skill>/.
    tests_dir = output_root / "tests" / skill
    replays_dir = tests_dir / "replays"
    replay_path = replays_dir / replay_filename
    test_path = tests_dir / f"test_{ts}.py"

    _write_replay_file(
        replay_path=replay_path,
        user_input=replay_user_input,
        source=f"forge retro {ts}",
    )
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test_code, encoding="utf-8")

    # AST validator gate.
    validation = validate_harness_only(test_path)
    if not validation.ok:
        rej = _write_reject(
            rejects_root=rejects_root, skill=skill, ts=ts,
            suffix="validator_rejected",
            body=test_code,
            reason="\n".join(["AST validator rejected:"] + validation.reasons),
        )
        # Clean up the bogus test from tests dir so it doesn't run.
        test_path.unlink(missing_ok=True)
        replay_path.unlink(missing_ok=True)
        return SynthesisResult(
            admitted_path=None, rejected_paths=[rej],
            reason="validator_rejected",
        )

    # N-red baseline gate (only if a runner was supplied).
    if baseline_runner is not None:
        if not admit_synthesized_test(
            test_path, baseline_runner=baseline_runner, runs=n_runs,
        ):
            rej = _write_reject(
                rejects_root=rejects_root, skill=skill, ts=ts,
                suffix="baseline_passed",
                body=test_code,
                reason=(
                    f"Baseline accidentally passed within {n_runs} runs — "
                    f"test is not deterministic-red (SOUL §1). "
                    f"Escalate the assertion."
                ),
            )
            test_path.unlink(missing_ok=True)
            replay_path.unlink(missing_ok=True)
            return SynthesisResult(
                admitted_path=None, rejected_paths=[rej],
                reason="baseline_passed",
            )

    return SynthesisResult(
        admitted_path=test_path, rejected_paths=[], reason="",
    )
