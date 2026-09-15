#!/usr/bin/env python3
"""
roundtable.py — roundtable orchestrator for synthetic experts.

Takes a URL or brief and runs it through all four launch experts (April Dunford,
Andy Raskin, Elena Verna, Kyle Poyar). Produces a structured markdown artifact
with one section per expert, plus a "where they'd disagree" coda.

Usage:
    python3 roundtable.py --url <url>                      # fetch page as brief
    python3 roundtable.py --brief <text>                   # use text directly
    python3 roundtable.py --brief-file <path>              # read brief from file
    python3 roundtable.py --url <url> --experts april-dunford,andy-raskin
    python3 roundtable.py --url <url> --model claude-opus-4-1  # override model

Requires: ANTHROPIC_API_KEY env var.
Default model: claude-sonnet-4-6 (per locked decision: Sonnet for iteration/build,
              Opus for published hero version).

Output: synthetic-experts/roundtables/YYYY-MM-DD-HHMMSS-<slug>.md
Cost estimate: 4 × Sonnet @ ~£0.05/call ≈ £0.20–0.30 per run
              4 × Opus @ ~£0.12/call ≈ £0.50 per run
"""

from __future__ import annotations

import argparse
import datetime as dt
import html.parser
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: PyYAML. Run: pip3 install PyYAML --break-system-packages")

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("Missing dependency: anthropic. Run: pip3 install anthropic --break-system-packages")


# --- Paths -------------------------------------------------------------------

# Relative to where the script was invoked (abspath keeps the AI-Lab symlink
# side), so AI-Lab runs use AI-Lab's profiles and a clone uses this repo's.
SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
EXPERTS_DIR = SCRIPT_DIR.parent                                 # synthetic-experts/
NEWSLETTER_ENV = EXPERTS_DIR.parent / "newsletter" / ".env"     # shared battlecard keys (AI-Lab only)
EXPERTS_ENV = EXPERTS_DIR / ".env"
PROFILES_DIR = EXPERTS_DIR / "profiles"
ROUNDTABLES_DIR = EXPERTS_DIR / "roundtables"
BASE_SYSTEM_PROMPT_PATH = EXPERTS_DIR / "prompts" / "base-system-prompt.md"

EXPERT_SLUGS = ["april-dunford", "andy-raskin", "elena-verna", "kyle-poyar"]

SECTION_MATCHERS = {
    "WHY_THEY_MATTER": re.compile(r"^##\s+Who you are and why it matters", re.IGNORECASE),
    "CORE_PRINCIPLES": re.compile(r"^##\s+Your worldview", re.IGNORECASE),
    "DECISION_FRAMEWORKS": re.compile(r"^##\s+Your decision frameworks", re.IGNORECASE),
    "COMMON_PATTERNS": re.compile(r"^##\s+Your default moves", re.IGNORECASE),
    "CONTRARIAN_VIEWS": re.compile(r"^##\s+Where you diverge", re.IGNORECASE),
    "VOICE_SAMPLES": re.compile(r"^##\s+How you sound", re.IGNORECASE),
    "OUT_OF_DOMAIN": re.compile(r"^##\s+Out of domain", re.IGNORECASE),
}


# --- HTML Text Extraction ---------------------------------------------------

class _TextExtractor(html.parser.HTMLParser):
    """Extract visible text from HTML, respecting script/style blocks."""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip = False
        self.title = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = False
        elif tag == "p":
            self.text_parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            text = data.strip()
            if text:
                self.text_parts.append(text + " ")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.text_parts.append("\n")


