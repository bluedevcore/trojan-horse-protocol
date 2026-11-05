"""Build a client's mock-mode fixtures from curated text, keyed by stable ids.

Fixture files are keyed by a hash of the exact request, so any change to a
prompt, the config or the sample data orphans them. This script keeps the
human-written responses in one editable file, ``fixtures/curated.json``:

    {
      "extract": {"<document file name>": {<fields as Claude would return them>}},
      "coding":  {"<entry id, e.g. T-05 or D-12>": {"payee": "...", "account": "...",
                                                    "confidence": "high", "reason": "..."}},
      "letters": {"<key, e.g. supplier:Acme Ltd>": {"subject": "...", "body": "..."}},
      "summary": "<manager summary>"
    }

and re-runs the sample data in mock mode, answering every Claude request from
that file and writing fresh hashed fixtures:

    python -m tools.bookkeeping.refresh_fixtures clients/<slug>           # rebuild fixtures
    python -m tools.bookkeeping.refresh_fixtures clients/<slug> --seed    # also add template
                                                                          # text for anything missing

``--seed`` writes the deterministic template answer (pattern reader, fallback
coding, template letter/summary) into curated.json for every id it has no
text for, marked ``"_todo": true``. Edit those entries into realistic text
that uses only facts in the request (the prompts are in the fixture files),
remove the ``_todo`` marks and run the script again. Extraction entries only
need the fields that are not empty; the rest are filled with empty values.
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
from tools.bookkeeping import ai, pipeline  # noqa: E402
from tools.bookkeeping.views import load_config  # noqa: E402

SECTIONS = {ai.EXTRACT_TASK: "extract", ai.CODING_TASK: "coding", ai.LETTERS_TASK: "letters"}


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if not str(k).startswith("_")}


def complete_extraction(fields: dict) -> dict:
    """Fill any schema field the curated entry leaves out with an empty value."""
    out = {}
    for name, spec in ai.EXTRACT_SCHEMA["properties"].items():
        if name in fields:
            out[name] = fields[name]
        elif spec.get("type") == "array":
            out[name] = []
        elif "anyOf" in spec:
            out[name] = None
        elif name == "confidence":
            out[name] = "high"
        elif name == "payment_status":
            out[name] = "unknown"
        elif name == "currency":
            out[name] = "GBP"
        else:
            out[name] = ""
    return out


class CuratedClient(ClaudeClient):
    """Mock client that answers from curated.json and records fixtures."""

    def __init__(self, curated: dict, **kwargs):
        super().__init__(mock=True, record_fixtures=True, **kwargs)
        self.curated = curated
        self.missing: dict[str, list[str]] = {}
        self.seeded: dict[str, dict] = {"extract": {}, "coding": {}, "letters": {}}
        self.used: dict[str, set] = {"extract": set(), "coding": set(), "letters": set()}

    def complete(self, *, task, system, prompt, json_schema=None, max_tokens=8000, mock_response=None):
        template = mock_response() if mock_response else None
        answer = template
        if task == ai.EXTRACT_TASK:
            name = ai.prompt_ids(task, prompt)[0]
            fields = (self.curated.get("extract") or {}).get(name)
            if fields:
                answer = complete_extraction(_clean(fields))
                self.used["extract"].add(name)
            else:
                self.missing.setdefault("extract", []).append(name)
                self.seeded["extract"][name] = {**template, "_todo": True}
        elif task == ai.CODING_TASK:
            items = json.loads(prompt.split("\n\n", 1)[1])
            by_id = {c["id"]: c for c in template["codes"]}
            known = self.curated.get("coding") or {}
            by_payee = {str(v.get("payee", "")).lower(): (k, v) for k, v in known.items()}
            codes = []
            for item in items:
                entry, key = known.get(item["id"]), item["id"]
                if entry and str(entry.get("payee", "")).lower() not in ("", str(item.get("payee", "")).lower()):
                    entry = None  # ids moved: fall back to the payee
                if entry is None and str(item.get("payee", "")).lower() in by_payee:
                    key, entry = by_payee[str(item["payee"]).lower()]
                if entry:
                    self.used["coding"].add(key)
                    codes.append({"id": item["id"], "account": entry["account"], "confidence": entry["confidence"],
                                  "reason": entry["reason"]})
                else:
                    self.missing.setdefault("coding", []).append(item["id"])
                    self.seeded["coding"][item["id"]] = {"payee": item.get("payee", ""), **{k: v for k, v in by_id[item["id"]].items() if k != "id"}, "_todo": True}
                    codes.append(by_id[item["id"]])
            answer = {"codes": codes}
        elif task == ai.LETTERS_TASK:
            reqs = json.loads(prompt.split("\n\n", 1)[1])
            by_key = {x["key"]: x for x in template["letters"]}
            known = self.curated.get("letters") or {}
            out = []
            for req in reqs:
                entry = known.get(req["key"])
                if entry:
                    self.used["letters"].add(req["key"])
                    out.append({"key": req["key"], "subject": entry["subject"], "body": entry["body"]})
                else:
                    self.missing.setdefault("letters", []).append(req["key"])
                    self.seeded["letters"][req["key"]] = {**{k: v for k, v in by_key[req["key"]].items() if k != "key"}, "_todo": True}
                    out.append(by_key[req["key"]])
            answer = {"letters": out}
        elif task == ai.SUMMARY_TASK:
            if self.curated.get("summary"):
                answer = self.curated["summary"]
            else:
                self.missing.setdefault("summary", []).append("summary")
                self.seeded["summary"] = template
        return super().complete(task=task, system=system, prompt=prompt, json_schema=json_schema,
                                max_tokens=max_tokens, mock_response=lambda: answer)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("client_dir", type=Path)
    parser.add_argument("--seed", action="store_true", help="write template text into curated.json for missing ids")
    args = parser.parse_args()

    client_dir = args.client_dir.resolve()
    fixtures = client_dir / "fixtures"
    curated_path = fixtures / "curated.json"
    curated = json.loads(curated_path.read_text(encoding="utf-8")) if curated_path.exists() else {}

    staging = client_dir / "fixtures.new"
    shutil.rmtree(staging, ignore_errors=True)
    config = load_config(client_dir)
    client = CuratedClient(curated, fixtures_dir=staging, cache_dir=staging / ".cache")
    result = pipeline.run(pipeline.sample_inputs(client_dir, config), config, client)
    shutil.rmtree(staging / ".cache", ignore_errors=True)
    for path in staging.rglob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["recorded_from"], record["model"] = "refresh_fixtures (fixtures/curated.json)", None
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fixtures.mkdir(exist_ok=True)
    for task in SECTIONS | {ai.SUMMARY_TASK: "summary"}:
        shutil.rmtree(fixtures / task, ignore_errors=True)
        if (staging / task).exists():
            (staging / task).rename(fixtures / task)
    shutil.rmtree(staging, ignore_errors=True)

    if args.seed and any(client.seeded[s] for s in ("extract", "coding", "letters")) or (args.seed and "summary" in client.seeded):
        for section in ("extract", "coding", "letters"):
            curated.setdefault(section, {}).update(client.seeded[section])
        if "summary" in client.seeded:
            curated["summary"] = client.seeded["summary"]
        curated_path.write_text(json.dumps(curated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Seeded template text into {curated_path} (entries marked _todo). Edit them, then run again.")

    n = sum(1 for _ in fixtures.rglob("*.json")) - int(curated_path.exists())
    print(f"Wrote {n} fixture files ({len(result.documents)} documents, {len(result.exceptions)} exceptions, "
          f"{len(result.letters)} emails).")
    for section, ids in client.missing.items():
        print(f"No curated {section} for: {', '.join(ids)} - template text was recorded"
              + ("" if args.seed else " (run with --seed to add editable entries)."))
    for section in ("extract", "coding", "letters"):
        stale = set((curated.get(section) or {})) - client.used[section] - set(client.seeded[section])
        if stale:
            print(f"Unused curated {section} entries (no longer requested): {', '.join(sorted(stale))}")
    todo = [f"{s}:{k}" for s in ("extract", "coding", "letters") for k, v in (curated.get(s) or {}).items()
            if isinstance(v, dict) and v.get("_todo")]
    if todo:
        print(f"{len(todo)} curated entries still marked _todo.")
    print("The summary must only use facts in its request: check it against fixtures/bookkeeping.summary/*.json.")


if __name__ == "__main__":
    main()
