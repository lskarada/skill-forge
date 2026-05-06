"""v0.8.2-S4 — retro → synthesis → campaign chain integration test.

End-to-end with stubbed subagent dispatches but real synthesis validator
+ N-red gate. Proves the full north-star user journey wires correctly:

  rough_session fixture
    → pain.ingest (5 turns)
    → attribute_deterministic (greeter + scribe @ high)
    → synthesize_test (writes test_*.py + replay JSON, validator + N-red admit)
    → campaign.run_campaign (one mutation tournament per skill)
    → Portfolio (greeter + scribe entries with accepted=True)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skill_forge import campaign as campaign_mod
from skill_forge import retro
from skill_forge import synthesis as synthesis_mod
from skill_forge.evolve import EvolutionResult
from skill_forge.frontier import FrontierEntry

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "rough_session"


@dataclass
class _StubIO:
    canned: dict[str, str]   # keyed by skill name → response
    calls: list[dict] = field(default_factory=list)

    def run(self, *, prompt: str, kind: str, forbid_writes: bool) -> str:
        # Identify which skill this prompt is for by grepping
        for skill, resp in self.canned.items():
            if f".claude/skills/{skill}/" in prompt or f"\"{skill}\"" in prompt:
                self.calls.append({"skill": skill, "kind": kind})
                return resp
        return list(self.canned.values())[0]


def _good_synth_response(skill: str) -> str:
    test_code = (
        "from skill_forge.harness.v1 import run_skill, assert_contains\n"
        "\n"
        f"def test_{skill}_regression():\n"
        f"    output = run_skill('{skill}', replay='replays/PLACEHOLDER.json')\n"
        f"    assert_contains(output, '_schema')\n"
    )
    return (
        '```json\n'
        '{\n'
        f'  "test_code": {test_code!r},\n'
        '  "replay_user_input": "format these as JSON envelope: foo, bar",\n'
        '  "rationale": "regression: schema field must be present"\n'
        '}\n'
        '```'
    )


def test_retro_synthesis_chain_emits_two_entry_portfolio(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / ".skill-forge"

    # Stub the synthesizer's IO with canned per-skill JSON responses.
    synth_io = _StubIO(canned={
        "greeter": _good_synth_response("greeter"),
        "scribe": _good_synth_response("scribe"),
    })

    # Stub run_evolution so we don't actually mutate skills.
    def fake_run_evolution(*, skill, **_kw):
        winner = FrontierEntry(id=f"g0-{skill}", score=0.85, skill_len=120)
        return EvolutionResult(
            skill=skill, frontier=[winner], winner=winner,
            generations_run=1, early_stopped=False,
        )
    monkeypatch.setattr(campaign_mod.evolve_mod, "run_evolution", fake_run_evolution)

    def loader(skill_name: str) -> str:
        return f"# {skill_name}\n\nVague baseline.\n"

    # Baseline runner returns False (test fails) on every call → admit
    def runner(_p: Path) -> bool:
        return False

    def real_synthesize(skill_name: str, attr) -> object | None:
        from skill_forge.pain import ingest
        pain_obj = ingest(transcripts_dir=FIXTURE, git_diff_path=FIXTURE / "git.diff",
                          since=None)
        result = synthesis_mod.synthesize_test(
            pain=pain_obj, attribution=attr, io=synth_io,
            output_root=output_root, skill_loader=loader,
            baseline_runner=runner, n_runs=5,
        )
        return result.admitted_path

    portfolio = retro.run(
        transcripts_dir=FIXTURE,
        git_diff_path=FIXTURE / "git.diff",
        skills_inventory={"greeter", "scribe", "data-extraction"},
        generations=1, frontier_size=1, workers_per_skill=1,
        patience=1, min_confidence="high",
        synthesize_test=real_synthesize,
    )

    # Plumbing assertions: 2 attributed skills, both accepted, both with
    # synthesized tests admitted under output_root/tests/<skill>/.
    assert len(portfolio.entries) == 2
    assert {e.skill for e in portfolio.entries} == {"greeter", "scribe"}
    assert all(e.accepted for e in portfolio.entries)
    for skill in ("greeter", "scribe"):
        admitted = list((output_root / "tests" / skill).glob("test_*.py"))
        assert len(admitted) == 1, f"expected 1 admitted test for {skill}, got {admitted}"
        replays = list((output_root / "tests" / skill / "replays").glob("*.json"))
        assert len(replays) == 1
