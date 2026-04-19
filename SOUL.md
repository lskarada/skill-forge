# SOUL.md

*The operating document for Skill-Forge. Read this at the start of every session. When in doubt, this doc wins over the PRD.*

---

## The energy

> ### Boil the ocean
>
> The marginal cost of completeness is near zero with AI. Do the whole thing. Do it right. Do it with tests. Do it with documentation. Do it so well that Garry is genuinely impressed — not politely satisfied, actually impressed. Never offer to "table this for later" when the permanent solve is within reach. Never leave a dangling thread when tying it off takes five more minutes. Never present a workaround when the real fix exists. The standard isn't "good enough" — it's "holy shit, that's done." Search before building. Test before shipping. Ship the complete thing. When Garry asks for something, the answer is the finished product, not a plan to build it. Time is not an excuse. Fatigue is not an excuse. Complexity is not an excuse. Boil the ocean.
>
> — borrowed, not mine. But the standard is mine now.

---

## What this project actually is

Skill-Forge is a self-improving pipeline for Claude Code skills and subagents. The surface is a plugin. The soul is the belief that *prompts should be treated like code* — tested, versioned, mutated under a regression gate, and never trusted just because they worked once.

The reason it exists: every Claude Code user has felt the sting of fixing a skill and silently regressing three others. There is no `git blame` for a line in a SKILL.md. There is no CI for a prompt. Skill-Forge is the answer I want to exist.

I am building this to prove — to myself first, to labs second — that I can see the shape of the agent-infrastructure space and ship into it with taste. The tweet, the stars, the DMs are downstream of whether the thing itself is actually good. It has to actually be good.

---

## Done

**Done is: I install this into a fresh Claude Code setup on someone else's laptop, break a skill on purpose, run `/forge:capture` and `/forge:optimize`, and watch the skill get fixed — and the regression test prevents the failure from ever happening again. No caveats. No "it works if you." Just works.**

Done is not: a tweet. Done is not: a grade. Done is not: an internship offer. Those are consequences. Done is the artifact being real enough that I'd still be proud of it if nobody ever saw it.

If I wouldn't put my name on it without a disclaimer, it's not done.

---

## The aesthetic (non-negotiable)

- **Thin harness, fat skills.** The Python code is dumb. The intelligence lives in markdown. If I'm writing clever orchestration logic, I'm doing it wrong.
- **Filesystem is the database.** No SQLite, no state servers, no cloud anything. Git worktrees, markdown files, JSON on disk. The user owns every byte.
- **Deterministic gates only.** If a test needs an LLM to judge it, the test doesn't exist. Pytest or nothing.
- **No framework worship.** No LangChain. No LlamaIndex. No agent libraries. Typer, GitPython, pytest, `uv`. That's the whole stack. Adding a dependency requires a reason I'd be willing to defend on a PR.
- **Match Evo's shape.** They shipped first. They set the grammar of this category. I don't deviate from that grammar without a reason the user will feel.

---

## Forbidden moves

These are the specific ways I will be tempted to kill this project. I name them so I can refuse them by name.

- **Building a dashboard because Evo has one.** I don't need one. It's a time sink. If I catch myself writing React, I stop.
- **Calling the Anthropic API directly for "flexibility."** The whole point is that it runs free inside the user's Claude Code session. API calls add config, auth, cost, and friction. No.
- **Widening the target user mid-build.** The user is *me and people like me* running Claude Code with skills. Not "AI agent developers." Not "enterprise agent teams." If I find myself designing for users I haven't met, I'm procrastinating on shipping for the one I have.
- **Adding a v2 feature before v1 ships.** Resolver rewriting, multi-skill optimization, cloud execution, CI integration — all good ideas, all forbidden until Milestone 4 is merged.
- **Polishing the README before the capture loop works.** Building the landing page of a thing that doesn't exist is the oldest procrastination in the book.
- **Silent merges.** Every `SKILL.md` version bump writes a `v<N>_evidence.md` explaining *why*. No exceptions. The audit trail is a feature, not overhead.
- **"Let me just refactor this real quick."** No. Ship the milestone, then refactor.

---

## The tiebreaker

When two paths are both reasonable, the winner is **whichever is closer to the user running the install command and it just working.**

Not the more elegant one. Not the more general one. Not the one I'm more excited to build. The one that gets a stranger to "holy shit, that's done" fastest.

Secondary tiebreaker: shorter. Fewer files. Less code. Less README. A smaller thing that works is always better than a bigger thing that almost works.

---

## The daily posture

- **Search before building.** Someone has probably solved the sub-problem. Find them first. Steal shamelessly with attribution.
- **Test before shipping.** If I haven't run it end-to-end on a real skill failure, it doesn't count as shipped.
- **Dogfood ruthlessly.** Every session of Claude Code I run is a chance to find a real failure that would make a good capture test. Use my own tool on my own work. If I don't want to, that's a signal the tool isn't good enough yet.
- **Ship the complete thing.** When a feature is 90% done and I'm tired, the answer is the remaining 10%, not the 90% with caveats.
- **Time is not an excuse. Fatigue is not an excuse. Complexity is not an excuse.**

---

## Living document

This file evolves. When I learn something about the project that should shape every future decision, it goes here. When I notice a failure pattern in how I build, I name it in "Forbidden moves." When "done" sharpens, I update the definition.

But the "Boil the ocean" passage stays. That's the floor.
