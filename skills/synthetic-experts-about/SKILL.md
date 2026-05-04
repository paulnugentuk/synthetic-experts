---
name: synthetic-experts-about
description: "Show the user what's in the Synthetic Experts skill pack — who the four experts are, where their published work lives, how the profiles are sourced, and how to get help. Use when someone invokes /synthetic-experts-about, asks 'what is this pack', 'who are these experts', or 'how does this work'."
---

# About Synthetic Experts

This pack contains four AI thought partners distilled from real operators' published work. Each one is installed as a slash command in Claude. Use them like you'd use a smart consultant — give context, ask the question, expect opinions back.

## The four experts

**April Dunford** — Positioning and differentiation. Author of *Obviously Awesome* and *Sales Pitch*. Reach for `/dunford` when a product is losing deals it should be winning, when "AI for X" doesn't feel like a real category, or when your "unique attributes" sound suspiciously like everyone else's.
→ [Obviously Awesome](https://www.obviouslyawesome.com/) · [Sales Pitch](https://www.salespitech.com/) · [Substack](https://april-dunford.substack.com/)

**Andy Raskin** — Strategic narrative and buyer psychology. Has shaped the narrative arc for 100+ companies. Use `/raskin` when the deck doesn't move buyers and nobody on the team can articulate the shift in the world that makes the product matter.
→ [Medium Essays](https://raskin.medium.com/)

**Elena Verna** — Product-led growth and AI-era acquisition. Currently Head of Growth at Lovable. `/verna` is the one to call when the old growth playbook is obviously dying and nobody has a strong view of what replaces it.
→ [Growth Scoop Substack](https://www.growthscoop.com/) · [LinkedIn](https://www.linkedin.com/in/elenaverna/)

**Kyle Poyar** — GTM strategy and pricing. Writes Growth Unhinged (78,000+ subscribers). `/poyar` for when pricing tiers don't capture value, when the GTM motion is muddled, or when someone on the team is still confusing "more traffic" with "more pipeline."
→ [Growth Unhinged Newsletter](https://www.growthunhinged.com/) · [LinkedIn](https://www.linkedin.com/in/kylepoyar/)

## The roundtable

`/roundtable` runs the same brief through all four experts and surfaces where they'd disagree. Useful when a problem cuts across positioning, narrative, growth, and pricing — and you want to see the trade-off rather than land on a single answer.

## How profiles are built

Each expert profile is distilled from their published work — books, podcasts, talks, articles, Substacks. We extract:

- Core principles (what they actually believe)
- Decision frameworks (the moves they teach)
- Default reframes (what they push back on)
- Contrarian views (where they diverge from mainstream)
- Voice samples (verbatim phrases from their published work)
- Domains (what they cover and what they decline)

Everything in these profiles is sourced. Where a stance is logically extended rather than directly published (e.g. an AI stance for an operator who hasn't yet published one), it's labelled "inferred."

**Sources per expert:**

- **Dunford:** *Obviously Awesome*, *Sales Pitch*, Lenny's Podcast appearances, her active Substack (through April 2026)
- **Raskin:** Medium essays, YouTube talks, SaaStr and similar conference keynotes
- **Verna:** Growth Scoop Substack (October 2025–April 2026), case studies, speaking appearances
- **Poyar:** Growth Unhinged newsletter, original research across 800+ companies, speaking and advisory work

## Voice integrity

Each expert response should contain at least one recognisable phrase or pattern from their actual work. If a response reads like generic advice with their name on top, the profile isn't doing its job — open an issue on the repo and we'll sharpen it.

## Updates

Profiles are maintained in the public repo. To pull in updates, `git pull origin main` in your cloned repo, then re-copy the skill folders to your `.claude/skills/` directory. Your old skills will be overwritten with the new training data.

## Operator notice

These profiles are distilled from publicly available work. Each of the four operators has been notified directly. If you're one of the operators and want your profile updated, taken down, or have feedback, open an issue at [github.com/paulnugentuk/synthetic-experts](https://github.com/paulnugentuk/synthetic-experts) or email paul@thebattlecard.com — change happens the same day.

## About The Battlecard

Synthetic Experts is part of [The Battlecard](https://thebattlecard.com/) — a weekly newsletter and skill pack for product marketers building with AI. Built by [Paul Nugent](https://www.linkedin.com/in/pauldnugent/).
