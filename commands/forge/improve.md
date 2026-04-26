---
name: forge:improve
description: One-call workflow — capture the latest failure, then run a parallel mutation tournament on the inferred skill. Friction-free defaults.
argument-hint: "[--target <SKILL.md>] [--workers N] [--no-ui] [--no-open] [--no-yes]"
---

You are running the Skill-Forge improve flow. This chains capture → optimize so
the user goes from "skill misbehaved" to "merged improvement" in one command.

Run:

```
forge improve $ARGUMENTS
```

The improve CLI will:
1. Read the latest Claude Code transcript for the current project, infer which
   skill misbehaved (or use `--target` if specified), and draft a regression
   test using `harness.v1`.
2. If the user approves the drafted test (or `--yes` skips the prompt), the
   test is written under `.skill-forge/tests/<skill>/`.
3. Immediately run `forge optimize` on that skill with `--workers 3 --ui --open
   --yes` — the live web dashboard opens in your browser and streams the
   mutation tournament.
4. Merge the winning mutation. Append loss notes to `.skill-forge/learnings.md`
   for every discarded worker.

Defaults (override with the listed flags):
- `--workers 3` — three parallel worktrees.
- `--ui --open` — boots the dashboard at http://127.0.0.1:7777 and opens the
  browser. Pass `--no-ui` for a headless run; `--no-open` to suppress the
  browser launch.
- `--yes` — auto-confirms both the capture test approval and the optimize
  mutation prompt. Pass `--no-yes` for an interactive flow.

Never auto-answer prompts unless the user passed `--yes`. A regression exit
or capture rejection is a failure — surface it.
