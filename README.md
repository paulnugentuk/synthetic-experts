# Synthetic Experts

AI thought partners trained on the operators you'd hire if you could afford them.

Four operators that product marketers channel constantly — Dunford, Raskin, Verna, Poyar — distilled into installable Claude skills. Each one loads a profile from the operator's actual published work and stays in character for the rest of your conversation. Or run all four against the same brief at once and see where they'd disagree.

## The four experts

- **April Dunford** — Positioning, messaging, sales pitch. Author of *Obviously Awesome* and *Sales Pitch*. Reach for `/dunford` when you can't tell why deals are stalling, when "AI for X" doesn't feel like a real category, or when your "unique attributes" sound suspiciously like everyone else's.

- **Andy Raskin** — Strategic narrative. Has built the narrative arc for 100+ companies and writes a long-running essay archive on how to do this well. Use `/raskin` when the deck doesn't move buyers and nobody on the team can articulate the shift in the world that makes the product matter.

- **Elena Verna** — Product-led growth and AI-era acquisition. Currently Head of Growth at Lovable, writes Growth Scoop on Substack. `/verna` is the one to call when the old growth playbook is obviously dying and nobody has a strong view of what replaces it.

- **Kyle Poyar** — Pricing and PLG go-to-market. Writes Growth Unhinged (78,000+ subscribers), former Openview partner. `/poyar` for when pricing tiers don't capture value, when the GTM motion is muddled, or when someone on the team is still confusing "more traffic" with "more pipeline."

## Installation

Requires Claude Pro, Team, or Enterprise.

### Claude Code

```bash
git clone https://github.com/paulnugentuk/synthetic-experts.git
cd synthetic-experts
cp -r skills/* ~/.claude/skills/
```

Restart Claude Code. The skills appear in your command palette.

### Cowork

```bash
git clone https://github.com/paulnugentuk/synthetic-experts.git
cd synthetic-experts
cp -r skills/* /path/to/your/cowork/folder/.claude/skills/
```

The skills load automatically in your next Claude session.

## Example session

```
You: /dunford

I'm building an AI-powered video editing tool. We're positioning it as
"editing for creators." Customers say it saves them hours. How should
we think about positioning this?

Claude (as April Dunford):

"Editing for creators" is feature packaging, not positioning. You've named
the tool, not explained why someone should care. Here's what I'd sharpen.

First question: who is desperate for this? "Creators" is too wide. Is it
TikTok editors racing on 48-hour turnarounds? YouTube long-form editors
sitting in 6-hour edit sessions? Podcast editors? The struggling moment is
completely different for each.

Once you know who's desperate, the competitive alternative becomes obvious.
For TikTok editors, you're not competing with DaVinci Resolve — you're
competing with "lose 8 hours a day to manual editing" or "hire a junior
editor I can't afford." That's where the positioning lives.

Next move: identify which one of your features directly solves the thing
they currently do manually that burns the most time. One feature. That
becomes your hook. Everything else is table stakes.
```

## How this works

Each profile is a markdown file with seven sections — core principles, decision frameworks, default moves, contrarian views, voice samples, AI stance, out-of-domain topics. The base system prompt is a template with placeholders for each section. At runtime, the profile fills the template, Claude reads it as the system prompt, and stays in character.

That's the whole architecture. The real work was the corpus distillation — pulling verbatim quotes from substack archives and podcast transcripts, sharpening contrarian views until they pass the "could only be this person" test, smoke-testing all four against each other to catch drift toward generic advice.

**Source corpus per expert:**

- **Dunford:** *Obviously Awesome*, *Sales Pitch*, Lenny's Podcast appearances, her active Substack (through April 2026)
- **Raskin:** Medium essays on narrative strategy, YouTube talks, keynotes from SaaStr and similar conferences
- **Verna:** Growth Scoop Substack (October 2025–April 2026), case studies, speaking appearances
- **Poyar:** Growth Unhinged newsletter, original research, speaking and advisory work

**The smoke-test that matters:** ask the same question to all four. Do you get four distinct answers? If two experts give substantively the same answer, one of them is under-distilled. Re-run after any profile edit.

