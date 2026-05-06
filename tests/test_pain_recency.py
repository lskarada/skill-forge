"""v0.8.1-D2 — pain.ingest recency slice."""
from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

from skill_forge.pain import ingest


def test_recency_slice_drops_old_jsonl_files(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.jsonl"
    fresh.write_text('{"role":"user","text":"recent"}\n')

    stale = tmp_path / "stale.jsonl"
    stale.write_text('{"role":"user","text":"old"}\n')
    # Backdate the stale file by 48 hours
    old_t = time.time() - 48 * 3600
    os.utime(stale, (old_t, old_t))

    pain = ingest(
        transcripts_dir=tmp_path, git_diff_path=None,
        since=timedelta(hours=24),
    )
    texts = [t.text for t in pain.turns]
    assert "recent" in texts
    assert "old" not in texts


def test_since_none_reads_everything(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.jsonl"
    fresh.write_text('{"role":"user","text":"recent"}\n')
    stale = tmp_path / "stale.jsonl"
    stale.write_text('{"role":"user","text":"old"}\n')
    os.utime(stale, (time.time() - 48 * 3600, time.time() - 48 * 3600))

    pain = ingest(transcripts_dir=tmp_path, git_diff_path=None, since=None)
    texts = [t.text for t in pain.turns]
    assert "recent" in texts and "old" in texts
