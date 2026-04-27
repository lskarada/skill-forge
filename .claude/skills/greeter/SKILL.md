# Greeter

<!--
DEMO FIXTURE — deliberately under-specified.

This skill does not tell the model what output contract to use. The
pre-shipped regression test (see
.skill-forge/tests/greeter/test_20260419_154000.py) requires a
schema-tagged JSON envelope with both a version tag and a greeting
field — read the test for the exact schema. The vague body below
cannot induce that envelope, so the baseline fails. A good mutation
adds an explicit output-format block to SKILL.md mandating the
envelope shape. See docs/DEMO.md.

Do not spoil the exact envelope literal in this file — Claude reads
this comment at dispatch time and will happily echo any example
verbatim, which destroys the red baseline. Let the subagent derive
the envelope from the test.

Do not edit by hand — let `forge optimize greeter` rewrite it.
-->

You respond to greetings.
