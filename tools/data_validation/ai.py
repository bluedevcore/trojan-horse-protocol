"""Claude steps for the data-validation tool: discrepancy notes and a short
manager summary. Claude only writes text here; every number it sees has
already been computed and checked by the deterministic engine.

Each step also has a deterministic template used in mock mode (when no
recorded fixture matches) and as a fallback if the API is unavailable.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import numpy as np
import pandas as pd

from core.claude import ClaudeClient, ClaudeResult

NOTES_TASK = "data_validation.notes"
SUMMARY_TASK = "data_validation.summary"

NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "note": {"type": "string"},
                    "likely_cause": {"type": "string"},
                    "suggested_action": {"type": "string"},
                },
                "required": ["id", "note", "likely_cause", "suggested_action"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["notes"],
    "additionalProperties": False,
}

NOTES_SYSTEM = """You draft discrepancy notes for a data validation report.

Data: {domain}
Readers: {audience}.

You receive exceptions that code has already detected and verified. For each one write:
- note: 2-3 sentences in plain UK English. Say what was found, with the key figures and dates from the input, and why it matters for the reports this data feeds.
- likely_cause: the most plausible explanation or two, phrased as possibilities ("Possibly...", "Most likely..."), never as established fact. If several exceptions concern the same meter or overlapping dates, point out the link and name the related exception IDs.
- suggested_action: one concrete next step for the administrator, in the imperative.

Rules:
- Use only the facts in the input. Do not invent readings, dates, people, suppliers or events.
- Do not recalculate or round differently; quote numbers as given.
- Never present a corrected value as certain. Any correction must be confirmed by a person before it is used.
- No markdown, no headings, no bullet characters.
Return exactly one note per exception ID."""

SUMMARY_SYSTEM = """You write the summary at the top of a data validation report for a busy manager who will read it in about 20 seconds.

Data: {domain}
Readers: {audience}.

Write 3 or 4 short sentences, at most 90 words, in plain UK English:
1. Overall data health: how much was checked and how much passed.
2. The issues that put the nearest reporting deadlines at risk, naming the deadline.
3. What needs a human decision before the reports go out.

Use only the facts given and quote figures as given. No markdown, no bullet points, no headings, no greeting."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items() if k != "exception_id"}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else round(float(value), 1)
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%d %b %Y")
    if value is pd.NaT or (not isinstance(value, (str, bool, int)) and value is not None and pd.isna(value)):
        return None
    return value

# ------------------------------------------------------------------- payloads


def exception_payloads(exceptions: pd.DataFrame, findings: list, key_label: str, display_headings: list[str]) -> list[dict]:
    by_id = {f.context.get("exception_id"): f for f in findings}
    out = []
    for _, row in exceptions.iterrows():
        f = by_id[row["ID"]]
        item = {
            "id": row["ID"],
            "check": row["Check"],
            "severity": row["Severity"],
            "record": row[key_label],
            **{h.lower().replace(" ", "_"): row[h] for h in display_headings if h in row and row[h] not in ("", None)},
            "dates": row["Date(s)"],
            "finding": row["Finding"],
            "value": row["Value"],
            "expected": row["Expected"],
            "needs_human_check": row["Needs human check"] == "Yes",
            "held_from_totals": row["Held from totals"] == "Yes",
            "context": _jsonable(f.context),
        }
        out.append(item)
    return out


def chunk_by_record(payloads: list[dict], size: int) -> list[list[dict]]:
    """Batches of about ``size`` exceptions, keeping one record's exceptions together
    so Claude can see links between them."""
    groups: dict[str, list[dict]] = {}
    for p in payloads:
        groups.setdefault(str(p["record"]), []).append(p)
    chunks, current = [], []
    for items in groups.values():
        if current and len(current) + len(items) > size:
            chunks.append(current)
            current = []
        current += items
    if current:
        chunks.append(current)
    return chunks

# ------------------------------------------------------------------ templates


