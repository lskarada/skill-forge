"""`forge retro --background` lifecycle (R10).

Detached subprocess (NOT a daemon) — survives terminal close via
`os.setsid`, but does NOT survive machine reboot. PID is written to
`.skill-forge/retro.pid`; `--kill` reads the file and sends SIGTERM
followed by SIGKILL after 10s.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


PID_FILE = Path(".skill-forge/retro.pid")


class RetroAlreadyRunningError(RuntimeError):
    """Raised when --background is invoked while another retro is alive."""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _spawn_background(*, cmd: list[str], pid_file: Path = PID_FILE) -> int:
    """Spawn `cmd` as a detached subprocess, write its PID, return PID.

    Idempotency: if a live retro is already tracked, raises
    RetroAlreadyRunningError.
    """
    if pid_file.exists():
        try:
            existing = int(pid_file.read_text().strip())
        except (ValueError, OSError):
            existing = 0
        if existing and _pid_alive(existing):
            raise RetroAlreadyRunningError(
                f"retro already running with PID {existing} — "
                f"`forge retro --kill` first or wait for completion"
            )
        # Stale pid file — remove it.
        pid_file.unlink(missing_ok=True)

    pid_file.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # equivalent to os.setsid in the child
    )
    pid_file.write_text(str(proc.pid))
    return proc.pid


def kill_background(*, pid_file: Path = PID_FILE, grace_seconds: int = 10) -> bool:
    """Send SIGTERM, wait grace_seconds, then SIGKILL if still alive. Removes
    the pid file in either case. Returns True if a process was killed,
    False if no live retro was tracked.
    """
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return False

    if not _pid_alive(pid):
        pid_file.unlink(missing_ok=True)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return False

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            pid_file.unlink(missing_ok=True)
            return True
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    pid_file.unlink(missing_ok=True)
    return True
