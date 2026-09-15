"""yt-dlp subtitle pulls and source filters in refresh_corpus.py (issue #3).

Nothing here touches the network: yt-dlp is replaced with a fake subprocess
and the VTT fixture is made up (modelled on YouTube's rolling auto-captions).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))

import refresh_corpus as rc  # noqa: E402

VTT = TOOLS_DIR / "tests" / "fixtures" / "vtt" / "rolling-captions.en.vtt"
EXPECTED_LINES = [
    "welcome back to the show",
    "today we're talking about pricing",
    "pages, and why most read like a menu.",
    "Q&A at the end, <no slides>",
]


# --- VTT parsing -------------------------------------------------------------

def test_rolling_captions_collapse_to_one_copy_of_each_line():
    assert rc.vtt_to_text(VTT.read_text(encoding="utf-8")).splitlines() == EXPECTED_LINES


# --- yt-dlp call -------------------------------------------------------------

def fake_yt_dlp(write_vtt: bool = True, returncode: int = 0, stderr: str = ""):
    seen: dict = {}

    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        if write_vtt:
            out_dir = Path(cmd[cmd.index("-o") + 1]).parent
            (out_dir / f"{cmd[-1]}.en.vtt").write_text(VTT.read_text(encoding="utf-8"), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode, "", stderr)

    return run, seen


def test_fetch_uses_the_agreed_yt_dlp_flags(monkeypatch):
    run, seen = fake_yt_dlp()
    monkeypatch.setattr(rc.subprocess, "run", run)
    text = rc.fetch_youtube_transcript("-VqmFI9vY7w")
    cmd = seen["cmd"]
    assert "--write-auto-subs" in cmd and "--skip-download" in cmd
    assert cmd[cmd.index("--sub-lang") + 1] == "en"
    assert cmd[cmd.index("--sub-format") + 1] == "vtt"
    assert cmd[-2:] == ["--", "-VqmFI9vY7w"]  # IDs can start with a dash
    assert text.splitlines() == EXPECTED_LINES


def test_fetch_raises_when_no_captions(monkeypatch):
    run, _ = fake_yt_dlp(write_vtt=False)
    monkeypatch.setattr(rc.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="no English auto-captions"):
        rc.fetch_youtube_transcript("AbCdEfGhIjK")


def test_fetch_raises_with_yt_dlp_error(monkeypatch):
    run, _ = fake_yt_dlp(write_vtt=False, returncode=1, stderr="ERROR: Sign in to confirm you're not a bot")
    monkeypatch.setattr(rc.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="not a bot"):
        rc.fetch_youtube_transcript("AbCdEfGhIjK")


# --- Handler -----------------------------------------------------------------

def test_handler_keeps_the_existing_frontmatter_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "fetch_youtube_transcript", lambda vid: "hello\nworld")
    monkeypatch.setattr(rc, "YOUTUBE_PAUSE_SECONDS", 0)
    new, notes = rc.handle_youtube_videos({"videoIds": ["AbCdEfGhIjK"]}, tmp_path, dry_run=False)
    assert new == 1, notes
    (written,) = (tmp_path / "fetched" / "youtube").glob("*.md")
    frontmatter = written.read_text(encoding="utf-8").split("---")[1]
    keys = [line.split(":")[0] for line in frontmatter.strip().splitlines()]
    assert keys == ["source", "sourceUrl", "title", "publishedAt", "fetchedAt",
                    "videoId", "transcriptSource", "note"]
    assert rc.fetched_video_ids(tmp_path / "fetched" / "youtube") == {"AbCdEfGhIjK"}


def test_failed_fetch_is_noted_and_skipped(monkeypatch, tmp_path):
    def fail(vid):
        raise RuntimeError("no English auto-captions available")
    monkeypatch.setattr(rc, "fetch_youtube_transcript", fail)
    new, notes = rc.handle_youtube_videos({"videoIds": ["AbCdEfGhIjK"]}, tmp_path, dry_run=False)
    assert new == 0
    assert "no English auto-captions" in notes[0]
    assert not (tmp_path / "fetched" / "youtube").exists()


# --- Source filters ----------------------------------------------------------

@pytest.fixture
def recorded(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    (corpus / "eps").mkdir(parents=True)
    (corpus / "eps" / "sources.yml").write_text(yaml.dump({
        "expert": "eps",
        "lastFullRefresh": None,
        "sources": [
            {"type": "rss", "name": "feed", "enabled": True},
            {"type": "youtube_videos", "name": "talks", "enabled": True},
            {"type": "linkedin_manual", "name": "posts", "enabled": True},
        ],
    }))
    monkeypatch.setattr(rc, "CORPUS_ROOT", corpus)
    calls: list[str] = []

    def recorder(source, corpus_dir, dry_run, **kwargs):
        calls.append(source["type"])
        return (0, [])

    for stype in ("rss", "youtube_videos", "linkedin_manual"):
        monkeypatch.setitem(rc.HANDLERS, stype, recorder)
    return calls, corpus / "eps" / "sources.yml"


def test_no_filter_runs_everything(recorded):
    calls, _ = recorded
    rc.refresh_expert("eps", dry_run=True)
    assert calls == ["rss", "youtube_videos", "linkedin_manual"]


def test_skip_youtube_group(recorded):
    calls, _ = recorded
    result = rc.refresh_expert("eps", dry_run=True, skip_sources=["youtube"])
    assert calls == ["rss", "linkedin_manual"]
    assert result["totals"]["handlers_filtered"] == 1


def test_only_youtube_group(recorded):
    calls, _ = recorded
    rc.refresh_expert("eps", dry_run=True, only_sources=["youtube"])
    assert calls == ["youtube_videos"]


def test_raw_source_type_works_as_a_filter(recorded):
    calls, _ = recorded
    rc.refresh_expert("eps", dry_run=True, only_sources=["rss"])
    assert calls == ["rss"]


def test_partial_run_leaves_last_full_refresh_alone(recorded):
    _, sources_yml = recorded
    rc.refresh_expert("eps", dry_run=False, skip_sources=["youtube"])
    assert yaml.safe_load(sources_yml.read_text())["lastFullRefresh"] is None
    rc.refresh_expert("eps", dry_run=False)
    assert yaml.safe_load(sources_yml.read_text())["lastFullRefresh"] is not None


# --- Weekly sweep ------------------------------------------------------------

def test_weekly_sweep_skips_youtube(tmp_path):
    """End to end in an AI-Lab-shaped layout: a pending YouTube video must not count."""
    root = tmp_path / "ai-lab-synthetic-experts"
    (root / "tools").parent.mkdir(parents=True)
    (root / "tools").symlink_to(TOOLS_DIR, target_is_directory=True)
    (root / "profiles").mkdir()
    (root / "profiles" / "eps.md").write_text("---\nname: Eps Expert\nslug: eps\n---\nProfile.\n")
    (root / "corpus" / "eps").mkdir(parents=True)
    (root / "corpus" / "eps" / "sources.yml").write_text(
        "expert: eps\nsources:\n  - type: youtube_videos\n    name: talks\n    enabled: true\n"
        "    videoIds: [\"AbCdEfGhIjK\"]\n"
    )
    inbox = root / "corpus" / "_inbox" / "linkedin"
    inbox.mkdir(parents=True)
    (inbox / "2026-09-01-someone-else.md").write_text("---\nauthor: \"Someone Else\"\n---\nA post.\n")

    env = {k: v for k, v in os.environ.items() if k != "SYNTHETIC_EXPERTS_CORPUS"}
    r = subprocess.run([sys.executable, str(root / "tools" / "sweep_linkedin.py"), "--dry-run"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "[eps] up to date" in r.stdout
    assert "--source youtube" in r.stdout
