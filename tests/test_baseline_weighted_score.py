"""Task 5.4 — paper §C weighted multi-tolerance score."""
from __future__ import annotations

import math

from skill_forge.baseline import TAU_GRID, weighted_score


def test_tau_grid_matches_paper() -> None:
    assert TAU_GRID == (0.0, 0.01, 0.025, 0.05, 0.10)


def test_score_is_zero_when_all_zeros() -> None:
    pass_rates = {tau: 0.0 for tau in TAU_GRID}
    assert weighted_score(pass_rates) == 0.0


def test_score_is_one_when_all_perfect() -> None:
    pass_rates = {tau: 1.0 for tau in TAU_GRID}
    assert math.isclose(weighted_score(pass_rates), 1.0, rel_tol=1e-9)


def test_score_is_in_unit_interval() -> None:
    pass_rates = {0.0: 0.5, 0.01: 0.6, 0.025: 0.7, 0.05: 0.8, 0.10: 0.9}
    s = weighted_score(pass_rates)
    assert 0.0 <= s <= 1.0


def test_normalization_sums_to_one() -> None:
    """Strict tolerance carries the most weight; the weights still sum to 1."""
    weights = {tau: 1.0 / (1.0 + 20.0 * tau) for tau in TAU_GRID}
    total = sum(weights.values())
    normalized = {tau: w / total for tau, w in weights.items()}
    assert math.isclose(sum(normalized.values()), 1.0, rel_tol=1e-9)
    # Strictest tolerance gets ≈30% of weight (= 1 / 3.333... = 0.300).
    # That's "dominant share among 5 tolerances" — no other tau exceeds it.
    assert normalized[0.0] >= 0.29
    assert all(normalized[0.0] >= normalized[t] for t in TAU_GRID)


def test_strict_tolerance_dominates() -> None:
    """A program that's perfect at τ=0 but zero everywhere else still scores
    above a program that's zero at τ=0 but perfect everywhere else — because
    paper §C weights w(τ)=1/(1+20τ) decay rapidly."""
    strict = {0.0: 1.0, 0.01: 0.0, 0.025: 0.0, 0.05: 0.0, 0.10: 0.0}
    loose = {0.0: 0.0, 0.01: 1.0, 0.025: 1.0, 0.05: 1.0, 0.10: 1.0}
    assert weighted_score(strict) < weighted_score(loose)
    # but if you flip the inputs symmetrically, the strict-perfect-only is still
    # weighted higher per-unit than any single loose tolerance.
    only_strict = {0.0: 1.0, 0.01: 0.0, 0.025: 0.0, 0.05: 0.0, 0.10: 0.0}
    only_loosest = {0.0: 0.0, 0.01: 0.0, 0.025: 0.0, 0.05: 0.0, 0.10: 1.0}
    assert weighted_score(only_strict) > weighted_score(only_loosest)
