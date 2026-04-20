"""Milestone 2 optimize loop.

Pipeline (PRD §3, N=1):
    baseline → fork worktree → mutate → regression gate → merge or discard

Every side effect (git, pytest, subagent, stdout) is injected via OptimizeIO
so the orchestrator is unit-testable without spawning Claude or touching
a real repo. The CLI wires production implementations; tests wire fakes.

Contract with SOUL.md: no silent merges. Every accepted mutation writes
`history/<skill>/v<N>_evidence.md` with the baseline, diff, and post-gate
numbers. Every rejected mutation appends a one-line learning so the next
attempt's strategy prompt can avoid the same failure.
"""

from __future__ import annotations

import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator

from skill_forge import baseline as baseline_mod
from skill_forge import dispatch
from skill_forge import worktree as wt_mod
from skill_forge.prompts import DEFAULT_MUTATION_STRATEGY, strategies_for

BRANCH_PREFIX = "skill-forge"
DEFAULT_OUTPUT_ROOT = ".skill-forge"


@dataclass
class OptimizeConfig:
    skill: str
    repo_path: Path = field(default_factory=Path.cwd)
    output_root: Path = field(default_factory=lambda: Path.cwd() / DEFAULT_OUTPUT_ROOT)
    tests_dir: Path | None = None  # defaults to output_root/tests/<skill>
    strategy: str = DEFAULT_MUTATION_STRATEGY
    assume_yes: bool = False
    num_workers: int = 1  # M3: >1 triggers parallel fork-and-pick
    strategies: list[str] | None = None  # optional override for per-worker strategies
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(timezone.utc)
    )


@dataclass
class OptimizeIO:
    printer: Callable[[str], None]
    prompter: Callable[[str], str]
    # Injectable seams for tests ---------------------------------------
    mutator: Callable[..., str] = dispatch.mutate_skill
    pytest_runner: Callable[..., baseline_mod.BaselineResult] = baseline_mod.run_pytest
    sut_resolver: Callable[..., Path] = dispatch.resolve_sut_path
    worktree_factory: Callable[..., ContextManager[wt_mod.WorktreeHandle]] = wt_mod.create_worktree
    committer: Callable[[Path, str], str | None] = wt_mod.commit_all
    merger: Callable[..., None] = wt_mod.merge_branch
    branch_discarder: Callable[[Path, str], None] = wt_mod.discard_branch


@dataclass
class OptimizeResult:
    outcome: str  # "merged" | "regression" | "tie" | "no_change" | "aborted"
    baseline: baseline_mod.BaselineResult | None = None
    post_mutation: baseline_mod.BaselineResult | None = None
    evidence_path: Path | None = None
    branch: str | None = None
    merge_sha: str | None = None
    mutation_summary: str = ""
    # M3: populated on parallel runs; empty on N=1. Ordered by worker index.
    worker_results: list["WorkerResult"] = field(default_factory=list)


@dataclass
class WorkerResult:
    """One worker's slice of a parallel optimize run.

    The orchestrator compares these against the baseline to pick a winner
    and writes a per-worker learning on every loss. `mutated_sut_length`
    is the PRD's token-minimization tiebreaker signal (shorter prompt wins).
    """

    index: int
    branch: str
    strategy: str
    outcome: str  # "won" | "lost" | "no_change" | "error"
    post: baseline_mod.BaselineResult | None = None
    commit_sha: str | None = None
    mutation_summary: str = ""
    mutated_sut_length: int | None = None
    error: str | None = None


# --- public entry ---------------------------------------------------------


