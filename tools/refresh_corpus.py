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
  - youtube_videos      : yt-dlp English auto-subtitles (run from the Mac; YouTube
                          tends to block datacentre IPs)
  - youtube_channel     : yt-dlp (optional)
  - linkedin_manual     : check-only, no auto-fetch
  - whisper_folder      : openai-whisper local OR OpenAI API (optional)
  - transcript_bank     : copy matching transcripts from a local folder of markdown
                          (e.g. a clone of a podcast archive); see the README

Source filters (repeatable; take a group name or a raw source type):
    python3 refresh_corpus.py --all --source youtube        # YouTube only, from Terminal
    python3 refresh_corpus.py --all --skip-source youtube   # everything else (the weekly sweep)
  Groups: feeds (substack, rss), youtube (youtube_videos, youtube_channel,
  youtube_discovery), linkedin, whisper, transcript_bank.

Install deps:
    pip install -r requirements.txt --break-system-packages
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from html import unescape as html_unescape
from pathlib import Path
from typing import Any

# --- Required deps ---
try:
    import yaml  # PyYAML
except ImportError:
    sys.exit("Missing dependency: PyYAML. Run: pip install PyYAML --break-system-packages")

# --- Optional deps (imported lazily inside handlers) ---
# feedparser                : for substack/rss
# yt_dlp                    : for youtube_videos (run as a subprocess), youtube_channel, --discover
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
    slug_suffix: str | None = None,
) -> Path:
    """Write a fetched item as markdown with YAML frontmatter.

    Filename: <type>/<YYYY-MM-DD>-<slug>[-<slug_suffix>].md
    Idempotent by default (won't overwrite existing file). Pass force=True to overwrite,
    useful when re-running after handler changes.
    """
    type_dir = corpus_dir / "fetched" / source_type
    type_dir.mkdir(parents=True, exist_ok=True)

    date_part = (date or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d")
    suffix = f"-{slug_suffix}" if slug_suffix else ""
    filename = f"{date_part}-{slugify(title)}{suffix}.md"
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


VIDEO_ID_RE = re.compile(r'^videoId:\s*"?([^"\s]+)"?\s*$')


def fetched_video_ids(youtube_dir: Path) -> set[str]:
    """Video IDs already in the corpus, read from each file's `videoId:` frontmatter.

    Filenames can't be used for this: slugify() lowercases them and strips the
    `__<id>` marker, and YouTube IDs are case-sensitive.
    """
    ids: set[str] = set()
    if not youtube_dir.exists():
        return ids
    for p in youtube_dir.glob("*.md"):
        with p.open(encoding="utf-8") as fh:
            if fh.readline().strip() != "---":
                continue
            for line in fh:
                if line.strip() == "---":
                    break
                m = VIDEO_ID_RE.match(line)
                if m:
                    ids.add(m.group(1))
                    break
    return ids


YOUTUBE_PAUSE_SECONDS = 2  # between videos in one run, to go easy on YouTube

_VTT_TIMING_RE = re.compile(r"^\d{2}:\d{2}(?::\d{2})?\.\d{3}\s+-->")
_VTT_HEADER_RE = re.compile(r"^(WEBVTT|Kind:|Language:|NOTE\b|STYLE\b|REGION\b)")
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def vtt_to_text(vtt: str) -> str:
    """Turn a WebVTT caption file into plain text, one caption line per line.

    YouTube auto-captions roll: each cue repeats the previous line above the new
    one, and short bridging cues repeat it again. Stripping the inline timing
    tags and dropping any line identical to the one before collapses that back
    to a single copy.
    """
    out: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or _VTT_TIMING_RE.match(line) or _VTT_HEADER_RE.match(line):
            continue
        line = html_unescape(_VTT_TAG_RE.sub("", line)).strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return "\n".join(out)


def _yt_dlp_command() -> list[str] | None:
    """yt-dlp from this Python if installed, else the yt-dlp binary on PATH."""
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    exe = shutil.which("yt-dlp")
    return [exe] if exe else None


def fetch_youtube_transcript(video_id: str) -> str:
    """Pull English auto-captions for one video with yt-dlp; return plain text.

    Same as: yt-dlp --write-auto-subs --sub-lang en --skip-download --sub-format vtt
    """
    base = _yt_dlp_command()
    if base is None:
        raise RuntimeError("yt-dlp not installed (pip install yt-dlp)")
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            *base,
            "--write-auto-subs", "--sub-lang", "en", "--skip-download", "--sub-format", "vtt",
            "--quiet", "--no-warnings",
            "-o", os.path.join(tmp, "%(id)s.%(ext)s"),
            "--", video_id,  # "--" because some IDs start with a dash
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            detail = (r.stderr.strip().splitlines() or ["no output"])[-1]
            raise RuntimeError(f"yt-dlp exit {r.returncode}: {detail}")
        vtts = sorted(Path(tmp).glob("*.vtt"))
        if not vtts:
            raise RuntimeError("no English auto-captions available")
        return vtt_to_text(vtts[0].read_text(encoding="utf-8"))


def handle_youtube_videos(
    source: dict,
    corpus_dir: Path,
    dry_run: bool,
) -> tuple[int, list[str]]:
    video_ids = source.get("videoIds") or []
    if not video_ids:
        return (0, ["no videoIds configured"])

    if not dry_run and _yt_dlp_command() is None:
        return (0, ["yt-dlp not installed — skipping. pip install yt-dlp"])

    already_fetched = fetched_video_ids(corpus_dir / "fetched" / "youtube")

    new_count = 0
    notes: list[str] = []
    requested = 0

    for vid in video_ids:
        if vid.startswith("TBD_") or len(vid) < 8:
            notes.append(f"skip placeholder: {vid}")
            continue

        if vid in already_fetched:
            continue
        already_fetched.add(vid)  # guards against the same ID listed twice

        if dry_run:
            # No network in dry-run: report what's pending and move on.
            notes.append(f"[DRY] would fetch: https://www.youtube.com/watch?v={vid}")
            new_count += 1
            continue

        if requested and YOUTUBE_PAUSE_SECONDS:
            time.sleep(YOUTUBE_PAUSE_SECONDS)
        requested += 1

        try:
            text = fetch_youtube_transcript(vid)
        except Exception as e:
            notes.append(f"{vid}: fetch failed ({type(e).__name__}: {e})")
            continue

        if not text.strip():
            notes.append(f"{vid}: empty transcript")
            continue

        url = f"https://www.youtube.com/watch?v={vid}"
        title = f"YouTube video {vid}"

        write_item(
            corpus_dir,
            "youtube",
            date=dt.datetime.now(dt.timezone.utc),
            title=f"{title}__{vid}",  # filename only; dedup reads videoId from frontmatter
            source_url=url,
            body=text,
            extra_frontmatter={
                "videoId": vid,
                "transcriptSource": "auto-captions",
                "note": "Auto-generated captions via yt-dlp (VTT, rolling lines collapsed). Speaker labels not preserved.",
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


def _read_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split markdown into (frontmatter dict, body). No frontmatter gives ({}, text)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, flags=re.S)
    if not m:
        return ({}, text)
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}, m.group(2))


