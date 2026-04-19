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

---

## Usage

Three slash commands:

| Command             | What it does                                                        |
| ------------------- | ------------------------------------------------------------------- |
| `/forge:capture`    | Read the last session, draft a pytest regression test, gate on Y/N. |
| `/forge:optimize`   | baseline → fork N worktrees → mutate → regression-gate → merge.     |
| `/forge:status`     | Show tracked skills, pending tests, merged runs, learnings size.    |

Typical loop:

```
# Your skill just misbehaved. Capture it.
/forge:capture --target .claude/skills/data-extraction/SKILL.md

# Review the drafted test. Approve if it's right.
# Test lands in .skill-forge/tests/data-extraction/test_<ts>.py

# Now run the mutation tournament. 5 parallel worktrees.
/forge:optimize data-extraction --workers 5

# Check what shipped.
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

## Explicit non-goals

- No dashboard. CLI only.
- No direct Anthropic API calls. Mutations go through Claude Code subagents.
- No LLM-as-judge. Tests are deterministic or they don't count.
- No LangChain or agent frameworks. Thin harness, fat skills.

---

## Roadmap

- **M1 — Capture.** Done.
- **M2 — Single-branch optimize.** Done.
- **M3 — Parallel worktrees (N workers, strategy variation).** Done.
- **M4 — Plugin packaging.** This release.
- **M5 — Polish + launch (demo video, dogfood case).**

See [PRD.md](./PRD.md) and [SOUL.md](./SOUL.md) for the long-form design
rationale. [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) lists what's deliberately
deferred.

---

## License

MIT.
