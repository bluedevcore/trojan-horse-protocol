"""Claude steps for the bookkeeping tool. Claude only reads documents,
classifies and writes text; every figure it is shown has been read from a
document or worked out by deterministic code first.

Four tasks (each has a deterministic template for mock mode / fallback):

    bookkeeping.extract   one request per document: fields as JSON
    bookkeeping.coding    batches of entries: account from the chart (enum)
    bookkeeping.letters   batches of emails (supplier queries, receipt requests,
                          payroll queries, customer chase letters)
    bookkeeping.summary   the 20-second manager summary

Stable ids inside each prompt (file name, entry id, letter key) let
refresh_fixtures.py re-key curated responses after a prompt change.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import numpy as np
import pandas as pd

from core.claude import ClaudeClient, ClaudeResult
from tools.bookkeeping.documents import DOC_TYPES, DocText, pattern_extract

EXTRACT_TASK = "bookkeeping.extract"
CODING_TASK = "bookkeeping.coding"
LETTERS_TASK = "bookkeeping.letters"
SUMMARY_TASK = "bookkeeping.summary"
MAX_WORKERS = 16

_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


EXTRACT_SCHEMA = _obj({
    "doc_type": {"type": "string", "enum": DOC_TYPES},
    "counterparty": {"type": "string"},
    "counterparty_vat_number": {"type": "string"},
    "document_number": {"type": "string"},
    "document_date": {"type": "string"},
    "due_date": {"type": "string"},
    "po_number": {"type": "string"},
    "project_reference": {"type": "string"},
    "currency": {"type": "string"},
    "net_total": _NUM,
    "vat_total": _NUM,
    "gross_total": _NUM,
    "vat_lines": {"type": "array", "items": _obj({"rate": {"type": "number"}, "net": {"type": "number"},
                                                  "vat": {"type": "number"}})},
    "line_items": {"type": "array", "items": _obj({"description": {"type": "string"}, "quantity": _NUM,
                                                   "unit_price": _NUM, "net": _NUM, "vat_rate": _NUM})},
    "payment_status": {"type": "string", "enum": ["paid", "unpaid", "unknown"]},
    "card_last4": {"type": "string"},
    "bank_sort_code": {"type": "string"},
    "bank_account_number": {"type": "string"},
    "service_period_start": {"type": "string"},
    "service_period_end": {"type": "string"},
    "statement_lines": {"type": "array", "items": _obj({"date": {"type": "string"}, "reference": {"type": "string"},
                                                        "description": {"type": "string"}, "amount": {"type": "number"}})},
    "summary": {"type": "string"},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    "uncertain_fields": {"type": "array", "items": {"type": "string"}},
    "notes": {"type": "string"},
})

EXTRACT_SYSTEM = """You read UK business documents for a bookkeeper and return their key fields as JSON.

The business: {company}. {domain}
{projects}
Rules:
- Copy values exactly as printed. Do not calculate, correct or fill in anything: if a printed total looks wrong, return the printed total. Code checks the arithmetic afterwards.
- Dates as YYYY-MM-DD (UK documents are day-first). Use "" for a date that is not shown.
- Amounts as plain numbers without currency symbols; null when not shown. Credit notes: give positive amounts (doc_type says it is a credit).
- net_total is the total before VAT, including any other tax that is part of the cost (such as Insurance Premium Tax); gross_total is the total payable.
- counterparty is the other business (the supplier on a purchase invoice or receipt, the customer on a sales invoice, the sender of a letter), never {company}.
- vat_lines: one entry per VAT rate in the document's VAT summary (rate in percent). If only one VAT amount is shown, give one line.
- line_items: the item lines as printed (at most 30).
- payment_status: "paid" for receipts and documents marked paid; "unpaid" for invoices awaiting payment; otherwise "unknown". card_last4 only if the last four digits of the paying card are shown.
- bank_sort_code / bank_account_number: the bank details printed for payment, if any.
- service_period_start / service_period_end: only if the document states the period it covers (an annual policy, a subscription).
- statement_lines: only for supplier statements, one per invoice, credit or payment listed.
- summary: one plain sentence saying what the document is and what it is for.
- confidence: how sure you are of the key fields. List doubtful field names in uncertain_fields. Use notes for anything a bookkeeper should know (a handwritten note, a change of bank details mentioned in an email, a foreign currency, a reminder that says it is a copy).
Never invent values."""

CODING_SYSTEM = """You assign bookkeeping entries to nominal accounts for a UK business.

