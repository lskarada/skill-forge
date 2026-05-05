"""Drive the dashboard through a full synthetic run lifecycle.

Used for visual verification of dashboard UI features (progress rings,
edge flow, winner pulse, loser fade, sparkline, strategy tags, elapsed
ticker) without burning API spend on real mutation subagents.

Run:
    uv run python scripts/dev_idle_dashboard.py [--port 7777] [--hold N]

The script pauses at each visually-distinct state so a screenshot tool
or a human eye can capture it. A `--hold` flag extends the final-state
hold (default 60s) so the dashboard stays alive after RunFinished.
"""
from __future__ import annotations

import argparse
import time

from skill_forge.dashboard import events as ev
from skill_forge.dashboard import server as srv


def emit(evt) -> None:
    ev.emit_event(evt)
    print(f"  → {evt}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--hold", type=int, default=60,
                    help="seconds to hold after RunFinished (default 60)")
    ap.add_argument("--phase-pause", type=float, default=4.0,
                    help="seconds between visually-distinct states")
    args = ap.parse_args()

    s = srv.DashboardServer(port=args.port)
    s.start()
    print(f"dashboard: http://127.0.0.1:{s.port}\n")

    pause = args.phase_pause

    # Phase 0 — run kicks off
    emit(ev.RunStarted(skill="greeter", run_id="dev-synthetic", num_workers=3))
    time.sleep(0.5)

    # Phase 1 — baseline runs and comes back red
    emit(ev.PhaseChanged(phase=1))
    time.sleep(1.0)
    emit(ev.BaselineCaptured(passed=0, failed=1, errors=0))
    time.sleep(pause)

    # Phase 2 — fork worktrees + spawn workers (queued). Real workers
    # pass spawned_at=time.monotonic() so the per-row elapsed clock is
    # sane; mirror that here.
    emit(ev.PhaseChanged(phase=2))
    now = time.monotonic()
    emit(ev.WorkerSpawned(worker_id="w0", spawned_at=now,
                          strategy="Restructure as a numbered checklist with imperative steps."))
    emit(ev.WorkerSpawned(worker_id="w1", spawned_at=now,
                          strategy="Tighten the output contract with an explicit format block."))
    emit(ev.WorkerSpawned(worker_id="w2", spawned_at=now,
                          strategy="Schema-tag every field with required/optional flags."))
    time.sleep(pause)

    # Phase 3 — mutating (this is where progress rings + edge flow are visible)
    emit(ev.PhaseChanged(phase=3))
    emit(ev.WorkerStatus(worker_id="w0", status="mutating"))
    emit(ev.WorkerStatus(worker_id="w1", status="mutating"))
    emit(ev.WorkerStatus(worker_id="w2", status="mutating"))
    print("\n  --- HOLD: workers in MUTATING (progress rings + flowing edges) ---")
    time.sleep(pause)

    # Mid-Phase-3 — workers transition to testing one at a time so the
    # sparkline picks up dots progressively.
    emit(ev.WorkerStatus(worker_id="w0", status="testing"))
    time.sleep(pause / 2)
    emit(ev.WorkerStatus(worker_id="w1", status="testing"))
    time.sleep(pause / 2)
    emit(ev.WorkerStatus(worker_id="w2", status="testing"))
    print("\n  --- HOLD: all workers TESTING ---")
    time.sleep(pause)

    # Tests come back — best-of-three differing scores so sparkline has shape
    emit(ev.WorkerTested(worker_id="w0", passed=1, failed=0, errors=0))
    time.sleep(0.6)
    emit(ev.WorkerTested(worker_id="w1", passed=1, failed=0, errors=0))
    time.sleep(0.6)
    emit(ev.WorkerTested(worker_id="w2", passed=1, failed=0, errors=0))
    time.sleep(pause)

    # Phase 4 — regression gate
    emit(ev.PhaseChanged(phase=4))
    time.sleep(pause)

    # Phase 5 — merge winner, discard the rest (winner pulse + losers fade)
    emit(ev.PhaseChanged(phase=5))
    emit(ev.WorkerStatus(worker_id="w0", status="merged"))
    emit(ev.WorkerStatus(worker_id="w1", status="discarded"))
    emit(ev.WorkerStatus(worker_id="w2", status="discarded"))
    print("\n  --- HOLD: w0 MERGED with pulse, w1+w2 DISCARDED faded ---")
    time.sleep(pause)

    emit(ev.RunFinished(outcome="merged"))
    print(f"\nfinished — holding {args.hold}s for inspection. Ctrl-C to exit early.")
    try:
        time.sleep(args.hold)
    except KeyboardInterrupt:
        pass
    finally:
        s.stop()


if __name__ == "__main__":
    main()