def template_note(p: dict) -> dict:
    """Deterministic note used in mock mode / when the API is unavailable."""
    ctx = p.get("context", {}) or {}
    rec = p["record"]
    where = f" at {p['site']}" if p.get("site") and not str(p.get("site")).startswith("?") else ""
    finding = p["finding"]
    check = p["check"].lower()
    cause, action = "Needs investigation.", "Check the source data and confirm the correct value with the site."
    rule = p.get("check", "")
    if "duplicate" in check:
        if ctx.get("identical"):
            cause, action = "The same row was exported or imported twice.", "No action needed; one copy has been kept. Check the export settings if this recurs."
        else:
            cause, action = "Possibly the reading was loaded twice, once with a corrected or doubled value.", "Confirm which value is correct with the data provider before the day is included in totals."
    elif "spike" in check:
        cause = "Possibly a genuine one-off load, a data-logger error, or readings from several days combined into one."
        action = "Ask the site whether anything unusual happened that day; keep the value out of totals until confirmed."
    elif "gap" in check or "missing days" in check:
        cause = "Possibly a communications outage on the meter or data logger."
        action = "Request the missing reads from the data provider" + (
            "; the register advance across the gap can be used to apportion consumption if they cannot be recovered." if ctx.get("register_advance_across_gap") else ".")
    elif "missing" in check:
        cause = "Possibly a failed read or a blank cell in the export."
        action = "Request a re-read or confirm whether the value can be derived from the register reads."
    elif "impossible" in check or "range" in check:
        cause = "Possibly a keying or decimal-place error, a meter exchange, or a register reset."
        action = "Check the meter's register reads and any meter exchange record, then correct the source data."
    elif "not in" in check or "reference" in rule.lower():
        cause = "Possibly a typo in the identifier, or an entry missing from the reference list."
        action = "Confirm the correct identifier and update either the export or the reference list."
    elif "register" in check or "mismatch" in check:
        cause = "The daily figure and the register advance disagree; one of them is likely mis-keyed."
        action = "Compare against the register reads and correct whichever figure is wrong."
    elif "zero" in check or "flat" in check:
        cause = "Possibly an inverter or meter fault, or the system was switched off."
        action = "Contact the site to check the equipment and confirm when it was restored."
    elif "unreadable" in check:
        cause = "The value cannot be read as entered; possibly a typing error."
        action = "Correct the value in the source file and re-run the check."
    note = f"{rec}{where}: {finding}"
    if p.get("held_from_totals"):
        note += " The value is held out of the validated totals until it is checked."
    return {"id": p["id"], "note": note, "likely_cause": cause, "suggested_action": action}


def template_summary(facts: dict) -> str:
    parts = [f"{facts['readings_checked']:,} readings from {facts['records']} {facts['record_noun']}s were checked for "
             f"{facts['period']}; {facts['pass_rate_pct']}% passed every check."]
    if facts.get("deadlines_at_risk"):
        d = facts["deadlines_at_risk"][0]
        parts.append(f"The {d['obligation']} (due {d['due']}) is at risk: {d['readiness'][:1].lower() + d['readiness'][1:]}.")
    parts.append(f"{facts['exceptions']} exceptions were found, {facts['needs_human_check']} of which need a human decision "
                 f"before the reports go out.")
    return " ".join(parts)

# ---------------------------------------------------------------------- calls


def draft_notes_and_summary(
    client: ClaudeClient,
    payloads: list[dict],
    facts: dict,
    *,
    domain: str,
    audience: str,
    chunk_size: int = 6,
    on_batch_done: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, dict], str, list[ClaudeResult]]:
    """Run the note batches and the summary in parallel.

    Returns (notes by exception id, summary text, all call results).
    """
    notes_system = NOTES_SYSTEM.format(domain=domain.strip(), audience=audience.strip())
    summary_system = SUMMARY_SYSTEM.format(domain=domain.strip(), audience=audience.strip())
    chunks = chunk_by_record(payloads, chunk_size)

    def notes_call(chunk: list[dict]) -> tuple[list[dict], ClaudeResult]:
        prompt = ("Write discrepancy notes for these exceptions (JSON):\n\n"
                  + json.dumps(chunk, ensure_ascii=False, indent=1))
        result = client.complete(task=NOTES_TASK, system=notes_system, prompt=prompt, json_schema=NOTES_SCHEMA,
                                 max_tokens=8000, mock_response=lambda: {"notes": [template_note(p) for p in chunk]})
        return chunk, result

    def summary_call() -> ClaudeResult:
        prompt = "Facts for the summary (JSON):\n\n" + json.dumps(_jsonable(facts), ensure_ascii=False, indent=1)
        return client.complete(task=SUMMARY_TASK, system=summary_system, prompt=prompt, max_tokens=4000,
                               mock_response=lambda: template_summary(facts))

    notes: dict[str, dict] = {}
    results: list[ClaudeResult] = []
    summary_result: ClaudeResult | None = None
    with ThreadPoolExecutor(max_workers=min(8, len(chunks) + 1)) as pool:
        summary_future = pool.submit(summary_call)
        futures = [pool.submit(notes_call, c) for c in chunks]
        done = 0
        for fut in as_completed(futures):
            chunk, result = fut.result()
            results.append(result)
            returned = {n.get("id"): n for n in (result.data or {}).get("notes", []) if isinstance(n, dict)}
            for p in chunk:
                n = returned.get(p["id"])
                if not n or not str(n.get("note", "")).strip():
                    n = template_note(p)  # Claude skipped this one: never leave a gap
                    n["source"] = "template"
                else:
                    n["source"] = result.source
                n["warning"] = result.warning
                notes[p["id"]] = n
            done += 1
            if on_batch_done:
                on_batch_done(done, len(chunks))
        summary_result = summary_future.result()
    results.append(summary_result)
    summary = summary_result.text.strip() or template_summary(facts)
    return notes, summary, results
