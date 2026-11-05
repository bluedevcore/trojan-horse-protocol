"""Repo-wide rules from CLAUDE.md that are cheap to enforce automatically."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
APP_DIRS = ["core", "tools", "clients"]
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".csv", ".json", ".txt", ".toml", ".eml", ".html"}


def _app_files():
    for d in APP_DIRS:
        for path in (ROOT / d).rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and "__pycache__" not in path.parts:
                yield path


def test_banned_word_never_appears_in_the_apps():
    banned = "tro" + "jan"  # split so this file does not trip its own check
    hits = [str(p.relative_to(ROOT)) for p in _app_files() if banned in p.read_text(errors="ignore").lower()]
    assert not hits, f"Remove the banned word from: {hits}"


def _clients():
    return sorted(p for p in (ROOT / "clients").iterdir() if p.is_dir() and (p / "app.py").exists())


def test_every_client_has_the_required_files_and_headline():
    for client in _clients():
        for name in ("app.py", "config.yaml", "DEMO_SCRIPT.md", "PITCH_MESSAGE.md", "NEXT_STEPS.md"):
            assert (client / name).exists(), f"{client.name} is missing {name}"
        assert any((client / "sample_data").iterdir()), f"{client.name} has no sample data"
        cfg = yaml.safe_load((client / "config.yaml").read_text())
        assert re.fullmatch(r".+: built as a prototype for .+", cfg["headline"]), cfg["headline"]


def test_pitch_messages_are_short_and_go_alongside_a_cv():
    for client in _clients():
        text = (client / "PITCH_MESSAGE.md").read_text()
        body = text.split("\n", 1)[1]  # skip the markdown title line
        assert len(body.split()) < 170, f"{client.name}: pitch too long"  # message itself must be < 150 words
        assert "alongside my cv" in text.lower(), f"{client.name}: say 'Alongside my CV'"
        assert "instead of a cv" not in text.lower(), f"{client.name}: do not say 'instead of a CV'"
