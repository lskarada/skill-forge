"""Task 5.7 — train/val split for evolve."""
from __future__ import annotations

from pathlib import Path

from skill_forge.validation_split import split_train_val


def test_multi_file_split_uses_val_prefix(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text("def test_a(): pass")
    (tmp_path / "test_b.py").write_text("def test_b(): pass")
    (tmp_path / "val_c.py").write_text("def test_c(): pass")
    (tmp_path / "val_d.py").write_text("def test_d(): pass")

    train, val, warning = split_train_val(tmp_path)

    assert sorted(p.name for p in train) == ["test_a.py", "test_b.py"]
    assert sorted(p.name for p in val) == ["val_c.py", "val_d.py"]
    assert warning is None


def test_multi_file_no_val_prefix_warns(tmp_path: Path) -> None:
    """Multi-file with NO val_*.py: train = all files, val = empty, warn."""
    (tmp_path / "test_a.py").write_text("def test_a(): pass")
    (tmp_path / "test_b.py").write_text("def test_b(): pass")

    train, val, warning = split_train_val(tmp_path)

    assert {p.name for p in train} == {"test_a.py", "test_b.py"}
    assert val == []
    assert warning is not None
    assert "val_" in warning


def test_single_file_splits_by_hash_70_30(tmp_path: Path) -> None:
    body = "\n".join(f"def test_{i}(): pass" for i in range(10))
    (tmp_path / "test_single.py").write_text(body)

    train, val, warning = split_train_val(tmp_path)

    # The single file is in BOTH lists, but with separate function-id sets.
    assert any(p.name == "test_single.py" for p in train)
    assert any(p.name == "test_single.py" for p in val)
    assert warning is not None
    assert "single test file" in warning


def test_empty_directory_returns_empty_split(tmp_path: Path) -> None:
    train, val, warning = split_train_val(tmp_path)
    assert train == []
    assert val == []
    assert warning is None or "no test files" in warning
