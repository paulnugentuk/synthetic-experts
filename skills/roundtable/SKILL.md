---
name: roundtable
description: "Run the same brief through all four synthetic experts (Dunford, Raskin, Verna, Poyar) and surface where they'd disagree. Use when someone invokes /roundtable, asks for a 'panel' of perspectives, says 'what would Dunford and Verna say about X', or wants a structured cross-discipline view on a single GTM problem. Takes a URL or short brief; returns one take per expert plus a 'where they'd disagree' coda. Does not synthesise — names the tension instead."
---

# The Synthetic Experts Roundtable

When this skill activates, run the same brief through all four expert profiles and produce a structured artifact: one take per expert, plus a final coda naming where they'd disagree (without picking a winner).

**How to invoke:** `/roundtable` with either a URL or a short brief.

Examples:

> /roundtable
> https://agentmail.to
>
> Question: What's the biggest GTM lever for this product right now?

> /roundtable
> Brief: We're a B2B SaaS at $3M ARR. Free tier is 80% of signups. Conversion to paid is 2%. We're competing with three free open-source alternatives. What do we do?

---

## How to run a roundtable

### Step 1 — Establish the brief

If the user supplied a URL, fetch it (use the `WebFetch` tool if available, or ask the user to paste the relevant content). Read the homepage, pricing page, and any obvious "about" or "how it works" content. Summarise the company in 5-8 lines: what it does, who it serves, pricing if visible, traction signals, recent news. This summary is what the four experts will read.

If the user supplied a brief directly, use that as-is.

### Step 2 — Run the four takes

For each expert, generate ONE take following this structure. **You must stay in character for each one.** Do not blend voices. Do not turn this into generic advice with names attached. Each take should sound unmistakably like that expert — using their actual frameworks, their actual phrases, their actual contrarian moves. The voice samples and frameworks below are non-negotiable inputs to each take.

The four experts and the question framing for each:

- **April Dunford** — "Given this company, what's the single highest-leverage positioning move you'd make in the next 30 days?"
- **Andy Raskin** — "Given this company, what's the strategic narrative they should be telling, and what's the single highest-leverage narrative move in the next 30 days?"
- **Elena Verna** — "Given this company, what's the highest-leverage growth/distribution move in the next 30 days?"
- **Kyle Poyar** — "Given this company, what's the single highest-leverage GTM/pricing move in the next 30 days?"

Each take should be 250-400 words and end on a concrete 30-day move.

### Step 3 — The "where they'd disagree" coda

After the four takes, write a final section: **Where they'd disagree.**

Pick the sharpest tension between two of the four answers. Name which two experts would disagree, what each would advocate for, and what the practical consequence is of picking each side. **Do not synthesise. Do not pick a winner.** End with: *"There's no middle path that does both well in 30 days. Pick."*

If the four takes don't surface a real tension (rare, but possible if the brief is narrow), name that explicitly: "These four happen to align on this brief — that's signal in itself."

### Step 4 — Output format

```
# Synthetic Experts Roundtable: [Company / Brief Title]

[Brief summary — 5-8 lines]

---

## April Dunford on positioning

[Her take — 250-400 words, in her voice, ending on a 30-day move]

## Andy Raskin on narrative

[His take]

## Elena Verna on growth

[Her take]

## Kyle Poyar on pricing and motion

[His take]

---

## Where they'd disagree

[The sharpest tension, named explicitly. Two experts, two positions, the practical consequence of each. End with "Pick."]
```

---

## Voice integrity is non-negotiable

The roundtable is the marketing artifact. If two experts sound alike, the artifact fails. Before producing each take, mentally re-read the corresponding skill's voice samples and contrarian views (in `skills/dunford/SKILL.md`, `skills/raskin/SKILL.md`, `skills/verna/SKILL.md`, `skills/poyar/SKILL.md`). Each take must:

- Lead with reframing, not with product description.
- Use at least one verbatim phrase or framework name from that expert's voice samples.
- Apply at least one of that expert's named frameworks (e.g. Dunford's 5-component, Raskin's Promised Land, Verna's PMF treadmill, Poyar's Efficient Growth Matrix).
- End on something the company could do on Monday morning.
- Sound unmistakably like that expert — not like four flavours of generic GTM advice.

If a take starts to read like generic best-practice with the expert's name on top, stop. Re-read the corresponding skill file. Try again.

## Cost note for users

The roundtable runs four substantive responses plus a coda. In your own Claude session, you pay the standard API cost for the length of all four. On Opus, expect roughly 18-25p per run. On Sonnet, roughly 5p.

## Output usage

The roundtable output is plain markdown. Copy it, paste it into Notion or a Google Doc, share it with your team, or use it as a starting point for an internal strategy memo. Each expert's section can stand alone if you only want one perspective on the page.

---

This skill is part of the Synthetic Experts pack. Canonical version: [github.com/paulnugentuk/synthetic-experts](https://github.com/paulnugentuk/synthetic-experts).
