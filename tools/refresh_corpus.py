#!/usr/bin/env python3
"""
refresh_corpus.py — pull new content into a synthetic expert's corpus.

Usage:
    python3 refresh_corpus.py <slug>              # refresh one expert
    python3 refresh_corpus.py --all               # refresh all experts with sources.yml
    python3 refresh_corpus.py <slug> --dry-run    # show what would be fetched, don't write

The corpus root is $SYNTHETIC_EXPERTS_CORPUS if set, otherwise corpus/ next
to tools/ (see the Paths section below).

Reads config from <corpus>/<slug>/sources.yml.
Writes fetched content to <corpus>/<slug>/fetched/<type>/.
Updates lastFetched timestamps in sources.yml.
Regenerates <corpus>/<slug>/index.md.

Handlers:
  - substack / rss      : feedparser (required)
  - youtube_videos      : youtube-transcript-api (required for this handler)
  - youtube_channel     : yt-dlp + youtube-transcript-api (optional)
  - linkedin_manual     : check-only, no auto-fetch
  - whisper_folder      : openai-whisper local OR OpenAI API (optional)

Install deps:
    pip install -r requirements.txt --break-system-packages
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# --- Required deps ---
try:
    import yaml  # PyYAML
except ImportError:
    sys.exit("Missing dependency: PyYAML. Run: pip install PyYAML --break-system-packages")

# --- Optional deps (imported lazily inside handlers) ---
# feedparser                : for substack/rss
# youtube_transcript_api    : for youtube_videos, youtube_channel
# yt_dlp                    : for youtube_channel
# whisper (or openai SDK)   : for whisper_folder


# --- Paths -------------------------------------------------------------------

#
# The corpus (other people's transcripts and posts) stays on the Mac and is
# gitignored. SYNTHETIC_EXPERTS_CORPUS points at it; without it the tools look
# for corpus/ next to tools/. abspath() is used instead of resolve() so that
# when AI-Lab's tools/ is a symlink to this repo, "next to tools/" still means
# AI-Lab. tools/tests/test_paths.py guards this.

CORPUS_ENV_VAR = "SYNTHETIC_EXPERTS_CORPUS"
SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
EXPERTS_DIR = SCRIPT_DIR.parent               # synthetic-experts/


def corpus_root() -> Path:
    env = os.environ.get(CORPUS_ENV_VAR)
    return Path(env).expanduser().absolute() if env else EXPERTS_DIR / "corpus"


CORPUS_ROOT = corpus_root()


# --- Utilities ---------------------------------------------------------------

def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\s-]", "", s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return s[:80] or "untitled"


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def write_item(
    corpus_dir: Path,
    source_type: str,
    *,
    date: dt.datetime | None,
    title: str,
    source_url: str,
    body: str,
    extra_frontmatter: dict[str, Any] | None = None,
    force: bool = False,
) -> Path:
    """Write a fetched item as markdown with YAML frontmatter.

    Filename: <type>/<YYYY-MM-DD>-<slug>.md
    Idempotent by default (won't overwrite existing file). Pass force=True to overwrite,
    useful when re-running after handler changes.
    """
    type_dir = corpus_dir / "fetched" / source_type
    type_dir.mkdir(parents=True, exist_ok=True)

    date_part = (date or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d")
    filename = f"{date_part}-{slugify(title)}.md"
    path = type_dir / filename

    if path.exists() and not force:
        return path  # idempotent — don't overwrite

    frontmatter = {
        "source": source_type,
        "sourceUrl": source_url,
        "title": title,
        "publishedAt": date.isoformat() if date else None,
        "fetchedAt": iso_now(),
    }
    if extra_frontmatter:
        frontmatter.update(extra_frontmatter)

    lines = ["---"]
    for k, v in frontmatter.items():
        if v is None:
            continue
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append("---\n")
    lines.append(body.strip())
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --- Handlers ----------------------------------------------------------------

def _clean_html_to_markdown(html: str) -> str:
    """Convert RSS HTML body to clean markdown. Removes image containers,
    subscription widgets, SVG icons, and other Substack/blog chrome.

    Falls back to regex stripping if html2text isn't installed.
    """
    # Strip known noise blocks before conversion (regex is fine — these are
    # well-defined container divs).
    noise_patterns = [
        r'<div class="captioned-image-container".*?</div>\s*</figure>\s*</div>',
        r'<div class="subscription-widget.*?</div>\s*</div>',
        r'<div class="subscription-widget-wrap.*?</div>\s*</div>',
        r'<svg\b[^>]*>.*?</svg>',
        r'<script\b[^>]*>.*?</script>',
        r'<style\b[^>]*>.*?</style>',
        r'<figure\b[^>]*>.*?</figure>',
    ]
    for pat in noise_patterns:
        html = re.sub(pat, "", html, flags=re.S)

    try:
        import html2text
        h = html2text.HTML2Text()
        h.body_width = 0          # no forced line wrapping
        h.ignore_images = True
        h.ignore_emphasis = False
        h.ignore_links = False
        h.protect_links = True
        return h.handle(html).strip()
    except ImportError:
        # Fallback: strip all tags
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text


def handle_feed(
    source: dict,
    corpus_dir: Path,
    dry_run: bool,
    force: bool = False,
) -> tuple[int, list[str]]:
    """substack / rss — both use feedparser."""
    try:
        import feedparser
    except ImportError:
        return (0, ["feedparser not installed — skipping. pip install feedparser --break-system-packages"])

    url = source.get("url")
    if not url:
        return (0, ["missing url"])

    last_fetched = parse_iso(source.get("lastFetched"))
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        return (0, [f"feed parse failed: {getattr(feed, 'bozo_exception', 'unknown')}"])

    new_count = 0
    notes: list[str] = []
    latest_seen: dt.datetime | None = None

    for entry in feed.entries:
        pub = None
        for key in ("published_parsed", "updated_parsed"):
            val = entry.get(key)
            if val:
                pub = dt.datetime(*val[:6], tzinfo=dt.timezone.utc)
                break

        if last_fetched and pub and pub <= last_fetched and not force:
            continue

        title = entry.get("title", "Untitled")
        link = entry.get("link", url)

        # Prefer full content over summary
        body = ""
        if entry.get("content"):
            body = entry.content[0].get("value", "")
        elif entry.get("summary"):
            body = entry.summary

        body = _clean_html_to_markdown(body)

        if pub and (latest_seen is None or pub > latest_seen):
            latest_seen = pub

        if dry_run:
            notes.append(f"[DRY] would fetch: {title} ({pub.date() if pub else 'no date'})")
            new_count += 1
            continue

        write_item(
            corpus_dir,
            source["type"],
            date=pub,
            title=title,
            source_url=link,
            body=body,
            extra_frontmatter={"feedName": source.get("name")},
            force=force,
        )
        new_count += 1

    if not dry_run and latest_seen:
        source["lastFetched"] = latest_seen.strftime("%Y-%m-%dT%H:%M:%SZ")

    return (new_count, notes)


def handle_youtube_videos(
    source: dict,
    corpus_dir: Path,
    dry_run: bool,
) -> tuple[int, list[str]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return (0, ["youtube-transcript-api not installed — skipping. pip install youtube-transcript-api --break-system-packages"])

    video_ids = source.get("videoIds") or []
    if not video_ids:
        return (0, ["no videoIds configured"])

    out_path = corpus_dir / "fetched" / "youtube"
    out_path.mkdir(parents=True, exist_ok=True)

    # Track already-fetched IDs via filename suffix `__<id>.md`
    already_fetched = {p.name.split("__")[-1].removesuffix(".md")
                       for p in out_path.glob("*__*.md")}

    api = YouTubeTranscriptApi()
    new_count = 0
    notes: list[str] = []

    for vid in video_ids:
        if vid.startswith("TBD_") or len(vid) < 8:
            notes.append(f"skip placeholder: {vid}")
            continue

        if vid in already_fetched:
            continue

        try:
            fetched = api.fetch(vid)
        except Exception as e:
            # Specific error classes vary between library versions; catch broadly
            etype = type(e).__name__
            notes.append(f"{vid}: fetch failed ({etype}: {e})")
            continue

        # FetchedTranscript iterates FetchedTranscriptSnippet (with .text/.start/.duration)
        segments = list(fetched)
        text = "\n".join(getattr(seg, "text", "").strip()
                         for seg in segments if getattr(seg, "text", "").strip())
        if not text.strip():
            notes.append(f"{vid}: empty transcript")
            continue

        url = f"https://www.youtube.com/watch?v={vid}"
        title = f"YouTube video {vid}"

        if dry_run:
            notes.append(f"[DRY] would fetch: {url} ({len(text)} chars)")
            new_count += 1
            continue

        write_item(
            corpus_dir,
            "youtube",
            date=dt.datetime.now(dt.timezone.utc),
            title=f"{title}__{vid}",  # embed id in filename for idempotency
            source_url=url,
            body=text,
            extra_frontmatter={
                "videoId": vid,
                "transcriptSource": "auto-captions",
                "note": "Auto-generated captions via youtube-transcript-api. Speaker labels not preserved.",
            },
        )
        new_count += 1

    return (new_count, notes)


def handle_youtube_channel(
    source: dict,
    corpus_dir: Path,
    dry_run: bool,
) -> tuple[int, list[str]]:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError:
        return (0, ["yt-dlp not installed — skipping channel. pip install yt-dlp --break-system-packages"])

    handle = source.get("channelHandle") or source.get("channelId")
    if not handle:
        return (0, ["missing channelHandle/channelId"])

    max_videos = int(source.get("maxVideos", 10))
    url = f"https://www.youtube.com/{handle}/videos" if handle.startswith("@") else f"https://www.youtube.com/channel/{handle}/videos"

    ydl_opts = {"quiet": True, "extract_flat": True, "playlistend": max_videos}
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return (0, [f"yt-dlp failed: {e}"])

    entries = info.get("entries") or []
    video_ids = [e.get("id") for e in entries if e.get("id")]

    # Reuse youtube_videos handler logic by synthesising a stub source
    stub = {"videoIds": video_ids}
    return handle_youtube_videos(stub, corpus_dir, dry_run)


def handle_linkedin_manual(
    source: dict,
    corpus_dir: Path,
    dry_run: bool,
) -> tuple[int, list[str]]:
    """Declared but not auto-fetched. Just report count of existing files."""
    linkedin_dir = corpus_dir / "fetched" / "linkedin"
    linkedin_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(linkedin_dir.glob("*.md"))
    msg = f"{len(files)} manually-pulled LinkedIn file(s) in {linkedin_dir.relative_to(CORPUS_ROOT.parent)}"
    if not files:
        msg += ". Use Claude in Chrome to pull posts from " + (source.get("url") or "profile") + "."

    return (0, [msg])


def handle_whisper_folder(
    source: dict,
    corpus_dir: Path,
    dry_run: bool,
) -> tuple[int, list[str]]:
    folder = corpus_dir / (source.get("folder") or "uploads")
    folder.mkdir(parents=True, exist_ok=True)
    processed = folder / "processed"
    processed.mkdir(exist_ok=True)

    audio_exts = {".mp3", ".mp4", ".wav", ".m4a", ".webm", ".mov"}
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in audio_exts]

    if not files:
        return (0, [f"no audio/video files in {folder.relative_to(CORPUS_ROOT.parent)}"])

    # Try local whisper first
    try:
        import whisper  # type: ignore
        backend = "local-whisper"
    except ImportError:
        whisper = None
        backend = None

    if not backend:
        try:
            from openai import OpenAI  # type: ignore
            if os.environ.get("OPENAI_API_KEY"):
                backend = "openai-api"
        except ImportError:
            pass

    if not backend:
        return (0, [
            f"{len(files)} audio file(s) waiting but no transcription backend available.",
            "Install one: pip install openai-whisper --break-system-packages   (local, free)",
            "Or: pip install openai --break-system-packages + set OPENAI_API_KEY   (cloud, $0.006/min)",
        ])

    new_count = 0
    notes: list[str] = []

    for f in files:
        if dry_run:
            notes.append(f"[DRY] would transcribe with {backend}: {f.name}")
            new_count += 1
            continue

        try:
            if backend == "local-whisper":
                model = whisper.load_model("base")
                result = model.transcribe(str(f))
                text = result.get("text", "")
            else:
                from openai import OpenAI  # type: ignore
                client = OpenAI()
                with open(f, "rb") as fh:
                    result = client.audio.transcriptions.create(
                        model="whisper-1", file=fh, response_format="text"
                    )
                text = result if isinstance(result, str) else str(result)
        except Exception as e:
            notes.append(f"{f.name}: transcription failed ({e})")
            continue

        if not text.strip():
            notes.append(f"{f.name}: empty transcript")
            continue

        write_item(
            corpus_dir,
            "whisper",
            date=dt.datetime.fromtimestamp(f.stat().st_mtime, tz=dt.timezone.utc),
            title=f.stem,
            source_url=f"local://{f.name}",
            body=text,
            extra_frontmatter={"backend": backend, "originalFilename": f.name},
        )
        # Move original to processed/ so it doesn't re-run
        f.rename(processed / f.name)
        new_count += 1

    return (new_count, notes)


HANDLERS = {
    "substack": handle_feed,
    "rss": handle_feed,
    "youtube_videos": handle_youtube_videos,
    "youtube_channel": handle_youtube_channel,
    "linkedin_manual": handle_linkedin_manual,
    "whisper_folder": handle_whisper_folder,
}


# --- YouTube discovery -------------------------------------------------------

def _yt_search(query: str, max_results: int = 10) -> list[dict]:
    """Run a YouTube search via yt-dlp (no API key required)."""
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError:
        return []

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "default_search": f"ytsearch{max_results}",
        "skip_download": True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
    except Exception:
        return []

    entries = info.get("entries") or []
    results = []
    for e in entries:
        if not e or not e.get("id"):
            continue
        results.append({
            "id": e.get("id"),
            "title": e.get("title") or "",
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration": e.get("duration") or 0,
            "url": e.get("url") or f"https://www.youtube.com/watch?v={e['id']}",
        })
    return results


def _read_candidates_seen_ids(candidates_path: Path) -> set[str]:
    if not candidates_path.exists():
        return set()
    text = candidates_path.read_text(errors="ignore")
    # Find all 11-char YouTube IDs we've listed before
    return set(re.findall(r"watch\?v=([A-Za-z0-9_-]{11})", text))


def run_youtube_discovery(config: dict, corpus_dir: Path, dry_run: bool) -> list[str]:
    """Search YouTube for candidates. Auto-promote strict matches into the
    sibling youtube_videos source. Write everything else to candidates.md.
    """
    report: list[str] = []
    discovery_sources = [s for s in config.get("sources", [])
                         if s.get("type") == "youtube_discovery" and s.get("enabled")]
    if not discovery_sources:
        return report

    # Find the youtube_videos source to promote into (first enabled one)
    video_source = next(
        (s for s in config.get("sources", [])
         if s.get("type") == "youtube_videos" and s.get("enabled")),
        None,
    )
    approved_ids: set[str] = set(video_source.get("videoIds") or []) if video_source else set()

    candidates_path = corpus_dir / "candidates.md"
    seen_ids = _read_candidates_seen_ids(candidates_path) | approved_ids

    all_candidates: list[dict] = []
    auto_added: list[dict] = []

    for src in discovery_sources:
        queries = src.get("queries") or []
        if not queries:
            continue
        max_per = int(src.get("maxPerQuery", 10))
        min_dur = int(src.get("minDurationSec", 600))      # 10 min default
        max_dur = int(src.get("maxDurationSec", 10800))    # 3 hr default
        name_match = (src.get("expertNameMatch") or "").lower()
        auto_approve = bool(src.get("autoApprove", False))

        for q in queries:
            report.append(f"  [discover] query: {q!r}")
            results = _yt_search(q, max_results=max_per)
            for r in results:
                vid = r["id"]
                if vid in seen_ids:
                    continue
                # Duration filter (Shorts + movies)
                dur = r.get("duration") or 0
                if dur and (dur < min_dur or dur > max_dur):
                    continue

                title_lower = (r.get("title") or "").lower()
                channel_lower = (r.get("channel") or "").lower()
                strict_match = bool(name_match) and (name_match in title_lower or name_match in channel_lower)

                r["query"] = q
                r["strict_match"] = strict_match
                all_candidates.append(r)
                seen_ids.add(vid)

                if auto_approve and strict_match and video_source is not None:
                    auto_added.append(r)
                    approved_ids.add(vid)

    # Mutate the youtube_videos source with auto-approved IDs
    if auto_added and video_source is not None and not dry_run:
        existing = list(video_source.get("videoIds") or [])
        for r in auto_added:
            if r["id"] not in existing:
                existing.append(r["id"])
        video_source["videoIds"] = existing
        report.append(f"  [discover] auto-approved {len(auto_added)} video(s) into videoIds")

    # Write candidates.md (append-friendly, keeps history)
    if all_candidates and not dry_run:
        _append_candidates_file(candidates_path, all_candidates, auto_added)
        report.append(f"  [discover] wrote {len(all_candidates)} candidate(s) to candidates.md")
    elif all_candidates:
        report.append(f"  [discover] [DRY] would record {len(all_candidates)} candidate(s) ({len(auto_added)} strict-match)")

    if not all_candidates:
        report.append("  [discover] no new candidates found")

    return report


def _append_candidates_file(path: Path, candidates: list[dict], auto_added: list[dict]) -> None:
    auto_ids = {r["id"] for r in auto_added}
    header = ""
    if not path.exists():
        header = (
            "# YouTube discovery candidates\n\n"
            "Candidates found via `youtube_discovery` queries in sources.yml.\n"
            "Strict matches (expert name in title or channel) are auto-added to `videoIds` when `autoApprove: true`.\n"
            "Other candidates need your review — copy the ID into sources.yml under `youtube_videos.videoIds` if you want the transcript.\n"
            "Rerun `refresh_corpus.py <slug>` after editing to fetch the approved ones.\n\n"
        )

    stamp = iso_now()
    lines = [header, f"## Run: {stamp}\n"] if header else [f"\n## Run: {stamp}\n"]

    # Group: auto-added first, then review queue
    auto = [c for c in candidates if c["id"] in auto_ids]
    review = [c for c in candidates if c["id"] not in auto_ids]

    if auto:
        lines.append("### Auto-added to videoIds\n")
        for c in auto:
            dur = c.get("duration") or 0
            mins = f"{dur // 60}m" if dur else "?"
            lines.append(f"- `{c['id']}` — [{c['title']}]({c['url']}) — {c['channel']} — {mins} — _query: {c['query']!r}_")
        lines.append("")

    if review:
        lines.append("### Review queue (copy ID into sources.yml to approve)\n")
        for c in review:
            dur = c.get("duration") or 0
            mins = f"{dur // 60}m" if dur else "?"
            lines.append(f"- [ ] `{c['id']}` — [{c['title']}]({c['url']}) — {c['channel']} — {mins} — _query: {c['query']!r}_")
        lines.append("")

    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


# --- Index regeneration ------------------------------------------------------

def regenerate_index(corpus_dir: Path, config: dict) -> None:
    """Walk fetched/ and write index.md with a per-source summary."""
    fetched = corpus_dir / "fetched"
    index_path = corpus_dir / "index.md"

    lines = [
        f"# Corpus index — {config.get('expert')}",
        "",
        f"_Last refresh: {config.get('lastFullRefresh') or 'never'}_",
        "",
    ]

    total = 0
    if fetched.exists():
        for subdir in sorted(fetched.iterdir()):
            if not subdir.is_dir():
                continue
            files = sorted(subdir.glob("*.md"))
            if not files:
                continue
            lines.append(f"## {subdir.name} ({len(files)})")
            lines.append("")
            for f in files[-20:]:  # last 20 per source
                lines.append(f"- `{f.name}`")
            if len(files) > 20:
                lines.append(f"- ... and {len(files) - 20} older")
            lines.append("")
            total += len(files)

    lines.insert(3, f"_Total items: {total}_")
    lines.insert(4, "")

    index_path.write_text("\n".join(lines), encoding="utf-8")


# --- Orchestration -----------------------------------------------------------

def refresh_expert(slug: str, dry_run: bool = False, force: bool = False, discover: bool = False) -> dict:
    corpus_dir = CORPUS_ROOT / slug
    config_path = corpus_dir / "sources.yml"

    if not config_path.exists():
        return {"slug": slug, "error": f"no sources.yml at {config_path}"}

    config = yaml.safe_load(config_path.read_text())
    sources = config.get("sources") or []

    totals = {"new_items": 0, "handlers_run": 0, "handlers_skipped": 0}
    report: list[str] = []

    # --- Optional discovery step: finds candidate YouTube videos, may mutate
    # the videoIds list of a sibling youtube_videos source.
    if discover:
        try:
            report.extend(run_youtube_discovery(config, corpus_dir, dry_run))
        except Exception as e:
            report.append(f"[discover] crashed: {e}")

    for source in sources:
        stype = source.get("type")
        if not source.get("enabled", False):
            totals["handlers_skipped"] += 1
            continue

        # Discovery is handled separately (above) — don't log a "no handler" warning for it
        if stype == "youtube_discovery":
            continue

        handler = HANDLERS.get(stype)
        if not handler:
            report.append(f"[{stype}] no handler — skipping")
            continue

        try:
            # Only handlers that accept `force` get it; others ignore via try/except
            try:
                new_count, notes = handler(source, corpus_dir, dry_run, force=force)
            except TypeError:
                new_count, notes = handler(source, corpus_dir, dry_run)
        except Exception as e:
            report.append(f"[{stype}] handler crashed: {e}")
            continue

        totals["new_items"] += new_count
        totals["handlers_run"] += 1
        prefix = f"[{stype}: {source.get('name', '')}]"
        if new_count:
            report.append(f"{prefix} fetched {new_count} item(s)")
        for n in notes:
            report.append(f"  {prefix} {n}")

    if not dry_run:
        config["lastFullRefresh"] = iso_now()
        config_path.write_text(
            yaml.dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        regenerate_index(corpus_dir, config)

    return {"slug": slug, "totals": totals, "report": report}


def list_experts() -> list[str]:
    if not CORPUS_ROOT.exists():
        return []
    return sorted(
        d.name for d in CORPUS_ROOT.iterdir()
        if d.is_dir() and (d / "sources.yml").exists()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh synthetic expert corpus.")
    parser.add_argument("slug", nargs="?", help="Expert slug (e.g. april-dunford)")
    parser.add_argument("--all", action="store_true", help="Refresh all experts")
    parser.add_argument("--dry-run", action="store_true", help="Don't write; report only")
    parser.add_argument("--force", action="store_true", help="Re-fetch and overwrite existing items (use after handler changes)")
    parser.add_argument("--discover", action="store_true", help="Run YouTube discovery queries before fetch; auto-promote strict matches")
    parser.add_argument("--list", action="store_true", help="List experts with sources.yml")
    args = parser.parse_args()

    if args.list:
        for s in list_experts():
            print(s)
        return 0

    if args.all:
        slugs = list_experts()
    elif args.slug:
        slugs = [args.slug]
    else:
        parser.print_help()
        return 2

    if not slugs:
        print(f"No experts found under {CORPUS_ROOT}. Set {CORPUS_ENV_VAR} or create <corpus>/<slug>/sources.yml.")
        return 1

    exit_code = 0
    for slug in slugs:
        print(f"\n=== {slug} ===")
        result = refresh_expert(slug, dry_run=args.dry_run, force=args.force, discover=args.discover)
        if result.get("error"):
            print(f"ERROR: {result['error']}")
            exit_code = 1
            continue
        for line in result["report"]:
            print(line)
        totals = result["totals"]
        print(f"Summary: {totals['new_items']} new item(s), "
              f"{totals['handlers_run']} handler(s) run, "
              f"{totals['handlers_skipped']} disabled.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
