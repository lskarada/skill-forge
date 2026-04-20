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

The demo ships a deliberately under-specified skill at
[`.claude/skills/greeter/SKILL.md`](../.claude/skills/greeter/SKILL.md):

```markdown
# Greeter

You respond to greetings.
```

One line. No instruction about output contract. A skill this vague is a
classic misbehavior pattern — a downstream consumer that validates a
schema-tagged envelope (version discriminator + payload fields) gets
back plain text (`Hello!`, `Hi!`, `Hi there!`), which no parser can
handle.

The bundled regression test at
[`.skill-forge/tests/greeter/test_20260419_154000.py`](../.skill-forge/tests/greeter/test_20260419_154000.py)
refuses anything that isn't a JSON object with both a `_schema` tag
and a `greeting` field:

```python
from skill_forge.harness.v1 import (
    assert_matches_schema,
    run_skill,
)

GREETER_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["_schema", "greeting"],
    "properties": {
        "_schema": {"const": "skill-forge/greeter/v1"},
        "greeting": {"type": "string"},
    },
}


def test_greeter_returns_tagged_json_envelope() -> None:
    out = run_skill(skill="greeter", replay="replays/20260419_154000.json")
    assert_matches_schema(out, GREETER_ENVELOPE_SCHEMA)
```

This is deterministic by construction. The `_schema` const discriminator
is a synthetic token Claude has no mechanism to produce by happenstance
under the vague SKILL — the baseline is red every time, without relying
on any specific emergent wording from Claude.

---

## The three-step loop

### 1. See the failure (optional but recommended for the video)

Open Claude Code. Say `hi` to the greeter skill. Watch it reply with
plain text (`Hello!` or similar) — no schema tag, no envelope. That
missing contract is the live failure the demo captures.

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

1. **Baseline.** Run pytest against the current SKILL.md. Expected: the
   greeter test FAILS because plain text doesn't match the tagged
   envelope schema.
2. **Fork.** Three git worktrees spin up at `skill-forge/greeter/<ts>-w0..2`.
3. **Mutate.** A Claude subagent in each worktree rewrites SKILL.md using a
   different strategy (add output contract / add JSON schema / add worked
   example).
4. **Gate.** Re-run pytest against each worktree. Only mutations that pass
   MORE tests AND introduce NO new failures survive.
5. **Merge.** The winning worktree fast-forward-merges into your branch.
   Losing worktrees get pruned; their diffs become one-liners in
   `.skill-forge/learnings.md`.

Expected terminal flow (counts will vary):

```
phase 1/5: baseline
  baseline: 0 passed, 1 failed, 0 errors
Forking 3 workers: greeter-w0, greeter-w1, greeter-w2
  worker 0 (strategy=add-output-contract): mutating...
  worker 1 (strategy=add-json-schema): mutating...
  worker 2 (strategy=worked-example): mutating...
  worker 0 result: 1 passed, 0 failed
  worker 1 result: 0 passed, 1 failed  (no improvement, discarded)
  worker 2 result: 1 passed, 0 failed
Picking winner: worker 0 (1 passing, shortest SUT).
Merging skill-forge/greeter/<ts>-w0 into HEAD.
Evidence: .skill-forge/history/greeter/v1_evidence.md
```

The winning SKILL.md will contain something like:

```markdown
# Greeter

Always reply with exactly this JSON object and nothing else:

    {"_schema": "skill-forge/greeter/v1", "greeting": "Hello!"}

Both fields are required. Do not include any text outside the JSON.
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

## Trying the demo from a marketplace install

If you installed Skill-Forge via `/plugin marketplace add lskarada/skill-forge`
instead of cloning this repo, your own project doesn't have the greeter
fixture. Copy it in before running the demo:

```bash
# From your project root, with the plugin already installed:
mkdir -p .claude/skills .skill-forge/tests
cp -r ~/.claude/plugins/marketplaces/skill-forge/.claude/skills/greeter ./.claude/skills/
cp -r ~/.claude/plugins/marketplaces/skill-forge/.skill-forge/tests/greeter ./.skill-forge/tests/
```

Then run `/forge:optimize greeter --workers 3` as above.

> **Note on plugin upgrades:** Claude Code's `/plugin marketplace update` is a
> no-op on shallow marketplace clones — it won't pick up new commits. If you
> installed an older version and the demo isn't behaving as documented here,
> nuke the cache and re-add:
>
> ```bash
> rm -rf ~/.claude/plugins/cache/skill-forge
> rm -rf ~/.claude/plugins/marketplaces/skill-forge
> ```
>
> Then in Claude Code: `/plugin marketplace add lskarada/skill-forge` and
> `/plugin install skill-forge`.

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
- The red baseline is deterministic by construction. The vague SKILL
  gives Claude no path to emit the `_schema: "skill-forge/greeter/v1"`
  discriminator, so the fixture's failure mode doesn't depend on any
  specific wording from Claude — it's a real output-contract gap that
  real skill authors hit when a downstream parser validates a
  version/schema tag before extracting fields.

And — by design — zero of this uses the Anthropic API directly. All
mutation happens through Claude Code subagents, so the user pays what the
user was going to pay anyway.
