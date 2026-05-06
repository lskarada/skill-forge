"""Assertion DSL v1 for Skill-Forge regression tests.

All captured tests import from this namespace and only this namespace.
See PRD §4. Future helpers ship in v2/v3 — removing or renaming a helper
here requires a version bump so old tests keep working indefinitely.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def run_skill(skill: str, replay: str) -> str:
    """Spawn a fresh Claude Code subagent with the SUT loaded and replay fed in.

    `skill` is the SUT name (e.g. "data-extraction"). `replay` is a path to a
    replay JSON file — absolute, or relative to the test file that owns it.

    Returns the subagent's final assistant message as a string.

    The concrete dispatch lives in skill_forge.dispatch so tests can inject a
    fake. We resolve the attribute lazily on every call so test monkeypatches
    against skill_forge.dispatch.run_skill take effect even after import.
    """
    from skill_forge import dispatch

    replay_path = Path(replay)
    if not replay_path.is_absolute():
        # "relative to the test file that owns it" — resolve against the
        # caller's file dir, not cwd. Falls back to cwd if the caller frame
        # has no resolvable file (e.g. interactive REPL).
        caller_frame = inspect.stack()[1]
        caller_file = caller_frame.filename
        if caller_file and caller_file not in ("<stdin>", "<string>"):
            replay_path = (Path(caller_file).resolve().parent / replay_path).resolve()
        else:
            replay_path = replay_path.resolve()
    return dispatch.run_skill(skill=skill, replay=str(replay_path))


def assert_contains(output: str, phrase: str) -> None:
    if phrase not in output:
        raise AssertionError(
            f"expected output to contain {phrase!r}; got (first 400 chars): {output[:400]!r}"
        )


def assert_not_contains(output: str, phrase: str) -> None:
    if phrase in output:
        idx = output.find(phrase)
        window = output[max(0, idx - 60) : idx + len(phrase) + 60]
        raise AssertionError(
            f"expected output NOT to contain {phrase!r}; found at offset {idx}: …{window!r}…"
        )


def assert_regex(output: str, pattern: str) -> None:
    if re.search(pattern, output) is None:
        raise AssertionError(
            f"expected output to match {pattern!r}; got (first 400 chars): {output[:400]!r}"
        )


def _extract_json(output: str) -> Any:
    """Parse `output` as JSON, or extract and parse the first JSON object/array.

    Tolerates surrounding prose (the skill under test may add commentary).
    """
    s = output.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        while start != -1:
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(s)):
                ch = s[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = s.find(opener, start + 1)

    raise AssertionError(
        f"expected output to contain parseable JSON; got (first 400 chars): {output[:400]!r}"
    )


def assert_json_has_field(output: str, field: str, parent: str | None = None) -> None:
    data = _extract_json(output)
    scope = data
    if parent is not None:
        if not isinstance(scope, dict) or parent not in scope:
            raise AssertionError(
                f"expected parent field {parent!r} in JSON output; available: {list(scope)[:10] if isinstance(scope, dict) else type(scope).__name__}"
            )
        scope = scope[parent]
    if not isinstance(scope, dict):
        raise AssertionError(
            f"expected JSON object at {'root' if parent is None else parent!r}; got {type(scope).__name__}"
        )
    if field not in scope:
        raise AssertionError(
            f"expected field {field!r} in {'root' if parent is None else parent!r}; available: {list(scope)[:10]}"
        )


def assert_matches_schema(output: str, schema: dict[str, Any]) -> None:
    data = _extract_json(output)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise AssertionError(
            f"JSON output failed schema validation at {path}: {first.message}"
        )


def assert_min_sources(output: str, n: int) -> None:
    """Asserts the parsed JSON output references at least n distinct sources.

    Looks for a `sources` array at the root; each element is either a string
    (treated as an identifier) or an object with an `id`, `url`, or `name`
    key. Distinctness is by that identifier.
    """
    data = _extract_json(output)
    if not isinstance(data, dict) or "sources" not in data:
        raise AssertionError(
            f"expected JSON object with a `sources` field; got keys: {list(data)[:10] if isinstance(data, dict) else type(data).__name__}"
        )
    raw = data["sources"]
    if not isinstance(raw, list):
        raise AssertionError(
            f"expected `sources` to be a list; got {type(raw).__name__}"
        )
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            seen.add(item)
        elif isinstance(item, dict):
            for key in ("id", "url", "name"):
                if key in item and isinstance(item[key], str):
                    seen.add(item[key])
                    break
    if len(seen) < n:
        raise AssertionError(
            f"expected at least {n} distinct sources; got {len(seen)}: {sorted(seen)[:10]}"
        )


def assert_answer_matches(
    output: str,
    ground_truth: str,
    *,
    tau: float = 0.0,
    threshold: float = 0.8,
) -> None:
    """v0.6: assert that `output` answers correctly per paper §C scoring.

    `tau` selects the strictest tolerance considered: tau=0.0 requires an
    exact numeric match; tau=0.05 allows up to 5% relative drift. The
    multi-tolerance weighted score must meet `threshold` (default 0.8,
    paper §C failure-flagging threshold) for the assertion to pass.

    Used by v0.8 retro synthesis tests and by v0.6 transfer harness checks.
    """
    from skill_forge import scoring

    pred_nums = scoring.extract_numbers(output)
    gt_nums = scoring.extract_numbers(ground_truth)

    if gt_nums:
        # Numeric path. When an explicit `tau > 0` is passed the caller is
        # signalling "drift up to tau is acceptable" — in that mode we gate
        # only on the strict-tau check (the weighted score, which mixes
        # several tolerances, can dip below threshold even when the answer
        # is squarely inside the requested tau).
        # When tau == 0 (default), gate on BOTH strict equality AND the
        # paper §C weighted threshold so a numerically-close-but-not-equal
        # answer still fails the strict pass.
        pred_at_tau = any(
            scoring.fuzzy_match_at_tau(predicted=p, ground_truth=gt_nums[0], tau=tau)
            for p in pred_nums
        )
        score = scoring.score_answer(predicted=output, ground_truth=ground_truth)
        gates_failed = (not pred_at_tau) or (tau == 0.0 and score < threshold)
        if gates_failed:
            raise AssertionError(
                f"answer mismatch: predicted nums={pred_nums[:5]} vs gt={gt_nums[:1]}; "
                f"score={score:.3f} threshold={threshold:.3f} tau={tau}"
            )
    else:
        score = scoring.score_answer(predicted=output, ground_truth=ground_truth)
        if score < threshold:
            raise AssertionError(
                f"answer mismatch (textual): expected {ground_truth!r} in output; "
                f"score={score:.3f} threshold={threshold:.3f}; "
                f"got (first 200 chars): {output[:200]!r}"
            )


def assert_pain_resolved(output: str, pain_signature: str) -> None:
    """v0.8: assert that the original pain signature no longer appears in `output`.

    Used by retro-flow synthesized tests: after the mutation lands, the
    failing phrase (e.g. "TypeError on parse" from the source transcript)
    must not recur in the post-mutation output. Pure substring check —
    case-sensitive — to keep determinism intact.
    """
    if pain_signature in output:
        idx = output.find(pain_signature)
        window = output[max(0, idx - 60) : idx + len(pain_signature) + 60]
        raise AssertionError(
            f"pain signature {pain_signature!r} present at offset {idx}: …{window!r}…"
        )


__all__ = [
    "run_skill",
    "assert_contains",
    "assert_not_contains",
    "assert_regex",
    "assert_json_has_field",
    "assert_matches_schema",
    "assert_min_sources",
    "assert_answer_matches",
    "assert_pain_resolved",
]
