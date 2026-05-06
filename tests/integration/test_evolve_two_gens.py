"""Task 5.8 — two-generation integration: frontier + program.yaml + git tags.

Threads the v0.5 primitives end-to-end without dispatching real subagents.
The mutator is a deterministic stub that returns canned scores.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skill_forge import evolve
from skill_forge.frontier import FrontierEntry
from skill_forge.git_tags import create_frontier_tag, list_frontier_tags
from skill_forge.program import Program, lineage_chain, write_program


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
             "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("a\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_two_generation_evolve_persists_tags_programs_and_lineage(repo: Path) -> None:
    skill = "greeter"
    programs_root = repo / ".skill-forge" / "programs" / skill

    # Stub one-gen mutator: each generation produces ONE candidate at
    # score 0.5 + 0.1 * gen, persists program.yaml, creates the frontier tag.
    def stub_one_gen(*, skill: str, gen_index, parent, k, workers_per_gen, repo_lock):
        candidate_id = f"g{gen_index}-w0"
        # Make a commit per generation so git tags can attach to distinct shas
        marker = repo / f"gen_{gen_index}.txt"
        marker.write_text(str(gen_index))
        _git(repo, "add", marker.name)
        _git(repo, "commit", "-q", "-m", f"gen-{gen_index}")

        write_program(
            programs_root / candidate_id / "program.yaml",
            Program(
                id=candidate_id,
                parent=parent.id,
                gen=gen_index,
                score=0.5 + 0.1 * gen_index,
                skill_len=100 + gen_index,
                created_at=f"2026-05-05T{18+gen_index:02d}:00:00Z",
            ),
        )
        create_frontier_tag(repo, skill=skill, program_id=candidate_id)

        return [FrontierEntry(
            id=candidate_id,
            score=0.5 + 0.1 * gen_index,
            skill_len=100 + gen_index,
        )]

    result = evolve.run_evolution(
        skill=skill,
        generations=2,
        frontier_size=1,
        workers_per_gen=1,
        patience=5,
        run_one_generation=stub_one_gen,
    )

    assert result.generations_run == 2
    assert result.early_stopped is False

    tags = list_frontier_tags(repo, skill=skill)
    assert sorted(tags) == ["frontier/greeter/g0-w0", "frontier/greeter/g1-w0"]

    # Lineage chain g1-w0 → g0-w0 → baseline
    chain = lineage_chain(programs_root=programs_root, leaf_id="g1-w0")
    assert [p.id for p in chain] == ["g0-w0", "g1-w0"]
    assert chain[0].parent == "baseline"

    # Frontier with k=1 keeps only the best (last gen with higher score).
    assert len(result.frontier) == 1
    assert result.frontier[0].id == "g1-w0"
