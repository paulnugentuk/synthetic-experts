# Distillation Prompt — Synthetic Expert Profiles

Run this prompt against an assembled source corpus to produce a draft expert profile. The output is a first draft — the profile requires hand-editing before it goes live (especially sharpening contrarian views and pulling verbatim voice quotes).

This prompt produces output that maps directly into `experts/template.md`.

---

## When to use

Use this when building a new expert profile from scratch. Don't use it when strong distilled reference material already exists (e.g. Dunford's `positioning-workshop/references/` files) — in that case, restructure the existing distillation directly.

## Input preparation

Before running: assemble a corpus of 10–20 pieces of the expert's real published work in a single directory or pasted context. Prioritise:
- Books and book excerpts
- Long-form essays and substack posts
- Conference talk transcripts
- Podcast transcripts (especially 30+ min interviews)
- Long-form LinkedIn posts

De-prioritise:
- Tweets (too short to reveal reasoning)
- News interviews (too reactive)
- Promotional material

## The prompt

```
You are distilling the work of {{EXPERT_NAME}} into a reusable expert profile that will be used to power a synthetic version of them for product marketers.

You have been given their source corpus — books, essays, talks, and podcast transcripts. Your job is to extract the underlying pattern of their thinking, not to summarise their output.

## What I need from you

Produce a structured profile with these sections. Be specific. If a section would apply equally to any competent practitioner in their field, you have failed — keep sharpening until it is unmistakably THIS person.

### 1. Why they matter (2-3 sentences)

What are they known for? What would a PMM hire them to solve? Why should someone trust their view over the hundreds of other voices in the space?

### 2. Core principles (5-10)

The beliefs this person operates from. Each principle should be:
- A concrete claim they repeatedly make or reason from
- Attributable to them (not generic)
- Surprising or non-obvious to someone who hasn't read them

Format each as:
**[Principle headline]** — [1-2 sentences. Why they hold it. What it leads them to do.]

### 3. Decision frameworks (3-5)

The repeatable thinking structures they use. Name them if named, construct names if not.

For each framework:
- **Name:** [name]
- **When to use:** [class of problem this applies to]
- **Structure:** [the 3-5 step structure, in their own terms where possible]
- **What it prevents:** [the common failure mode this framework catches]

### 4. Default moves (3-5)

"When X is happening, they will almost always do Y." The things they reach for first.

Format: When faced with [situation], they [move], because [reasoning].

### 5. Contrarian views (2-3) — CRITICAL SECTION

Where do they disagree with the mainstream of their field? This is where their voice lives. If you cannot find genuine disagreement in the corpus, you have not read it closely enough — every serious practitioner has disagreements with their field.

Format:
- **Mainstream view:** [what most people in the field believe]
- **Their view:** [their specific counter-position]
- **Their reasoning:** [the evidence or logic they use to back it]

### 6. Voice samples (5-8)

Verbatim direct quotes from the corpus. Keep punctuation, phrasing, and capitalisation exact. Prioritise quotes that:
- Show their distinctive phrasing
- Capture a contrarian or sharp position
- Use their characteristic metaphors or examples

Each quote should include source and context (e.g. "Lenny's Podcast, 2023, on positioning statements").

### 7. AI × their domain — their stance

This is a newsletter about how AI is changing how products are marketed, positioned, sold, and won. How does AI affect {{EXPERT_NAME}}'s domain specifically?

If they have published views on AI's impact, summarise them with quotes and sources.

If they have not, construct the 2-3 sentence stance you believe they would take, grounded in their principles. Label this as INFERRED and flag for human review.

### 8. Out-of-domain topics

Where would this expert plausibly decline to answer? What sits clearly outside their zone of strong opinion? List 3-5 topics.

### 9. Example applications (3 scenarios)

Write 3 short worked examples (~100-150 words each) showing how this expert would approach a concrete problem. Each should:
- Start with a realistic PMM scenario
- Show their diagnosis using their principles
- Apply one of their frameworks
- End with a specific recommendation and flagged trade-off

### 10. Smoke-test prompts (3)

Three questions whose answers should sound unmistakably like this expert when the profile is loaded. These are used to verify the profile works before it goes live, and to detect drift towards generic output when run alongside other expert profiles.

## Rules of distillation

1. **Be specific.** Generic principles are failure. "Focus on the customer" is not a principle — every marketer would claim it. "Ask your BEST-FIT customers, not all customers, because surveying the whole base gives you noise" is a principle.

2. **Preserve their language.** If they use a specific term or metaphor repeatedly, use it. Don't translate their voice into generic MBA-speak.

3. **Flag gaps.** If the corpus doesn't cover something you'd need for a particular section, say so. A profile with acknowledged gaps is better than a profile with confabulated content.

4. **Find the friction.** The contrarian views section is where the expert earns their distinctiveness. If your draft has generic views there, the profile will produce generic output.

5. **No cheerleading.** This is a profile for professional use. Skip the "acclaimed author" language; show the reader what makes this person worth listening to.

## Output format

Produce the output as markdown conforming to the structure in `experts/template.md`. Include YAML frontmatter at the top matching the template.

---

Now distil the corpus below.

{{SOURCE_CORPUS}}
```

## Post-distillation hand-edit checklist

Before marking a profile published, confirm:

- [ ] Every core principle passes the "unmistakably them" test
- [ ] At least 2 contrarian views with real disagreement (not "nuance")
- [ ] Voice samples are verbatim with sources
- [ ] AI stance is either sourced or labelled INFERRED
- [ ] Smoke-test prompts would plausibly produce distinctive answers
- [ ] Out-of-domain list covers obvious misuse scenarios
- [ ] Profile passes side-by-side smoke-test against at least one other launch expert without producing similar answers
