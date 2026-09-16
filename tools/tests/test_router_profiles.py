"""route_linkedin_posts.py registers experts from published profiles.

The profiles in this repo carry no `slug` field (the AI-Lab drafts do), so the
router falls back to the filename. Without that, a run from this repo finds no
experts and stops.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))

import route_linkedin_posts as router  # noqa: E402


def test_slug_falls_back_to_the_profile_filename(tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "elena-verna.md").write_text('---\nname: "Elena Verna"\n---\nProfile.\n')
    (profiles / "april-dunford.md").write_text('---\nname: "April Dunford"\nslug: "april-dunford"\n---\nProfile.\n')
    monkeypatch.setattr(router, "PROFILES_DIR", profiles)
    monkeypatch.setattr(router, "CORPUS_ROOT", tmp_path / "corpus")
    assert sorted(e["slug"] for e in router.build_expert_registry()) == ["april-dunford", "elena-verna"]


def test_every_published_profile_registers(monkeypatch):
    repo_profiles = TOOLS_DIR.parent / "profiles"
    monkeypatch.setattr(router, "PROFILES_DIR", repo_profiles)
    registry = router.build_expert_registry()
    assert len(registry) == len(list(repo_profiles.glob("*.md"))) > 0