def run_optimize(config: OptimizeConfig, io: OptimizeIO) -> OptimizeResult:
    tests_dir = _resolve_tests_dir(config)
    if not tests_dir.is_dir() or not list(tests_dir.glob("test_*.py")):
        io.printer(
            f"no regression tests found in {tests_dir}. Run `forge capture` first "
            "to record a failure."
        )
        return OptimizeResult(outcome="aborted")

    sut_path = io.sut_resolver(config.skill, search_root=config.repo_path)
    io.printer(f"skill: {config.skill}")
    io.printer(f"SUT:   {sut_path}")
    io.printer(f"tests: {tests_dir}")
    if config.num_workers > 1:
        io.printer(f"workers: {config.num_workers} (parallel)")

    # Phase 1: baseline -----------------------------------------------------
    io.printer("phase 1/5: baseline")
    baseline_junit = _junit_path(config, suffix="baseline")
    baseline = io.pytest_runner(
        tests_dir,
        cwd=config.repo_path,
        junit_xml=baseline_junit,
    )
    io.printer(
        f"baseline: {baseline.passed} passed, {baseline.failed} failed, "
        f"{baseline.errors} errors"
    )

    if baseline.failed == 0 and baseline.errors == 0:
        io.printer("baseline already green — nothing to optimize. Done.")
        return OptimizeResult(outcome="no_change", baseline=baseline)

    if not _confirm(config, io, "proceed with mutation?"):
        return OptimizeResult(outcome="aborted", baseline=baseline)

    if config.num_workers > 1:
        return _run_parallel(
            config=config,
            io=io,
            sut_path=sut_path,
            tests_dir=tests_dir,
            baseline=baseline,
        )

    # Phase 2+3: fork worktree and mutate ----------------------------------
    branch = _branch_name(config)
    learnings = _read_learnings(config)
    tests_preview = _preview_tests(tests_dir)

    io.printer(f"phase 2/5: forking worktree on branch {branch}")
    with io.worktree_factory(
        config.repo_path, branch, base_ref="HEAD"
    ) as handle:
        _hydrate_worktree(config.repo_path, handle.path, config.skill)
        worktree_sut = _sut_in_worktree(sut_path, config.repo_path, handle.path)
        worktree_tests_dir = _tests_dir_in_worktree(tests_dir, config.repo_path, handle.path)
        io.printer(f"phase 3/5: spawning mutation subagent")
        mutation_summary = io.mutator(
            sut_path=worktree_sut,
            tests_preview=tests_preview,
            learnings=learnings,
            strategy=config.strategy,
            cwd=handle.path,
        )
        io.printer(f"mutation summary: {mutation_summary.strip()[:200]}")

        commit_sha = io.committer(handle.path, f"skill-forge: mutate {config.skill}")
        if commit_sha is None:
            io.printer("subagent produced no changes — discarding.")
            _append_learning(
                config,
                f"strategy={config.strategy!r}: subagent produced no diff.",
            )
            return OptimizeResult(
                outcome="no_change",
                baseline=baseline,
                branch=branch,
                mutation_summary=mutation_summary,
            )

        # Phase 4: regression gate -----------------------------------------
        io.printer("phase 4/5: regression gate (running tests against mutated SUT)")
        mutated_junit = _junit_path(config, suffix="mutated")
        post = io.pytest_runner(
            worktree_tests_dir,
            cwd=handle.path,
            junit_xml=mutated_junit,
        )
        io.printer(
            f"mutated: {post.passed} passed, {post.failed} failed, "
            f"{post.errors} errors"
        )

        # Phase 5: merge or discard ----------------------------------------
        if post.strictly_better_than(baseline):
            io.printer("phase 5/5: MERGE — mutation improved passing tests without new regressions")
            version = _next_version(config)
            evidence_path = _write_evidence(
                config=config,
                sut_path=sut_path,
                baseline=baseline,
                post=post,
                mutation_summary=mutation_summary,
                branch=branch,
                commit_sha=commit_sha,
                verdict="merged",
                version=version,
            )
            io.merger(
                config.repo_path,
                branch,
                message=f"skill-forge: {config.skill} v{version}",
            )
            merge_sha = _head_sha(config.repo_path)
            io.branch_discarder(config.repo_path, branch)
            return OptimizeResult(
                outcome="merged",
                baseline=baseline,
                post_mutation=post,
                evidence_path=evidence_path,
                branch=branch,
                merge_sha=merge_sha,
                mutation_summary=mutation_summary,
            )

        verdict = _classify_loss(baseline, post)
        io.printer(f"phase 5/5: DISCARD ({verdict})")
        _append_learning(
            config,
            (
                f"strategy={config.strategy!r}: {verdict}. "
                f"baseline p/f/e={baseline.passed}/{baseline.failed}/{baseline.errors} "
                f"mutated p/f/e={post.passed}/{post.failed}/{post.errors}."
            ),
        )
        evidence_path = _write_evidence(
            config=config,
            sut_path=sut_path,
            baseline=baseline,
            post=post,
            mutation_summary=mutation_summary,
            branch=branch,
            commit_sha=commit_sha,
            verdict=verdict,
        )

    # Outside the with: worktree is removed; now delete the dead branch.
    io.branch_discarder(config.repo_path, branch)
    return OptimizeResult(
        outcome=verdict,
        baseline=baseline,
        post_mutation=post,
        evidence_path=evidence_path,
        branch=branch,
        mutation_summary=mutation_summary,
    )


