#!/usr/bin/env python3
"""
route_linkedin_posts.py — move LinkedIn posts from inbox to the right expert.

Reads:    <corpus>/_inbox/linkedin/*.md
Writes:   <corpus>/<slug>/fetched/linkedin/<same-filename>
          (leaves unroutable posts in inbox with routedTo: unroutable)

Matching logic (in priority order):
    1. authorUrl (normalised) matches an expert's linkedin_manual.url
    2. author (case-insensitive exact) matches an expert's profile name

Expert registry is built from synthetic-experts/profiles/<slug>.md YAML frontmatter
(name, slug) plus the linkedin_manual source in each expert's sources.yml.

Usage:
    python3 synthetic-experts/tools/route_linkedin_posts.py
    python3 synthetic-experts/tools/route_linkedin_posts.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: PyYAML. Run: pip install PyYAML --break-system-packages")

# --- Paths -------------------------------------------------------------------
# Same rule as refresh_corpus.py: $SYNTHETIC_EXPERTS_CORPUS, else corpus/ next
# to tools/, worked out with abspath() so the AI-Lab symlink keeps working.

SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
EXPERTS_DIR = SCRIPT_DIR.parent                    # synthetic-experts/
PROFILES_DIR = EXPERTS_DIR / "profiles"
_corpus_env = os.environ.get("SYNTHETIC_EXPERTS_CORPUS")
CORPUS_ROOT = Path(_corpus_env).expanduser().absolute() if _corpus_env else EXPERTS_DIR / "corpus"
INBOX = CORPUS_ROOT / "_inbox" / "linkedin"


# --- Utilities ---------------------------------------------------------------

def normalise_linkedin_url(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip().lower()
    # force https, strip www
    u = re.sub(r"^http://", "https://", u)
    u = re.sub(r"^https://www\.", "https://", u)
    # strip trailing slash and query string
    u = u.split("?")[0].rstrip("/")
    return u


def read_frontmatter_and_body(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, flags=re.S)
    if not m:
        return ({}, text)
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm, m.group(2))


def write_frontmatter_and_body(path: Path, fm: dict[str, Any], body: str) -> None:
    lines = ["---"]
    for k, v in fm.items():
        if v is None:
            lines.append(f"{k}: null")
            continue
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append("---\n")
    lines.append(body.lstrip())
    path.write_text("\n".join(lines), encoding="utf-8")


# --- Expert registry ---------------------------------------------------------

def build_expert_registry() -> list[dict[str, Any]]:
    """Return list of {slug, name, linkedinUrl, corpusDir} for every expert
    that has both a profile and a sources.yml."""
    experts: list[dict[str, Any]] = []
    if not PROFILES_DIR.exists():
        return experts

    for profile in sorted(PROFILES_DIR.glob("*.md")):
        fm, _ = read_frontmatter_and_body(profile)
        slug = fm.get("slug") or profile.stem  # published profiles carry no slug field
        name = fm.get("name")
        if not slug or not name:
            continue

        corpus_dir = CORPUS_ROOT / slug
        sources_path = corpus_dir / "sources.yml"
        linkedin_url = None
        if sources_path.exists():
            cfg = yaml.safe_load(sources_path.read_text()) or {}
            for src in cfg.get("sources") or []:
                if src.get("type") == "linkedin_manual" and src.get("url"):
                    linkedin_url = src["url"]
                    break

        experts.append({
            "slug": slug,
            "name": name,
            "name_lower": name.lower(),
            "linkedinUrl": normalise_linkedin_url(linkedin_url),
            "corpusDir": corpus_dir,
        })
    return experts


def match_expert(post_fm: dict[str, Any], registry: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the matching expert dict or None."""
    author_url = normalise_linkedin_url(post_fm.get("authorUrl"))
    author = (post_fm.get("author") or "").strip().lower()

    if author_url:
        for e in registry:
            if e["linkedinUrl"] and e["linkedinUrl"] == author_url:
                return e

    if author:
        for e in registry:
            if e["name_lower"] == author:
                return e

    return None


# --- Main --------------------------------------------------------------------

def route(dry_run: bool = False) -> dict[str, Any]:
    INBOX.mkdir(parents=True, exist_ok=True)
    registry = build_expert_registry()

    if not registry:
        return {"error": f"no experts found in {PROFILES_DIR}"}

    files = sorted(INBOX.glob("*.md"))
    # Filter out files that are explicitly metadata (e.g. _sweep-log.md)
    files = [f for f in files if not f.name.startswith("_")]

    counts = {"total": len(files), "routed": 0, "unroutable": 0, "already_unroutable": 0}
    routed_by_slug: dict[str, int] = {}
    report: list[str] = []

    for f in files:
        fm, body = read_frontmatter_and_body(f)

        # Skip already-routed (shouldn't happen — routed files are moved — but be defensive)
        if fm.get("routedTo") and fm["routedTo"] != "unroutable":
            continue
        if fm.get("routedTo") == "unroutable":
            counts["already_unroutable"] += 1
            continue

        match = match_expert(fm, registry)
        if match is None:
            counts["unroutable"] += 1
            fm["routedTo"] = "unroutable"
            if not dry_run:
                write_frontmatter_and_body(f, fm, body)
            report.append(f"  unroutable: {f.name} (author: {fm.get('author', '?')})")
            continue

        dest_dir = match["corpusDir"] / "fetched" / "linkedin"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.name

        fm["routedTo"] = match["slug"]

        if dry_run:
            report.append(f"  [DRY] {f.name} → {match['slug']}")
        else:
            # Atomic-ish move: update frontmatter in place, then shutil.move.
            write_frontmatter_and_body(f, fm, body)
            try:
                shutil.move(str(f), str(dest))
                report.append(f"  routed: {f.name} → {match['slug']}")
            except (PermissionError, OSError) as e:
                # Fallback: copy + try to empty the source. Used when the inbox
                # mount prohibits delete (eg. sandbox testing). On a normal Mac
                # filesystem shutil.move will succeed.
                shutil.copy2(str(f), str(dest))
                try:
                    f.unlink()
                    report.append(f"  routed: {f.name} → {match['slug']} (copy+delete)")
                except (PermissionError, OSError):
                    report.append(f"  routed: {f.name} → {match['slug']} (copy kept — could not remove source: {e})")

        counts["routed"] += 1
        routed_by_slug[match["slug"]] = routed_by_slug.get(match["slug"], 0) + 1

    return {"counts": counts, "by_slug": routed_by_slug, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description="Route LinkedIn inbox posts to experts.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would move; don't change files")
    args = parser.parse_args()

    result = route(dry_run=args.dry_run)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    c = result["counts"]
    print(f"Inbox: {c['total']} post(s)")
    for line in result["report"]:
        print(line)
    if result["by_slug"]:
        print("Routed by expert:")
        for slug, n in sorted(result["by_slug"].items(), key=lambda kv: -kv[1]):
            print(f"  {slug}: {n}")
    print(f"Summary: routed {c['routed']}, unroutable {c['unroutable']}"
          f"{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
