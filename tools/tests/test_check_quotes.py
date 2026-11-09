"""check_quotes.py: every voice-sample quote must appear word for word in the corpus.

Made-up profiles and corpus only; real corpus content stays out of the repo.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))

import check_quotes as cq  # noqa: E402

PROFILE = """---
name: "Alpha Expert"
---

## How you sound

> "the map is not the territory, mostly" — *Made-up Podcast* (01/02/2025)

> "We’re hungry for proof, real proof" — Made-up Talk, 2024

> "a line nobody ever said" — Made-up Book

Not a quote: > "inline" — ignored because the line doesn't start with >.
"""

TRANSCRIPT = """---
title: "the map is not the territory, mostly"
source: "youtube"
---

and I always say the Map is not
the territory mostly okay so
we're hungry for proof real proof you know
"""


def make(tmp_path: Path, profile: str = PROFILE, transcript: str | None = TRANSCRIPT) -> tuple[Path, Path]:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "alpha-expert.md").write_text(profile, encoding="utf-8")
    corpus = tmp_path / "corpus"
    if transcript is not None:
        d = corpus / "alpha-expert" / "fetched" / "youtube"
        d.mkdir(parents=True)
        (d / "2025-02-01-made-up.md").write_text(transcript, encoding="utf-8")
    else:
        corpus.mkdir()
    return profiles, corpus


def test_parses_voice_sample_lines_only(tmp_path):
    profiles, _ = make(tmp_path)
    quotes = cq.profile_quotes(profiles / "alpha-expert.md")
    assert [q.quote for q in quotes] == [
        "the map is not the territory, mostly",
        "We’re hungry for proof, real proof",
        "a line nobody ever said",
    ]
    assert quotes[0].source == "*Made-up Podcast* (01/02/2025)"


def test_ignores_case_punctuation_line_breaks_and_curly_apostrophes(tmp_path):
    profiles, corpus = make(tmp_path)
    quotes, why = cq.check_expert("alpha-expert", profiles, corpus)
    assert why is None
    assert quotes[0].found_in == "fetched/youtube/2025-02-01-made-up.md"
    assert quotes[1].found_in is not None


def test_a_quote_not_in_the_corpus_is_missing(tmp_path):
    profiles, corpus = make(tmp_path)
    quotes, _ = cq.check_expert("alpha-expert", profiles, corpus)
    assert quotes[2].found_in is None


def test_frontmatter_does_not_count_as_corpus(tmp_path):
    transcript = '---\ntitle: "a line nobody ever said"\n---\n\nsomething else entirely\n'
    profiles, corpus = make(tmp_path, transcript=transcript)
    quotes, _ = cq.check_expert("alpha-expert", profiles, corpus)
    assert quotes[2].found_in is None


def test_words_must_match_exactly(tmp_path):
    profile = '> "the map is the territory" — Made-up\n'
    profiles, corpus = make(tmp_path, profile=profile)
    quotes, _ = cq.check_expert("alpha-expert", profiles, corpus)
    assert quotes[0].found_in is None


def test_no_corpus_folder_is_reported_not_crashed(tmp_path):
    profiles, corpus = make(tmp_path, transcript=None)
    quotes, why = cq.check_expert("alpha-expert", profiles, corpus)
    assert quotes == [] and "no corpus folder" in why


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOLS_DIR / "check_quotes.py"), *args], capture_output=True, text=True)


def test_cli_exits_1_when_a_quote_is_missing(tmp_path):
    profiles, corpus = make(tmp_path)
    r = run_cli("--profiles", str(profiles), "--corpus", str(corpus))
    assert r.returncode == 1
    assert "alpha-expert: 2 of 3 quotes found" in r.stdout
    assert "MISSING" in r.stdout and "a line nobody ever said" in r.stdout


def test_cli_exits_0_when_every_quote_is_found(tmp_path):
    profile = '> "the map is not the territory, mostly" — Made-up Podcast\n'
    profiles, corpus = make(tmp_path, profile=profile)
    r = run_cli("--profiles", str(profiles), "--corpus", str(corpus))
    assert r.returncode == 0, r.stdout
    assert "1 of 1 quotes found" in r.stdout


def test_cli_named_expert_without_corpus_fails(tmp_path):
    profiles, corpus = make(tmp_path, transcript=None)
    r = run_cli("alpha-expert", "--profiles", str(profiles), "--corpus", str(corpus))
    assert r.returncode == 1
    assert "can't check" in r.stdout


def test_cli_default_skips_profiles_without_corpus(tmp_path):
    profiles, corpus = make(tmp_path, transcript=None)
    r = run_cli("--profiles", str(profiles), "--corpus", str(corpus))
    assert r.returncode == 0
    assert "No quotes checked." in r.stdout