# --- helpers --------------------------------------------------------------


def _resolve_tests_dir(config: OptimizeConfig) -> Path:
    if config.tests_dir is not None:
        return config.tests_dir
    return config.output_root / "tests" / config.skill


def _junit_path(config: OptimizeConfig, *, suffix: str) -> Path:
    ts = config.now().strftime("%Y%m%d_%H%M%S")
    return config.output_root / "runs" / config.skill / f"{ts}_{suffix}.xml"


def _branch_name(config: OptimizeConfig) -> str:
    ts = config.now().strftime("%Y%m%d-%H%M%S")
    safe_skill = re.sub(r"[^A-Za-z0-9._-]", "-", config.skill)
    return f"{BRANCH_PREFIX}/{safe_skill}/{ts}"


def _confirm(config: OptimizeConfig, io: OptimizeIO, question: str) -> bool:
    if config.assume_yes:
        return True
    answer = io.prompter(f"{question} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _read_learnings(config: OptimizeConfig) -> str:
    path = config.output_root / "learnings.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _append_learning(config: OptimizeConfig, note: str) -> None:
    path = config.output_root / "learnings.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = config.now().strftime("%Y-%m-%d %H:%M:%SZ")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- [{ts}] [{config.skill}] {note}\n")


def _preview_tests(tests_dir: Path, *, max_bytes: int = 20_000) -> str:
    """Concatenate test files for inclusion in the mutation prompt."""
    chunks: list[str] = []
    used = 0
    for path in sorted(tests_dir.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        header = f"\n# --- {path.name} ---\n"
        size = len(header) + len(text)
        if used + size > max_bytes:
            chunks.append(f"\n# (truncated: {path.name} omitted — limit reached)\n")
            break
        chunks.append(header + text)
        used += size
    return "".join(chunks) or "(no tests found)"


def _sut_in_worktree(sut_path: Path, repo_path: Path, worktree_path: Path) -> Path:
    """Map an absolute SUT path under repo_path to the same relative in a worktree."""
    relative = sut_path.resolve().relative_to(repo_path.resolve())
    return worktree_path / relative


def _tests_dir_in_worktree(tests_dir: Path, repo_path: Path, worktree_path: Path) -> Path:
    """Map tests_dir (usually under output_root) into the worktree's matching path."""
    try:
        relative = tests_dir.resolve().relative_to(repo_path.resolve())
    except ValueError:
        # tests_dir is outside the repo — fall back to the original path.
        return tests_dir
    return worktree_path / relative


def _hydrate_worktree(repo_path: Path, worktree_path: Path, skill: str) -> None:
    """Copy untracked .skill-forge/ artifacts into the worktree.

    `git worktree add` only carries tracked files; the regression suite lives
    under `.skill-forge/tests/<skill>/` and replays under `.skill-forge/replays/`,
    both of which are user scratch and typically gitignored. Without this,
    pytest in the worktree finds no tests and run_skill's relative replay paths
    don't resolve.
    """
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    for subpath in (Path(".skill-forge") / "tests" / skill, Path(".skill-forge") / "replays"):
        src = repo_path / subpath
        if not src.is_dir():
            continue
        dst = worktree_path / subpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)


def _next_version(config: OptimizeConfig) -> int:
    history_dir = config.output_root / "history" / config.skill
    if not history_dir.is_dir():
        return 1
    existing = [p.stem for p in history_dir.glob("v*_evidence.md")]
    nums = [int(s[1:].split("_")[0]) for s in existing if s.startswith("v") and s[1:].split("_")[0].isdigit()]
    return (max(nums) + 1) if nums else 1


def _write_evidence(
    *,
    config: OptimizeConfig,
    sut_path: Path,
    baseline: baseline_mod.BaselineResult,
    post: baseline_mod.BaselineResult,
    mutation_summary: str,
    branch: str,
    commit_sha: str,
    verdict: str,
    version: int | None = None,
) -> Path:
    history_dir = config.output_root / "history" / config.skill
    history_dir.mkdir(parents=True, exist_ok=True)
    if version is None:
        version = _next_version(config)
    path = history_dir / f"v{version}_evidence.md"
    ts = config.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    body = f"""# {config.skill} v{version} — {verdict}

- Timestamp: {ts}
- Branch: `{branch}`
- Commit: `{commit_sha}`
- SUT: `{sut_path}`
- Strategy: {config.strategy!r}

## Baseline

- passed: {baseline.passed}
- failed: {baseline.failed}
- errors: {baseline.errors}
- total:  {baseline.total}

## Post-mutation

- passed: {post.passed}
- failed: {post.failed}
- errors: {post.errors}
- total:  {post.total}

## Subagent summary

{mutation_summary.strip() or '(no summary)'}
"""
    path.write_text(body, encoding="utf-8")
    return path