The business: {company}. {domain}

Chart of accounts (choose only from these):
{chart}

For each entry give:
- account: exactly one account name from the chart.
- confidence: "high" if the evidence clearly fits, "medium" if likely, "low" if the purpose is unclear or the items are mixed, so a person must decide.
- reason: one short sentence quoting the evidence (merchant, items bought, any note).
Use only the facts given. Return one code per entry id."""

CODING_SCHEMA_BASE = {"id": {"type": "string"}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                      "reason": {"type": "string"}}

LETTERS_SYSTEM = """You draft short emails for the accounts team at {company}. {domain}

Each request gives the recipient and the points to raise. Every point has already been checked by code.
For each request write:
- subject: specific, under 80 characters, quoting the main reference.
- body: "Hello <first name>," (or "Hello," if no contact name), then one or two short paragraphs that cover every point with the references, dates and amounts exactly as given, a clear request, and when a reply is needed ({reply_by}). End with "Kind regards," and then "{signature}" on its own line.
Tone: supplier and payroll queries are friendly and precise; requests to colleagues for receipts are brief and friendly; customer letters follow the tone given for that customer.
If a point is about changed bank details, say we will phone them on the number we already hold to confirm, and that we never change bank details from an email; do not ask for bank details by email.
Do not mention legal action unless the tone is a final notice. Never invent facts, names, dates or amounts. Plain text, no markdown."""

LETTERS_SCHEMA = {"type": "object", "properties": {"letters": {"type": "array", "items": _obj(
    {"key": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}})}},
    "required": ["letters"], "additionalProperties": False}

SUMMARY_SYSTEM = """You write the summary at the top of a bookkeeping run for a busy finance manager who will read it in about 20 seconds.

The business: {company}. {domain}

