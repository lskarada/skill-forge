"""Phase-A gates A.1 + A.2 — run_improve orchestrator.

Threads the existing run_capture → run_optimize chain together with sane
defaults (`--workers 3`, `--ui`, `--open`, `--yes`) so a user can call
`forge improve` and get a merged improvement without thinking about flags.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from skill_forge import baseline as baseline_mod
from skill_forge import capture as cap_mod
from skill_forge import improve as imp_mod
from skill_forge import optimize as opt_mod
from skill_forge import worktree as wt_mod


FROZEN_TIME = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)


# ---- Gate A.1 — Unit ----------------------------------------------------


def test_orchestrator_chains_capture_then_optimize(tmp_path: Path) -> None:
    """capture returns approved+skill='greeter'; optimize must be invoked
    with that skill and the friction-free defaults baked in."""
    captured: dict[str, Any] = {}
    optimized: dict[str, Any] = {}

    def fake_run_capture(config: cap_mod.CaptureConfig, io: cap_mod.CaptureIO):
        captured["config"] = config
        return cap_mod.CaptureResult(
            approved=True, outcome="approved", skill_name="greeter",
            test_path=tmp_path / ".skill-forge/tests/greeter/test_x.py",
        )

    def fake_run_optimize(config: opt_mod.OptimizeConfig, io: opt_mod.OptimizeIO):
        optimized["config"] = config
        return opt_mod.OptimizeResult(outcome="merged")

    config = imp_mod.ImproveConfig(
        target=None,
        repo_path=tmp_path,
        output_root=tmp_path / ".skill-forge",
        num_workers=3,
        assume_yes=True,
        ui=False, open_browser=False,
    )
    io = imp_mod.ImproveIO(
        printer=lambda _m: None,
        prompter=lambda _m: "y",
        run_capture=fake_run_capture,
        run_optimize=fake_run_optimize,
    )
    result = imp_mod.run_improve(config, io)

    assert result.capture_outcome == "approved"
    assert result.optimize_outcome == "merged"
    assert captured["config"].assume_yes is True
    assert optimized["config"].skill == "greeter"
    assert optimized["config"].num_workers == 3
    assert optimized["config"].assume_yes is True


def test_skips_optimize_when_capture_rejects(tmp_path: Path) -> None:
    """capture returns rejected → optimize is never called."""
    optimize_called = []

    def fake_run_capture(config, io):
        return cap_mod.CaptureResult(
            approved=False, outcome="rejected", skill_name="greeter",
        )

    def fake_run_optimize(config, io):
        optimize_called.append(True)
        return opt_mod.OptimizeResult(outcome="merged")

    config = imp_mod.ImproveConfig(
        target=None, repo_path=tmp_path, output_root=tmp_path / ".skill-forge",
        num_workers=3, assume_yes=True, ui=False, open_browser=False,
    )
    io = imp_mod.ImproveIO(
        printer=lambda _m: None, prompter=lambda _m: "y",
        run_capture=fake_run_capture, run_optimize=fake_run_optimize,
    )
    result = imp_mod.run_improve(config, io)

    assert result.capture_outcome == "rejected"
    assert result.optimize_outcome is None
    assert optimize_called == []


def test_capture_skill_name_threads_to_optimize(tmp_path: Path) -> None:
    """The skill name from capture must flow into the optimize config —
    even if --target was not passed by the user."""
    optimized: dict[str, Any] = {}

    def fake_run_capture(config, io):
        return cap_mod.CaptureResult(
            approved=True, outcome="approved", skill_name="data-extraction",
        )

    def fake_run_optimize(config, io):
        optimized["skill"] = config.skill
        return opt_mod.OptimizeResult(outcome="merged")

    config = imp_mod.ImproveConfig(
        target=None, repo_path=tmp_path, output_root=tmp_path / ".skill-forge",
        num_workers=3, assume_yes=True, ui=False, open_browser=False,
    )
    io = imp_mod.ImproveIO(
        printer=lambda _m: None, prompter=lambda _m: "y",
        run_capture=fake_run_capture, run_optimize=fake_run_optimize,
    )
    imp_mod.run_improve(config, io)
    assert optimized["skill"] == "data-extraction"


# ---- Gate A.2 — Automation ----------------------------------------------


def test_no_capture_outcome_short_circuits(tmp_path: Path) -> None:
    """capture skipped (e.g. user said no, or DSL gap) → optimize NOT
    called; ImproveResult flags the short-circuit."""
    def fake_run_capture(config, io):
        return cap_mod.CaptureResult(
            approved=False, outcome="skipped", skill_name="greeter",
        )

    def fake_run_optimize(config, io):
        raise AssertionError("optimize must not be called when capture skipped")

    config = imp_mod.ImproveConfig(
        target=None, repo_path=tmp_path, output_root=tmp_path / ".skill-forge",
        num_workers=3, assume_yes=True, ui=False, open_browser=False,
    )
    io = imp_mod.ImproveIO(
        printer=lambda _m: None, prompter=lambda _m: "y",
        run_capture=fake_run_capture, run_optimize=fake_run_optimize,
    )
    result = imp_mod.run_improve(config, io)
    assert result.capture_outcome == "skipped"
    assert result.optimize_outcome is None
    assert result.exit_code == 1  # signals to CLI to exit non-zero


def test_escape_hatch_outcome_proceeds_to_optimize(tmp_path: Path) -> None:
    """An escape-hatch test (free-form pytest, not the DSL) is still a
    real test — optimize should run against it."""
    optimize_called = []

    def fake_run_capture(config, io):
        return cap_mod.CaptureResult(
            approved=True, outcome="escape_hatch", skill_name="greeter",
        )

    def fake_run_optimize(config, io):
        optimize_called.append(True)
        return opt_mod.OptimizeResult(outcome="merged")

    config = imp_mod.ImproveConfig(
        target=None, repo_path=tmp_path, output_root=tmp_path / ".skill-forge",
        num_workers=3, assume_yes=True, ui=False, open_browser=False,
    )
    io = imp_mod.ImproveIO(
        printer=lambda _m: None, prompter=lambda _m: "y",
        run_capture=fake_run_capture, run_optimize=fake_run_optimize,
    )
    result = imp_mod.run_improve(config, io)
    assert result.capture_outcome == "escape_hatch"
    assert optimize_called == [True]


def test_full_chain_with_realistic_fakes(tmp_path: Path) -> None:
    """End-to-end automation gate — drive run_improve against the same
    fakes test_optimize_m3 uses for the optimize side, plus a fake
    dispatcher for capture. Asserts: capture writes a real test file,
    optimize spawns 3 workers and merges, ImproveResult.optimize_outcome
    == 'merged'."""
    # Set up a fixture skill + a fake transcript directory.
    repo = tmp_path / "repo"
    repo.mkdir()
    sut_dir = repo / ".claude" / "skills" / "greeter"
    sut_dir.mkdir(parents=True)
    (sut_dir / "SKILL.md").write_text("loose initial body\n")

    # Pre-existing tests dir + at least one test file (capture's job is
    # to add another, but we need at least one for run_optimize to run).
    tests_dir = repo / ".skill-forge" / "tests" / "greeter"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_seed.py").write_text("def test_seed(): assert True\n")

    # Fake transcript so run_capture has something to chew on. The
    # capture-side dispatcher is faked too, so the contents don't matter.
    projects_dir = tmp_path / ".claude" / "projects"
    proj_subdir = projects_dir / "fake-project"
    proj_subdir.mkdir(parents=True)
    transcript = proj_subdir / "fake.jsonl"
    transcript.write_text(
        '{"type":"user","message":{"role":"user","content":"hi"}}\n'
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"bad output"}]}}\n'
    )

    def fake_dispatcher(excerpt: str, target: str | None) -> dict:
        return {
            "skill_name": "greeter",
            "failure_note": "missed",
            "source_turn_index": 1,
            "trigger_turn_index": 0,
            "conversation": [{"role": "user", "content": "hi"}],
            "test_code": (
                "from skill_forge.harness.v1 import run_skill, assert_contains\n"
                "\n"
                "def test_says_hello():\n"
                "    out = run_skill('greeter', conversation=[{'role':'user','content':'hi'}])\n"
                "    assert_contains(out, 'Hello')\n"
            ),
        }

    capture_io = cap_mod.CaptureIO(
        printer=lambda _m: None, prompter=lambda _m: "y",
        dispatcher=fake_dispatcher,
    )

    # Optimize-side fakes: copy the patterns from test_optimize_m3.
    sut_path = sut_dir / "SKILL.md"

    def fake_pytest(t_dir, *, cwd, junit_xml, timeout=600, extra_args=None):
        junit_xml.parent.mkdir(parents=True, exist_ok=True)
        junit_xml.write_text("<testsuite tests='2' failures='1'/>")
        if "mutated" not in junit_xml.name:
            return baseline_mod.BaselineResult(
                passed=1, failed=1, errors=0, skipped=0, total=2,
                returncode=1, junit_xml_path=junit_xml,
            )
        # Worker passes everything → wins.
        return baseline_mod.BaselineResult(
            passed=2, failed=0, errors=0, skipped=0, total=2,
            returncode=0, junit_xml_path=junit_xml,
        )

    def fake_resolver(skill, *, search_root=None):
        return sut_path

    @contextmanager
    def fake_worktree(repo_path, branch, *, base_ref="HEAD", worktree_parent=None):
        wt = repo_path / ".skill-forge" / "runs" / branch
        wt.mkdir(parents=True, exist_ok=True)
        wt_sut = wt / sut_path.relative_to(repo_path)
        wt_sut.parent.mkdir(parents=True, exist_ok=True)
        wt_sut.write_text(sut_path.read_text())
        yield wt_mod.WorktreeHandle(path=wt, branch=branch, base_ref=base_ref)

    def fake_mutator(*, sut_path, tests_preview, learnings, strategy, cwd):
        # Worker writes a winning body; index inferred from cwd.
        idx = int(str(cwd).rsplit("/w", 1)[-1])
        sut_path.write_text(f"winning body w{idx}\n")
        return f"w{idx}: mutated"

    def fake_committer(worktree_path, message):
        return "a" * 40

    optimize_io = opt_mod.OptimizeIO(
        printer=lambda _m: None, prompter=lambda _m: "y",
        mutator=fake_mutator, pytest_runner=fake_pytest,
        sut_resolver=fake_resolver, worktree_factory=fake_worktree,
        committer=fake_committer,
        merger=lambda *a, **kw: None,
        branch_discarder=lambda *a, **kw: None,
    )

    config = imp_mod.ImproveConfig(
        target=None,
        repo_path=repo,
        output_root=repo / ".skill-forge",
        num_workers=3,
        assume_yes=True,
        ui=False, open_browser=False,
        projects_dir=projects_dir,
        transcript_path=transcript,
        cwd=repo,
        now=lambda: FROZEN_TIME,
    )
    io = imp_mod.ImproveIO(
        printer=lambda _m: None, prompter=lambda _m: "y",
        run_capture=lambda c, _io: cap_mod.run_capture(c, capture_io),
        run_optimize=lambda c, _io: opt_mod.run_optimize(c, optimize_io),
    )

    result = imp_mod.run_improve(config, io)
    assert result.capture_outcome == "approved"
    assert result.optimize_outcome == "merged"
    # capture wrote a test file
    new_tests = list(tests_dir.glob("test_2026*.py"))
    assert new_tests, f"capture didn't write a new test file in {tests_dir}"
