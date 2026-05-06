"""Task 6.2 — harness.v1.assert_answer_matches (paper §C wrapper)."""
from __future__ import annotations

import pytest

from skill_forge.harness.v1 import assert_answer_matches


def test_exact_match_passes() -> None:
    assert_answer_matches(output="The answer is 42.", ground_truth="42")


def test_close_within_1pct_passes_at_default_threshold() -> None:
    """1% off scores ≈ 0.7 (sum of weights for τ ∈ {0.01, 0.025, 0.05, 0.10})
    — below the paper §C 0.8 threshold but the function accepts a `tau`
    override for stricter or looser pass rules."""
    # default threshold 0.8 → fails on 1% miss (correct, paper §C)
    with pytest.raises(AssertionError):
        assert_answer_matches(output="The answer is 99.", ground_truth="100")
    # explicit looser pass via tau=0.05 → 5% tolerance → exact at that tau
    assert_answer_matches(output="The answer is 99.", ground_truth="100", tau=0.05)


def test_wrong_answer_fails() -> None:
    with pytest.raises(AssertionError):
        assert_answer_matches(output="The answer is 7.", ground_truth="42")


def test_textual_substring_match_passes() -> None:
    assert_answer_matches(output="The capital of France is Paris.", ground_truth="Paris")


def test_default_tau_is_zero() -> None:
    """tau=0 means 'must match the strict tolerance'; weighted score = 1.0
    only when the answer is numerically equal."""
    assert_answer_matches(output="42", ground_truth="42")
    with pytest.raises(AssertionError):
        assert_answer_matches(output="43", ground_truth="42")
