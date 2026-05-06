"""Train / val split for the evolve loop (paper §2.3.1).

Conventions:
  - Multi-file tests directory: files named `val_*.py` form the validation
    set; everything else is training. If no val files exist, train = all
    files, val = empty, with a warning to add explicit val files.
  - Single-file tests directory: split test functions ~70/30 by hash. The
    same file appears in both lists, with the function-id sets attached so
    the runner can `pytest -k "test_a or test_b"` against the appropriate
    subset.

The split is deterministic by content hash so re-runs across versions
agree on which functions are train vs val (paper §2.3.1 stratification).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

VAL_PREFIX = "val_"
HASH_TRAIN_RATIO = 0.70


def _list_test_files(tests_dir: Path) -> list[Path]:
    return sorted(p for p in tests_dir.glob("test_*.py") if p.is_file()) + \
           sorted(p for p in tests_dir.glob("val_*.py") if p.is_file())


def split_train_val(tests_dir: Path) -> tuple[list[Path], list[Path], str | None]:
    """Return (train_files, val_files, warning_message_or_None).

    For the "multi-file with val_*.py" path the same Path objects appear at
    most once across the two lists. For the "single test file" path, the
    same Path appears in both lists; the caller is expected to filter
    functions via `pytest -k`.
    """
    if not tests_dir.is_dir():
        return [], [], None

    files = _list_test_files(tests_dir)
    if not files:
        return [], [], "no test files in directory"

    val_files = [p for p in files if p.name.startswith(VAL_PREFIX)]
    other_files = [p for p in files if not p.name.startswith(VAL_PREFIX)]

    if len(files) >= 2:
        if val_files:
            return other_files, val_files, None
        return other_files, [], (
            "no val_*.py file found — using all tests for training; "
            "add `val_<name>.py` to define a held-out validation set"
        )

    # Exactly one file: hash-split functions.
    only = files[0]
    return (
        [only],
        [only],
        f"single test file — hash-splitting functions {HASH_TRAIN_RATIO:.0%}/{1-HASH_TRAIN_RATIO:.0%} train/val",
    )


_FUNC_DEF_RE = re.compile(r"^\s*def\s+(test_[A-Za-z0-9_]+)\s*\(", re.M)


def split_test_functions(test_file: Path) -> tuple[list[str], list[str]]:
    """For a single-file test, deterministically partition test functions
    by hash into ~70% train / 30% val. Returns (train_names, val_names)."""
    body = test_file.read_text(encoding="utf-8")
    names = _FUNC_DEF_RE.findall(body)
    train: list[str] = []
    val: list[str] = []
    for name in sorted(set(names)):
        digest = hashlib.sha256(name.encode("utf-8")).digest()
        # First byte / 255 in [0, 1)
        bucket = digest[0] / 255.0
        if bucket < HASH_TRAIN_RATIO:
            train.append(name)
        else:
            val.append(name)
    return train, val
