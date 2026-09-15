#!/usr/bin/env python3
"""
create_github_issues.py — file the improvement-plan issues on GitHub via `gh`.

Parses an issues spec (default: improvement-plan-issues.md next to tools/, which
lives in AI-Lab), creates labels + milestone if missing, creates one issue per
`### ` heading in file order, then creates the epic with a task list linking
every child.

Usage (from the Mac, gh authenticated):
    cd ~/AI-Lab/projects/battlecard/synthetic-experts
    python3 tools/create_github_issues.py --dry-run     # print what would be created
    python3 tools/create_github_issues.py               # do it
    python3 tools/create_github_issues.py --spec <path> # use a different spec file

Idempotence: skips any issue whose exact title already exists (open or closed).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = "paulnugentuk/synthetic-experts"
MILESTONE = "Six-expert roundtable"
# abspath keeps the AI-Lab side of the tools/ symlink, where the spec lives.
SPEC = Path(os.path.abspath(__file__)).parent.parent / "improvement-plan-issues.md"

LABELS = {
    "agent": ("0E8A16", "Cloud session can do this unattended (green lane)"),
    "desk": ("1D76DB", "Needs the Mac: local corpus, yt-dlp, Whisper, or Paul"),
    "needs-paul": ("D93F0B", "Paul decides or hand-edits"),
    "phase:a": ("C5DEF5", "Pipeline"),
    "phase:b": ("C5DEF5", "Corpus"),
    "phase:c": ("C5DEF5", "Distil"),
    "phase:d": ("C5DEF5", "Roundtable + ship"),
    "epic": ("5319E7", "North-star issue with child task list"),
}

HEADING_RE = re.compile(r"^(#{2,3}) (.+?)$")
LABEL_RE = re.compile(r"`([a-z:-]+)`")


def gh(*args: str, dry: bool = False, capture: bool = True) -> str:
    cmd = ["gh", *args]
    if dry:
        print("  $", " ".join(cmd))
        return ""
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"gh failed: {' '.join(cmd)}")
    return r.stdout.strip()


def parse_spec(text: str):
    """Return (epic, issues). Each is dict(title, labels, body)."""
    epic, issues, cur = None, [], None
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            level, heading = m.group(1), m.group(2).strip()
            labels = LABEL_RE.findall(heading)
            title = LABEL_RE.sub("", heading).strip()
            if level == "##" and title.startswith("Epic:"):
                cur = epic = {"title": title[len("Epic:"):].strip(), "labels": labels + ["epic"], "body": []}
            elif level == "###":
                cur = {"title": title, "labels": labels, "body": []}
                issues.append(cur)
            else:
                cur = None  # phase headers etc.
            continue
        if cur is not None and not line.startswith("---"):
            cur["body"].append(line)
    for it in ([epic] if epic else []) + issues:
        it["body"] = "\n".join(it["body"]).strip()
    return epic, issues


def existing_titles(dry: bool) -> set[str]:
    if dry:
        return set()
    out = gh("issue", "list", "--repo", REPO, "--state", "all", "--limit", "500", "--json", "title")
    return {i["title"] for i in json.loads(out or "[]")}


def ensure_labels(dry: bool) -> None:
    have = set()
    if not dry:
        out = gh("label", "list", "--repo", REPO, "--limit", "100", "--json", "name")
        have = {l["name"] for l in json.loads(out or "[]")}
    for name, (colour, desc) in LABELS.items():
        if name in have:
            continue
        gh("label", "create", name, "--repo", REPO, "--color", colour, "--description", desc, dry=dry)


def ensure_milestone(dry: bool) -> None:
    if dry:
        print(f"  (would ensure milestone '{MILESTONE}')")
        return
    out = gh("api", f"repos/{REPO}/milestones?state=all")
    if any(m["title"] == MILESTONE for m in json.loads(out or "[]")):
        return
    gh("api", f"repos/{REPO}/milestones", "-f", f"title={MILESTONE}",
       "-f", "description=Six distinct expert voices on a real Series B company, published.")


def create_issue(it: dict, dry: bool) -> str:
    args = ["issue", "create", "--repo", REPO, "--title", it["title"],
            "--body", it["body"], "--milestone", MILESTONE]
    for l in it["labels"]:
        args += ["--label", l]
    if dry:
        print(f"  would create: {it['title']}  [{', '.join(it['labels'])}]")
        return "#?"
    url = gh(*args)
    print(f"  created: {url}  {it['title']}")
    return url


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--spec", type=Path, default=SPEC, help=f"Issues spec (default: {SPEC})")
    args = ap.parse_args()
    dry = args.dry_run
    spec = args.spec

    if not spec.exists():
        raise SystemExit(f"Spec not found: {spec}. Pass --spec <path>.")
    epic, issues = parse_spec(spec.read_text())
    if not issues:
        raise SystemExit(f"No issues parsed from {spec}")
    print(f"Parsed {len(issues)} issues + epic from {spec.name}\n")

    print("Labels / milestone")
    ensure_labels(dry)
    ensure_milestone(dry)

    have = existing_titles(dry)
    print("\nIssues")
    created: list[tuple[str, str]] = []
    for it in issues:
        if it["title"] in have:
            print(f"  skip (exists): {it['title']}")
            continue
        created.append((it["title"], create_issue(it, dry)))

    if epic and epic["title"] not in have:
        print("\nEpic")
        tasks = "\n".join(f"- [ ] {url} {title}" for title, url in created)
        epic["body"] = epic["body"] + "\n\n## Children\n\n" + tasks
        create_issue(epic, dry)

    print("\nNext: add the new issues to the HQ project board (Status: Ready for week-1 items, Inbox for the rest).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
