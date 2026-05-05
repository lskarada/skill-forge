# Skill-Forge

**A Claude Code plugin that makes your skills and subagents self-improving.**

You point it at a `SKILL.md` (or subagent definition) that keeps misbehaving.
It captures the failure from your session, drafts a regression test, forks
parallel Claude Code subagents in git worktrees to try fixes, keeps the
winner, and commits. Your `SKILL.md` files get a CI/CD pipeline for free.

Inspired by [Evo](https://github.com/evo-hq/evo) and
[Karpathy's autoresearch](https://github.com/karpathy/autoresearch).
Evo optimizes your code. Skill-Forge optimizes your instructions.

---

## Install

```
/plugin marketplace add lskarada/skill-forge
/plugin install skill-forge
```

Requires:
- Claude Code
- Python 3.12+
- `uv` (or any tool that can install an entry-point script named `forge`)
- A git repo (the optimizer creates throw-away worktrees)

From source:

```
git clone https://github.com/lskarada/skill-forge.git
cd skill-forge
uv sync
uv run forge --help
```

Optional live web dashboard (off by default):

```
forge optimize <skill> --workers 3 --ui --open
```

Just pass `--ui`. The wrapper detects the flag and pulls the `[ui]`
extras (FastAPI, uvicorn, jinja2) into the same uvx env it already uses;
no separate install step, no venv to manage. Core CLI usage stays
lightweight — the extras only land on disk the first time you actually
ask for the dashboard.

The dashboard binds 127.0.0.1 only and auto-picks port 7777..7799
(override with `--port`). It streams the live tournament: top-bar phase,
baseline / best-so-far stats, a workers table, and a slide-over
drilldown with diff / transcript / tests for each worker — including
the discarded ones.

### Upgrading (known Claude Code cache bug)

Claude Code's `/plugin marketplace update` is a no-op on shallow marketplace
clones — it won't pick up new commits from the skill-forge repo. If an upgrade
seems stuck (e.g. you hit `No module named pytest` on a version older than
0.1.1), nuke the cache and re-add the marketplace:

```
rm -rf ~/.claude/plugins/cache/skill-forge
rm -rf ~/.claude/plugins/marketplaces/skill-forge
```

Then in Claude Code:

```
/plugin marketplace add lskarada/skill-forge
/plugin install skill-forge
```

This is a Claude Code plugin-manager issue, not a skill-forge bug. Once a
fresh install lands on your machine, subsequent upgrades are only reliable by
repeating the nuke-and-re-add dance.

---

## Usage

Four slash commands:

| Command             | What it does                                                        |
| ------------------- | ------------------------------------------------------------------- |
| `/forge:improve`    | One-call workflow — capture + optimize chained with friction-free defaults. |
| `/forge:capture`    | Just capture: read the last session, draft a pytest regression test, gate on Y/N. |
| `/forge:optimize`   | Just optimize: baseline → fork N worktrees → mutate → regression-gate → merge. |
| `/forge:status`     | Show tracked skills, pending tests, merged runs, learnings size.    |

Recommended loop (one command):

```
# Your skill just misbehaved. Run improve.
/forge:improve

# (or) target it explicitly:
/forge:improve --target .claude/skills/data-extraction/SKILL.md
```

Improve chains capture → optimize with `--workers 3 --ui --open --yes` baked
in: it reads the latest transcript, infers which skill misbehaved, drafts a
regression test under `.skill-forge/tests/<skill>/`, opens the live web
dashboard in your browser, and runs the mutation tournament. The merged
winner lands on your branch. Pass `--no-ui`, `--no-open`, or `--no-yes` to
override any default.

For more control, run capture and optimize separately:

```
/forge:capture --target .claude/skills/data-extraction/SKILL.md
/forge:optimize data-extraction --workers 5
/forge:status
```

Every merge writes `.skill-forge/history/<skill>/v<N>_evidence.md` so you can
audit what changed and why. Every *losing* mutation writes a one-line entry to
`.skill-forge/learnings.md` so the next run's mutation prompt can avoid the
same mistake.

---

## What's in the box

- **Typer CLI** (`forge capture | optimize | status`) — the thin harness.
- **Assertion DSL** (`skill_forge.harness.v1`) — `run_skill`, `assert_contains`,
  and a small JSON-shape DSL. Tests are composed from these; free-form pytest
  is an escape hatch, not the happy path.
- **Worktree orchestration** — one git worktree per mutation, merged only on
  strict improvement, discarded otherwise.
- **Deterministic gate** — pytest pass/fail counts. No LLM-as-judge.
- **Failure as memory** — every loss becomes a prompt input for the next run.

---

## Verification

Three pytest tiers, gated by markers and excluded from the default run:

- `uv run pytest tests/ -q` — unit suite (~4s, must stay green).
- `bin/verify-dashboard` — real-Chromium dashboard E2E (~30s).
- `bin/verify-fresh-install` — fresh-clone marketplace-install simulation (~10–12 min). Automates the 5-consecutive-red-baselines ship gate plus 8 other contract tests.

---

## Explicit non-goals

- No direct Anthropic API calls. Mutations go through Claude Code subagents.
- No LLM-as-judge. Tests are deterministic or they don't count.
- No LangChain or agent frameworks. Thin harness, fat skills.
- The opt-in dashboard binds 127.0.0.1 only — no auth, no remote serving.

---

## Roadmap

- **M1 — Capture.** Done.
- **M2 — Single-branch optimize.** Done.
- **M3 — Parallel worktrees (N workers, strategy variation).** Done.
- **M4 — Plugin packaging.** Done.
- **M5 — Polish + launch.** Demo fixture + walkthrough in
  [`docs/DEMO.md`](./docs/DEMO.md).
- **M6 — Live web dashboard.** Opt-in `--ui` flag.
- **M7 — One-call workflow + bracket UI.** `/forge:improve` chains capture +
  optimize; dashboard adds live elapsed clock, "Why" reasoning tab, and a
  bracket diagram of each round.

---

## License

MIT.
