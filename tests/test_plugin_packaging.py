"""Milestone 4 — plugin packaging surface.

These tests don't exercise Claude Code itself. They lock down the files that
a stranger who runs `/plugin marketplace add lskarada/skill-forge` would see:

- `.claude-plugin/plugin.json` — valid JSON, names the plugin, points at commands/.
- `.claude-plugin/commands/forge/{capture,optimize,status}.md` — each file exists,
  has YAML frontmatter, and shells out to the `forge` CLI.

If any of these break, the plugin is not marketplace-ready.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO / ".claude-plugin"
COMMANDS_DIR = PLUGIN_DIR / "commands" / "forge"


def test_plugin_manifest_exists_and_parses() -> None:
    manifest_path = PLUGIN_DIR / "plugin.json"
    assert manifest_path.is_file(), f"missing manifest at {manifest_path}"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["name"] == "skill-forge"
    assert data["version"], "plugin version must be set"
    assert data["description"]
    # Point at ./commands so Claude Code can discover slash commands.
    assert data["commands"] == "./commands"


def test_plugin_commands_directory_layout() -> None:
    assert COMMANDS_DIR.is_dir(), f"missing commands dir: {COMMANDS_DIR}"
    for name in ("capture", "optimize", "status"):
        p = COMMANDS_DIR / f"{name}.md"
        assert p.is_file(), f"missing slash command file: {p}"


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
