#!/usr/bin/env python3
"""Check that every voice-sample quote in a profile appears word for word in the corpus.

A voice sample is a line in a profile of the form

    > "the quoted words" — Source, date

The check reads every fetched file under ``<corpus>/<slug>/fetched/`` (frontmatter
left out) and looks for the quoted words in order. Case, punctuation and line
breaks are ignored, because auto-captions carry little punctuation and wrap
mid-sentence; the words themselves must match exactly.

Usage:
    python3 tools/check_quotes.py                      # every profile with a corpus folder
    python3 tools/check_quotes.py robert-cialdini      # one or more experts
    python3 tools/check_quotes.py --all-profiles       # also list profiles with no corpus folder

Exit code 1 when any checked quote is missing, so it can gate a commit. The corpus
lives on Paul's Mac (SYNTHETIC_EXPERTS_CORPUS), so this runs there, not in CI.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
REPO_DIR = SCRIPT_DIR.parent
CORPUS_ENV_VAR = "SYNTHETIC_EXPERTS_CORPUS"

QUOTE_LINE = re.compile(r'^>\s*["“](?P<quote>.+?)["”]\s+[—-]+\s+(?P<source>.+?)\s*$')
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'"})
_NON_WORD = re.compile(r"[^a-z0-9']+")


def corpus_root() -> Path:
    env = os.environ.get(CORPUS_ENV_VAR)
    return Path(env).expanduser().absolute() if env else REPO_DIR / "corpus"


def normalise(text: str) -> str:
    """Lower case, straight apostrophes, everything that isn't a word character a single space."""
    text = text.lower().translate(_APOSTROPHES)
    text = _NON_WORD.sub(" ", text)
    text = re.sub(r"(?<![a-z0-9])'|'(?![a-z0-9])", " ", text)  # quote marks, not apostrophes
    return " " + " ".join(text.split()) + " "


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


@dataclass
class Quote:
    line: int
    quote: str
    source: str
    found_in: str | None = None


def profile_quotes(profile: Path) -> list[Quote]:
    out = []
    for n, line in enumerate(profile.read_text(encoding="utf-8").splitlines(), 1):
        m = QUOTE_LINE.match(line.strip())
        if m:
            out.append(Quote(n, m.group("quote").strip(), m.group("source").strip()))
    return out


def corpus_texts(expert_dir: Path) -> list[tuple[str, str]]:
    fetched = expert_dir / "fetched"
    if not fetched.is_dir():
        return []
    texts = []
    for f in sorted(fetched.rglob("*")):
        if f.is_file() and f.suffix.lower() in {".md", ".txt"}:
            body = strip_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            texts.append((str(f.relative_to(expert_dir)), normalise(body)))
    return texts


def check_expert(slug: str, profiles_dir: Path, corpus: Path) -> tuple[list[Quote], str | None]:
    """Return the profile's quotes with found_in set, or a reason the expert can't be checked."""
    profile = profiles_dir / f"{slug}.md"
    if not profile.is_file():
        return [], f"no profile at {profile}"
    expert_dir = corpus / slug
    if not expert_dir.is_dir():
        return [], f"no corpus folder at {expert_dir}"
    texts = corpus_texts(expert_dir)
    quotes = profile_quotes(profile)
    for q in quotes:
        needle = normalise(q.quote)
        for name, body in texts:
            if needle in body:
                q.found_in = name
                break
    return quotes, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("experts", nargs="*", help="expert slugs (default: every profile with a corpus folder)")
    ap.add_argument("--profiles", type=Path, default=REPO_DIR / "profiles", help="profiles folder")
    ap.add_argument("--corpus", type=Path, default=None, help=f"corpus folder (default: ${CORPUS_ENV_VAR} or corpus/)")
    ap.add_argument("--all-profiles", action="store_true", help="also report profiles with no corpus folder")
    args = ap.parse_args(argv)

    corpus = args.corpus.expanduser().absolute() if args.corpus else corpus_root()
    slugs = args.experts or sorted(p.stem for p in args.profiles.glob("*.md"))
    explicit = bool(args.experts)

    missing_total = checked_total = 0
    for slug in slugs:
        quotes, why = check_expert(slug, args.profiles, corpus)
        if why:
            if explicit:
                print(f"{slug}: can't check, {why}")
                missing_total += 1
            elif args.all_profiles:
                print(f"{slug}: skipped, {why}")
            continue
        found = [q for q in quotes if q.found_in]
        print(f"{slug}: {len(found)} of {len(quotes)} quotes found in the corpus")
        for q in quotes:
            mark = "ok     " if q.found_in else "MISSING"
            where = q.found_in or "not in corpus"
            print(f"  {mark} line {q.line}: \"{q.quote}\" ({q.source}) -> {where}")
        checked_total += len(quotes)
        missing_total += len(quotes) - len(found)

    if checked_total == 0 and missing_total == 0:
        print("No quotes checked.")
    return 1 if missing_total else 0


if __name__ == "__main__":
    sys.exit(main())