def _as_datetime(value: Any) -> dt.datetime | None:
    """Frontmatter dates arrive as date, datetime or string; normalise to UTC datetime."""
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)
    if isinstance(value, str):
        parsed = parse_iso(value.strip())
        if parsed:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return None


def _match_bank_file(
    fm: dict[str, Any], rel_path: str, guests: list[str], fragments: list[str]
) -> tuple[bool, str | None]:
    """Return (matched, speaker). Guest names match by case-insensitive containment,
    so "Elena Verna" matches Lenny's "Elena Verna 2.0". Fragments match anywhere in
    the path inside the bank, because Lenny's mirror names the folder, not the file."""
    file_guests = fm.get("guest") or fm.get("guests") or []
    if isinstance(file_guests, str):
        file_guests = [file_guests]
    joined = " | ".join(str(g) for g in file_guests).lower()
    for g in guests:
        if g.lower() in joined:
            return (True, g)
    path_lower = rel_path.lower()
    if any(frag in path_lower for frag in fragments):
        speaker = guests[0] if guests else (str(file_guests[0]) if file_guests else None)
        return (True, speaker)
    return (False, None)


def _bank_copies(out_dir: Path) -> tuple[set[str], set[str]]:
    """(sourceHash values, videoId values) of transcripts already copied."""
    hashes: set[str] = set()
    video_ids: set[str] = set()
    if not out_dir.exists():
        return hashes, video_ids
    for p in out_dir.glob("*.md"):
        fm, _ = _read_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        if fm.get("sourceHash"):
            hashes.add(str(fm["sourceHash"]))
        if fm.get("videoId"):
            video_ids.add(str(fm["videoId"]))
    return hashes, video_ids


