"""Milestone 4 — plugin packaging surface.

These tests don't exercise Claude Code itself. They lock down the files that
a stranger who runs `/plugin marketplace add lskarada/skill-forge` would see:

- `.claude-plugin/marketplace.json` — valid JSON, names the marketplace,
  lists the `skill-forge` plugin at `./plugins/skill-forge`.
- `plugins/skill-forge/.claude-plugin/plugin.json` — valid JSON, names the
  plugin.
- `plugins/skill-forge/commands/forge/{capture,optimize,status}.md` — each
  file exists, has YAML frontmatter, and shells out to the `forge` CLI.
  (Commands live at the plugin ROOT, per Claude Code's plugins-reference:
  "Components must be at the plugin root, not inside .claude-plugin/.")

If any of these break, the plugin is not marketplace-ready.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MARKETPLACE_DIR = REPO / ".claude-plugin"
PLUGIN_ROOT = REPO / "plugins" / "skill-forge"
PLUGIN_DIR = PLUGIN_ROOT / ".claude-plugin"
COMMANDS_DIR = PLUGIN_ROOT / "commands" / "forge"


def test_marketplace_manifest_exists_and_parses() -> None:
    path = MARKETPLACE_DIR / "marketplace.json"
    assert path.is_file(), f"missing marketplace manifest at {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["name"] == "skill-forge"
    assert data["owner"]["name"], "marketplace owner.name must be set"
    plugins = data["plugins"]
    assert isinstance(plugins, list) and plugins, "plugins list must be non-empty"
    entry = next((p for p in plugins if p.get("name") == "skill-forge"), None)
    assert entry is not None, "marketplace must list the skill-forge plugin"
    # Relative path sources must start with ./ per the marketplace spec.
    assert entry["source"] == "./plugins/skill-forge"


def test_plugin_manifest_exists_and_parses() -> None:
    manifest_path = PLUGIN_DIR / "plugin.json"
    assert manifest_path.is_file(), f"missing manifest at {manifest_path}"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["name"] == "skill-forge"
    assert data["version"], "plugin version must be set"
    assert data["description"]


def test_plugin_commands_directory_layout() -> None:
    assert COMMANDS_DIR.is_dir(), f"missing commands dir: {COMMANDS_DIR}"
    for name in ("capture", "optimize", "status"):
        p = COMMANDS_DIR / f"{name}.md"
        assert p.is_file(), f"missing slash command file: {p}"


def test_commands_not_inside_claude_plugin_dir() -> None:
    # Regression guard: Claude Code's plugins-reference says components
    # MUST live at the plugin root, not inside `.claude-plugin/`.
    stray = PLUGIN_DIR / "commands"
    assert not stray.exists(), (
        f"commands must live at plugin root ({COMMANDS_DIR}), not under "
        f"{stray}"
    )


@pytest.mark.parametrize(
    "command,expected_forge_verb",
    [
        ("capture", "forge capture"),
        ("optimize", "forge optimize"),
        ("status", "forge status"),
    ],
)
def test_command_frontmatter_and_invocation(command: str, expected_forge_verb: str) -> None:
    path = COMMANDS_DIR / f"{command}.md"
    text = path.read_text(encoding="utf-8")

    # YAML-style frontmatter bracketed by --- lines.
    m = re.match(r"^---\n(?P<body>.*?)\n---\n(?P<rest>.*)$", text, re.DOTALL)
    assert m is not None, f"{path} missing --- frontmatter"
    frontmatter = m.group("body")
    body = m.group("rest")

    assert f"name: forge:{command}" in frontmatter, (
        f"expected name: forge:{command} in frontmatter of {path}"
    )
    assert "description:" in frontmatter

    # The body must document that the command delegates to the `forge` CLI.
    assert expected_forge_verb in body, (
        f"{path} should invoke `{expected_forge_verb}`"
    )
