# Synthetic Experts Skill Pack

## What This Is

Distributable Claude skill pack containing four synthetic expert personas trained on real operators' published work. Each expert (April Dunford, Andy Raskin, Elena Verna, Kyle Poyar) is a dedicated `/slash-command` thought partner offering opinionated, framework-based advice grounded in their actual thinking.

v1 ships four experts + roundtable orchestrator + about page. Chris Orlob follows in v1.1 once corpus assembly completes.

## Architecture (post-rewire 2026-05-04)

Each `skills/<name>/SKILL.md` is **self-contained** — the system prompt, profile content, voice samples, and frameworks are all inlined directly into the SKILL.md body. There is no runtime dependency on absolute paths, separate profile files, or the battlecard source repo. Users install one skill folder and it works.

The reference `profiles/` folder at the repo root mirrors the inlined content for transparency and contribution — but it is not loaded at runtime. If you edit a profile there, you must also update the corresponding `skills/<name>/SKILL.md` for the change to take effect for installed users.

## Repo split (from 15/09/2026, issue #1)

This repo holds the public skill pack (`skills/`, `profiles/`) and, since issue #1, the tooling that builds it (`tools/`, `prompts/`). The source corpus stays on Paul's Mac.

| In this repo (public) | Local only (gitignored) |
|---|---|
| `tools/*.py`, `tools/requirements.txt`, `tools/tests/` | `corpus/`: fetched transcripts, posts, each expert's `sources.yml` |
| `prompts/base-system-prompt.md`, `prompts/distillation-prompt.md` | `smoke-tests/`, `roundtables/`: run outputs |
| `skills/`, `profiles/` | Draft profiles and `profiles/*.bak` in AI-Lab |

Why: cloud sessions can only see GitHub, so the tools need to live here for agents to work on them. The corpus is other people's transcripts and posts, which probably don't belong in a public repo, so it stays on the Mac.

### Pointing the tools at the corpus

Set `SYNTHETIC_EXPERTS_CORPUS` to the corpus folder:

```bash
export SYNTHETIC_EXPERTS_CORPUS=~/AI-Lab/projects/battlecard/synthetic-experts/corpus
python3 tools/refresh_corpus.py --list
```

When it's unset, the tools look for `corpus/` next to `tools/`. On the Mac, `~/AI-Lab/projects/battlecard/synthetic-experts/tools` is a relative symlink to `../../synthetic-experts-skillpack/tools`, so a run through that path finds the AI-Lab corpus without the variable. That only works because the scripts build paths with `os.path.abspath`, which leaves symlinks alone; `Path.resolve()` would follow the symlink into the clone. `tools/tests/test_paths.py` checks it.

Profiles, prompts and run outputs follow the same rule: they're read relative to where the script was invoked. From AI-Lab that means the AI-Lab working copies; from a clone it means this repo's.

### Two clones on the Mac, one job each (decided 16/09/2026)

- `~/Code/synthetic-experts` is the dev checkout. Branch, test and open PRs here.
- `~/AI-Lab/projects/synthetic-experts-skillpack` is the runtime clone. The weekly Cowork sweep runs its `tools/`, because a Cowork scheduled task mounts a single folder (`~/AI-Lab`) and can't see `~/Code`. Keep it on `main` with no local changes, and after each merge run:

```bash
git -C ~/AI-Lab/projects/synthetic-experts-skillpack pull --ff-only
```

Don't clone the repo anywhere else, and don't point anything in AI-Lab at `~/Code`. Absolute paths outside `~/AI-Lab` don't resolve inside the sandbox.

### Which tickets need the Mac

Issues labelled `agent` can be done by a cloud session from this repo alone: tool code, tests, prompts, skills and docs. Issues labelled `desk` need the Mac, because they touch the local corpus, pull YouTube from a residential IP, run Whisper, or need Paul's judgement. A cloud session that picks up a `desk` ticket should stop and say so on the issue.

YouTube in particular: `refresh_corpus.py` pulls English auto-subtitles with yt-dlp, and YouTube tends to block datacentre IPs, so the weekly sweep leaves it out (`--skip-source youtube`). Paul runs it from Terminal on the Mac instead:

```bash
python3 tools/refresh_corpus.py --all --source youtube
```

### Tests and CI

`python -m pytest tools/` runs the tool tests. CI (`.github/workflows/ci.yml`) runs them on every PR, plus `refresh_corpus.py --list` against the fixture corpus in `tools/tests/fixtures/corpus/`. Fixtures should be made up; real corpus content stays out of the repo.

## Source of Truth for profiles (developer-facing only)

Profiles are still drafted, smoke-tested and refreshed in AI-Lab at `/Users/paulnugent/AI-Lab/projects/battlecard/synthetic-experts/`. When changes ship, port them into this distribution repo by:

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

Out of scope for v1: the corpus and run outputs (local only, see Repo split), Chris Orlob profile, API wrapper, persistence layer, hosted demo.
