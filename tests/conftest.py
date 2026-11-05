import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """Tests never hit the network and never share a cache."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEMO_RECORD_FIXTURES", raising=False)
    monkeypatch.setenv("DEMO_MOCK", "1")
    for name in ("CLAUDE_MODEL", "DEMO_CLAUDE_EFFORT", "CLAUDE_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CACHE_DIR", str(tmp_path / "claude-cache"))
