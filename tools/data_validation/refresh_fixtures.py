"""Re-key a client's mock-mode fixtures after a prompt or data change.

Fixture files are keyed by a hash of the exact request, so any change to the
prompts, rules or sample data orphans them (the sample run then falls back to
template text, and ``tests/test_nfu_pipeline.py`` fails to remind you).

This script re-runs the sample data in mock mode and writes fresh fixture
files, re-using the existing hand-written/recorded notes **by exception ID**
and the existing summary text:

    python -m tools.data_validation.refresh_fixtures clients/nfu-energy [--notes notes.json]

``--notes`` optionally supplies replacement notes as
``{"EX-01": {"note": ..., "likely_cause": ..., "suggested_action": ...}, "summary": "..."}``.
Exception IDs are stable as long as the sample data and rules produce the
same exceptions. Check the output: a changed exception list needs new notes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.claude import ClaudeClient  # noqa: E402
from tools.data_validation import ai, pipeline  # noqa: E402
from tools.data_validation.views import load_config  # noqa: E402


def existing_texts(fixtures: Path) -> tuple[dict[str, dict], str | None]:
    notes, summary = {}, None
    for path in sorted(fixtures.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        response = record.get("response", {})
        if record.get("task") == ai.NOTES_TASK:
            for n in (response.get("data") or {}).get("notes", []):
                notes[n["id"]] = n
        elif record.get("task") == ai.SUMMARY_TASK:
            summary = response.get("text")
    return notes, summary


class _ReplayClient(ClaudeClient):
    """Mock client that answers from known texts and records new fixtures."""

    def __init__(self, notes: dict[str, dict], summary: str | None, **kwargs):
        super().__init__(mock=True, record_fixtures=True, **kwargs)
        self.known_notes, self.known_summary, self.missing = notes, summary, []

    def complete(self, *, task, system, prompt, json_schema=None, max_tokens=8000, mock_response=None):
        if task == ai.NOTES_TASK:
            ids = [item["id"] for item in json.loads(prompt.split("\n\n", 1)[1])]
            fallback = mock_response() if mock_response else {"notes": []}
            by_id = {n["id"]: n for n in fallback["notes"]}
            out = []
            for i in ids:
                if i in self.known_notes:
                    out.append({k: self.known_notes[i][k] for k in ("id", "note", "likely_cause", "suggested_action")})
                else:
                    self.missing.append(i)
                    out.append(by_id[i])
            data = {"notes": out}
            return super().complete(task=task, system=system, prompt=prompt, json_schema=json_schema,
                                    max_tokens=max_tokens, mock_response=lambda: data)
        if task == ai.SUMMARY_TASK and self.known_summary:
            text = self.known_summary
            return super().complete(task=task, system=system, prompt=prompt, json_schema=json_schema,
                                    max_tokens=max_tokens, mock_response=lambda: text)
        return super().complete(task=task, system=system, prompt=prompt, json_schema=json_schema,
                                max_tokens=max_tokens, mock_response=mock_response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("client_dir", type=Path)
    parser.add_argument("--notes", type=Path, help="JSON file of replacement notes keyed by exception ID")
    args = parser.parse_args()

    client_dir = args.client_dir.resolve()
    fixtures = client_dir / "fixtures"
    notes, summary = existing_texts(fixtures) if fixtures.exists() else ({}, None)
    if args.notes:
        extra = json.loads(args.notes.read_text(encoding="utf-8"))
        summary = extra.pop("summary", summary)
        for i, n in extra.items():
            notes[i] = {"id": i, **n}

    staging = client_dir / "fixtures.new"
    shutil.rmtree(staging, ignore_errors=True)
    config = load_config(client_dir)
    client = _ReplayClient(notes, summary, fixtures_dir=staging, cache_dir=staging / ".cache")
    result = pipeline.run(pipeline.sample_inputs(client_dir, config), config, client)
    shutil.rmtree(staging / ".cache", ignore_errors=True)
    for path in staging.rglob("*.json"):  # say where the text came from
        record = json.loads(path.read_text(encoding="utf-8"))
        record["recorded_from"], record["model"] = "refresh_fixtures (curated or previously recorded text)", None
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(fixtures, ignore_errors=True)
    staging.rename(fixtures)

    print(f"Wrote {sum(1 for _ in fixtures.rglob('*.json'))} fixture files for {len(result.exceptions)} exceptions.")
    if client.missing:
        print("No existing note for:", ", ".join(client.missing), "- template text was recorded; edit those files.")
    if not summary:
        print("No existing summary - template text was recorded; edit the summary fixture.")


if __name__ == "__main__":
    main()
