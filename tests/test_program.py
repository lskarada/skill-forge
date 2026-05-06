"""Task 5.2 — program.yaml reader/writer + lineage chain reconstruction."""
from __future__ import annotations

from pathlib import Path

from skill_forge.program import Program, lineage_chain, read_program, write_program


def test_round_trip_program(tmp_path: Path) -> None:
    p = Program(
        id="g0-w0",
        parent="baseline",
        gen=0,
        score=0.812,
        skill_len=1234,
        created_at="2026-05-05T18:00:00Z",
    )

    path = tmp_path / "program.yaml"
    write_program(path, p)
    roundtrip = read_program(path)

    assert roundtrip == p


def test_read_program_handles_quoted_strings(tmp_path: Path) -> None:
    path = tmp_path / "program.yaml"
    path.write_text(
        'id: "g1-w2"\n'
        'parent: "g0-w0"\n'
        "gen: 1\n"
        "score: 0.95\n"
        "skill_len: 200\n"
        'created_at: "2026-05-05T19:00:00Z"\n'
    )
    p = read_program(path)
    assert p.id == "g1-w2"
    assert p.parent == "g0-w0"
    assert p.gen == 1


def test_lineage_chain_walks_parent_pointers(tmp_path: Path) -> None:
    base = Program(id="g0-w0", parent="baseline", gen=0, score=0.5,
                   skill_len=100, created_at="t0")
    mid = Program(id="g1-w1", parent="g0-w0", gen=1, score=0.7,
                  skill_len=120, created_at="t1")
    leaf = Program(id="g2-w0", parent="g1-w1", gen=2, score=0.85,
                   skill_len=140, created_at="t2")

    for prog in (base, mid, leaf):
        write_program(tmp_path / prog.id / "program.yaml", prog)

    chain = lineage_chain(programs_root=tmp_path, leaf_id="g2-w0")

    assert [p.id for p in chain] == ["g0-w0", "g1-w1", "g2-w0"]


def test_lineage_chain_stops_at_baseline_sentinel(tmp_path: Path) -> None:
    base = Program(id="g0-w0", parent="baseline", gen=0, score=0.5,
                   skill_len=100, created_at="t0")
    write_program(tmp_path / base.id / "program.yaml", base)

    chain = lineage_chain(programs_root=tmp_path, leaf_id="g0-w0")
    assert [p.id for p in chain] == ["g0-w0"]