def handle_transcript_bank(
    source: dict,
    corpus_dir: Path,
    dry_run: bool,
) -> tuple[int, list[str]]:
    """Copy matching transcripts from a local folder of markdown files.

        - type: transcript_bank
          name: Lenny's Podcast (community mirror)
          path: ~/transcripts/lennys
          match: { guest: ["Elena Verna"], filenameContains: ["elena-verna"] }
          enabled: true

    Matches land in fetched/transcript-bank/ with standard frontmatter. The bank
    is only read. Idempotent: each copy records a hash of the bank folder's name
    plus the file's path inside it, and files with a known hash are skipped.
    """
    raw_path = source.get("path")
    if not raw_path:
        return (0, ["missing path"])
    bank = Path(str(raw_path)).expanduser()
    if not bank.is_dir():
        return (0, [f"bank folder not found: {bank}"])

    match = source.get("match") or {}
    guests = [str(g) for g in (match.get("guest") or [])]
    fragments = [str(s).lower() for s in (match.get("filenameContains") or [])]
    if not guests and not fragments:
        return (0, ["no match rules (match.guest / match.filenameContains); skipped so the whole bank isn't copied"])

    seen, seen_videos = _bank_copies(corpus_dir / "fetched" / "transcript-bank")
    new_count = 0
    notes: list[str] = []

    for f in sorted(bank.rglob("*.md")):
        rel = f.relative_to(bank)
        if any(part.startswith(".") for part in rel.parts):
            continue  # .git, .github and the like
        rel_path = rel.as_posix()
        source_hash = hashlib.sha1(f"{bank.name}/{rel_path}".encode("utf-8")).hexdigest()[:12]
        if source_hash in seen:
            continue

        fm, body = _read_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        matched, speaker = _match_bank_file(fm, rel_path, guests, fragments)
        if not matched:
            continue
        seen.add(source_hash)

        # Archives sometimes hold the same episode twice (Lenny's mirror has
        # andy-raskin/ and andy-raskin_/ with one video_id); copy it once.
        video_id = fm.get("video_id") or fm.get("videoId")
        if video_id and str(video_id) in seen_videos:
            notes.append(f"skip duplicate of video {video_id}: {rel_path}")
            continue
        if video_id:
            seen_videos.add(str(video_id))

        if dry_run:
            notes.append(f"[DRY] would copy: {rel_path}")
            new_count += 1
            continue

        title = str(fm.get("title") or (f.parent.name if f.stem == "transcript" else f.stem))
        extra: dict[str, Any] = {
            "speaker": speaker,
            "bank": source.get("name") or bank.name,
            "sourcePath": rel_path,
            "sourceHash": source_hash,
        }
        if video_id:
            extra["videoId"] = str(video_id)

        write_item(
            corpus_dir,
            "transcript-bank",
            date=_as_datetime(fm.get("publish_date") or fm.get("publishedAt") or fm.get("date")),
            title=title,
            source_url=fm.get("sourceUrl") or fm.get("youtube_url") or fm.get("url"),
            body=body,
            extra_frontmatter=extra,
            slug_suffix=source_hash[:8],
        )
        new_count += 1

    return (new_count, notes)


