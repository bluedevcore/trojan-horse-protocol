"""Claude client wrapper used by every tool.

What it adds on top of the ``anthropic`` SDK:

* **Disk cache** keyed by a hash of the request, so demo re-runs are instant
  and cost nothing.
* **Mock mode** (no ``ANTHROPIC_API_KEY``, or ``DEMO_MOCK=1``): no network at
  all. Responses come from fixture files recorded for the sample data, or
  from a deterministic ``mock_response`` callable supplied by the tool.
* **Fixture recording** (``DEMO_RECORD_FIXTURES=1``): every response is also
  written to the fixtures folder so it can be replayed in mock mode.
* **Graceful failure**: an API error or refusal never crashes the demo; the
  tool's ``mock_response`` is used instead and a warning is returned.

Claude is only used for writing and classifying text. All maths, matching and
validation stays in deterministic Python in the tools.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core import REPO_ROOT, settings
from core.cache import DiskCache, stable_hash

# Models that accept the server-side refusal fallback (``fallbacks: "default"``).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

MockResponse = Callable[[], "str | dict | list"]
_UNSET: Any = object()


@dataclass
class ClaudeResult:
    text: str
    data: Any = None  # parsed JSON when a schema was requested
    source: str = "api"  # api | cache | fixture | mock | fallback
    model: str | None = None
    seconds: float = 0.0
    warning: str | None = None
    usage: dict = field(default_factory=dict)

    @property
    def from_ai(self) -> bool:
        """True when the text was written by Claude (live, cached or recorded)."""
        return self.source in ("api", "cache", "fixture")


class ClaudeClient:
    def __init__(
        self,
        *,
        fixtures_dir: str | Path | None = None,
        cache_dir: str | Path | None = None,
        model: str | None = None,
        effort: str | None = _UNSET,
        mock: bool | None = None,
        record_fixtures: bool | None = None,
        sdk_client: Any = None,
    ):
        self.mock = settings.is_mock_mode() if mock is None else mock
        self.model = model or settings.claude_model()
        self.effort = settings.claude_effort() if effort is _UNSET else effort
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else None
        cache_root = cache_dir or settings.get_setting("CLAUDE_CACHE_DIR") or REPO_ROOT / ".cache" / "claude"
        self.cache = DiskCache(cache_root)
        self.record = settings.flag("DEMO_RECORD_FIXTURES") if record_fixtures is None else record_fixtures
        self._sdk = sdk_client
        self.calls: list[ClaudeResult] = []

    # ------------------------------------------------------------------ public
    @property
    def mode_label(self) -> str:
        return "Mock mode" if self.mock else f"Live: {self.model}"

    def complete(
        self,
        *,
        task: str,
        system: str,
        prompt: str,
        json_schema: dict | None = None,
        max_tokens: int = 8000,
        mock_response: MockResponse | None = None,
    ) -> ClaudeResult:
        """Run one Claude request (or its mock/cached equivalent).

        ``task`` names the request type (e.g. ``"data_validation.notes"``) and
        is used to organise fixture files.
        """
        started = time.perf_counter()
        fixture_key = stable_hash({"task": task, "system": system, "prompt": prompt, "schema": json_schema})
        if self.mock:
            result = self._mock(task, fixture_key, mock_response, json_schema is not None)
        else:
            result = self._live(task, system, prompt, json_schema, max_tokens, mock_response)
        result.seconds = round(time.perf_counter() - started, 3)
        if self.record and result.source in ("api", "cache", "mock"):
            self._write_fixture(task, fixture_key, prompt, result)
        self.calls.append(result)
        return result

    # ----------------------------------------------------------------- mocking
    def _fixture_path(self, task: str, key: str) -> Path | None:
        if not self.fixtures_dir:
            return None
        return self.fixtures_dir / task / f"{key}.json"

    def _load_fixture(self, path: Path | None) -> dict | None:
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        except (OSError, KeyError, json.JSONDecodeError):
            return None

    def _mock(self, task: str, key: str, mock_response: MockResponse | None, wants_json: bool) -> ClaudeResult:
        recorded = self._load_fixture(self._fixture_path(task, key))
        if recorded is not None:
            return ClaudeResult(text=recorded.get("text", ""), data=recorded.get("data"), source="fixture", model="fixture")
        if mock_response is not None:
            return _wrap(mock_response(), source="mock", model="mock")
        default = self._load_fixture(self.fixtures_dir / task / "default.json" if self.fixtures_dir else None)
        if default is not None:
            return ClaudeResult(text=default.get("text", ""), data=default.get("data"), source="fixture", model="fixture")
        placeholder = {} if wants_json else "[Mock mode] Claude would write this text when an API key is set."
        return _wrap(placeholder, source="mock", model="mock")

    def _write_fixture(self, task: str, key: str, prompt: str, result: ClaudeResult) -> None:
        path = self._fixture_path(task, key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "task": task,
            "key": key,
            "recorded_from": result.source,
            "model": result.model,
            "prompt": prompt,
            "response": {"text": result.text, "data": result.data},
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # -------------------------------------------------------------------- live
    def _client(self):
        if self._sdk is None:
            import anthropic

            self._sdk = anthropic.Anthropic(api_key=settings.api_key(), timeout=90.0, max_retries=2)
        return self._sdk

    def _live(self, task, system, prompt, json_schema, max_tokens, mock_response) -> ClaudeResult:
        cache_key = stable_hash(
            {"model": self.model, "effort": self.effort, "system": system, "prompt": prompt,
             "schema": json_schema, "max_tokens": max_tokens}
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            return ClaudeResult(text=cached["text"], data=cached.get("data"), source="cache", model=cached.get("model"))

        try:
            response = self._send(system, prompt, json_schema, max_tokens)
        except Exception as exc:  # network, auth, rate limit, bad request...
            return self._fallback(mock_response, json_schema is not None, f"Claude API call failed ({type(exc).__name__}): {exc}")

        if getattr(response, "stop_reason", None) == "refusal":
            return self._fallback(mock_response, json_schema is not None, "Claude declined this request; a template draft was used instead.")

        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text").strip()
        data = None
        if json_schema is not None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return self._fallback(mock_response, True, "Claude returned malformed JSON; a template draft was used instead.")
        if getattr(response, "stop_reason", None) == "max_tokens" and json_schema is None:
            text += " …"

        usage = getattr(response, "usage", None)
        result = ClaudeResult(
            text=text,
            data=data,
            source="api",
            model=getattr(response, "model", self.model),
            usage={"input_tokens": getattr(usage, "input_tokens", None), "output_tokens": getattr(usage, "output_tokens", None)},
        )
        self.cache.set(cache_key, {"text": result.text, "data": result.data, "model": result.model, "task": task})
        return result

    def _send(self, system: str, prompt: str, json_schema: dict | None, max_tokens: int):
        output_config: dict[str, Any] = {}
        if self.effort:
            output_config["effort"] = self.effort
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if output_config:
            kwargs["output_config"] = output_config
        client = self._client()
        if self.model in _FALLBACK_MODELS:
            # If a safety classifier declines, the API re-runs the request on
            # Anthropic's recommended fallback model instead of refusing.
            return client.beta.messages.create(betas=[_FALLBACK_BETA], fallbacks="default", **kwargs)
        return client.messages.create(**kwargs)

    def _fallback(self, mock_response: MockResponse | None, wants_json: bool, warning: str) -> ClaudeResult:
        if mock_response is not None:
            result = _wrap(mock_response(), source="fallback", model="template")
        else:
            result = _wrap({} if wants_json else "", source="fallback", model="template")
        result.warning = warning
        return result


def _wrap(value: Any, *, source: str, model: str) -> ClaudeResult:
    if isinstance(value, str):
        return ClaudeResult(text=value, data=None, source=source, model=model)
    return ClaudeResult(text=json.dumps(value, ensure_ascii=False), data=value, source=source, model=model)
