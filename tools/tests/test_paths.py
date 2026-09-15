"""Path resolution for the corpus tools.

Covers the two ways the tools find the corpus: SYNTHETIC_EXPERTS_CORPUS, and the
default of corpus/ next to tools/, including through a symlinked tools/ (the
AI-Lab layout on the Mac, which the weekly Cowork sweep depends on).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
FIXTURE_CORPUS = TOOLS_DIR / "tests" / "fixtures" / "corpus"
FIXTURE_EXPERTS = ["alpha-expert", "beta-expert"]


def run(args: list[str], corpus: str | None = None, home: Path | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "SYNTHETIC_EXPERTS_CORPUS"}
    if corpus is not None:
        env["SYNTHETIC_EXPERTS_CORPUS"] = corpus
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, env=env)


def ai_lab_layout(tmp_path: Path) -> Path:
    """Mimic AI-Lab: <root>/tools is a symlink to this repo's tools/, <root>/corpus is real."""
    root = tmp_path / "ai-lab-synthetic-experts"
    (root / "corpus" / "gamma-expert").mkdir(parents=True)
    (root / "corpus" / "gamma-expert" / "sources.yml").write_text("expert: gamma-expert\nsources: []\n")
    (root / "tools").symlink_to(TOOLS_DIR, target_is_directory=True)
    return root


def test_env_var_sets_corpus_root():
    r = run([str(TOOLS_DIR / "refresh_corpus.py"), "--list"], corpus=str(FIXTURE_CORPUS))
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == FIXTURE_EXPERTS


def test_env_var_expands_tilde(tmp_path):
    (tmp_path / "my-corpus" / "delta-expert").mkdir(parents=True)
    (tmp_path / "my-corpus" / "delta-expert" / "sources.yml").write_text("expert: delta-expert\nsources: []\n")
    r = run([str(TOOLS_DIR / "refresh_corpus.py"), "--list"], corpus="~/my-corpus", home=tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["delta-expert"]


def test_dry_run_on_fixture_has_nothing_pending():
    r = run([str(TOOLS_DIR / "refresh_corpus.py"), "--all", "--dry-run"], corpus=str(FIXTURE_CORPUS))
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("Summary: 0 new item(s)") == len(FIXTURE_EXPERTS)


def test_router_uses_env_corpus():
    code = f"import sys; sys.path.insert(0, {str(TOOLS_DIR)!r}); import route_linkedin_posts as r; print(r.INBOX)"
    r = run(["-c", code], corpus=str(FIXTURE_CORPUS))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(FIXTURE_CORPUS / "_inbox" / "linkedin")


def test_default_corpus_follows_invoked_path_through_symlink(tmp_path):
    root = ai_lab_layout(tmp_path)
    r = run([str(root / "tools" / "refresh_corpus.py"), "--list"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["gamma-expert"]


def test_sweep_imports_stay_on_symlink_side(tmp_path):
    root = ai_lab_layout(tmp_path)
    r = run([str(root / "tools" / "sweep_linkedin.py"), "--dry-run", "--skip-refresh"])
    assert r.returncode == 0, r.stderr
    # With an empty inbox the sweep prints where it looked; that must be AI-Lab's corpus.
    assert str(root / "corpus" / "_inbox" / "linkedin") in r.stdout