HANDLERS = {
    "substack": handle_feed,
    "rss": handle_feed,
    "youtube_videos": handle_youtube_videos,
    "youtube_channel": handle_youtube_channel,
    "linkedin_manual": handle_linkedin_manual,
    "whisper_folder": handle_whisper_folder,
    "transcript_bank": handle_transcript_bank,
}

# Groups for --source / --skip-source. Raw source types are accepted too.
SOURCE_GROUPS = {
    "substack": "feeds",
    "rss": "feeds",
    "youtube_videos": "youtube",
    "youtube_channel": "youtube",
    "youtube_discovery": "youtube",
    "linkedin_manual": "linkedin",
    "whisper_folder": "whisper",
    "transcript_bank": "transcript_bank",
}
SOURCE_CHOICES = sorted(set(SOURCE_GROUPS) | set(SOURCE_GROUPS.values()))


def source_selected(stype: str, only: list[str] | None = None, skip: list[str] | None = None) -> bool:
    names = {stype, SOURCE_GROUPS.get(stype, stype)}
    if only and not names & set(only):
        return False
    if skip and names & set(skip):
        return False
    return True


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

def refresh_expert(
    slug: str,
    dry_run: bool = False,
    force: bool = False,
    discover: bool = False,
    only_sources: list[str] | None = None,
    skip_sources: list[str] | None = None,
) -> dict:
    corpus_dir = CORPUS_ROOT / slug
    config_path = corpus_dir / "sources.yml"

    if not config_path.exists():
        return {"slug": slug, "error": f"no sources.yml at {config_path}"}

    config = yaml.safe_load(config_path.read_text())
    sources = config.get("sources") or []
    filtered = bool(only_sources or skip_sources)

    totals = {"new_items": 0, "handlers_run": 0, "handlers_skipped": 0, "handlers_filtered": 0}
    report: list[str] = []

    # --- Optional discovery step: finds candidate YouTube videos, may mutate
    # the videoIds list of a sibling youtube_videos source.
    if discover and source_selected("youtube_discovery", only_sources, skip_sources):
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

        if not source_selected(stype, only_sources, skip_sources):
            totals["handlers_filtered"] += 1
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
            verb = "would fetch" if dry_run else "fetched"
            report.append(f"{prefix} {verb} {new_count} item(s)")
        for n in notes:
            report.append(f"  {prefix} {n}")

    if not dry_run:
        if not filtered:  # a partial run isn't a full refresh
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
    parser.add_argument("--source", action="append", choices=SOURCE_CHOICES, metavar="NAME",
                        help="Only run these sources (repeatable). Groups: feeds, youtube, linkedin, whisper; raw types also work.")
    parser.add_argument("--skip-source", action="append", choices=SOURCE_CHOICES, metavar="NAME",
                        help="Skip these sources (repeatable). The weekly sweep skips youtube.")
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
        result = refresh_expert(slug, dry_run=args.dry_run, force=args.force, discover=args.discover,
                                only_sources=args.source, skip_sources=args.skip_source)
        if result.get("error"):
            print(f"ERROR: {result['error']}")
            exit_code = 1
            continue
        for line in result["report"]:
            print(line)
        totals = result["totals"]
        filtered = f", {totals['handlers_filtered']} filtered out" if totals["handlers_filtered"] else ""
        print(f"Summary: {totals['new_items']} new item(s), "
              f"{totals['handlers_run']} handler(s) run, "
              f"{totals['handlers_skipped']} disabled{filtered}.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
