"""Task 8.6 — harness.v1.assert_pain_resolved."""
from __future__ import annotations

import pytest

from skill_forge.harness.v1 import assert_pain_resolved


def test_passes_when_signature_absent() -> None:
    assert_pain_resolved(output="A clean output without errors.", pain_signature="TypeError")


def test_fails_when_signature_present() -> None:
    with pytest.raises(AssertionError, match="pain signature 'TypeError'"):
        assert_pain_resolved(output="Got TypeError on parse", pain_signature="TypeError")


def test_signature_check_is_case_sensitive() -> None:
    # `typeerror` (lowercase) should NOT match `TypeError` — determinism over leniency.
    assert_pain_resolved(output="got typeerror on parse", pain_signature="TypeError")