def fetch_url_as_brief(url: str, timeout_sec: int = 5) -> tuple[str, str]:
    """
    Fetch URL and extract title + visible text as brief.
    Returns (title, text) tuple, caps text at 8000 chars.
    Raises URLError if fetch fails.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            html_content = response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as e:
        raise urllib.error.URLError(
            f"Failed to fetch {url}: {e}. Try using gstack /browse or --brief-file instead."
        ) from e

    parser = _TextExtractor()
    parser.feed(html_content)

    # Extract title from <title> tag
    title_match = re.search(r"<title>([^<]+)</title>", html_content, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else "Untitled"

    # Join text and cap at 8000 chars
    text = " ".join(parser.text_parts).strip()
    text = re.sub(r"\s+", " ", text)  # collapse multiple spaces
    text = text[:8000]

    return title, text


# --- Profile Parsing (from smoke_test.py) -----------------------------------

def parse_profile(path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter + markdown sections from profile file."""
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Extract YAML frontmatter
    if not lines[0].startswith("---"):
        raise ValueError(f"Profile {path.name} missing YAML frontmatter delimiter")

    fm_end = None
    for i in range(1, len(lines)):
        if lines[i].startswith("---"):
            fm_end = i
            break

    if fm_end is None:
        raise ValueError(f"Profile {path.name} unclosed YAML frontmatter")

    fm_text = "\n".join(lines[1:fm_end])
    md_text = "\n".join(lines[fm_end + 1 :])

    fm = yaml.safe_load(fm_text) or {}

    # Classify markdown sections
    sections = {}
    current_section = None
    current_content = []

    for line in md_text.split("\n"):
        matched = False
        for slot_name, pattern in SECTION_MATCHERS.items():
            if pattern.match(line):
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = slot_name
                current_content = []
                matched = True
                break

        if not matched and current_section:
            current_content.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_content).strip()

    return {"frontmatter": fm, "sections": sections}


def load_base_system_prompt() -> str:
    """Load base system prompt template from file."""
    if not BASE_SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(f"Base system prompt not found: {BASE_SYSTEM_PROMPT_PATH}")

    content = BASE_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    # Extract first code-fence block
    match = re.search(r"```\n(.*?)\n```", content, re.DOTALL)
    if not match:
        raise ValueError("No code-fence template found in base-system-prompt.md")

    return match.group(1)


def fill_template(template: str, fm: dict, sections: dict, user_input: str) -> str:
    """Replace {{PLACEHOLDER}} tokens in template."""
    result = template

    # Frontmatter placeholders
    for key, value in fm.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))

    # Section placeholders
    for slot_name, content in sections.items():
        result = result.replace(f"{{{{{slot_name}}}}}", content)

    # User input
    result = result.replace("{{USER_INPUT}}", user_input)

    return result


# --- Claude API Calls -------------------------------------------------------

def _load_dotenv_if_present():
    """Load .env if present (newsletter or experts)."""
    env_path = NEWSLETTER_ENV if NEWSLETTER_ENV.exists() else EXPERTS_ENV
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()


def call_claude(
    system: str, user_input: str, model: str = "claude-sonnet-4-6", max_tokens: int = 1000
) -> tuple[str, dict[str, int]]:
    """
    Call Claude API and return (response_text, token_usage_dict).
    """
    _load_dotenv_if_present()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in environment or .env")

    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_input}],
    )

    text = response.content[0].text
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    return text, usage


# --- Cost Estimation --------------------------------------------------------

def estimate_cost(model: str, num_expert_calls: int = 4) -> tuple[float, bool]:
    """
    Estimate GBP cost for roundtable run.
    Returns (cost, should_warn) where should_warn is True if cost > £1.

    Pricing (per 1k tokens):
    - Sonnet 4.6: input £0.003, output £0.015
    - Opus 4.1: input £0.015, output £0.045

    Rough estimates per call (assuming ~1500 input + 500 output tokens):
    - Sonnet: ~£0.015 per call × 4 ≈ £0.06
    - Opus: ~£0.045 per call × 4 ≈ £0.18
    """
    if "opus" in model.lower():
        cost_per_call = 0.045  # £0.045 per call
    else:
        cost_per_call = 0.015  # £0.015 per call (Sonnet)

    # Add coda synthesis call
    total_calls = num_expert_calls + 1
    total_cost = cost_per_call * total_calls

    should_warn = total_cost > 1.0

    return total_cost, should_warn


# --- Roundtable Output -------------------------------------------------------

