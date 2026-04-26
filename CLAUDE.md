# CLAUDE.md — Skill-Forge

Project-scoped instructions for Claude Code working on the Skill-Forge repo.

## What this project is

A Claude Code plugin that runs a tournament of parallel git worktrees to fix
a misbehaving `SKILL.md` (or subagent). It captures a failure, drafts a
pytest regression test, forks workers to mutate the skill, keeps only
mutations that strictly improve pass/fail counts, and merges the winner.

Read `README.md` and `docs/DEMO.md` before non-trivial work.

## Commands you will actually run

```bash
uv sync                          # install deps into .venv
uv run pytest tests/ -q          # unit suite (must stay green)
uv run forge --help              # CLI entry point
uv run forge status              # inspect tracked skills
uv run forge capture --target <SKILL path>
uv run forge optimize <skill>    # serial (workers=1)
uv run forge optimize <skill> --workers 3 --yes  # full loop, auto-confirm
```

Baseline-only (no API spend): pipe `n` to decline the mutation prompt:

```bash
echo n | uv run forge optimize <skill> --workers 1
```

The CLI has no `--workers 0`; `--workers` is clamped to `[1, 16]`.

## Layout

- `src/skill_forge/cli.py` — Typer entry point.
- `src/skill_forge/optimize.py` — the 5-phase loop. **Do not refactor while
  building new milestones.** Treat as stable even when it looks crufty.
- `src/skill_forge/capture.py`, `baseline.py`, `worktree.py`, `dispatch.py`,
  `transcript.py`, `prompts.py`, `status.py` — one module per phase / concern.
- `src/skill_forge/harness/v1.py` — the assertion DSL (`run_skill`,
  `assert_contains`, `assert_json_has_field`, `assert_matches_schema`,
  `assert_min_sources`, …). Tests are composed from these; free-form
  pytest is an escape hatch, not the happy path.
- `tests/` — unit tests (run with `uv run pytest tests/ -q`).
- `.skill-forge/tests/<skill>/` — regression tests for tracked skills.
  Separate tree, not part of the unit suite.
- `.skill-forge/history/<skill>/v<N>_evidence.md` — receipts for every merge.
- `.skill-forge/learnings.md` — one-line entry per losing mutation, fed
  into the next mutation prompt.
- `.claude/skills/greeter/` + `.skill-forge/tests/greeter/` — the demo
  fixture. Shipped as the first-run proof of the 5-phase loop.
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
  `pyproject.toml` — three places the version string lives; bump together.

## Non-obvious rules

- **`pytest` belongs in `[project].dependencies`, not a dev group.** Phase 1
  (baseline) runs pytest inside a uvx-installed marketplace copy; if pytest
  is dev-only, the install won't have it and baseline blows up.
- **Claude Code blocks subagent writes anywhere under `.claude/`.** Skill-
  Forge works around this by staging the SUT at `MUTATION_TARGET.md` at the
  worktree root; the worker edits the staged copy and the harness copies it
  back into `.claude/skills/...`. Don't "simplify" this into a direct edit.
- **Dispatch wrapper forces terse output.** The final assistant turn is
  constrained to "Produce only the final assistant response... No
  commentary." (`dispatch.py:141–152`). This is load-bearing for test
  determinism — do not soften it.
- **No LLM-as-judge, anywhere.** The only success signal is pytest
  pass/fail counts. If someone proposes adding an LLM scoring pass, the
  answer is no.
- **No direct Anthropic API calls.** All mutation happens through
  Claude Code subagents (`/forge:optimize`) so the user pays what they
  were going to pay anyway.

## Demo fixture is load-bearing

`.claude/skills/greeter/SKILL.md` + `.skill-forge/tests/greeter/` are the
only end-to-end proof a fresh user sees. Rules:

- The red baseline must be deterministic **by construction**, not by
  sampling. If the test asserts something Claude produces by happenstance
  ≥1 time in 20 runs, the baseline is not deterministic.
- Do not put the literal winning output inside `SKILL.md` (even in an HTML
  comment). Claude reads the comment at dispatch time and will echo any
  example it finds, which destroys the red baseline.
- The mutation subagent gets the test file as context. It can derive the
  envelope shape from the test — don't spoon-feed it in the SKILL.

## Shipping a new version

1. Bump `pyproject.toml`, `.claude-plugin/plugin.json`,
   `.claude-plugin/marketplace.json` (two version fields).
2. Gate 1: `uv run pytest tests/ -q` — all green.
3. Gate 2 (if demo touched): 5 consecutive red baselines on a fresh
   `git clone` of the repo, using `echo n | uv run forge optimize greeter --workers 1`.
4. Gate 3 (if the loop logic changed): one full
   `uv run forge optimize greeter --workers 3 --yes` run on a fresh clone;
   verify Phase 5 merge commit exists.
5. One commit, push. No split-PR dance for a single ship.

## Known upstream issue

Claude Code's `/plugin marketplace update` is a no-op on shallow
marketplace clones. Documented in `README.md` with the nuke-and-re-add
workaround. This is a Claude Code bug, not ours — don't try to fix it
from this repo.

## Dashboard verification loop (REQUIRED for any UI change)

The dashboard has end-to-end behaviour that pytest unit tests can't
verify: SSE actually delivering OOB swaps to the live DOM, click
handlers covering both `<tr>` rows and SVG `<g>` bracket nodes, the
elapsed clock advancing on the heartbeat without a manual reload. Two
real bugs slipped through to a paying user before this loop existed;
never again.

**The contract: after editing any of**

- `src/skill_forge/dashboard/static/*`
- `src/skill_forge/dashboard/templates/*`
- `src/skill_forge/dashboard/routes.py`
- any code path that emits dashboard events

**run the browser-driven verification loop before claiming the change
works:**

```bash
uv run pytest tests/manual/test_dashboard_browser.py -m manual -v
```

It boots a real `DashboardServer` on a free port, launches headless
Chromium via Playwright, drives the bus through scripted events, and
asserts the DOM mutates exactly as a real user would observe — five
assertions, ~13 seconds. If any fail, the dashboard is broken even
if every unit test passes. Read the assertion message; it names
the user-observable behaviour that broke.

One-time setup on a fresh clone:

```bash
uv sync --extra ui --extra ui-test
uv run playwright install chromium
```

The Playwright suite lives under `tests/manual/` and is excluded from
the default pytest run via `addopts = "-m 'not manual'"` in
`pyproject.toml`. CI doesn't run it (no browser); the local loop is
where it lives.

## When in doubt

Read `SOUL.md`. It documents what "done" means for this project and
which corners must not be cut.

Codex will review your output once you are done.
