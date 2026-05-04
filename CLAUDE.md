# Synthetic Experts Skill Pack

## What This Is

Distributable Claude skill pack containing four synthetic expert personas trained on real operators' published work. Each expert (April Dunford, Andy Raskin, Elena Verna, Kyle Poyar) is a dedicated `/slash-command` thought partner offering opinionated, framework-based advice grounded in their actual thinking.

v1 ships four experts + roundtable orchestrator + about page. Chris Orlob follows in v1.1 once corpus assembly completes.

## Architecture (post-rewire 2026-05-04)

Each `skills/<name>/SKILL.md` is **self-contained** — the system prompt, profile content, voice samples, and frameworks are all inlined directly into the SKILL.md body. There is no runtime dependency on absolute paths, separate profile files, or the battlecard source repo. Users install one skill folder and it works.

The reference `profiles/` folder at the repo root mirrors the inlined content for transparency and contribution — but it is not loaded at runtime. If you edit a profile there, you must also update the corresponding `skills/<name>/SKILL.md` for the change to take effect for installed users.

## Source of Truth (developer-facing only)

The battlecard source repo at `/Users/paulnugent/AI-Lab/projects/battlecard/synthetic-experts/` is the working copy where new profiles are drafted, smoke-tested, and refreshed. When changes ship, port them into this distribution repo by:

1. Updating the canonical profile copy in `profiles/<name>.md`
2. Updating the corresponding `skills/<name>/SKILL.md` (re-inline the relevant sections)
3. Bumping the snapshot date at the bottom of the SKILL.md

This is friction-by-design — the skill pack should ship slower than the source repo, with a deliberate cherry-pick step.

## Distribution Model

Public-facing distribution layer at `github.com/paulnugentuk/synthetic-experts`. Install by cloning and copying skill folders into Claude Code or Cowork `.claude/skills/` directory.

Skills are designed to be installed by end-users, not forked or modified. Voice integrity and grounding in published work are non-negotiable — if a profile drifts from source material, it fails.

## v1 Scope

- Four expert personas (Dunford, Raskin, Verna, Poyar)
- Roundtable orchestrator (pure-prompt — runs in user's own Claude session, no Python)
- About page with links to published work
- README with install instructions and example
- MIT licence

Out of scope for v1: corpus/smoke-tests/tools directories, Chris Orlob profile, API wrapper, persistence layer, hosted demo.