Write 3 or 4 short sentences, at most 90 words, in plain UK English:
1. What was processed and how much is ready to post.
2. The most important problems, naming the supplier, person or customer.
3. What needs a decision or a reply before month end.
Use only the facts given and quote figures as given. No markdown, no bullet points, no greeting."""


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else round(float(value), 2)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%d %b %Y")
    if value is pd.NaT or (value is not None and not isinstance(value, (str, bool, int)) and pd.isna(value)):
        return None
    return value


def _context(config: dict) -> dict:
    ai_cfg = config.get("ai") or {}
    company = (config.get("company") or {}).get("name", "the business")
    return {"company": company, "domain": str(ai_cfg.get("domain", "")).strip(),
            "signature": ai_cfg.get("signature", "Accounts team"), "reply_by": ai_cfg.get("reply_by", "within five working days")}

# --------------------------------------------------------------- extraction


def extract_prompt(doc: DocText) -> str:
    return f"File name: {doc.name}\nFile type: {doc.kind}\n\n--- DOCUMENT TEXT ---\n{doc.text}"


def extract_documents(client: ClaudeClient, docs: list[DocText], config: dict, *, projects: list[dict] | None = None,
                      on_done: Callable[[int, int], None] | None = None) -> list[tuple[dict, ClaudeResult]]:
    ctx = _context(config)
    proj = ""
    if projects:
        proj = ("Known projects (use the exact project_reference if the document clearly relates to one, else \"\"):\n"
                + "\n".join(f"- {p.get('project_ref')}: {p.get('project_name', '')}"
                            + (f" ({p['site']})" if p.get("site") else "") for p in projects) + "\n")
    system = EXTRACT_SYSTEM.format(company=ctx["company"], domain=ctx["domain"], projects=proj)

    def one(doc: DocText) -> tuple[dict, ClaudeResult]:
        result = client.complete(task=EXTRACT_TASK, system=system, prompt=extract_prompt(doc), json_schema=EXTRACT_SCHEMA,
                                 max_tokens=6000, mock_response=lambda: pattern_extract(doc))
        data = result.data if isinstance(result.data, dict) and result.data.get("doc_type") else pattern_extract(doc)
        return data, result

    return _parallel(one, docs, on_done)

# ------------------------------------------------------------------- coding


def coding_schema(account_names: list[str]) -> dict:
    item = _obj({"id": CODING_SCHEMA_BASE["id"], "account": {"type": "string", "enum": account_names},
                 "confidence": CODING_SCHEMA_BASE["confidence"], "reason": CODING_SCHEMA_BASE["reason"]})
    return {"type": "object", "properties": {"codes": {"type": "array", "items": item}},
            "required": ["codes"], "additionalProperties": False}


def template_code(item: dict, fallback: str) -> dict:
    return {"id": item["id"], "account": fallback, "confidence": "low",
            "reason": "No AI suggestion available (mock mode): needs coding by hand."}


def code_entries(client: ClaudeClient, items: list[dict], chart_for_prompt: list[dict], account_names: list[str],
                 config: dict, *, fallback: str, batch_size: int = 12) -> tuple[dict[str, dict], list[ClaudeResult]]:
    if not items:
        return {}, []
    ctx = _context(config)
    system = CODING_SYSTEM.format(company=ctx["company"], domain=ctx["domain"],
                                  chart=json.dumps(chart_for_prompt, ensure_ascii=False, indent=1))
    schema = coding_schema(account_names)
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

    def one(batch):
        prompt = "Entries to code (JSON):\n\n" + json.dumps(jsonable(batch), ensure_ascii=False, indent=1)
        result = client.complete(task=CODING_TASK, system=system, prompt=prompt, json_schema=schema, max_tokens=4000,
                                 mock_response=lambda: {"codes": [template_code(i, fallback) for i in batch]})
        return batch, result

    codes, results = {}, []
    for batch, result in _parallel(one, batches):
        results.append(result)
        returned = {c.get("id"): c for c in (result.data or {}).get("codes", []) if isinstance(c, dict)}
        for item in batch:
            c = returned.get(item["id"])
            if not c or c.get("account") not in account_names:
                c = template_code(item, fallback)
                c["source"] = "template"
            else:
                c["source"] = result.source
            codes[item["id"]] = c
    return codes, results

# ------------------------------------------------------------------ letters


def template_letter(req: dict, ctx: dict) -> dict:
    first = (req.get("contact") or "").split(" ")[0] if req.get("contact") else ""
    greet = f"Hello {first}," if first else "Hello,"
    rtype = req["recipient_type"]
    points = req["points"]
    refs = ", ".join(p["ref"] for p in points if p.get("ref"))
    if rtype == "cardholder":
        subject = f"Receipts needed for {len(points)} card payment{'s' if len(points) != 1 else ''}"
        intro = "Could you send me the receipts for these company card payments, please?"
    elif rtype == "customer" and req.get("tone"):
        subject = f"{req.get('tone_label') or 'Payment reminder'}: {refs}"[:80]
        intro = f"Our records show the following {'is' if len(points) == 1 else 'are'} now overdue."
    elif rtype == "payroll_bureau":
        subject = f"Payroll query: {refs}"[:80]
        intro = "We have a query on this month's payroll report before wages are paid."
    else:
        subject = f"Query on {refs}"[:80] if refs else "Accounts query"
        intro = "We have a query on the following before we can process it."
    lines = [f"- {p['ref'] + ': ' if p.get('ref') else ''}{p['ask'] or p['issue']}" for p in points]
    body = (f"{greet}\n\n{intro}\n\n" + "\n".join(lines)
            + f"\n\nI'd be grateful for a reply {ctx['reply_by']}.\n\nKind regards,\n{ctx['signature']}")
    return {"key": req["key"], "subject": subject, "body": body}


def draft_letters(client: ClaudeClient, requests: list[dict], config: dict, *, batch_size: int = 3
                  ) -> tuple[dict[str, dict], list[ClaudeResult]]:
    if not requests:
        return {}, []
    ctx = _context(config)
    system = LETTERS_SYSTEM.format(**ctx)
    batches = [requests[i:i + batch_size] for i in range(0, len(requests), batch_size)]

    def one(batch):
        prompt = "Emails to draft (JSON):\n\n" + json.dumps(jsonable(batch), ensure_ascii=False, indent=1)
        result = client.complete(task=LETTERS_TASK, system=system, prompt=prompt, json_schema=LETTERS_SCHEMA,
                                 max_tokens=6000,
                                 mock_response=lambda: {"letters": [template_letter(r, ctx) for r in batch]})
        return batch, result

    letters, results = {}, []
    for batch, result in _parallel(one, batches):
        results.append(result)
        returned = {x.get("key"): x for x in (result.data or {}).get("letters", []) if isinstance(x, dict)}
        for req in batch:
            x = returned.get(req["key"])
            if not x or not str(x.get("body", "")).strip():
                x = template_letter(req, ctx)
                x["source"] = "template"
            else:
                x["source"] = result.source
            letters[req["key"]] = x
    return letters, results

# ------------------------------------------------------------------ summary


def _n(count: int, word: str, plural: str = "") -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def template_summary(facts: dict) -> str:
    docs, ready = facts.get("documents", 0), facts.get("entries_ready", 0)
    parts = [f"{_n(docs, 'document')} {'was' if docs == 1 else 'were'} read and {_n(ready, 'entry', 'entries')} "
             f"(£{facts.get('value_ready', 0):,.2f}) {'is' if ready == 1 else 'are'} ready to import."]
    if facts.get("high_severity"):
        top = facts["high_severity"][:2]
        parts.append("Main problems: " + "; ".join(f"{h['check']} ({h['who']})" for h in top) + ".")
    exc, checks, emails = facts.get("exceptions", 0), facts.get("needs_human_check", 0), facts.get("emails", 0)
    parts.append(f"{_n(exc, 'exception')} {'was' if exc == 1 else 'were'} found; {checks} need{'s' if checks == 1 else ''} a "
                 f"decision and {_n(emails, 'email')} {'is' if emails == 1 else 'are'} drafted for checking before month end.")
    return " ".join(parts)


def write_summary(client: ClaudeClient, facts: dict, config: dict) -> ClaudeResult:
    ctx = _context(config)
    system = SUMMARY_SYSTEM.format(company=ctx["company"], domain=ctx["domain"])
    prompt = "Facts for the summary (JSON):\n\n" + json.dumps(jsonable(facts), ensure_ascii=False, indent=1)
    return client.complete(task=SUMMARY_TASK, system=system, prompt=prompt, max_tokens=2000,
                           mock_response=lambda: template_summary(facts))

# ------------------------------------------------------------------ helpers


def _parallel(fn, items: list, on_done: Callable[[int, int], None] | None = None) -> list:
    """Run ``fn`` over items in parallel, returning results in input order."""
    if not items:
        return []
    results: list = [None] * len(items)
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(items))) as pool:
        futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
        done = 0
        for fut in _as_completed(futures):
            results[futures[fut]] = fut.result()
            done += 1
            if on_done:
                on_done(done, len(items))
    return results


def _as_completed(futures):
    from concurrent.futures import as_completed

    return as_completed(futures)


def prompt_ids(task: str, prompt: str) -> list[str]:
    """Stable ids inside a prompt (used by refresh_fixtures)."""
    if task == EXTRACT_TASK:
        m = re.match(r"File name: (.+)", prompt)
        return [m.group(1).strip()] if m else []
    if task in (CODING_TASK, LETTERS_TASK):
        payload = json.loads(prompt.split("\n\n", 1)[1])
        return [p["id" if task == CODING_TASK else "key"] for p in payload]
    return ["summary"]
