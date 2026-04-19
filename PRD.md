# Skill-Forge

**A Claude Code plugin that makes your skills and subagents self-improving.**

You hand it a skill (or subagent definition) that's been misbehaving. It captures the failure, writes a regression test, forks parallel Claude Code subagents in git worktrees to try fixes, keeps the winner, and commits. Your `SKILL.md` files get a CI/CD pipeline for free.

Inspired by [Evo](https://github.com/evo-hq/evo) and [Karpathy's autoresearch](https://github.com/karpathy/autoresearch). Evo optimizes your code. Skill-Forge optimizes your instructions.

---

## 1. The Problem (read this first)

Claude Code users accumulate `SKILL.md` files and subagent definitions over time. They're written in natural language, they fail in ways that are hard to predict, and when you fix one failure you often regress three others. There's no test suite for a prompt. There's no git blame for *why* a line in a skill exists. Fixes are vibes-based.

Skill-Forge treats skills as code. Every failure becomes a test. Every proposed fix has to pass the full regression suite before it gets merged. The loop is:

```
failure → captured test → forked worktrees → parallel mutations → regression gate → merge winner
```

**The wedge vs. Evo:** Evo runs benchmarks you already have. Skill-Forge has to *manufacture* the benchmark from a failed Claude Code session. The capture-and-generate-test pipeline is the hard part and the defensible part. Build that well and the rest follows.

---

## 2. Architecture

Three components, strictly separated.

### 2.1 The Plugin (thin harness)

- Ships as a Claude Code plugin: `/plugin marketplace add <your-handle>/skill-forge`
- Exposes three slash commands (MVP):
  - `/forge:capture` — grab the last failure from the current session
  - `/forge:optimize` — run the mutation loop against captured failures
  - `/forge:status` — show current baseline, pending tests, recent runs
- The plugin shell is a Python CLI (Typer) that Claude Code invokes. It orchestrates but does not reason.

### 2.2 The Skill Under Test (SUT)

- User points Skill-Forge at any markdown file: `/forge:capture --target .claude/skills/data-extraction/SKILL.md`
- Also works for subagent definitions (`.claude/agents/*.md`) — any markdown is valid.
- The SUT is the thing that gets mutated. It is *never* mutated in place — only in worktrees.

### 2.3 The Orchestrator

- Stateless Python script. Dispatches Claude Code subagents. Waits for `result.json` files in worktrees. Runs pytest.
- **Does not call the Anthropic API directly.** All LLM work happens inside spawned Claude Code subagents using the user's existing session. Zero API cost to the user. This mirrors Evo.

---

## 3. The Workflow (the meat of the build)

### Phase 0 — Capture the failure (Auto-TDD)

1. User runs `/forge:capture` after a skill misbehaves in their session.
2. Plugin reads the most recent transcript from `~/.claude/projects/<hash>/` (Claude Code stores session JSONL files here — verify exact path during build).
3. A capture subagent reads the transcript, identifies the skill invocation that went wrong, and drafts:
   - A `pytest` test file asserting the correct behavior (schema validation, required fields, forbidden outputs)
   - A short `failure_note.md` explaining what went wrong in human terms
4. **DSL constraint.** The capture agent composes the test from the Assertion DSL helpers only (see Section 4). Free-form pytest is not the default path. If the failure cannot be expressed in the current DSL, the capture agent says so explicitly at the approval gate and presents three options:
   - **(a) Skip this test.** Some failures aren't worth a regression test (e.g., a one-off flake). No-op, nothing is written.
   - **(b) Write a free-form pytest escape hatch.** The capture agent drafts plain pytest. The approval gate flags the test as `unreviewed surface area` and records it in `.skill-forge/history/<skill-name>/escape_hatches.md`. Use sparingly.
   - **(c) Expand the DSL.** User notes the missing helper. Adding a new helper is a Milestone 2+ decision and blocks this specific test — pick (a) or (b) to unblock the current capture session.
5. **Human gate:** Plugin prints the drafted test and asks `Approve this test? [y/N]`. Nothing proceeds without approval. This is non-negotiable — if the test is wrong, the optimizer will optimize toward the wrong thing.
6. On approval, test is written to `.skill-forge/tests/<skill-name>/test_<timestamp>.py` and the failure trace is appended to `.skill-forge/learnings.md`.

### Phase 1 — Establish baseline

- Run the full pytest suite for this skill against the current `SKILL.md`.
- Record pass/fail counts. This is the score to beat.

### Phase 2 — Fork (parallel worktrees)

- `/forge:optimize` creates N git worktrees (default N=5, configurable).
- Each worktree gets a branch: `skill-forge/opt-<run_id>-<n>`.
- Each worktree contains a pristine copy of the repo at HEAD.

### Phase 3 — Mutate (parallel subagents)

- Orchestrator spawns N Claude Code subagents, one per worktree, with a prompt that includes:
  - The SUT markdown
  - The full test suite for this skill
  - The current `learnings.md` (what other mutations have already failed — prevents duplicate work)
  - A **strategy directive** that varies per subagent (e.g., "restructure as checklist", "add stricter output schema", "rewrite the skill description/resolver for better triggering", "tighten examples")
- Each subagent edits only the SUT file. Not code. Not tests. Not config.
- Subagent returns when it commits its mutation to its worktree branch.

### Phase 4 — Regression gate

- Orchestrator runs pytest in each worktree.
- Scores are deterministic: `tests_passed / tests_total`.
- Tiebreaker: shorter prompt wins (token minimization).

### Phase 5 — Merge and learn

- Winning branch merges to main. Losing branches are destroyed, but their failure traces are appended to `.skill-forge/learnings.md`.
- A `.skill-forge/history/v<N>_evidence.md` file is written explaining *why* this version beat the previous one. This is the audit trail — future mutations must read it before editing.

---

## 4. The Assertion DSL

All generated tests are written against a narrow helper library at `skill_forge.harness.v1`. The capture agent composes tests from this library — free-form pytest is an escape hatch (see Section 3, Phase 0), not the default path.

The DSL exists for two reasons:

1. **The human approval gate is only meaningful if tests are readable.** A 40-line free-form pytest file hides bugs. A short stack of named helper calls is reviewable at a glance.
2. **The optimizer's fitness signal is only trustworthy if tests are correct.** Narrow helpers have a vetted surface area; free-form pytest can silently pass for the wrong reason — converging on the wrong fitness target is the single biggest failure mode for this whole system.

### 4.1 The helper set (v1)

All helpers importable from `skill_forge.harness.v1`:

| Helper | Purpose |
|---|---|
| `run_skill(skill, replay)` | Spawn a fresh Claude Code subagent with the (mutated) `SKILL.md` loaded and the replay conversation fed in. Returns the subagent's final assistant output as a string. |
| `assert_contains(output, phrase)` | Asserts `phrase in output`. |
| `assert_not_contains(output, phrase)` | Asserts `phrase not in output`. |
| `assert_regex(output, pattern)` | Asserts `re.search(pattern, output)` is not None. |
| `assert_json_has_field(output, field, parent=None)` | Parses output as JSON (or extracts the first JSON block), asserts `field` is present at `parent` (or at root). |
| `assert_matches_schema(output, schema)` | Validates the parsed JSON output against a `jsonschema` Draft 2020-12 schema. |
| `assert_min_sources(output, n)` | Convenience for citation-style skills: parses output, asserts at least `n` distinct source references. |

Helpers raise `AssertionError` with a short diagnostic on failure. No silent passes, no partial matches masquerading as success.

### 4.2 Import pattern

Tests import *only* from the versioned namespace:

```python
from skill_forge.harness.v1 import run_skill, assert_json_has_field, assert_not_contains
```

Future helpers ship in `v2`, `v3`, etc. Old tests keep working indefinitely — adding a helper does not break existing tests, and removing one requires a version bump. The capture agent always writes `v1` imports unless the user has explicitly opted into a newer version for a specific skill (post-MVP).

### 4.3 Canonical test shape

Every generated test follows this exact structure:

```python
# .skill-forge/tests/data-extraction/test_20260417_1430.py
"""
Captured: 2026-04-17 14:30
Transcript: ~/.claude/projects/<hash>/481a1348.jsonl (turn 14)
Why it failed: the skill returned prose when the user needed structured JSON
with a `sources` field, and included an apology phrase that violates the
skill's own 'no hedging' instruction.
"""
from skill_forge.harness.v1 import (
    run_skill,
    assert_json_has_field,
    assert_not_contains,
)

def test_structured_output_with_sources():
    output = run_skill(
        skill="data-extraction",
        replay="replays/20260417_1430.json",
    )
    assert_json_has_field(output, "sources")
    assert_not_contains(output, "I'm sorry")
```

No `conftest.py` gymnastics, no fixtures, no class-based test organization. One replay file, one or more helper calls. If a test needs more than ~5 helper calls or more than one `run_skill` invocation, the capture agent flags it at the approval gate as "complex test — review carefully or split into two tests."

### 4.4 Replay format

A replay is a JSON file at `.skill-forge/tests/<skill-name>/replays/<timestamp>.json`. Locked shape:

```json
{
  "replay_version": "1",
  "captured_at": "2026-04-17T14:30:00Z",
  "source_transcript": "~/.claude/projects/-Users-lskarada-Documents-SkillForge/481a1348.jsonl",
  "source_turn_index": 14,
  "replay_mode": "full_conversation",
  "conversation": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "trigger_turn_index": 2
}
```

Fields:

- `replay_version` — schema version of this file; `"1"` for MVP. Bump on breaking changes.
- `captured_at` — ISO 8601 timestamp of capture.
- `source_transcript` — path to the original `.jsonl` transcript for audit.
- `source_turn_index` — zero-indexed position of the failing turn in the source transcript.
- `replay_mode` — `"full_conversation"` (default) or `"trigger_only"` if the user passed `--replay=trigger-only` at capture time.
- `conversation` — the ordered list of turns to replay. For `full_conversation`, every user/assistant turn up to and including the trigger. For `trigger_only`, a single-element list containing just the trigger user message.
- `trigger_turn_index` — zero-indexed position of the triggering user message within `conversation`. Always points at a `"role": "user"` turn.

`run_skill` reads this file, instantiates a subagent, feeds each turn in order, and returns the subagent's final assistant output.

---

## 5. File Layout

```
<user's repo>/
├── .claude/
│   └── skills/
│       └── data-extraction/
│           └── SKILL.md                    # the SUT
├── .skill-forge/
│   ├── tests/
│   │   └── data-extraction/
│   │       ├── test_20260417_1430.py       # approved regression tests
│   │       └── test_20260417_1615.py
│   ├── history/
│   │   └── data-extraction/
│   │       ├── v1_evidence.md              # why v1 → v2
│   │       └── v2_evidence.md
│   ├── runs/
│   │   └── <run_hash>/
│   │       ├── worktree_0/result.json
│   │       ├── worktree_1/result.json
│   │       └── ...
│   └── learnings.md                        # shared failure memory
└── ...
```

---

## 6. Tech Stack

- **CLI:** `Typer`
- **Version control:** `GitPython` for programmatic worktree management
- **Testing:** `pytest` + `jsonschema` for structural assertions
- **LLM orchestration:** Claude Code subagents spawned via the plugin SDK. **Do not use LiteLLM or direct Anthropic API calls in the MVP.** Zero-cost, zero-config matters for adoption.
- **Package management:** `uv` (same as Evo — match the aesthetic)
- **Python:** 3.12+

---

## 7. Build Order (strict — do not skip ahead)

### Milestone 1: Capture (highest risk, build first)
- [ ] Skeleton Typer CLI with `capture` command
- [ ] Read latest Claude Code session transcript (verify path, handle multi-project case)
- [ ] Identify which skill was invoked and what went wrong
- [ ] Draft a pytest test file via a spawned subagent
- [ ] Human approval gate (simple Y/N prompt)
- [ ] Write approved test to disk

**Ship criteria:** You can run `forge capture` after a failed session and end up with a valid pytest file on disk.

### Milestone 2: Baseline + single-branch optimize
- [ ] `optimize` command that runs pytest against current SUT to establish baseline
- [ ] Create *one* worktree, spawn *one* mutation subagent, run tests
- [ ] If passing > baseline, merge; if not, discard

**Ship criteria:** End-to-end loop works with N=1. No parallelism yet.

### Milestone 3: Parallel worktrees
- [ ] Scale to N=5 worktrees, parallel subagent dispatch (asyncio or subprocess.Popen)
- [ ] Strategy directive variation per subagent
- [ ] Shared `learnings.md` write/read

**Ship criteria:** `forge optimize` runs 5 parallel mutations and merges the winner.

### Milestone 4: Plugin packaging
- [ ] `.claude-plugin/plugin.json` manifest
- [ ] Slash command wrappers (`/forge:capture`, `/forge:optimize`, `/forge:status`)
- [ ] README with install instructions mirroring Evo's format
- [ ] Marketplace-ready

**Ship criteria:** A stranger can `/plugin marketplace add <handle>/skill-forge` and use it.

### Milestone 5: Polish for launch
- [ ] Demo video: break a skill on camera → `/forge:capture` → `/forge:optimize` → fixed skill + regression test
- [ ] Launch tweet drafted (pattern: Alok's Evo tweet)
- [ ] One real dogfood case — use Skill-Forge on a skill in your own setup and document the before/after

---

## 8. Explicit Non-Goals

- **No dashboard.** Evo has one. You don't need one for MVP. Pure CLI.
- **No direct Anthropic API calls.** Everything goes through Claude Code subagents.
- **No LLM-as-judge evaluation.** Tests are deterministic or they don't count. If a test can't be expressed as pytest assertions, reject it at the capture gate.
- **No free-form pytest in the default capture path.** The Assertion DSL (Section 4) is the only path exercised by the optimizer. Escape-hatch tests exist but are flagged as `unreviewed surface area` and not treated as reviewed. If free-form pytest becomes the common case, the DSL is wrong and needs to be expanded — not worked around.
- **No LangChain, no agent frameworks.** Thin harness, fat skills.
- **No multi-user / cloud / auth.** Local filesystem is the database.
- **No support for non-Claude-Code agents in MVP.** Skill-Forge is Claude Code-native. Broader support is a v2 conversation.

---

## 9. Success Criteria (for the course and for launch)

- **Technical:** A user can install the plugin, capture a real failure, and get a merged fix within 10 minutes. The regression test prevents the failure from ever happening again in their session.
- **Narrative:** The launch tweet follows Evo's pattern — short demo video, clear wedge, inspiration credits to Karpathy/Evo. Target: 50+ bookmarks in 48 hours. Bookmark ratio matters more than likes.
- **Career signal:** The repo demonstrates agent-infrastructure taste — worktree orchestration, deterministic gates, failure-as-memory. This is the exact skill set labs hire for.

---

## 10. Open Questions (resolve during Milestone 1)

- Exact path and format of Claude Code session transcripts on the current Claude Code version — this may have changed; verify before coding the parser.
- Does the Claude Code plugin SDK expose a clean way to spawn subagents from within a plugin command, or does the orchestrator need to shell out? Read Evo's source to confirm the pattern.
- How to handle multi-skill failures (one session triggered two skills, both misbehaved)? MVP punt: require the user to specify `--target` explicitly.

---

## 11. First Commands to Run

You're working in `~/Documents/SkillForge` (already created, empty). From that directory:

```bash
cd ~/Documents/SkillForge
uv init . --name skill-forge
uv add typer gitpython pytest jsonschema
mkdir -p src/skill_forge .claude-plugin tests
touch src/skill_forge/__init__.py src/skill_forge/cli.py
```

Then: build Milestone 1. Do not touch Milestone 2 until capture works end-to-end.
