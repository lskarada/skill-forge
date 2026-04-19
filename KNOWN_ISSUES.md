# Known Issues

Things noticed but deliberately deferred. Each entry names the failure mode,
the trigger, and the milestone that would be the right time to fix it. If
you hit one of these in practice, the fix is no longer deferred.

---

## transcript.py

### Live-file read race
**Trigger:** the most recent `.jsonl` is usually the session that is *currently
running*, still being written to. A partial final line is possible.
**Impact:** the partial line is silently skipped by `load_entries` (covered by
`test_midwrite_partial_line_is_skipped`), but on very rare timing, the file
could be mid-write when we `open()` and we'd read a shorter snapshot than
exists on disk a moment later. No lock, no snapshot.
**When to fix:** if capture ever misses a failure because of this, not before.
Expected rate: <1/20 captures.

### `--current-session` not distinguishable
**Trigger:** today the latest transcript is almost always the session you're
running in. There's no way to say "the *previous* session." A user running
`forge capture` against the current session is reading a file they're still
writing; capturing from a prior session requires `--transcript <path>`.
**When to fix:** Milestone 2. If an explicit "previous session" heuristic is
needed beyond the `--transcript` override, add it when the mutation loop
lands.

---

## capture.py

### Escape-hatch tests are not guaranteed to be runnable
**Trigger:** when the capture agent picks `cannot_express_in_dsl=true` and the
user chooses option (b), we write the agent's free-form pytest verbatim
(prefixed with a warning comment). We don't syntax-check or import-check it.
**When to fix:** Milestone 2, when test execution is wired into the mutation
loop. A syntax-invalid escape-hatch test will fail loud at run time.

### `--yes` on DSL-gap defaults to skip
**Trigger:** the DSL-gap branch offers three choices (skip / hatch / note).
Under `--yes`, we can't pick between them, so we fall through to (a) skip.
This means scripted runs never auto-generate escape-hatch tests, which is
conservative but may surprise dogfood users.
**When to fix:** never, probably. The escape hatch is intentionally friction-
laden; if a scripted run needs one, the transcript deserves a human look.

---

## optimize.py

### Workers do not cross-pollinate
**Trigger:** Milestone 3 ships N parallel workers, but each is isolated —
they all fork from the same baseline and cannot see peer mutations while
in flight. Losers only inform *future* runs via `learnings.md`, never the
current tournament.
**When to fix:** Milestone 4+ if a real skill plateaus on a strategy set
that clearly needs a "build on this partial win" step.

### Tiebreak is SUT length only
**Trigger:** `_pick_winner` prefers more passing, then fewer errors, then
shorter mutated SUT, then lower worker index. This is a crude proxy for
"the more token-efficient skill is better." Two workers that emit the
same-length rewrite (different wording) get picked by index order.
**When to fix:** if dogfood shows the wrong worker keeps winning the
tiebreak. A content-similarity or prompt-token-count signal is the next
step up.

### Merge conflicts are surfaced as errors, not resolved
**Trigger:** the mutation only touches SUT markdown, so in practice merges
are fast-forward clean. But if the user commits to main between baseline
and merge, `git merge` can conflict. We raise WorktreeError rather than
attempt resolution.
**When to fix:** Milestone 3 or later, if users hit it during dogfood.

### No rollback on partial merge
**Trigger:** `worktree.merge_branch` + `branch_discarder` + evidence write
happen sequentially. If the process dies between merge and branch delete,
the branch is orphaned but harmless — `git worktree prune` later cleans it.
If it dies between evidence write and merge, evidence points at an
un-merged commit.
**When to fix:** if it happens in practice. The blast radius is a stale
evidence file, not a corrupted repo.

### Learnings file is append-only; never rotated
**Trigger:** `learnings.md` accumulates one line per discarded mutation.
Over hundreds of runs it becomes large, and the mutation prompt reads the
whole file. M3 makes this worse (N-1 learnings per run, not 1).
**When to fix:** Milestone 4+, or when a single `forge optimize` invocation
feeds > ~10k chars of learnings to the subagent.

### run_skill shells out for every assertion
**Trigger:** a test file with N replays triggers N `claude -p` calls. Each
one is tens of seconds. Multiplied by the pytest baseline + regression
run (2x), a skill with 5 tests takes ~10 minutes to optimize.
**When to fix:** Milestone 4. A "SUT snapshot" or in-process response
cache could collapse identical replays.

### Evidence only records counts, not diffs
**Trigger:** `v<N>_evidence.md` shows pass/fail counts and the subagent's
summary, but not the actual SKILL.md diff. The git log has it, but the
evidence file alone isn't self-contained for offline review.
**When to fix:** cheap fix, do it whenever someone complains — run
`git diff base..branch -- <sut>` and embed in evidence.

---

## Project-wide

### No CI
**Trigger:** tests have to be run by hand with `uv run pytest`.
**When to fix:** when there's enough to break — probably Milestone 2 or 3.

### No test coverage for rendering
**Trigger:** `render_turn` and `_render_block` in transcript.py are only
smoke-tested by eyeballing real output. Cosmetic regressions (empty thinking
blocks, oversized tool_use input, tool_result with list-of-dicts content)
could slip in silently.
**When to fix:** if rendering becomes load-bearing for the capture agent's
accuracy (i.e., if the agent starts misclassifying failures because of bad
excerpts), add render tests then.

### `claude -p` subagent dispatch is subprocess-level
**Trigger:** `dispatch.run_claude` shells out to the `claude` binary and
assumes it's on PATH. No retry, no streaming, no structured error recovery
— a transient LLM failure crashes the capture. `SKILL_FORGE_CLAUDE_BIN`
env var exists for tests but not for production robustness.
**When to fix:** Milestone 2, when multiple subagent calls compound the
risk. A structured dispatch layer with retry/timeout is warranted then.

---

## bin/forge wrapper (M4)

### Mid-session plugin install requires a new Claude Code session
**Noted:** 2026-04-19.
**Trigger:** Claude Code injects a plugin's `bin/` directory into the Bash
tool's PATH at **session start**. Running `/plugin install skill-forge@skill-forge`
inside an already-running session does not update that PATH, so `forge`
stays "command not found" until the user opens a new Claude Code session.
The plugin install itself succeeds; only the bare-CLI path is affected.
Slash commands work either way because they're dispatched through the
plugin router, not PATH.
**Impact:** a stranger following the README in one sitting hits this on
the first `forge --help` attempt and is likely to assume the install
failed.
**When to fix:** not a SkillForge bug — this is Claude Code plugin loader
behavior. Fix is documentation: README should tell readers to restart
Claude Code after install before using the bare `forge` command.
Milestone 5 polish.

### `bin/forge` hard-requires `uvx`; no fallback
**Noted:** 2026-04-19.
**Trigger:** the wrapper checks for `uvx` on PATH and, if missing, prints
an install hint (brew / pip / astral.sh install script) and exits 127.
There is no secondary code path — no `pipx`, no `python -m`, no vendored
venv. If the user refuses to install `uv`, the plugin is dead weight.
**Impact:** one extra prerequisite on every fresh install. Acceptable
tradeoff for the MVP (uvx eliminates venv management entirely), but it
*is* a real door-slam rather than a soft recommendation.
**When to fix:** Milestone 5+ if dogfood shows users bouncing off the
uv requirement. A `pipx run --spec <plugin-root> forge` fallback would
cover the "already have pipx, don't want another tool" audience without
much code. Not urgent until someone actually asks.
