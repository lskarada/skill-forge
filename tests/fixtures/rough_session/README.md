# rough_session/ fixture

Hand-curated rough session for v0.8 retro tests. The pain ingestor walks
both transcripts plus the synthetic git diff and emits a `PainSession`
that attributes pain to exactly two skills.

| File | Turn IDs | Tool calls | User complaint | Expected attribution |
|---|---|---|---|---|
| transcript_001.jsonl | 0,1,2 | `Skill: greeter` (turn 1) | "no, the output isn't tagged" (turn 2) | greeter @ high (literal invocation) |
| transcript_002.jsonl | 0,1 | `Skill: scribe` (turn 1) | "wrong, I needed bullets" (turn 0) | scribe @ high (literal invocation) |

Total turns: 3 + 2 = 5 (`len(pain.turns) == 5`).
Error signatures: `{"TypeError"}` (from transcript_002 turn 1).
Changed files: `{"src/foo.py", "src/bar.py"}` (from git.diff).
