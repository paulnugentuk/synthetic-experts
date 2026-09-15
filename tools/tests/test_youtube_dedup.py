"""YouTube dedup in refresh_corpus.py (issue #2).

Dedup reads the videoId frontmatter field. Filenames can't be trusted:
slugify() lowercases them and drops the __<id> marker, and YouTube IDs are
case-sensitive. No test here touches the network.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))

import refresh_corpus as rc  # noqa: E402

FIXTURES = TOOLS_DIR / "tests" / "fixtures" / "youtube"


def corpus_with(tmp_path: Path, fixture: str) -> Path:
    corpus_dir = tmp_path / "expert"
    shutil.copytree(FIXTURES / fixture, corpus_dir / "fetched" / "youtube")
    return corpus_dir


class FakeApi:
    calls: list[str] = []

    def fetch(self, vid):
        FakeApi.calls.append(vid)
        return [SimpleNamespace(text=f"transcript for {vid}")]


class NoNetworkApi:
    def fetch(self, vid):
        raise AssertionError(f"dry-run made a network call for {vid}")


@pytest.fixture
def fake_api(monkeypatch):
    import youtube_transcript_api
    FakeApi.calls = []
    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApi)
    return FakeApi


@pytest.fixture
def no_network(monkeypatch):
    import youtube_transcript_api
    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", NoNetworkApi)


# Fixture 1: same title, different IDs (the IDs differ only in case, which the
# old filename slug would have collapsed into one).

def test_same_title_different_ids_are_both_recognised(tmp_path):
    corpus_dir = corpus_with(tmp_path, "same-title-different-ids")
    assert rc.fetched_video_ids(corpus_dir / "fetched" / "youtube") == {"AbCdEfGhIjK", "abcdefghijk"}


def test_same_title_different_ids_only_new_id_is_pending(tmp_path, no_network):
    corpus_dir = corpus_with(tmp_path, "same-title-different-ids")
    source = {"videoIds": ["AbCdEfGhIjK", "abcdefghijk", "ZZZZZZZZZZZ"]}
    new, notes = rc.handle_youtube_videos(source, corpus_dir, dry_run=True)
    assert new == 1
    assert notes == ["[DRY] would fetch: https://www.youtube.com/watch?v=ZZZZZZZZZZZ"]


# Fixture 2: same ID, different title (the duplicate state the real corpus is in
# after the 25/05 re-fetch).

def test_same_id_different_title_counts_once_and_is_not_refetched(tmp_path, fake_api):
    corpus_dir = corpus_with(tmp_path, "same-id-different-title")
    yt = corpus_dir / "fetched" / "youtube"
    assert rc.fetched_video_ids(yt) == {"Q1w2E3r4T5y"}
    new, _ = rc.handle_youtube_videos({"videoIds": ["Q1w2E3r4T5y"]}, corpus_dir, dry_run=False)
    assert new == 0
    assert fake_api.calls == []
    assert len(list(yt.glob("*.md"))) == 2


def test_fetch_is_idempotent(tmp_path, fake_api):
    corpus_dir = corpus_with(tmp_path, "same-id-different-title")
    source = {"videoIds": ["Q1w2E3r4T5y", "NewVideo123"]}
    first, _ = rc.handle_youtube_videos(source, corpus_dir, dry_run=False)
    second, _ = rc.handle_youtube_videos(source, corpus_dir, dry_run=False)
    assert (first, second) == (1, 0)
    assert fake_api.calls == ["NewVideo123"]
    assert "NewVideo123" in rc.fetched_video_ids(corpus_dir / "fetched" / "youtube")


def test_same_id_listed_twice_is_fetched_once(tmp_path, fake_api):
    new, _ = rc.handle_youtube_videos({"videoIds": ["DupDupDup12", "DupDupDup12"]}, tmp_path / "expert", dry_run=False)
    assert new == 1
    assert fake_api.calls == ["DupDupDup12"]


def test_files_without_frontmatter_are_ignored(tmp_path):
    yt = tmp_path / "fetched" / "youtube"
    yt.mkdir(parents=True)
    (yt / "stray.md").write_text("videoId: \"NotFrontMat\"\nno frontmatter fence here\n")
    assert rc.fetched_video_ids(yt) == set()