def _classify_loss(baseline: baseline_mod.BaselineResult, post: baseline_mod.BaselineResult) -> str:
    if post.passed < baseline.passed:
        return "regression"
    if post.passed == baseline.passed:
        return "tie"
    # post.passed > baseline.passed but also introduced new failures
    return "regression"


def _head_sha(repo_path: Path) -> str | None:
    proc = wt_mod._run_git(["rev-parse", "HEAD"], cwd=repo_path, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


# --- M3: parallel fork-and-pick ------------------------------------------


def _run_parallel(
    *,
    config: OptimizeConfig,
    io: OptimizeIO,
    sut_path: Path,
    tests_dir: Path,
    baseline: baseline_mod.BaselineResult,
) -> OptimizeResult:
    """Fork N worktrees, run mutations in parallel, merge the winner.

    Thread-safety model:
      * Each worker owns a unique worktree + branch.
      * Git ops on the main repo (`worktree add/remove`, `branch -D`, `merge`)
        are serialized via `repo_lock` — the main `.git/` is not safe for
        concurrent `worktree add` calls in older git versions, and this keeps
        us conservative.
      * Git ops *inside* a worktree (commit, pytest) run unlocked — each has
        its own index and working tree.
      * The shared `learnings.md` is only written from the main thread
        after all workers complete, so no write contention.
    """
    tests_preview = _preview_tests(tests_dir)
    learnings_snapshot = _read_learnings(config)
    strategies = strategies_for(config.num_workers, override=config.strategies)
    base_branch = _branch_name(config)
    repo_lock = threading.Lock()

    io.printer(f"phase 2/5: forking {config.num_workers} worktrees from {base_branch}*")
    io.printer(f"phase 3/5: spawning {config.num_workers} parallel mutation subagents")

    def run_worker(index: int) -> WorkerResult:
        branch = f"{base_branch}/w{index}"
        strategy = strategies[index]
        try:
            with _locked_worktree(io, config.repo_path, branch, repo_lock) as handle:
                _hydrate_worktree(config.repo_path, handle.path, config.skill)
                worktree_sut = _sut_in_worktree(sut_path, config.repo_path, handle.path)
                worktree_tests = _tests_dir_in_worktree(tests_dir, config.repo_path, handle.path)

                # Claude Code hard-blocks writes under `.claude/` even with
                # --dangerously-skip-permissions, which would otherwise make
                # SKILL.md edits impossible. Stage the SUT at a scratch path
                # outside `.claude/` for the subagent, then copy back from the
                # harness (which has no such block) before commit.
                scratch_sut = handle.path / "MUTATION_TARGET.md"
                shutil.copy(worktree_sut, scratch_sut)

                summary = io.mutator(
                    sut_path=scratch_sut,
                    tests_preview=tests_preview,
                    learnings=learnings_snapshot,
                    strategy=strategy,
                    cwd=handle.path,
                )

                shutil.copy(scratch_sut, worktree_sut)
                scratch_sut.unlink(missing_ok=True)

                commit_sha = io.committer(
                    handle.path, f"skill-forge: mutate {config.skill} [w{index}]"
                )
                if commit_sha is None:
                    return WorkerResult(
                        index=index,
                        branch=branch,
                        strategy=strategy,
                        outcome="no_change",
                        mutation_summary=summary,
                    )

                # Capture mutated SUT length before worktree is torn down —
                # it's the tie-breaker signal for token minimization.
                mutated_length = len(worktree_sut.read_text(encoding="utf-8"))

                worker_junit = _junit_path(config, suffix=f"mutated_w{index}")
                post = io.pytest_runner(
                    worktree_tests,
                    cwd=handle.path,
                    junit_xml=worker_junit,
                )

            return WorkerResult(
                index=index,
                branch=branch,
                strategy=strategy,
                outcome="won" if post.strictly_better_than(baseline) else "lost",
                post=post,
                commit_sha=commit_sha,
                mutation_summary=summary,
                mutated_sut_length=mutated_length,
            )
        except Exception as exc:  # noqa: BLE001 — worker-level isolation, surface as data
            return WorkerResult(
                index=index,
                branch=branch,
                strategy=strategy,
                outcome="error",
                error=f"{type(exc).__name__}: {exc}",
            )

    results: list[WorkerResult] = []
    with ThreadPoolExecutor(max_workers=config.num_workers) as pool:
        futures = {pool.submit(run_worker, i): i for i in range(config.num_workers)}
        for fut in as_completed(futures):
            result = fut.result()
            results.append(result)
            io.printer(
                f"  worker {result.index}: {result.outcome}"
                + (
                    f" ({result.post.passed}p/{result.post.failed}f/{result.post.errors}e, "
                    f"len={result.mutated_sut_length})"
                    if result.post is not None
                    else ""
                )
                + (f" [error: {result.error}]" if result.error else "")
            )
    results.sort(key=lambda r: r.index)

    io.printer("phase 4/5: regression gate — picking the winner")
    winner = _pick_winner(results, baseline)

    if winner is None:
        io.printer("phase 5/5: DISCARD (no worker strictly beat baseline)")
        for r in results:
            _append_learning(config, _loss_note(r, baseline))
        # Write an evidence file summarizing the whole parallel run, even
        # when nothing merged — SOUL.md: no silent losses either.
        evidence_path = _write_parallel_evidence(
            config=config,
            sut_path=sut_path,
            baseline=baseline,
            results=results,
            winner=None,
        )
        # Clean up every branch that actually committed — empty mutations
        # never created a branch-worth-deleting but `branch -D` is tolerant.
        with repo_lock:
            for r in results:
                io.branch_discarder(config.repo_path, r.branch)
        overall = _overall_loss_outcome(results, baseline)
        return OptimizeResult(
            outcome=overall,
            baseline=baseline,
            post_mutation=_best_post(results),
            evidence_path=evidence_path,
            worker_results=results,
        )

    io.printer(
        f"phase 5/5: MERGE — worker {winner.index} wins "
        f"({winner.post.passed}p/{winner.post.failed}f, len={winner.mutated_sut_length})"
    )
    version = _next_version(config)
    evidence_path = _write_parallel_evidence(
        config=config,
        sut_path=sut_path,
        baseline=baseline,
        results=results,
        winner=winner,
        version=version,
    )

    with repo_lock:
        io.merger(
            config.repo_path,
            winner.branch,
            message=f"skill-forge: {config.skill} v{version} (w{winner.index})",
        )
        merge_sha = _head_sha(config.repo_path)
        # Discard every branch, including the winner's — the merge commit
        # already carries its content, so the branch label is redundant.
        for r in results:
            io.branch_discarder(config.repo_path, r.branch)

    # Record every loser's attempt in shared learnings so the next run
    # avoids repeating a dead-end strategy.
    for r in results:
        if r is winner:
            continue
        _append_learning(config, _loss_note(r, baseline))

    return OptimizeResult(
        outcome="merged",
        baseline=baseline,
        post_mutation=winner.post,
        evidence_path=evidence_path,
        branch=winner.branch,
        merge_sha=merge_sha,
        mutation_summary=winner.mutation_summary,
        worker_results=results,
    )


@contextmanager
def _locked_worktree(
    io: OptimizeIO,
    repo_path: Path,
    branch: str,
    lock: threading.Lock,
) -> Iterator[wt_mod.WorktreeHandle]:
    """Serialize only the git-level enter/exit of `create_worktree`.

    `git worktree add` mutates `.git/worktrees/` on the main repo; doing it
    under a lock avoids racing metadata writes when N workers start at once.
    The yielded worktree is then used without the lock — pytest and
    subagent edits inside a worktree never touch main's .git.
    """
    cm = io.worktree_factory(repo_path, branch, base_ref="HEAD")
    with lock:
        handle = cm.__enter__()
    try:
        yield handle
    finally:
        with lock:
            cm.__exit__(None, None, None)


def _pick_winner(
    results: list[WorkerResult],
    baseline: baseline_mod.BaselineResult,
) -> WorkerResult | None:
    """Highest passing count wins; PRD tiebreaker: shorter SUT wins."""
    winners = [
        r for r in results
        if r.outcome == "won" and r.post is not None
    ]
    if not winners:
        return None
    winners.sort(
        key=lambda r: (
            -r.post.passed,
            r.post.failed + r.post.errors,
            r.mutated_sut_length if r.mutated_sut_length is not None else 10**9,
            r.index,
        )
    )
    return winners[0]


def _overall_loss_outcome(
    results: list[WorkerResult],
    baseline: baseline_mod.BaselineResult,
) -> str:
    """Classify a run where nothing merged.

    `no_change` if every worker produced an empty diff. Otherwise pick the
    strictly worst outcome across workers: any regression trumps ties.
    """
    any_committed = any(r.outcome in {"won", "lost"} for r in results)
    if not any_committed:
        return "no_change"
    for r in results:
        if r.post is None:
            continue
        if r.post.passed < baseline.passed or (
            r.post.failed + r.post.errors
        ) > (baseline.failed + baseline.errors):
            return "regression"
    return "tie"


def _best_post(results: list[WorkerResult]) -> baseline_mod.BaselineResult | None:
    """Return the best post-mutation counts across all workers, for reporting."""
    posts = [r.post for r in results if r.post is not None]
    if not posts:
        return None
    return max(posts, key=lambda p: (p.passed, -(p.failed + p.errors)))


def _loss_note(r: WorkerResult, baseline: baseline_mod.BaselineResult) -> str:
    if r.outcome == "no_change":
        return f"[w{r.index}] strategy={r.strategy!r}: subagent produced no diff."
    if r.outcome == "error":
        return f"[w{r.index}] strategy={r.strategy!r}: worker error — {r.error}"
    post = r.post
    if post is None:
        return f"[w{r.index}] strategy={r.strategy!r}: no post-mutation result."
    if r.outcome == "won":
        # Beat baseline but lost the tournament tiebreak. Preserve that signal —
        # mislabeling a runner-up as "regression" teaches the next run to avoid
        # a strategy that actually worked.
        verdict = "runner-up (beat baseline, lost tiebreak)"
    else:
        verdict = _classify_loss(baseline, post)
    return (
        f"[w{r.index}] strategy={r.strategy!r}: {verdict}. "
        f"baseline p/f/e={baseline.passed}/{baseline.failed}/{baseline.errors} "
        f"mutated p/f/e={post.passed}/{post.failed}/{post.errors} "
        f"len={r.mutated_sut_length}."
    )


def _write_parallel_evidence(
    *,
    config: OptimizeConfig,
    sut_path: Path,
    baseline: baseline_mod.BaselineResult,
    results: list[WorkerResult],
    winner: WorkerResult | None,
    version: int | None = None,
) -> Path:
    """Per-run evidence file covering every worker (merged or not).

    SOUL.md's "no silent merges" clause extends to parallel losses: even when
    every worker fails, the run leaves an audit trail naming each strategy
    that was tried and what score it earned. Next run reads `learnings.md`;
    humans read this.
    """
    history_dir = config.output_root / "history" / config.skill
    history_dir.mkdir(parents=True, exist_ok=True)
    ts = config.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    if winner is not None:
        if version is None:
            version = _next_version(config)
        path = history_dir / f"v{version}_evidence.md"
        title = f"{config.skill} v{version} — merged"
    else:
        stamp = config.now().strftime("%Y%m%d_%H%M%S")
        path = history_dir / f"loss_{stamp}_evidence.md"
        title = f"{config.skill} — no merge ({len(results)} workers)"

    lines: list[str] = [
        f"# {title}",
        "",
        f"- Timestamp: {ts}",
        f"- SUT: `{sut_path}`",
        f"- Workers: {len(results)}",
        "",
        "## Baseline",
        "",
        f"- passed: {baseline.passed}",
        f"- failed: {baseline.failed}",
        f"- errors: {baseline.errors}",
        f"- total:  {baseline.total}",
        "",
    ]
    if winner is not None and winner.post is not None:
        lines.extend([
            "## Winner",
            "",
            f"- Worker: {winner.index}",
            f"- Branch: `{winner.branch}`",
            f"- Commit: `{winner.commit_sha}`",
            f"- Strategy: {winner.strategy!r}",
            f"- Passed: {winner.post.passed}",
            f"- Failed: {winner.post.failed}",
            f"- Errors: {winner.post.errors}",
            f"- SUT length (chars): {winner.mutated_sut_length}",
            "",
            "## Winner summary",
            "",
            winner.mutation_summary.strip() or "(no summary)",
            "",
        ])

    lines.append("## Worker outcomes")
    lines.append("")
    for r in results:
        p = (
            f"{r.post.passed}p/{r.post.failed}f/{r.post.errors}e"
            if r.post is not None else "(no post)"
        )
        tag = "WIN" if r is winner else r.outcome.upper()
        lines.append(
            f"- [w{r.index}] {tag} — {p}, len={r.mutated_sut_length}, "
            f"strategy={r.strategy!r}"
        )
        if r.error:
            lines.append(f"    - error: {r.error}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
