---
name: forge:capture
description: Capture the most recent failure from this Claude Code session and draft a regression test.
argument-hint: "[--target <path/to/SKILL.md>] [--transcript <session.jsonl>] [--yes]"
---

You are running the Skill-Forge capture flow. Invoke the `forge` CLI to read the
current session transcript, draft a pytest regression test via a capture
subagent, and gate it behind a human Y/N approval.

Run:

```
forge capture $ARGUMENTS
```

The capture CLI will:
1. Read the most recent Claude Code session transcript (or the one the user
   passed via `--transcript`).
2. Spawn a capture subagent that picks the failing skill invocation and
   drafts a pytest test file using the Assertion DSL (`skill_forge.harness.v1`).
3. Print the drafted test and ask the user to approve it.
4. On approval, write the test to `.skill-forge/tests/<skill>/test_<ts>.py` and
   append the failure to `.skill-forge/learnings.md`.

Do not proceed past the human approval gate. If the user rejects, exit cleanly.
