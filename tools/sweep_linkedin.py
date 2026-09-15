#!/usr/bin/env python3
"""
sweep_linkedin.py — the weekly LinkedIn + corpus sweep.

The full weekly pipeline:

  1. Claude-in-Chrome (run separately via /browse) pulls saved posts from
     https://www.linkedin.com/my-items/saved-posts/ into
     synthetic-experts/corpus/_inbox/linkedin/ (one markdown file per post, with
     frontmatter matching linkedin-saved-posts-runbook.md).

  2. This script runs route_linkedin_posts.py to move each post to the right
     expert's fetched/linkedin/ based on author match.

  3. This script runs refresh_corpus.py --all --skip-source youtube to pull any
     new Substack/RSS posts and flag the newly-routed LinkedIn posts. YouTube is
     left out because it tends to block the sandbox's datacentre IP; Paul runs
     `refresh_corpus.py --all --source youtube` from Terminal instead.

  4. Summary printed at the end.

Usage:
    python3 synthetic-experts/tools/sweep_linkedin.py
    python3 synthetic-experts/tools/sweep_linkedin.py --dry-run
    python3 synthetic-experts/tools/sweep_linkedin.py --skip-refresh    # only route; skip the full feed refresh

If the inbox is empty, the script will tell you to run /browse first.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# abspath() rather than resolve(): the sibling modules below take their corpus
# default from their own __file__, which comes from this sys.path entry. Keeping
# the invoked (symlinked) path means a run from AI-Lab still uses AI-Lab's corpus.
SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(SCRIPT_DIR))

import route_linkedin_posts as router          # noqa: E402
import refresh_corpus as refresher              # noqa: E402

# YouTube tends to block datacentre IPs, which is where the scheduled sweep runs.
SWEEP_SKIP_SOURCES = ["youtube"]


BANNER = """
╔════════════════════════════════════════════════════════════╗
║             Weekly expert-corpus sweep                     ║
╚════════════════════════════════════════════════════════════╝
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly LinkedIn + corpus sweep.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen; don't change files")
    parser.add_argument("--skip-refresh", action="store_true", help="Only run router; skip refresh_corpus --all")
    args = parser.parse_args()

    print(BANNER)

    # --- Step 1: check inbox ---
    inbox = router.INBOX
    inbox.mkdir(parents=True, exist_ok=True)
    inbox_files = [p for p in sorted(inbox.glob("*.md")) if not p.name.startswith("_")]

    if not inbox_files:
        print("LinkedIn inbox is empty at:")
        print(f"  {inbox}")
        print("")
        print("Run /browse (Claude in Chrome) first to pull saved posts from LinkedIn.")
        print("See synthetic-experts/corpus/linkedin-saved-posts-runbook.md for the navigation recipe.")
        print("")
        print("If you want to just do the non-LinkedIn refresh anyway, run:")
        print("  python3 synthetic-experts/tools/refresh_corpus.py --all")
        return 0

    print(f"Step 1 — LinkedIn inbox: {len(inbox_files)} post(s) to route\n")

    # --- Step 2: route ---
    print("Step 2 — Author-match routing")
    result = router.route(dry_run=args.dry_run)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return 1

    for line in result["report"]:
        print(line)
    c = result["counts"]
    print(f"  → routed {c['routed']} new, {c['unroutable']} new-unroutable, "
          f"{c['already_unroutable']} already-unroutable (manual triage needed)"
          f"{' (dry run)' if args.dry_run else ''}")

    total_unroutable = c["unroutable"] + c["already_unroutable"]
    if total_unroutable:
        print(f"  {total_unroutable} post(s) remain in inbox pending manual review.")
        print("  Located at: synthetic-experts/corpus/_inbox/linkedin/")
    print("")

    # --- Step 3: corpus refresh ---
    if args.skip_refresh:
        print("Step 3 — Skipped (--skip-refresh)")
        return 0

    print("Step 3 — Corpus refresh, all experts (YouTube skipped)")
    slugs = refresher.list_experts()
    if not slugs:
        print("  No experts with sources.yml found.")
        return 0

    total_new = 0
    for slug in slugs:
        res = refresher.refresh_expert(slug, dry_run=args.dry_run, force=False, discover=False,
                                       skip_sources=SWEEP_SKIP_SOURCES)
        if res.get("error"):
            print(f"  [{slug}] ERROR: {res['error']}")
            continue
        new = res["totals"]["new_items"]
        total_new += new
        if new:
            print(f"  [{slug}] {new} new item(s)")
        else:
            print(f"  [{slug}] up to date")

    print("")
    print(f"Summary: routed {c['routed']} LinkedIn post(s), "
          f"{total_new} new fetched item(s) across {len(slugs)} expert(s).")
    print("YouTube isn't part of this sweep. From Terminal on the Mac:")
    print("  python3 tools/refresh_corpus.py --all --source youtube")
    return 0


if __name__ == "__main__":
    sys.exit(main())
