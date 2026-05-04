# Distribution and Installation

## Who This Is For

Founders and CMOs at Series B scale-ups who want strategic thought partnership on positioning, narrative, growth, and pricing from world-class operators. No credentials required — if you can run Claude Code or Cowork, you can install and use these experts.

## Requirements

- Claude Pro, Team, or Enterprise account
- Claude Code (desktop) or Cowork session (local)
- Git (to clone this repo)

## Installation

### Claude Code

1. Clone this repository:
```bash
git clone https://github.com/paulnugentuk/synthetic-experts.git
cd synthetic-experts
```

2. Copy the skills to your Claude Code skills directory:
```bash
cp -r skills/dunford/ ~/.claude/skills/dunford/
cp -r skills/raskin/ ~/.claude/skills/raskin/
cp -r skills/verna/ ~/.claude/skills/verna/
cp -r skills/poyar/ ~/.claude/skills/poyar/
cp -r skills/roundtable/ ~/.claude/skills/roundtable/
cp -r skills/synthetic-experts-about/ ~/.claude/skills/synthetic-experts-about/
```

3. Restart Claude Code. The skills appear in your command palette.

### Cowork

1. In your Cowork session folder, create `.claude/skills/` if it doesn't exist.

2. Copy the skill folders into `.claude/skills/`:
```bash
cp -r skills/dunford/ .claude/skills/dunford/
cp -r skills/raskin/ .claude/skills/raskin/
cp -r skills/verna/ .claude/skills/verna/
cp -r skills/poyar/ .claude/skills/poyar/
cp -r skills/roundtable/ .claude/skills/roundtable/
cp -r skills/synthetic-experts-about/ .claude/skills/synthetic-experts-about/
```

3. Skills load automatically in your next session.

## Using the Skills

Once installed, trigger each expert by their slash command in any Claude chat:

- `/dunford` — positioning and differentiation
- `/raskin` — strategic narrative and buyer psychology
- `/verna` — product-led growth and AI-era acquisition
- `/poyar` — GTM strategy and pricing
- `/roundtable` — ask all four at once and see where they disagree
- `/synthetic-experts-about` — links to their published work and corpus sourcing

## Updates

When we publish updates to expert profiles or prompts, pull the latest version of this repo and re-copy the skill folders. Your old skills will be overwritten with the new training data.

```bash
git pull origin main
cp -r skills/*/ ~/.claude/skills/  # or .claude/skills/ for Cowork
```

## Operator Note

These profiles are distilled from publicly available work. Each operator has been notified of this project and the distribution model. If you have feedback, corrections, or want your profile updated, open an issue on this repo or email paul@thebattlecard.com.
