import json
from types import SimpleNamespace

from core import settings
from core.cache import DiskCache, stable_hash
from core.claude import ClaudeClient


class FakeSDK:
    """Stands in for anthropic.Anthropic; records calls."""

    def __init__(self, text="Live answer", stop_reason="end_turn", fail=False):
        self.calls = []
        self.text, self.stop_reason, self.fail = text, stop_reason, fail
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("network down")
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.text)],
            stop_reason=self.stop_reason, model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_stable_hash_ignores_key_order():
    assert stable_hash({"a": 1, "b": [1, 2]}) == stable_hash({"b": [1, 2], "a": 1})
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


def test_disk_cache_roundtrip_and_corrupt_file(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.get("k") is None
    cache.set("k", {"text": "hi"})
    assert cache.get("k") == {"text": "hi"}
    (tmp_path / "bad.json").write_text("{not json")
    assert cache.get("bad") is None


def test_mock_mode_when_no_key(monkeypatch):
    monkeypatch.delenv("DEMO_MOCK", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert settings.is_mock_mode()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert not settings.is_mock_mode()
    monkeypatch.setenv("DEMO_MOCK", "1")
    assert settings.is_mock_mode()


def test_mock_uses_fixture_then_template(tmp_path):
    client = ClaudeClient(fixtures_dir=tmp_path, mock=True)
    # No fixture yet: falls back to the tool's template responder
    res = client.complete(task="t", system="s", prompt="p", mock_response=lambda: "template text")
    assert (res.text, res.source) == ("template text", "mock")
    # Record a fixture for that exact request, then it is preferred
    key = stable_hash({"task": "t", "system": "s", "prompt": "p", "schema": None})
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / f"{key}.json").write_text(json.dumps({"response": {"text": "recorded", "data": None}}))
    res = client.complete(task="t", system="s", prompt="p", mock_response=lambda: "template text")
    assert (res.text, res.source) == ("recorded", "fixture")
    assert res.from_ai


def test_mock_json_template(tmp_path):
    client = ClaudeClient(fixtures_dir=tmp_path, mock=True)
    res = client.complete(task="t", system="s", prompt="p", json_schema={"type": "object"},
                          mock_response=lambda: {"notes": [1, 2]})
    assert res.data == {"notes": [1, 2]}
    assert json.loads(res.text) == {"notes": [1, 2]}


def test_live_call_is_cached(tmp_path):
    sdk = FakeSDK()
    client = ClaudeClient(mock=False, cache_dir=tmp_path, sdk_client=sdk, model="claude-opus-5-5", effort="low")
    first = client.complete(task="t", system="s", prompt="p")
    second = client.complete(task="t", system="s", prompt="p")
    assert first.text == second.text == "Live answer"
    assert (first.source, second.source) == ("api", "cache")
    assert len(sdk.calls) == 1
    sent = sdk.calls[0]
    assert sent["output_config"] == {"effort": "low"}
    assert sent["fallbacks"] == "default" and sent["betas"]
    assert "temperature" not in sent and "thinking" not in sent


def test_live_json_schema_request(tmp_path):
    sdk = FakeSDK(text='{"ok": true}')
    client = ClaudeClient(mock=False, cache_dir=tmp_path, sdk_client=sdk, model="claude-haiku-5-5", effort=None)
    res = client.complete(task="t", system="s", prompt="p", json_schema={"type": "object"})
    assert res.data == {"ok": True}
    assert sdk.calls[0]["output_config"] == {"format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert "fallbacks" not in sdk.calls[0]  # only sent to models that support it


def test_live_failure_falls_back_with_warning(tmp_path):
    client = ClaudeClient(mock=False, cache_dir=tmp_path, sdk_client=FakeSDK(fail=True))
    res = client.complete(task="t", system="s", prompt="p", mock_response=lambda: "template")
    assert res.source == "fallback" and res.text == "template"
    assert "network down" in res.warning
    assert not res.from_ai


def test_refusal_falls_back(tmp_path):
    client = ClaudeClient(mock=False, cache_dir=tmp_path, sdk_client=FakeSDK(stop_reason="refusal"))
    res = client.complete(task="t", system="s", prompt="p", mock_response=lambda: "template")
    assert res.source == "fallback" and res.warning


def test_record_fixtures(tmp_path):
    client = ClaudeClient(fixtures_dir=tmp_path / "fx", mock=True, record_fixtures=True)
    client.complete(task="notes", system="s", prompt="p", mock_response=lambda: "draft")
    files = list((tmp_path / "fx" / "notes").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["response"]["text"] == "draft"
