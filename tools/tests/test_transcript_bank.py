"""transcript_bank handler in refresh_corpus.py (issue #4).

The fixture bank holds three made-up transcripts laid out like Lenny's
community mirror (episodes/<slug>/transcript.md). Two match the Verna rules:
ep-001 on its guest field, elena-verna-40 on its folder name. jane-doe doesn't.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))

import refresh_corpus as rc  # noqa: E402

BANK = TOOLS_DIR / "tests" / "fixtures" / "transcript-bank" / "lennys-sample"
VERNA_RULES = {"guest": ["Elena Verna"], "filenameContains": ["elena-verna"]}


def source(path: Path | str = BANK, match: dict | None = None) -> dict:
    return {
        "type": "transcript_bank",
        "name": "Lenny's sample",
        "path": str(path),
        "match": VERNA_RULES if match is None else match,
        "enabled": True,
    }


def snapshot(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def copied(corpus_dir: Path) -> dict[str, dict]:
    out = {}
    for p in (corpus_dir / "fetched" / "transcript-bank").glob("*.md"):
        fm, body = rc._read_frontmatter(p.read_text(encoding="utf-8"))
        out[fm["sourcePath"]] = {**fm, "_body": body, "_file": p.name}
    return out


def test_two_of_three_match_and_a_second_run_changes_nothing(tmp_path):
    before = snapshot(BANK)
    first, _ = rc.handle_transcript_bank(source(), tmp_path, dry_run=False)
    files_after_first = sorted(p.name for p in (tmp_path / "fetched" / "transcript-bank").iterdir())
    second, _ = rc.handle_transcript_bank(source(), tmp_path, dry_run=False)
    files_after_second = sorted(p.name for p in (tmp_path / "fetched" / "transcript-bank").iterdir())

    assert (first, second) == (2, 0)
    assert files_after_first == files_after_second
    assert len(files_after_first) == 2
    assert snapshot(BANK) == before  # the bank is only read


def test_matched_files_and_their_frontmatter(tmp_path):
    rc.handle_transcript_bank(source(), tmp_path, dry_run=False)
    items = copied(tmp_path)
    assert set(items) == {"episodes/ep-001/transcript.md", "episodes/elena-verna-40/transcript.md"}

    by_guest = items["episodes/ep-001/transcript.md"]
    assert by_guest["source"] == "transcript-bank"
    assert by_guest["sourceUrl"] == "https://www.youtube.com/watch?v=AbCdEfGhIjK"
    assert by_guest["title"] == "A made-up episode about activation | Elena Verna"
    assert by_guest["publishedAt"].startswith("2023-04-23")
    assert by_guest["fetchedAt"]
    assert by_guest["speaker"] == "Elena Verna"
    assert by_guest["videoId"] == "AbCdEfGhIjK"
    assert "guest:" not in by_guest["_body"]  # original frontmatter isn't repeated in the body

    by_path = items["episodes/elena-verna-40/transcript.md"]
    assert "sourceUrl" not in by_path  # the original has none
    assert by_path["speaker"] == "Elena Verna"
    assert by_path["publishedAt"].startswith("2025-12-01")


def test_dry_run_reports_without_writing(tmp_path):
    new, notes = rc.handle_transcript_bank(source(), tmp_path, dry_run=True)
    assert new == 2
    assert sorted(notes) == [
        "[DRY] would copy: episodes/elena-verna-40/transcript.md",
        "[DRY] would copy: episodes/ep-001/transcript.md",
    ]
    assert not (tmp_path / "fetched").exists()


def test_filename_rule_alone_takes_speaker_from_the_file(tmp_path):
    rc.handle_transcript_bank(source(match={"filenameContains": ["ep-001"]}), tmp_path, dry_run=False)
    (only,) = copied(tmp_path).values()
    assert only["speaker"] == "Elena Verna 2.0"


def test_missing_folder_and_missing_rules_are_reported(tmp_path):
    assert rc.handle_transcript_bank(source(path=tmp_path / "nope"), tmp_path, dry_run=False)[0] == 0
    new, notes = rc.handle_transcript_bank(source(match={}), tmp_path, dry_run=False)
    assert new == 0 and "no match rules" in notes[0]


def test_hidden_folders_are_skipped_and_tilde_expands(tmp_path, monkeypatch):
    bank = tmp_path / "home" / "bank"
    shutil.copytree(BANK, bank)
    (bank / ".git").mkdir()
    (bank / ".git" / "elena-verna-notes.md").write_text("---\nguest: Elena Verna\n---\nNot a transcript.\n")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    new, _ = rc.handle_transcript_bank(source(path="~/bank"), tmp_path / "expert", dry_run=False)
    assert new == 2


def test_same_episode_twice_in_the_bank_is_copied_once(tmp_path):
    bank = tmp_path / "bank"
    shutil.copytree(BANK, bank)
    shutil.copytree(bank / "episodes" / "ep-001", bank / "episodes" / "ep-001_")  # same video_id
    new, notes = rc.handle_transcript_bank(source(path=bank), tmp_path / "expert", dry_run=False)
    assert new == 2
    assert any("skip duplicate of video AbCdEfGhIjK" in n for n in notes)
    again, _ = rc.handle_transcript_bank(source(path=bank), tmp_path / "expert", dry_run=False)
    assert again == 0


def test_refresh_expert_runs_the_bank_and_the_filter_accepts_it(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    (corpus / "elena-verna").mkdir(parents=True)
    (corpus / "elena-verna" / "sources.yml").write_text(yaml.dump({"expert": "elena-verna", "sources": [source()]}))
    monkeypatch.setattr(rc, "CORPUS_ROOT", corpus)
    assert "transcript_bank" in rc.SOURCE_CHOICES
    result = rc.refresh_expert("elena-verna", dry_run=False, only_sources=["transcript_bank"])
    assert result["totals"]["new_items"] == 2
    assert "transcript-bank (2)" in (corpus / "elena-verna" / "index.md").read_text()
