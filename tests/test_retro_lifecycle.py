"""Task 8.9 — forge retro --background lifecycle (PID-file managed)."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from skill_forge import retro_lifecycle as rl


def test_background_writes_pidfile_and_kill_removes_it(tmp_path: Path) -> None:
    pid_file = tmp_path / "retro.pid"
    pid = rl._spawn_background(cmd=["sleep", "60"], pid_file=pid_file)
    try:
        assert pid_file.exists()
        assert int(pid_file.read_text()) == pid
    finally:
        killed = rl.kill_background(pid_file=pid_file, grace_seconds=2)
    assert killed is True
    assert not pid_file.exists()


def test_second_background_invocation_errors(tmp_path: Path) -> None:
    pid_file = tmp_path / "retro.pid"
    pid = rl._spawn_background(cmd=["sleep", "60"], pid_file=pid_file)
    try:
        with pytest.raises(rl.RetroAlreadyRunningError):
            rl._spawn_background(cmd=["sleep", "60"], pid_file=pid_file)
    finally:
        rl.kill_background(pid_file=pid_file, grace_seconds=2)


def test_kill_when_no_pidfile_returns_false(tmp_path: Path) -> None:
    pid_file = tmp_path / "missing.pid"
    assert rl.kill_background(pid_file=pid_file) is False


def test_stale_pidfile_is_replaced(tmp_path: Path) -> None:
    pid_file = tmp_path / "retro.pid"
    # PID 999999 is almost certainly not alive
    pid_file.write_text("999999")

    pid = rl._spawn_background(cmd=["sleep", "1"], pid_file=pid_file)
    try:
        assert int(pid_file.read_text()) == pid
    finally:
        # Wait for sleep 1 to finish, then ensure file removed via kill
        time.sleep(1.5)
        rl.kill_background(pid_file=pid_file, grace_seconds=1)
