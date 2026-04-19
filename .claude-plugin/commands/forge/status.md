---
name: forge:status
description: Show tracked skills, pending tests, merged runs, and learnings.
argument-hint: "[--skill <name>] [--output-root <path>]"
---

You are running the Skill-Forge status report. Invoke the `forge` CLI to
inspect the local `.skill-forge/` directory and summarize what's tracked.

Run:

```
forge status $ARGUMENTS
```

The status CLI will:
1. Walk `.skill-forge/tests/` to list every skill with a regression suite.
2. Walk `.skill-forge/history/<skill>/` to count merged versions (`v<N>_evidence.md`)
   and loss runs (`loss_<ts>_evidence.md`).
3. Report the most recent merged version per skill and its timestamp.
4. Report the current size of `learnings.md`.

This command is read-only. It does not run pytest and does not spawn any
subagent. Safe to call any time.
