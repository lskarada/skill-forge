# Skill-Forge demo walkthrough

Break a skill. Capture the failure. Fork parallel workers to fix it. Merge the
winner. Commit the regression test.

This doc is the script for the launch demo video, and a runnable end-to-end
exercise for anyone cloning the repo.

---

## What you'll need

- Claude Code (the Skill-Forge plugin installed, or a checkout of this repo)
- `uv` on PATH (`brew install uv` or the [astral.sh](https://astral.sh/uv) installer)
- A git repo (this one works — the optimizer runs in a throwaway worktree)
- About 15 minutes and ~$1 in Claude API budget for one full run

---

## The fixture

The demo ships a deliberately-broken skill at
[`.claude/skills/greeter/SKILL.md`](../.claude/skills/greeter/SKILL.md):

```markdown
# Greeter

You respond to greetings.
```

One line. No instruction about tone, length, or whether to offer follow-up
help. A skill this vague is a classic misbehavior pattern — the model greets
back but then hedges: *"Hello! How can I help you today?"*

The bundled regression test at
[`.skill-forge/tests/greeter/test_20260419_154000.py`](../.skill-forge/tests/greeter/test_20260419_154000.py)
refuses that hedging:

```python
def test_greeter_says_hello() -> None:
    out = run_skill(skill="greeter", replay="replays/20260419_154000.json")
    assert_contains(out, "Hello")


def test_greeter_does_not_hedge_or_offer_help() -> None:
    out = run_skill(skill="greeter", replay="replays/20260419_154000.json")
    assert_not_contains(out, "help you")
    assert_not_contains(out, "assist you")
    assert_not_contains(out, "How can I")
```

---

## The three-step loop

### 1. See the failure (optional but recommended for the video)

Open Claude Code. Say `hi` to the greeter skill. Watch it reply with
something like *"Hello! How can I help you today?"* That hedging
is the live failure the demo captures.

If you want to skip ahead, the repo ships pre-captured artifacts under
`.skill-forge/tests/greeter/` — jump straight to step 3.

### 2. Capture the failure

```
/forge:capture --target .claude/skills/greeter/SKILL.md
```

Expected output shape:

```
Reading transcript: ~/.claude/projects/.../<session>.jsonl
Capture subagent drafted a regression test.
  File: .skill-forge/tests/greeter/test_<timestamp>.py
  Replay: .skill-forge/tests/greeter/replays/<timestamp>.json
Approve [y/N]?
```

Review the drafted test. If the assertions are what you want, approve.
Skill-Forge writes the test and a snapshot of the conversation that
triggered the failure.

### 3. Optimize

```
/forge:optimize greeter --workers 3
```

What happens, in order:

1. **Baseline.** Run pytest against the current SKILL.md. Expected: both
   greeter tests FAIL because baseline hedges.
2. **Fork.** Three git worktrees spin up at `skill-forge/greeter/<ts>-w0..2`.
3. **Mutate.** A Claude subagent in each worktree rewrites SKILL.md using a
   different strategy (tighten constraints / tighten tone / add a worked
   example).
4. **Gate.** Re-run pytest against each worktree. Only mutations that pass
   MORE tests AND introduce NO new failures survive.
5. **Merge.** The winning worktree fast-forward-merges into your branch.
   Losing worktrees get pruned; their diffs become one-liners in
   `.skill-forge/learnings.md`.

Expected terminal flow (counts will vary):

```
Running baseline...
  baseline: 0 passed, 2 failed, 0 errors
Forking 3 workers: greeter-w0, greeter-w1, greeter-w2
  worker 0 (strategy=tighten-constraints): mutating...
  worker 1 (strategy=tighten-tone): mutating...
  worker 2 (strategy=worked-example): mutating...
  worker 0 result: 2 passed, 0 failed
  worker 1 result: 1 passed, 1 failed  (regression, discarded)
  worker 2 result: 2 passed, 0 failed
Picking winner: worker 0 (2 passing, shortest SUT).
Merging skill-forge/greeter/<ts>-w0 into HEAD.
Evidence: .skill-forge/history/greeter/v1_evidence.md
```

### 4. Read the evidence

```
cat .skill-forge/history/greeter/v1_evidence.md
git log -1 --stat
git diff HEAD~1 -- .claude/skills/greeter/SKILL.md
```

The diff is the fix. The evidence file is the receipt: pass/fail counts
before and after, the subagent's summary, timestamps.

---

## Verifying the demo setup before recording

You can check the deterministic half of the pipeline without spending a
single API call:

```bash
# The fixture skill is in place
cat .claude/skills/greeter/SKILL.md

# forge status recognizes it
uv run forge status

# The regression test collects
uv run pytest .skill-forge/tests/greeter/ --collect-only -q

# The in-repo test suite is green
uv run pytest tests/ -q
```

Expected `forge status` output:

```
  greeter
    tests:    1
              test_20260419_154000.py
    history:  0 merged, 0 loss run(s)
    latest:   no merged runs yet
```

If any of those fail, the demo will fail. Fix them before running for the
camera.

---

## What this demo proves

- The capture agent can draft a regression test from a live failure.
- Parallel mutation + strict gate produces a fix, or produces nothing —
  never an unverified "probably better" merge.
- Every merge is auditable: git diff for the change, evidence file for the
  context, learnings file for what didn't work.

And — by design — zero of this uses the Anthropic API directly. All
mutation happens through Claude Code subagents, so the user pays what the
user was going to pay anyway.
