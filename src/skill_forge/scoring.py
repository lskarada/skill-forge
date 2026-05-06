"""Paper §C deterministic fuzzy scorer for answer correctness.

Pure functions, no IO. Used by `harness.v1.assert_answer_matches` (Task 6.2)
and the v0.8 retro synthesis test admission gate.

Scoring algorithm:
  1. Extract numeric tokens from both predicted and ground_truth, applying
     unit normalization (`5 million` → 5_000_000, `7.5%` → 7.5).
  2. If both have at least one numeric, score on the multi-tolerance grid
     using `baseline.weighted_score`.
  3. Otherwise, score by case-insensitive substring containment (1.0 if
     ground_truth substring appears in predicted, else 0.0).

Year-filter (paper §C): a bare 4-digit number in [1700, 2100] is suppressed
when the ground truth itself contains no year in that range — this avoids
false matches like "reported in 2023" being graded against a numeric
ground truth that happens to equal 2023.
"""
from __future__ import annotations

import re

from skill_forge.baseline import TAU_GRID, weighted_score


_UNIT_FACTORS = {
    "thousand": 1_000.0,
    "million": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "trillion": 1_000_000_000_000.0,
}


# Match a number, optionally followed by a unit word.
_NUMBER_RE = re.compile(
    r"(?P<num>-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>thousand|million|billion|trillion)?",
    re.IGNORECASE,
)


def extract_numbers(text: str) -> list[float]:
    """Pull numeric tokens out of `text` with unit normalization.

    `7.5%`, `5 million`, `42`, `1977` all extract their numeric values.
    Returns floats in source order.
    """
    out: list[float] = []
    for m in _NUMBER_RE.finditer(text):
        try:
            value = float(m.group("num"))
        except ValueError:
            continue
        unit = m.group("unit")
        if unit:
            value *= _UNIT_FACTORS[unit.lower()]
        out.append(value)
    return out


def _looks_like_year(n: float) -> bool:
    return n.is_integer() and 1700.0 <= n <= 2100.0


def _filter_years(nums: list[float], gt_has_year: bool) -> list[float]:
    if gt_has_year:
        return nums
    return [n for n in nums if not _looks_like_year(n)]


def fuzzy_match_at_tau(*, predicted: float, ground_truth: float, tau: float) -> bool:
    """Return True if predicted is within tau (relative) of ground_truth."""
    if ground_truth == 0.0:
        return abs(predicted - ground_truth) <= tau
    return abs(predicted - ground_truth) / abs(ground_truth) <= tau


def _per_tau_pass_rate(predicted_nums: list[float], gt_num: float) -> dict[float, float]:
    rates: dict[float, float] = {}
    for tau in TAU_GRID:
        rates[tau] = 1.0 if any(
            fuzzy_match_at_tau(predicted=p, ground_truth=gt_num, tau=tau)
            for p in predicted_nums
        ) else 0.0
    return rates


def score_answer(*, predicted: str, ground_truth: str) -> float:
    """Score `predicted` against `ground_truth` in [0, 1].

    Numeric path: weighted multi-tolerance match across paper §C's tau grid.
    Textual fallback: 1.0 if ground_truth substring appears in predicted, else 0.0.
    """
    gt_nums_raw = extract_numbers(ground_truth)
    if not gt_nums_raw:
        # Textual fallback
        return 1.0 if ground_truth.strip().lower() in predicted.lower() else 0.0

    gt_has_year = any(_looks_like_year(n) for n in gt_nums_raw)
    pred_nums = _filter_years(extract_numbers(predicted), gt_has_year)
    gt_nums = _filter_years(gt_nums_raw, gt_has_year)

    if not gt_nums or not pred_nums:
        return 1.0 if ground_truth.strip().lower() in predicted.lower() else 0.0

    # When ground truth has multiple numbers, score against the FIRST and
    # take that as the answer signal (paper §C). Multi-number lists in ground
    # truth are rare in the SkillForge use case; we keep the simpler path.
    gt_num = gt_nums[0]
    rates = _per_tau_pass_rate(pred_nums, gt_num)
    return weighted_score(rates)
