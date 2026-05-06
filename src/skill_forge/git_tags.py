"""Git tag wrapper for the v0.5 Pareto frontier.

Each program admitted to the frontier gets a tag of the form
`frontier/<skill>/<program_id>` pointing at its commit. Tags are the
source of truth across fresh clones — they round-trip through `git push`
without any external state file.

Pure thin wrapper around `git tag` / `git tag -l` / `git tag -d`. We use
subprocess directly (matching the rest of SkillForge's git interactions
in optimize.py) rather than gitpython, to keep the dependency surface
small and the failure modes legible.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _tag_name(skill: str, program_id: str) -> str:
    return f"frontier/{skill}/{program_id}"


def create_frontier_tag(repo_path: Path, *, skill: str, program_id: str) -> None:
    """Create (or no-op if already present) the frontier tag at HEAD.

    Idempotent: re-creating an existing tag is a no-op so retry/loop
    semantics in the orchestrator don't crash on duplicate admits.
    """
    tag = _tag_name(skill, program_id)
    existing = subprocess.run(
        ["git", "tag", "-l", tag],
        cwd=str(repo_path), capture_output=True, text=True, check=True,
    ).stdout.strip()
    if existing == tag:
        return
    subprocess.run(
        ["git", "tag", tag],
        cwd=str(repo_path), check=True, capture_output=True,
    )


def list_frontier_tags(repo_path: Path, *, skill: str) -> list[str]:
    """Return all `frontier/<skill>/*` tags in the repo (un-sorted)."""
    pattern = f"frontier/{skill}/*"
    out = subprocess.run(
        ["git", "tag", "-l", pattern],
        cwd=str(repo_path), capture_output=True, text=True, check=True,
    ).stdout
    return [t for t in out.splitlines() if t.strip()]


def delete_frontier_tag(repo_path: Path, *, skill: str, program_id: str) -> None:
    """Delete the `frontier/<skill>/<program_id>` tag if present (idempotent)."""
    tag = _tag_name(skill, program_id)
    subprocess.run(
        ["git", "tag", "-d", tag],
        cwd=str(repo_path), capture_output=True, check=False,
    )