## The roundtable

Run the same question through all four experts at once. `/roundtable` returns one structured take per expert, plus a coda naming where they'd disagree (without picking a winner).

```
/roundtable

Company: AgentMail (AI email infrastructure for agents)
Question: What's the single biggest GTM lever for this product right now?
```

Runs in your own Claude session — you pay the standard API cost. About 18p per run on Opus.

## Find their own work

These skills are a discovery layer. The full depth lives in the operators' own writing — click through.

- **April Dunford** — [Obviously Awesome](https://www.obviouslyawesome.com/) · [Sales Pitch](https://www.salespitech.com/) · [Substack](https://april-dunford.substack.com/)
- **Andy Raskin** — [Medium Essays](https://raskin.medium.com/)
- **Elena Verna** — [Growth Scoop Substack](https://www.growthscoop.com/) · [LinkedIn](https://www.linkedin.com/in/elenaverna/)
- **Kyle Poyar** — [Growth Unhinged Newsletter](https://www.growthunhinged.com/) · [LinkedIn](https://www.linkedin.com/in/kylepoyar/)

## For maintainers: the corpus tools

The skills above are all a user needs. The `tools/` folder is how the profiles get built: it refreshes each expert's source corpus, which stays on Paul's Mac and isn't part of this repo (`CLAUDE.md` explains why).

```bash
pip install -r tools/requirements.txt
export SYNTHETIC_EXPERTS_CORPUS=/path/to/corpus
python3 tools/refresh_corpus.py --list
python3 tools/refresh_corpus.py --all --dry-run
```

Each expert has a `<corpus>/<slug>/sources.yml` listing where their material comes from: Substack or RSS feeds, YouTube videos, manually clipped LinkedIn posts, audio for Whisper, and transcript banks. `--source` and `--skip-source` limit a run to some of them (for example `--source youtube`).

### Transcript banks

A transcript bank is a local folder of markdown transcripts, such as a clone of a podcast archive or your own Whisper output. `refresh_corpus.py` walks it and copies any transcript that belongs to the expert into `fetched/transcript-bank/`.

```yaml
sources:
  - type: transcript_bank
    name: Lenny's Podcast (community mirror)
    path: ~/transcripts/lennys
    match:
      guest: ["Elena Verna"]
      filenameContains: ["elena-verna"]
    enabled: true
```

- `path` is the bank folder. `~` is expanded, and hidden folders such as `.git` are skipped.
- `match.guest` picks up a transcript whose frontmatter `guest` (or `guests`) field contains one of these names, ignoring case, so "Elena Verna" also matches "Elena Verna 2.0".
- `match.filenameContains` picks up a transcript whose path inside the bank contains one of these strings, ignoring case. Lenny's mirror names each episode folder after the guest (`episodes/elena-verna-20/transcript.md`), so the folder name counts.
- A source needs at least one rule. With none, it's skipped, so a whole archive can't be copied by accident.

Each copy gets the standard frontmatter (`source`, `sourceUrl` when the original has one, `title`, `publishedAt`, `fetchedAt`, `speaker`) plus `sourcePath` and `sourceHash`. The hash comes from the bank folder's name and the file's path inside it, which makes re-runs safe: anything already copied is skipped, and the bank itself is only ever read. `--source transcript_bank` runs the banks on their own.

## About

Built by [Paul Nugent](https://www.linkedin.com/in/pauldnugent/). Part of [The Battlecard](https://thebattlecard.com/) — a weekly newsletter and tools for product marketers building with AI.

This is v1. Chris Orlob comes in v1.1 once his corpus is assembled. The longer roster — Patrick Campbell on pricing, Peep Laja on B2B research, Jason Lemkin on SaaS — comes if the v1 framing lands.

## Operator notice

These profiles are distilled from publicly available work — books, podcasts, talks, articles, Substacks. Operators are being contacted directly. If you're one of the four featured operators and want your profile updated, taken down, or removed entirely, open an issue or email [paul@thebattlecard.com](mailto:paul@thebattlecard.com) and it will happen the same day.

## License

MIT — See LICENSE file.