def write_roundtable_markdown(
    output_path: Path,
    brief: str,
    url: str | None,
    experts: dict[str, tuple[str, dict]],
    responses: dict[str, str],
    coda: str,
    model: str,
    total_tokens: int,
):
    """Write structured markdown artifact."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Roundtable: Synthetic Experts",
        "",
        "## Brief",
        "",
        brief,
        "",
    ]

    if url:
        lines.extend(["**Source:** " + url, ""])

    lines.extend(["## Expert Takes", ""])

    for slug in EXPERT_SLUGS:
        if slug not in experts:
            continue
        display_name, _ = experts[slug]
        response = responses.get(slug, "")
        lines.extend(
            [
                f"### {display_name}",
                "",
                response,
                "",
            ]
        )

    lines.extend(
        [
            "## Where They'd Disagree",
            "",
            coda,
            "",
            "---",
            "",
            f"**Model:** {model}  ",
            f"**Experts:** {', '.join(experts.keys())}  ",
            f"**Total tokens:** {total_tokens}  ",
            f"**Generated:** {dt.datetime.now().isoformat()}  ",
        ]
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")


# --- Orchestration -----------------------------------------------------------

def generate_slug(url: str | None, brief: str) -> str:
    """Generate slug from URL domain or brief."""
    if url:
        try:
            domain = urlparse(url).netloc.replace("www.", "").split(".")[0]
            return domain
        except Exception:
            pass

    # Slugify first 40 chars of brief
    slug = brief[:40].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:30]


def run(
    brief: str,
    url: str | None = None,
    experts: list[str] | None = None,
    model: str = "claude-sonnet-4-6",
    output_path: Path | None = None,
    dry_run: bool = False,
) -> Path:
    """
    Main orchestration logic.
    Returns path to generated roundtable markdown.
    """
    if experts is None:
        experts = EXPERT_SLUGS

    # Load profiles
    profile_data = {}
    for slug in experts:
        profile_path = PROFILES_DIR / f"{slug}.md"
        if not profile_path.exists():
            print(f"ERROR: Profile not found: {profile_path}", file=sys.stderr)
            sys.exit(1)
        profile_data[slug] = parse_profile(profile_path)

    # Load base system prompt
    base_template = load_base_system_prompt()

    # Estimate cost
    cost, should_warn = estimate_cost(model, len(experts))
    if should_warn and not dry_run:
        response = input(
            f"Estimated cost: £{cost:.2f}. Continue? (y/n) "
        )
        if response.lower() != "y":
            print("Cancelled.")
            sys.exit(0)

    # Per-expert question framing.
    # The shared "highest-leverage move in your domain" prompt drifted every
    # expert toward Dunford's positioning canvas in v1. Each expert now gets a
    # question framed in their own lane to anchor them to their actual framework.
    EXPERT_QUESTIONS = {
        "april-dunford": (
            "Apply your 5-component positioning framework to this company. "
            "Walk through: competitive alternatives (including 'do nothing' or 'just use ChatGPT'), "
            "unique attributes against those alternatives, value via the 'so what?' ladder, "
            "the desperate target customer (situational triggers, not demographics), and the market category choice. "
            "End with the single positioning move you'd make in the next 30 days."
        ),
        "andy-raskin": (
            "Build the strategic narrative for this company using your 5-Part Narrative arc. "
            "Walk through: the Shift in the world that creates urgency, the Stakes for buyers who don't act, "
            "the Promised Land (a world-centric vision, not feature list), the Obstacles between buyer and Promised Land, "
            "and the Evidence that this company can actually deliver them there. "
            "End with the single narrative move you'd make in the next 30 days. "
            "Do NOT default to positioning frameworks — that's downstream of narrative work."
        ),
        "elena-verna": (
            "Diagnose this company through your growth-loops + PMF-treadmill lens. "
            "Walk through: which growth loop they're running (or should be), where it's leaking, "
            "whether they're optimising for revenue or trust/lovability, "
            "whether agents are first-class users in the product, and whether their distribution channels are still alive. "
            "End with the single growth move you'd make in the next 30 days. "
            "Do NOT default to positioning frameworks — your lens is loops, retention, and distribution health."
        ),
        "kyle-poyar": (
            "Analyse this company through your pricing + GTM-motions framework. "
            "Walk through: what their pricing architecture signals about who their buyer is, "
            "which GTM motion (PLG, sales-led, account-based, hybrid) the pricing supports, "
            "what conversion-by-source data would expose, "
            "and where measurement is hiding the real story. "
            "End with the single pricing or motion move you'd make in the next 30 days. "
            "Ground every claim in benchmark data where possible (your published numbers preferred). "
            "Do NOT default to positioning frameworks — your lens is monetisation and motion mechanics."
        ),
    }

    # Run expert calls
    responses = {}
    total_tokens = 0

    for slug in experts:
        if dry_run:
            responses[slug] = f"[DRY RUN: skipped {slug}]"
            continue

        fm = profile_data[slug]["frontmatter"]
        sections = profile_data[slug]["sections"]
        # Fall back to the generic question if a custom expert is added later.
        question = EXPERT_QUESTIONS.get(
            slug,
            "Given this company/product/brief, what's the single highest-leverage move "
            "you'd make in your domain in the next 30 days? Be specific, name the frameworks "
            "you're using, and end on a concrete action — not a summary."
        )
        system = fill_template(base_template, fm, sections, question)

        try:
            # 2500 token cap (was 1000 in v1) — v1 truncated 3 of 4 responses
            # mid-sentence at the boundary. 2500 lets each take include both
            # the diagnosis and the recommendation comfortably.
            response_text, usage = call_claude(system, brief, model=model, max_tokens=2500)
            responses[slug] = response_text
            total_tokens += usage["input_tokens"] + usage["output_tokens"]
        except Exception as e:
            print(f"ERROR calling Claude for {slug}: {e}", file=sys.stderr)
            sys.exit(1)

    # Run coda synthesis (identify tensions, don't merge)
    if dry_run:
        coda = "[DRY RUN: skipped coda]"
    else:
        coda_system = (
            "You are facilitating a roundtable. Identify the 1–2 sharpest tensions across the expert takes below. "
            "Name each tension specifically: which expert holds which position, why, and what the practical "
            "consequence of each side is for the company being discussed. Use the experts' actual names "
            "(April Dunford, Andy Raskin, Elena Verna, Kyle Poyar). Do not synthesise, do not pick a winner, "
            "do not produce a 'where they agree' section. The coda should sharpen disagreement, not soften it. "
            "Cap at 250 words. Do not invent positions the experts did not take in the responses provided."
        )
        coda_user = "\n\n".join(
            [f"### {slug}\n{responses[slug]}" for slug in experts if slug in responses]
        )

        try:
            # Bumped from 300 to 500 tokens — v1 coda truncated mid-sentence.
            coda_text, usage = call_claude(coda_system, coda_user, model=model, max_tokens=500)
            coda = coda_text
            total_tokens += usage["input_tokens"] + usage["output_tokens"]
        except Exception as e:
            print(f"ERROR calling Claude for coda: {e}", file=sys.stderr)
            sys.exit(1)

    # Prepare output path
    if output_path is None:
        slug = generate_slug(url, brief)
        timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        output_path = ROUNDTABLES_DIR / f"{timestamp}-{slug}.md"

    # Build expert metadata dict
    expert_metadata = {}
    for slug in experts:
        if slug in profile_data:
            fm = profile_data[slug]["frontmatter"]
            display_name = fm.get("name", slug)
            expert_metadata[slug] = (display_name, fm)

    # Write output
    write_roundtable_markdown(
        output_path, brief, url, expert_metadata, responses, coda, model, total_tokens
    )

    print(f"Roundtable written to: {output_path}")
    return output_path


# --- CLI Handler -------------------------------------------------------------

def main():
    """Parse CLI arguments and run roundtable."""
    parser = argparse.ArgumentParser(
        description="Run a brief through synthetic expert roundtable.",
        epilog="Cost: ~£0.06 per run (Sonnet) or ~£0.18 per run (Opus).",
    )

    # Mutually exclusive input group
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="URL to fetch and use as brief")
    input_group.add_argument("--brief", help="Brief text (use quotes for multi-word)")
    input_group.add_argument("--brief-file", help="Path to file containing brief")

    parser.add_argument(
        "--experts",
        default=",".join(EXPERT_SLUGS),
        help=f"Comma-separated expert slugs (default: {','.join(EXPERT_SLUGS)})",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Claude model (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--output",
        help="Output path (default: synthetic-experts/roundtables/YYYY-MM-DD-HHMMSS-<slug>.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip API calls, show what would happen",
    )

    args = parser.parse_args()

    # Resolve brief
    if args.url:
        try:
            title, text = fetch_url_as_brief(args.url)
            brief = f"**{title}**\n\n{text}"
            url = args.url
        except urllib.error.URLError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.brief_file:
        brief_path = Path(args.brief_file)
        if not brief_path.exists():
            print(f"ERROR: Brief file not found: {brief_path}", file=sys.stderr)
            sys.exit(1)
        brief = brief_path.read_text(encoding="utf-8")
        url = None
    else:
        brief = args.brief
        url = None

    # Parse experts list
    experts = [s.strip() for s in args.experts.split(",")]

    # Parse output path
    output_path = Path(args.output) if args.output else None

    # Run
    try:
        run(
            brief=brief,
            url=url,
            experts=experts,
            model=args.model,
            output_path=output_path,
            dry_run=args.dry_run,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
