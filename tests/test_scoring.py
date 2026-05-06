"""Task 6.1 — paper §C deterministic fuzzy scorer."""
from __future__ import annotations

import math

from skill_forge.scoring import (
    extract_numbers,
    fuzzy_match_at_tau,
    score_answer,
)


def test_extract_numbers_pure_numeric() -> None:
    assert extract_numbers("42") == [42.0]


def test_extract_numbers_with_million_unit() -> None:
    """`5 million` should produce 5_000_000."""
    nums = extract_numbers("5 million")
    assert any(abs(n - 5_000_000) < 1e-6 for n in nums)


def test_extract_numbers_year_filter() -> None:
    """A bare 4-digit year inside prose ('reported in 2023') should NOT
    contribute as the answer's numeric value when the question isn't
    year-themed. The function returns numbers WITHOUT year-filtering;
    the year filter is applied at the scoring step."""
    nums = extract_numbers("the prevalence reported in 2023 was 7.5%")
    assert 7.5 in nums
    # 2023 also appears, but downstream scoring skips it via year-filter when
    # the ground truth lacks year context.


def test_extract_numbers_hybrid_text() -> None:
    """`March 1977` should yield 1977 (the year is the only number)."""
    nums = extract_numbers("March 1977")
    assert nums == [1977.0]


def test_extract_numbers_multi_number_list() -> None:
    """Comma-separated numerics produce all of them."""
    nums = extract_numbers("scores were 7.5, 8.2, and 9.1")
    assert sorted(nums) == [7.5, 8.2, 9.1]


def test_fuzzy_match_at_tau_exact() -> None:
    assert fuzzy_match_at_tau(predicted=42.0, ground_truth=42.0, tau=0.0) is True


def test_fuzzy_match_at_tau_within_pct() -> None:
    assert fuzzy_match_at_tau(predicted=99.0, ground_truth=100.0, tau=0.05) is True
    assert fuzzy_match_at_tau(predicted=99.0, ground_truth=100.0, tau=0.0) is False


def test_score_answer_textual_substring_match() -> None:
    score = score_answer(predicted="The capital is Paris.", ground_truth="Paris")
    assert score == 1.0


def test_score_answer_textual_no_match_zero() -> None:
    score = score_answer(predicted="The capital is Berlin.", ground_truth="Paris")
    assert score == 0.0


def test_score_answer_numeric_uses_weighted_grid() -> None:
    """A 1% off answer should score about w(τ=0.01) — well above 0, well below 1."""
    score = score_answer(predicted="99", ground_truth="100")
    assert 0.0 < score < 1.0
    assert math.isclose(score, 0.7, abs_tol=0.05)


def test_score_answer_year_filter_avoids_false_match() -> None:
    """Ground truth `7.5`, predicted `the prevalence reported in 2023 was 7.5%`
    matches on 7.5, NOT on 2023. Score should be ≈1.0."""
    score = score_answer(
        predicted="the prevalence reported in 2023 was 7.5%",
        ground_truth="7.5",
    )
    assert math.isclose(score, 1.0, abs_tol=0.01)
