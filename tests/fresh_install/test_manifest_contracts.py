"""Static manifest contract tests.

These tests parse repo source files directly (no clone). They guard
the version-agreement and pytest-in-deps rules from CLAUDE.md.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_versions_agree() -> None:
    """All three manifests (pyproject.toml, plugin.json, marketplace.json)
    agree on the version string. CLAUDE.md "three places the version
    string lives; bump together"; SOUL.md "version bumped in all three
    manifests."

    Note: marketplace.json has TWO version fields — `metadata.version`
    AND `plugins[0].version`. Both must match.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    plugin = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    marketplace = json.loads(
        (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text()
    )

    py_version = pyproject["project"]["version"]
    plugin_version = plugin["version"]
    marketplace_metadata = marketplace["metadata"]["version"]
    plugins_list = marketplace["plugins"]
    skill_forge_entry = next(
        (p for p in plugins_list if p["name"] == "skill-forge"), None
    )
    assert skill_forge_entry is not None, (
        "marketplace.json plugins[] missing skill-forge entry"
    )
    marketplace_plugin = skill_forge_entry["version"]

    versions = {
        "pyproject.toml [project].version": py_version,
        ".claude-plugin/plugin.json .version": plugin_version,
        ".claude-plugin/marketplace.json .metadata.version": marketplace_metadata,
        ".claude-plugin/marketplace.json .plugins[skill-forge].version": (
            marketplace_plugin
        ),
    }
    unique = set(versions.values())
    assert len(unique) == 1, (
        "Manifest version drift detected — bump all four together:\n"
        + "\n".join(f"  {k}: {v}" for k, v in versions.items())
    )


def test_pytest_in_runtime_deps_not_dev() -> None:
    """Pytest must be in `[project].dependencies`, NOT in a dev-only
    group. Phase 1 (baseline) runs pytest inside a uvx-installed
    marketplace copy; if pytest is dev-only, that install won't have
    it and baseline blows up. CLAUDE.md non-obvious rule."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    runtime_deps = pyproject["project"]["dependencies"]
    runtime_pkgs = {
        dep.split(">=")[0].split("==")[0].split("<")[0].strip()
        for dep in runtime_deps
    }
    assert "pytest" in runtime_pkgs, (
        "pytest is missing from [project].dependencies. CLAUDE.md: "
        "'pytest belongs in [project].dependencies, not a dev group.' "
        "Phase 1 baseline runs pytest inside the uvx env; this regression "
        "would silently break the loop."
    )

    # Belt-and-suspenders: if a dependency-groups.dev exists, it must
    # not contain pytest as a separate entry (which could shadow runtime).
    dep_groups = pyproject.get("dependency-groups", {})
    dev_group = dep_groups.get("dev", [])
    dev_pkgs = {
        dep.split(">=")[0].split("==")[0].split("<")[0].strip()
        for dep in dev_group
    }
    assert "pytest" not in dev_pkgs, (
        "pytest appears in [dependency-groups].dev — remove it; "
        "the runtime entry is canonical."
    )
