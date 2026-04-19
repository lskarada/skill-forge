---
name: forge:optimize
description: Run one baseline → mutate → regression-gate → merge cycle on a skill, optionally in parallel worktrees.
argument-hint: "<skill-name> [--workers N] [--strategies …] [--strategy …] [--tests-dir …] [--output-root …] [--yes]"
---

You are running the Skill-Forge optimize loop. Invoke the `forge` CLI to run
the mutation tournament against the named skill.

Run:

```
forge optimize $ARGUMENTS
```

The optimize CLI will:
1. Run the full pytest suite for the skill to establish a baseline score.
2. Create N git worktrees (default 1; `--workers 5` for the parallel tournament).
3. Spawn one mutation subagent per worktree with a strategy directive.
4. Re-run pytest in each worktree. Keep the strictly-better winner.
5. Merge the winner's branch into the current working tree; discard losers.
6. Write `.skill-forge/history/<skill>/v<N>_evidence.md` summarizing the run
   and append loser learnings to `.skill-forge/learnings.md`.

Never auto-answer prompts unless the user passed `--yes`. A regression exit is
a failure — surface it.
