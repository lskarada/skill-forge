"""Tasks 8.4 + 8.5 — synthesis AST validator + N-red baseline gate."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from skill_forge.synthesis import (
    ValidationResult,
    admit_synthesized_test,
    validate_harness_only,
)


@pytest.fixture
def write(tmp_path: Path):
    def _write(name: str, body: str) -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(body).lstrip())
        return p
    return _write


# --- Task 8.4 — AST validator ---------------------------------------------


def test_a_harness_only_file_passes(write) -> None:
    p = write("test_ok.py", '''
        from skill_forge.harness.v1 import run_skill, assert_matches_schema

        SCHEMA = {"type": "object", "required": ["greeting"]}

        def test_greeter():
            output = run_skill("greeter", replay="x.json")
            assert_matches_schema(output, SCHEMA)
    ''')
    result = validate_harness_only(p)
    assert isinstance(result, ValidationResult)
    assert result.ok is True
    assert result.reasons == []


def test_b_pytest_import_fails(write) -> None:
    p = write("test_pytest_import.py", '''
        import pytest
        from skill_forge.harness.v1 import run_skill

        def test_x():
            run_skill("greeter", replay="x.json")
    ''')
    result = validate_harness_only(p)
    assert result.ok is False
    assert any("import pytest" in r for r in result.reasons)


def test_c_bare_assert_no_harness_call_fails(write) -> None:
    p = write("test_bare.py", '''
        from skill_forge.harness.v1 import run_skill

        def test_no_harness_call():
            assert 1 == 1
    ''')
    result = validate_harness_only(p)
    assert result.ok is False
    assert any("no harness Call" in r for r in result.reasons)


def test_d_star_import_fails(write) -> None:
    p = write("test_star.py", '''
        from skill_forge.harness.v1 import *

        def test_x():
            run_skill("x", replay="x.json")
    ''')
    result = validate_harness_only(p)
    assert result.ok is False
    assert any("star import" in r for r in result.reasons)


def test_e_validation_result_lists_all_reasons(write) -> None:
    p = write("test_multi.py", '''
        import pytest
        from skill_forge.harness.v1 import *

        def test_x():
            assert 1 == 1
    ''')
    result = validate_harness_only(p)
    assert result.ok is False
    # pytest import + star + no harness call → ≥ 3 reasons
    assert len(result.reasons) >= 3


def test_f_syntax_error_reported_not_crashed(write) -> None:
    p = write("test_syntax.py", "def broken(\n")  # unclosed paren
    result = validate_harness_only(p)
    assert result.ok is False
    assert any("syntax error" in r.lower() for r in result.reasons)


# --- Task 8.5 — N-red baseline gate ---------------------------------------


class _FakeRunner:
    """Returns canned per-call results: True=pass, False=fail."""

    def __init__(self, results: list[bool]) -> None:
        self.results = list(results)
        self.calls = 0

    def __call__(self, test_path: Path) -> bool:
        idx = self.calls
        self.calls += 1
        return self.results[idx]


def test_admit_rejects_when_baseline_passes_any_run(tmp_path: Path) -> None:
    p = tmp_path / "t.py"
    p.write_text("def test_flaky(): pass\n")
    runner = _FakeRunner([True, False, False, False, False])  # 1 pass, 4 fail
    assert admit_synthesized_test(p, baseline_runner=runner, runs=5) is False


def test_admit_accepts_when_baseline_fails_n_consecutively(tmp_path: Path) -> None:
    p = tmp_path / "t.py"
    p.write_text("def test_solid(): pass\n")
    runner = _FakeRunner([False] * 5)
    assert admit_synthesized_test(p, baseline_runner=runner, runs=5) is True


def test_admit_default_runs_is_5(tmp_path: Path) -> None:
    p = tmp_path / "t.py"
    p.write_text("def test_x(): pass\n")
    runner = _FakeRunner([False] * 10)
    assert admit_synthesized_test(p, baseline_runner=runner) is True
    assert runner.calls == 5


def test_admit_rejects_runs_below_minimum(tmp_path: Path) -> None:
    p = tmp_path / "t.py"
    p.write_text("def test_x(): pass\n")
    runner = _FakeRunner([False] * 5)
    with pytest.raises(ValueError, match="runs"):
        admit_synthesized_test(p, baseline_runner=runner, runs=2)
