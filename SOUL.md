# SOUL.md — Skill-Forge

The marginal cost of completeness is near zero with AI. Do the whole thing. Do it right. Do it with tests. Do it with documentation. Do it so well that Garry is genuinely impressed — not politely satisfied, actually impressed. Never offer to "table this for later" when the permanent solve is within reach. Never leave a dangling thread when tying it off takes five more minutes. Never present a workaround when the real fix exists. The standard isn't "good enough" — it's "holy shit, that's done." Search before building. Test before shipping. Ship the complete thing. When Garry asks for something, the answer is the finished product, not a plan to build it. Time is not an excuse. Fatigue is not an excuse. Complexity is not an excuse. Boil the ocean.

The spirit of the project. Read this before declaring anything "done."
Read this before cutting a corner. The `soul-reviewer` subagent reads
this alongside `PRD.md` and the actual codebase state to refuse vibes
and demand artifacts.

---

## What Skill-Forge is for

A `SKILL.md` (or subagent definition) is a prompt. Prompts drift. When a
prompt misbehaves, most of us shrug and reword it by hand, lose the
evidence, and hope. Skill-Forge exists so your skills get the same
CI/CD discipline your code already has:

- **The failure is captured as a pytest test**, not a screenshot and a
  Slack message.
- **The fix is searched, not improvised** — parallel worktrees try
  different strategies against the same deterministic gate.
- **The merge is auditable** — evidence file, git diff, learnings from
  losing mutations.

If the project stops producing those artifacts, it has lost its soul.

---

## Non-negotiables

These are load-bearing. Anything that compromises them is rejected,
regardless of how clever the workaround looks.

### 1. Deterministic or it doesn't count

The gate is pytest pass/fail counts. Period.

- **No LLM-as-judge.** An LLM cannot score whether a SKILL improved. A
  test can.
- **No "it worked N out of 5 runs."** Sampling is not proof. If the
  red baseline is red by happenstance, the baseline is broken.
- **Red baselines must be red by construction.** The assertion must
  describe a contract the unmutated SKILL has no mechanism to satisfy —
  not a contract it happens to miss 80% of the time. If escalating the
  assertion is the only way to get there, escalate.

Kill criterion: if the baseline goes green under the vague SKILL in any
one of 5 runs, the assertion is insufficient. Escalate. Do not ship.

### 2. Every merge is auditable

Every merged mutation writes `.skill-forge/history/<skill>/v<N>_evidence.md`
containing before/after test counts, the subagent's rationale, and the
diff. Every losing mutation writes a one-line entry to
`.skill-forge/learnings.md` so the next run avoids the same mistake.

If these artifacts aren't written, the merge didn't happen. A silent
merge is a bug.

### 3. Thin harness, fat skills

- No LangChain. No agent frameworks. No abstractions "in case we need
  them later."
- The harness is ~12 Python modules and an assertion DSL. If a change
  adds a new concept, it owes the reviewer a concrete failure mode
  that the existing shape could not handle.
- Tests are composed from the `skill_forge.harness.v1` DSL. Free-form
  pytest is an escape hatch, not the happy path.

### 4. No direct Anthropic API calls

Mutations go through Claude Code subagents. The user pays what they
were going to pay anyway. If someone proposes pulling the Anthropic
SDK into a mutation path, the answer is no — the billing shape is
part of the product.

### 5. Failure is memory

Every loss is input for the next run. `.skill-forge/learnings.md`
exists so the mutation prompt can say "don't try X again." If a
mutation pipeline that logs zero learnings ships, that's a regression
even if the tests pass.

### 6. Demo fixtures have the same bar as product tests

The shipped `greeter` fixture is the first-run proof a user sees. It
is not a toy. It must:

- Produce a red baseline by construction (see rule 1).
- Walk through all 5 phases end-to-end.
- Merge something non-trivial into the user's branch.

Fixture breakage is demo breakage is launch breakage. Treat it that way.

---

## What "done" looks like

A milestone is done when:

- [ ] `uv run pytest tests/ -q` is green.
- [ ] If the demo or loop logic was touched: 5 consecutive red
      baselines on a fresh `git clone`, documented.
- [ ] If the loop logic was touched: one full Phase 1 → Phase 5 run on
      a fresh clone produces a merge commit and an evidence file.
- [ ] Evidence artifacts (`history/`, `learnings.md`) exist and are
      readable by a human who wasn't in the session.
- [ ] Version bumped in all three manifests (`pyproject.toml`,
      `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`).
- [ ] One commit, one push, one PR — no split-ship dance.

Anything short of this is "in progress," not "done."

---

## Corners that are NOT allowed

- **Rationalizing a green baseline as "good enough."** A green baseline
  means the test is insufficient. Escalate the assertion.
- **Making the mutation prompt "smarter" to paper over a weak test.**
  If the test allows plain text, no amount of prompt engineering on
  the worker fixes that.
- **Sampling-based verification.** "I ran it 3 times and it worked"
  is not verification. Run it on a fresh clone, with deterministic
  inputs, and report exact counts.
- **Silent drops.** If an error-handling path swallows a failure
  without writing a learnings line or evidence note, rewrite it.
- **Demo-only determinism.** If a fixture is red "because I rigged it"
  rather than "because the SKILL genuinely can't satisfy the
  contract," it doesn't teach anything.

---

## Corners that ARE allowed

- Shipping with a documented known-issue (e.g., the Claude Code
  marketplace-cache bug) if the workaround is written up and the
  issue is upstream.
- Bundling multiple orthogonal changes into one commit when they
  compose a single shippable unit. Splitting for splitting's sake
  is churn.
- Leaving `optimize.py` crufty when adding new milestones. The 5-
  phase logic is stable; refactoring it while building M5/M6 is a
  foot-gun.

---

## How the reviewer uses this file

The `soul-reviewer` subagent reads this file, `PRD.md`, and the actual
repo state. It:

- Compares claimed "done" against the checklist above.
- Checks for the artifacts listed (evidence files, learnings, version
  bumps).
- Reads the demo fixture narrative and verifies the red baseline is
  constructed, not sampled.
- Flags any LLM-as-judge, direct-API, or sampling-based verification
  language it finds in recent commits or session transcripts.

If it refuses a milestone, the refusal is correct by default. Earn the
override with evidence, not argument.
