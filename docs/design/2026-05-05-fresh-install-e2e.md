# Fresh-Install E2E Test Tier

**Date:** 2026-05-05
**Status:** Approved (architecture + test list + failure-mode handling)
**Author:** Claude (under user direction)

## Context

SkillForge ships through the Claude Code marketplace. A new user runs `/plugin marketplace add <repo>`, then `/plugin install skill-forge`, then `/forge:capture` and `/forge:optimize`. The Python plugin is resolved by `bin/forge`, which delegates to `uvx --from "${PLUGIN_ROOT}[ui]" forge`.

`CLAUDE.md` documents two manual ship gates that exercise this flow:
- **Gate 2:** "5 consecutive red baselines on a fresh `git clone`."
- **Gate 3:** "One full `optimize greeter --workers 3 --yes` run on a fresh clone."

These gates are run by hand. Between releases there is **nothing automated** that catches a regression in the fresh-install path. The classes of regression that slip through:

- Plugin manifest version drift across `pyproject.toml`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (two version fields). SOUL.md non-negotiable; bump-together rule in CLAUDE.md.
- `pytest` accidentally moved to a dev-only dependency group (CLAUDE.md non-obvious rule; would silently break Phase 1 baseline inside the uvx env).
- `bin/forge` wrapper not auto-enabling `[ui]` extras for the `improve` subcommand (bug 963).
- Demo fixture's red baseline drifting from "red by construction" to "red by sampling" (SOUL.md non-negotiable #1).
- Load-bearing string contract in `dispatch.py` (terse-output constraint) being "soften[ed]" away.
- Load-bearing string contract in `optimize.py` (`MUTATION_TARGET.md` staging path) being "simplified" away.
- An `import anthropic` accidentally landing in `src/` (SOUL.md non-negotiable #4).

## Non-goals

- Driving the real `/plugin marketplace add` flow inside Claude Code. Opaque to test headlessly; `uvx --from <local>` covers the same install contract.
- L3 full optimize loop (Phase 1 → Phase 5 with mutation workers). Wall-clock 3–8 min and non-deterministic (mutations may legitimately all lose). Stays as the manual `CLAUDE.md` Gate 3 before tagging.
- Replacing `tests/verify/` (dashboard browser tier) or `tests/manual/` (real-server uvicorn tier). Those are orthogonal.
- Adding LLM-as-judge scoring or any sampling-based verification. SOUL.md forbids both.

## Architecture

One new test tier and one shell entrypoint, mirroring the existing `tests/verify/` + `bin/verify-dashboard` pattern.

### Files added

- `bin/verify-fresh-install` — shell entry point. Ensures `uv` is present, runs `pytest tests/fresh_install/ -m fresh_install -v -x`. First run does `uv sync` to make `pytest` and clone helpers available; later runs are warm.
- `tests/fresh_install/__init__.py` — empty.
- `tests/fresh_install/conftest.py` — two fixtures:
  - `uv_cache` (session-scoped): one `tmp_path_factory.mktemp("uv-cache")` directory used by every live test in the session. The first live test pays ~30s for cold uvx resolution; later tests reuse the cache. Doesn't touch the user's global cache.
  - `fresh_clone` (function-scoped): per test, creates `tmp_path/checkout/`, runs `git clone --local <repo_root> <tmp_path/checkout>` (hardlinks; ~0.3s). `git clone --local` reflects committed state only — to verify uncommitted changes against this tier, commit first. Yields a dataclass `FreshClone(clone_dir, forge, env)` where `env` includes `UV_CACHE_DIR` pointing at the session cache.
- `tests/fresh_install/test_manifest_contracts.py` — tests #1, #2 (static parses; no subprocess).
- `tests/fresh_install/test_uvx_install.py` — tests #3, #4 (live uvx subprocess).
- `tests/fresh_install/test_demo_fixture.py` — tests #5, #6 (drives `bin/forge` against greeter).
- `tests/fresh_install/test_static_contracts.py` — tests #7, #8, #9 (grep-based; no subprocess).

### Files modified

- `pyproject.toml`:
  - `[tool.pytest.ini_options].addopts` becomes `"-m 'not manual and not verify and not fresh_install'"`.
  - `[tool.pytest.ini_options].markers` gains `"fresh_install: cold uvx-install simulation against a fresh git clone, excluded from default CI"`.
- `CLAUDE.md` — under "Commands you will actually run", add `bin/verify-fresh-install`. Under "Shipping a new version", note that this tier automates Gate 2 (Gate 3 stays manual).
- `README.md` — one line in the testing section pointing at the new tier.

### Lifecycle of a single test

```
session starts
  └─ uv_cache fixture (session-scoped)
      └─ tmp_path_factory.mktemp("uv-cache")     (one cache, reused)

test starts
  └─ fresh_clone fixture (function-scoped)
      ├─ git clone --local <repo_root> <tmp>/checkout   (~0.3s)
      ├─ env = os.environ | {"UV_CACHE_DIR": <session uv_cache>}
      └─ yield FreshClone(clone_dir, forge, env)
test body
  └─ subprocess.run([forge, ...], env=env, cwd=clone_dir,
                    capture_output=True, timeout=N, check=False)
      └─ asserts on returncode, stdout, files-on-disk, git log
test ends
  └─ tmp_path cleaned by pytest

session ends
  └─ uv_cache tmp dir cleaned
```

No mocks. **Each test gets a fresh clone** (per-test isolation of filesystem state). **All live tests share one uvx cache** (per-session, for speed). The cache is read-mostly from a test's perspective — clones never share state, only resolved wheels.

## Test list

Total wall-clock: ~3.5 min cold (one ~30s uvx resolve + ~3 min of `forge` invocations), ~3 min warm.

| # | Test | SkillForge contract pinned | Source citation | Cost |
|---|---|---|---|---|
| 1 | `test_manifest_versions_agree` | `pyproject.toml.version` ≡ `plugin.json.version` ≡ `marketplace.json.metadata.version` ≡ `marketplace.json.plugins[skill-forge].version`. | CLAUDE.md "three places the version string lives" + SOUL.md "version bumped in all three manifests" | static, ~0.1s |
| 2 | `test_pytest_in_runtime_deps_not_dev` | `[project].dependencies` (in `pyproject.toml`) includes `pytest`; no separate `[dependency-groups].dev` entry shadows it. | CLAUDE.md "pytest belongs in `[project].dependencies`, not a dev group" | static, ~0.1s |
| 3 | `test_uvx_cold_install_help_works` | `bin/forge --help` exits 0 from a fresh clone with cold `UV_CACHE_DIR`; stdout contains `Usage:` and `forge`. | bug 963 + general resolvability | uvx cold, ~30s once per session |
| 4 | `test_forge_status_clean_repo_no_crash` | `bin/forge status` against a clone with no `.skill-forge/` state exits 0 and does not crash on missing sidecar. | onboarding edge case | reuses cache, ~3s |
| 5 | `test_greeter_baseline_red_by_construction_5x` | `echo n \| bin/forge optimize greeter --workers 1` produces a Phase 1 pytest result with `failed > 0`. **Run 5 consecutive times in one test; ALL must be red.** Any single green run fails the test (assertion: `all(r.failed > 0 for r in results)`). The failure message includes per-run failed/passed counts and a stdout excerpt. | SOUL.md non-negotiable #1 + ship Gate 2 | ~25s × 5 = ~2 min |
| 6 | `test_capture_emits_test_dir_under_skill_forge` | After its **own** `bin/forge optimize greeter --workers 1` (with `echo n`) — independent run, no implicit ordering with test 5 — `<clone>/.skill-forge/tests/greeter/` exists with at least one `test_*.py` file. | CLAUDE.md "regression tests for tracked skills … separate tree" | reuses cache, ~25s |
| 7 | `test_mutation_target_staging_contract_intact` | `src/skill_forge/optimize.py` source contains the literal string `"MUTATION_TARGET.md"`. (Path verified at spec time: `optimize.py:685`.) | CLAUDE.md "Skill-Forge works around [the .claude/ write block] by staging the SUT at `MUTATION_TARGET.md`" | static, ~0.1s |
| 8 | `test_terse_dispatch_constraint_intact` | `src/skill_forge/dispatch.py` source contains the literal string `"Produce only the final assistant response"`. (Path verified at spec time: `dispatch.py:144`.) | CLAUDE.md "load-bearing for test determinism — do not soften it" | static, ~0.1s |
| 9 | `test_no_anthropic_sdk_imports_in_src` | No file under `src/` contains `import anthropic` or `from anthropic` (regex on each `.py` file). | CLAUDE.md + SOUL.md non-negotiable #4 | static, ~0.1s |

### "5x" rationale

SOUL.md forbids sampling-based verification: "I ran it 3 times and it worked" is rejected. Test 6 is the **inverse**: the assertion is `all 5 red`. A single green run fails the test. This matches CLAUDE.md Gate 2 verbatim ("5 consecutive red baselines") and is a deterministic kill criterion, not a probabilistic one.

## Failure-mode handling

When a test fails, the diagnostic must point at root cause. Bypasses forbidden:

- **No `time.sleep` polling with a fixed timeout.** Subprocess invocations use `timeout=N` (hard kill) and surface stdout+stderr in the assertion message.
- **No `pytest.skip` on environment.** The tier already gates on `-m fresh_install`; per-test skips are forbidden. If `uv` is missing, the conftest fails loudly with an install hint (matching `bin/forge`'s own behavior).
- **No `try/except: pass`.** Every subprocess assertion includes captured output on failure.
- **No mocking of `git`, `uv`, or `pytest`.** Mocks make the tier a lie — its purpose is to catch real install/run breakage.
- **No retries on flake.** A "flaky" test in this tier means an actual contract is non-deterministic — investigate at root cause, don't paper over.

### Test 5 specifically (5x red baseline)

If any of the 5 runs goes green, the failure message prints:

```
Test 5 violated SOUL.md non-negotiable #1 (red by construction):
  run 1/5: failed=2 passed=0
  run 2/5: failed=2 passed=0
  run 3/5: failed=0 passed=2  ← GREEN, broke determinism
  run 4/5: failed=2 passed=0
  run 5/5: failed=2 passed=0

Green-run stdout (truncated):
  <first 200 chars of pytest output from the green run>

Diagnose: did the SKILL accidentally satisfy the assertion (real bug)
or did pytest never run (env issue)?
```

Two failure modes, two fixes — the message points the operator at the right one.

### Static-contract tests (7, 8, 9)

If they fail, the test was right and the contract changed. The fix is:
1. Update the test string to match the new contract location.
2. Update the comment in the test that cites the CLAUDE.md / SOUL.md rule (so the citation never rots).
3. Update CLAUDE.md if the rule itself moved.

The test never gets deleted to make a build green.

## Best practices applied

From `shanraisshan/claude-code-best-practice` and project memory:

1. **"Product verification skills"** (their `signup-flow-driver`, `checkout-verifier`) — `tests/fresh_install/` IS the SkillForge-shaped product verifier, overfitted to the install + capture + baseline flow.
2. **Phase-gated tests** (their pattern; user's `feedback_phased_gated_plans` memory) — this adds the missing distribution-layer tier on top of unit + verify, without inflating any one tier.
3. **uvx-extras gating** (user's `feedback_uvx_optional_features` memory) — tests 3, 4, 5, 6 verify the cold uvx env from a fresh cache, exactly the path that bug 963 broke.
4. **No brittle bypasses** (user's `feedback_overfitted_tests` memory) — encoded in §"Failure-mode handling".
5. **Marker exclusion via addopts** (user's `feedback_pytest_marker_exclusion` memory) — `-m 'not manual and not verify and not fresh_install'` updates the existing pattern.

## Resolved decisions

- **Clone reflects HEAD, not working tree.** `git clone --local` only includes committed code, matching what a marketplace install would actually deliver. To verify uncommitted changes against this tier, commit first.
- **uvx cache is session-scoped, clone is per-test.** Cache shared for speed (~30s cold paid once); clone fresh per test for filesystem isolation. Tests never share `.skill-forge/` state.
- **Test 6 runs its own `forge optimize`** rather than coupling to test 5's iteration order. Adds ~25s; buys order-independence.
- **Tests 4 (live `import pytest` in uvx env)** dropped — redundant with test 2 (static manifest parse) + test 5 (live behavior would crash without pytest).
- **No L3 (full mutation loop) in this tier.** Stays as manual `CLAUDE.md` Gate 3 before tagging — wall-clock and non-determinism make it wrong for automated fast-feedback.
- **Subprocess timeouts:** `bin/forge --help` ⇒ 60s (covers cold uvx); `forge status` ⇒ 30s; `forge optimize greeter --workers 1` ⇒ 60s. Hard kill, no retries; assertion message includes captured stdout/stderr on timeout.
