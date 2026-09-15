#!/usr/bin/env python3
"""
smoke_test.py — distinctiveness harness for synthetic experts.

Runs a shared question bank through every expert profile side by side.
Output: a markdown table for human review + a pairwise similarity score
that flags any two expert responses that read too alike.

Usage:
    python3 synthetic-experts/tools/smoke_test.py                          # default bank, all experts
    python3 synthetic-experts/tools/smoke_test.py --experts april-dunford,chris-orlob
    python3 synthetic-experts/tools/smoke_test.py --questions-file custom.md
    python3 synthetic-experts/tools/smoke_test.py --model claude-haiku-4-5-20251001  # cheaper run

Requires: ANTHROPIC_API_KEY env var.
Default model: claude-sonnet-4-6 (best voice fidelity).

Output: synthetic-experts/smoke-tests/YYYY-MM-DD-HHMMSS.md
Cost target: under £0.75 per full run (5 experts × 5 questions × ~1500 output tokens).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: PyYAML. Run: pip3 install PyYAML --break-system-packages")

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("Missing dependency: anthropic. Run: pip3 install anthropic --break-system-packages")


# --- Paths -------------------------------------------------------------------

SCRIPT_DIR = Path(os.path.abspath(__file__)).parent   # abspath keeps the AI-Lab symlink side
EXPERTS_DIR = SCRIPT_DIR.parent                # synthetic-experts/
PROJECT_ROOT = EXPERTS_DIR.parent              # <...>/battlecard/
PROFILES_DIR = EXPERTS_DIR / "profiles"
PROMPTS_DIR = EXPERTS_DIR / "prompts"
OUTPUT_DIR = EXPERTS_DIR / "smoke-tests"

# .env lives in the newsletter project — API keys are shared across battlecard
# sub-projects. Look there first; fall back to a local .env in synthetic-experts/.
ENV_PATHS = [
    PROJECT_ROOT / "newsletter" / ".env",
    EXPERTS_DIR / ".env",
]


def _load_dotenv_if_present() -> None:
    """Read the first available .env and populate os.environ for any unset keys.
    Keeps this script usable without needing `source .env` before running.
    """
    env_path = next((p for p in ENV_PATHS if p.exists()), None)
    if env_path is None:
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            # Support both `KEY=value` and `export KEY=value`
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # .env parsing should never break the script — fall through to the
        # explicit ANTHROPIC_API_KEY check and let the user source it manually.
        pass


_load_dotenv_if_present()


# --- Default question bank ---------------------------------------------------
#
# Chosen to force each expert off their reflex and into their distinctive
# thinking. The right answer is visibly different per expert if the profiles
# are well-distilled — if two experts produce substantively the same answer to
# the same question, one of them is under-distilled.

DEFAULT_QUESTIONS = [
    "A mid-stage B2B SaaS is stuck at $10M ARR. Deals are closing but at a slower pace and lower ACV than a year ago. Churn is creeping up. Where would you look first, and why?",
    "How is AI changing the way products are marketed, positioned, sold, and won? What specifically, in your domain, is different now versus two years ago?",
    "We have 50 paying customers. We're debating whether to focus on getting 500 more or making these 50 love us more. Which do you pick, and what's the first thing you'd do on Monday?",
    "We're losing late-stage deals to a competitor we genuinely can't differentiate against on features. The sales team says we need better feature parity. What do you tell them?",
    "What's the single most common mistake you see teams make in their first year of scaling, and what does the fix actually look like?",
]


# --- Profile parsing ---------------------------------------------------------

# Matchers map placeholder names → list of substrings that must all appear in
# the (normalised) heading text. Normalised = lowercase, expert name stripped,
# trailing "(N)" counts stripped. First matching heading wins for each slot.
SECTION_MATCHERS = {
    "WHY_THEY_MATTER":      [["why", "matter"]],
    "CORE_PRINCIPLES":      [["core", "principle"]],
    "DECISION_FRAMEWORKS":  [["decision", "framework"], ["framework"]],
    "COMMON_PATTERNS":      [["default", "move"], ["common", "pattern"]],
    "CONTRARIAN_VIEWS":     [["contrarian"]],
    "VOICE_SAMPLES":        [["voice", "sample"]],
    "OUT_OF_DOMAIN":        [["out", "domain"], ["limit"]],
}


def _normalise_heading(h: str, expert_name: str = "") -> str:
    """Lowercase, strip expert name occurrences, strip '(N)' counts."""
    out = h.lower()
    if expert_name:
        out = out.replace(expert_name.lower(), "")
    out = re.sub(r"\s*\(\d+\)\s*", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _classify_heading(heading_norm: str) -> str | None:
    """Return placeholder slot name if the heading matches any matcher, else None."""
    for slot, matcher_options in SECTION_MATCHERS.items():
        for required_substrings in matcher_options:
            if all(s in heading_norm for s in required_substrings):
                return slot
    return None


def parse_profile(path: Path) -> tuple[dict, dict[str, str]]:
    """Return (frontmatter, sections-keyed-by-slot-name) from a profile markdown file.

    Sections dict keys are placeholder slot names (WHY_THEY_MATTER, CORE_PRINCIPLES, etc.)
    not raw heading text. This makes template filling straightforward and robust to
    heading-text variations across profiles.
    """
    text = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.S)
    if not fm_match:
        raise ValueError(f"no YAML frontmatter in {path}")
    fm = yaml.safe_load(fm_match.group(1)) or {}
    body = fm_match.group(2)

    expert_name = str(fm.get("name", ""))
    sections: dict[str, str] = {}

    for m in re.finditer(r"^##\s+([^\n]+)\n(.*?)(?=\n##\s|\Z)", body, re.M | re.S):
        heading_raw = m.group(1).strip()
        heading_norm = _normalise_heading(heading_raw, expert_name)
        content = m.group(2).strip()

        slot = _classify_heading(heading_norm)
        if slot and slot not in sections:
            # First match wins per slot (keeps "Decision frameworks" before
            # a later heading containing "framework")
            sections[slot] = content

    return fm, sections


def load_base_system_prompt() -> str:
    """Extract the template from base-system-prompt.md (first triple-backtick block)."""
    path = PROMPTS_DIR / "base-system-prompt.md"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"```\n(.*?)\n```", text, re.S)
    if not m:
        raise ValueError("base-system-prompt.md has no code-fence template block")
    return m.group(1)


def fill_template(template: str, fm: dict, sections: dict[str, str], user_input: str) -> str:
    """Fill the base-system-prompt template placeholders from parsed profile sections."""
    result = template.replace("{{NAME}}", str(fm.get("name", "Unknown")))
    result = result.replace("{{USER_INPUT}}", user_input)
    for slot in SECTION_MATCHERS:
        content = sections.get(slot, f"[missing section: {slot}]")
        result = result.replace("{{" + slot + "}}", content)
    return result


# --- Claude call -------------------------------------------------------------

def call_claude(system: str, user_input: str, model: str, max_tokens: int = 1500) -> str:
    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_input}],
    )
    parts = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts).strip()


# --- Similarity check --------------------------------------------------------

def _bigrams(text: str) -> set[tuple[str, str]]:
    words = re.findall(r"\w+", text.lower())
    return set(zip(words, words[1:]))


def bigram_overlap(a: str, b: str) -> float:
    """Jaccard-like overlap: |A∩B| / min(|A|,|B|). 0.0–1.0.
    Using min() rather than union so short-but-similar strings aren't penalised.
    """
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / min(len(ba), len(bb))


# --- Output ------------------------------------------------------------------

def write_report(
    output_path: Path,
    *,
    experts: list[str],
    questions: list[str],
    responses: dict[tuple[str, int], str],
    similarity_flags: list[tuple[int, str, str, float]],
    model: str,
) -> None:
    lines: list[str] = []
    lines.append(f"# Distinctiveness smoke test — {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(f"- Model: `{model}`")
    lines.append(f"- Experts: {', '.join(experts)}")
    lines.append(f"- Questions: {len(questions)}")
    lines.append(f"- Responses captured: {len(responses)}")
    lines.append("")

    # Summary of flags
    lines.append("## Similarity flags")
    lines.append("")
    if similarity_flags:
        lines.append("Pairs with >60% bigram overlap. Investigate whether one expert is under-distilled.")
        lines.append("")
        lines.append("| Question # | Expert A | Expert B | Overlap |")
        lines.append("|---|---|---|---|")
        for qi, ea, eb, score in similarity_flags:
            lines.append(f"| Q{qi+1} | {ea} | {eb} | {score:.0%} |")
    else:
        lines.append("✓ No expert-pair responses exceeded the 60% overlap threshold.")
    lines.append("")

    # Per-question details
    for qi, question in enumerate(questions):
        lines.append(f"## Q{qi+1}: {question}")
        lines.append("")
        for expert in experts:
            resp = responses.get((expert, qi), "[no response]")
            lines.append(f"### {expert}")
            lines.append("")
            lines.append(resp)
            lines.append("")
        lines.append("---")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# --- Orchestration -----------------------------------------------------------

def run(
    expert_slugs: list[str] | None,
    questions: list[str],
    model: str,
    dry_run: bool,
) -> int:
    template = load_base_system_prompt()

    profiles: dict[str, tuple[dict, dict[str, str]]] = {}
    if expert_slugs is None:
        expert_slugs = sorted(p.stem for p in PROFILES_DIR.glob("*.md"))

    for slug in expert_slugs:
        p = PROFILES_DIR / f"{slug}.md"
        if not p.exists():
            print(f"[skip] {slug}: no profile at {p}", file=sys.stderr)
            continue
        profiles[slug] = parse_profile(p)

    if not profiles:
        print("No profiles loaded. Aborting.", file=sys.stderr)
        return 1

    experts = list(profiles.keys())
    total_calls = len(experts) * len(questions)

    print(f"Smoke-test plan:")
    print(f"  Experts: {', '.join(experts)}")
    print(f"  Questions: {len(questions)}")
    print(f"  Total API calls: {total_calls}")
    print(f"  Model: {model}")
    if dry_run:
        print(f"  (dry run — no API calls will be made)")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set in environment.", file=sys.stderr)
        return 1

    responses: dict[tuple[str, int], str] = {}

    for qi, question in enumerate(questions):
        print(f"\nQ{qi+1}: {question[:80]}...")
        for slug in experts:
            fm, sections = profiles[slug]
            system = fill_template(template, fm, sections, question)
            try:
                text = call_claude(system, question, model=model)
            except Exception as e:
                print(f"  [{slug}] ERROR: {e}")
                text = f"[error: {e}]"
            responses[(slug, qi)] = text
            word_count = len(text.split())
            print(f"  [{slug}] {word_count} words")

    # Pairwise similarity per question
    flags: list[tuple[int, str, str, float]] = []
    for qi in range(len(questions)):
        for i, ea in enumerate(experts):
            for eb in experts[i+1:]:
                score = bigram_overlap(responses[(ea, qi)], responses[(eb, qi)])
                if score > 0.60:
                    flags.append((qi, ea, eb, score))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    output_path = OUTPUT_DIR / f"{stamp}.md"

    write_report(
        output_path,
        experts=experts,
        questions=questions,
        responses=responses,
        similarity_flags=flags,
        model=model,
    )

    print(f"\nReport written: {output_path}")
    if flags:
        print(f"⚠  {len(flags)} pair(s) exceeded 60% overlap — review flagged questions.")
    else:
        print("✓ All expert pairs below the 60% overlap threshold.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Distinctiveness smoke test for synthetic experts.")
    parser.add_argument("--experts", help="Comma-separated expert slugs (default: all)")
    parser.add_argument("--questions-file", help="Path to markdown file with one question per paragraph")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Claude model (default: claude-sonnet-4-6)")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no API calls")
    args = parser.parse_args()

    slugs = args.experts.split(",") if args.experts else None

    questions = DEFAULT_QUESTIONS
    if args.questions_file:
        text = Path(args.questions_file).read_text(encoding="utf-8")
        questions = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    return run(expert_slugs=slugs, questions=questions, model=args.model, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
