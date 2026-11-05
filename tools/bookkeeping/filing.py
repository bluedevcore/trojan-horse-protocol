"""Filing: decide which project folder each document belongs in and give it
a consistent file name. Deterministic: uses the project reference Claude
read from the document (checked against the project register), a reference
pattern in the text, or keyword matches. Anything unclear is left unfiled
for a person to choose."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from tools.bookkeeping.checks import Finding

CATEGORY_FOLDERS = {
    "invoice": "Invoices", "credit_note": "Invoices", "receipt": "Receipts", "statement": "Statements",
    "remittance": "Payments", "purchase_order": "Orders", "contract": "Contracts", "correspondence": "Correspondence",
    "timesheet": "Timesheets", "other": "Other",
}


def _safe(text: str, limit: int = 40) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-")[:limit] or "document"


def file_documents(docs: list[dict], texts: dict[str, str], projects: pd.DataFrame, *,
                   ref_pattern: str | None = None, unfiled_folder: str = "_To file",
                   noun: str = "project") -> tuple[pd.DataFrame, list[Finding]]:
    """Returns (filing index, findings for documents that could not be placed).

    ``noun`` is the client's word for a project (config ``filing.noun``, e.g.
    "property"); it is used in the finding text and the index column names."""
    findings: list[Finding] = []
    proj = projects.copy() if projects is not None else pd.DataFrame(columns=["project_ref", "project_name"])
    for col in ("client", "site", "keywords"):
        if col not in proj:
            proj[col] = ""
    refs = {str(r).strip().upper(): rec for r, rec in zip(proj["project_ref"], proj.to_dict("records"))}
    rows = []
    for d in docs:
        text = texts.get(d["doc_id"], "")
        chosen, how = None, ""
        claimed = str(d.get("project_reference") or "").strip().upper()
        if claimed in refs:
            chosen, how = refs[claimed], "reference on the document"
        if chosen is None and ref_pattern:
            found = {m.upper() for m in re.findall(ref_pattern, text, flags=re.I)} & set(refs)
            if len(found) == 1:
                chosen, how = refs[found.pop()], "reference found in the text"
        if chosen is None:
            hits = []
            for rec in proj.to_dict("records"):
                words = [w.strip() for w in re.split(r"[;,|]", f"{rec.get('site', '')};{rec.get('keywords', '')}") if len(w.strip()) >= 5]
                if any(w.lower() in text.lower() for w in words):
                    hits.append(rec)
            if len(hits) == 1:
                chosen, how = hits[0], "site / keyword match"
        category = CATEGORY_FOLDERS.get(d["doc_type"], "Other")
        date = d.get("document_date")
        stem = "_".join(x for x in [f"{date:%Y-%m-%d}" if date is not None else "undated", category[:-1] if category.endswith("s") else category,
                                    _safe(d.get("counterparty") or "unknown"), _safe(d.get("document_number"), 20) if d.get("document_number") else ""] if x)
        suffix = Path(d["file"]).suffix.lower()
        if chosen is None:
            folder = f"{unfiled_folder}"
            findings.append(Finding("unfiled_document", subject=d.get("counterparty") or d["file"], reference=d["file"],
                                    date=date, source=d["file"], doc_ids=[d["doc_id"]],
                                    finding=f"No {noun} reference, site or keyword in “{d['file']}” matches the {noun} register"
                                            + (f" (the document mentions “{d['project_reference']}”)." if d.get("project_reference") else ".")))
        else:
            folder = f"{_safe(chosen['project_ref'], 20)} {chosen.get('project_name', '')}".strip() + f"/{category}"
        rows.append({"Doc": d["doc_id"], "Original file": d["file"], "Type": d["doc_type"].replace("_", " ").capitalize(),
                     "From / to": d.get("counterparty", ""), "Date": date,
                     noun.capitalize(): chosen["project_ref"] if chosen is not None else "",
                     f"{noun.capitalize()} name": chosen.get("project_name", "") if chosen is not None else "",
                     "Filed by": how or "needs a person", "Folder": folder, "New file name": stem + suffix,
                     "Summary": d.get("summary", "")})
    return pd.DataFrame(rows), findings


def filing_zip(index: pd.DataFrame, originals: dict[str, bytes]) -> bytes:
    """A zip of the documents in their project folders, plus the index as CSV."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in index.to_dict("records"):
            data = originals.get(r["Original file"])
            if data is not None:
                zf.writestr(f"{r['Folder']}/{r['New file name']}", data)
        zf.writestr("filing-index.csv", index.to_csv(index=False))
    return buffer.getvalue()
