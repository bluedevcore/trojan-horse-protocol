"""Unstructured documents: get the text out of PDFs, emails and text files,
normalise what Claude (or the pattern reader) extracted, and check the
arithmetic. No AI in this module.

The *pattern reader* is a deterministic, regex-based fallback used in mock
mode for uploaded files and whenever Claude is unavailable. It handles clean,
typed invoices reasonably well and marks everything it reads as low
confidence, so a person checks it.
"""

from __future__ import annotations

import email
import io
import re
from dataclasses import dataclass, field
from email import policy
from pathlib import Path

import pandas as pd

DOC_SUFFIXES = {".pdf", ".eml", ".txt", ".md"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".gif", ".tif", ".tiff"}
DOC_TYPES = ["invoice", "credit_note", "receipt", "statement", "remittance", "purchase_order", "contract",
             "correspondence", "timesheet", "other"]
MAX_TEXT_CHARS = 15000  # per document; a long PDF is cut with a visible marker


class DocumentError(Exception):
    """A document that cannot be read; the message is shown to the user."""


@dataclass
class DocText:
    name: str
    kind: str  # pdf | email | text
    text: str
    subject: str = ""
    sender: str = ""
    attachments: list[str] = field(default_factory=list)
    truncated: bool = False

# ------------------------------------------------------------------- reading


def read_document(name: str, data: bytes) -> DocText:
    suffix = Path(name).suffix.lower()
    if not data:
        raise DocumentError(f"“{name}” is empty.")
    if suffix in IMAGE_SUFFIXES:
        raise DocumentError(f"“{name}” is a photo. This prototype reads PDFs, emails and text files; "
                            "photo receipts would need OCR (see NEXT_STEPS.md).")
    if suffix == ".pdf":
        text = pdf_text(data, name)
        doc = DocText(name, "pdf", text)
    elif suffix == ".eml":
        doc = email_text(data, name)
    elif suffix in (".txt", ".md"):
        doc = DocText(name, "text", _decode(data))
    else:
        raise DocumentError(f"“{name}” is a {suffix or 'file'} file; documents must be PDF, EML or TXT.")
    if not doc.text.strip():
        raise DocumentError(f"“{name}” has no readable text (it may be a scanned image, which needs OCR).")
    if len(doc.text) > MAX_TEXT_CHARS:
        doc.text = doc.text[:MAX_TEXT_CHARS] + "\n[… document continues; only the first part was read]"
        doc.truncated = True
    return doc


def pdf_text(data: bytes, name: str = "document.pdf") -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # pypdf raises many types for broken files
        raise DocumentError(f"“{name}” could not be opened as a PDF ({type(exc).__name__}).") from exc
    return "\n\n".join(p.strip() for p in pages if p.strip())


def email_text(data: bytes, name: str = "message.eml") -> DocText:
    try:
        msg = email.message_from_bytes(data, policy=policy.default)
    except Exception as exc:
        raise DocumentError(f"“{name}” could not be read as an email ({type(exc).__name__}).") from exc
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        body = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            body = _strip_html(body)
    parts = [f"From: {msg.get('From', '')}", f"To: {msg.get('To', '')}", f"Date: {msg.get('Date', '')}",
             f"Subject: {msg.get('Subject', '')}", "", body.strip()]
    attachments = []
    for part in msg.iter_attachments():
        fname = part.get_filename() or "attachment"
        attachments.append(fname)
        payload = part.get_payload(decode=True) or b""
        if fname.lower().endswith(".pdf") or part.get_content_type() == "application/pdf":
            try:
                parts += ["", f"--- Attachment: {fname} ---", pdf_text(payload, fname)]
            except DocumentError:
                parts += ["", f"--- Attachment: {fname} (could not be read) ---"]
        elif part.get_content_maintype() == "text":
            parts += ["", f"--- Attachment: {fname} ---", _decode(payload)]
        else:
            parts += ["", f"--- Attachment: {fname} (not read: {part.get_content_type()}) ---"]
    return DocText(name, "email", "\n".join(parts).strip(), subject=str(msg.get("Subject", "")),
                   sender=str(msg.get("From", "")), attachments=attachments)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _strip_html(html_text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html_text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).replace("&pound;", "£").replace("&amp;", "&").replace("&nbsp;", " ")

# ---------------------------------------------------------- pattern reader

_MONEY = r"(-?£?\s?-?\$?€?\s?[\d,]+\.\d{2})"
_DATE = (r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
         r"\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4})")


def _money(text: str) -> float | None:
    try:
        return float(re.sub(r"[£$€,\s]", "", text))
    except (TypeError, ValueError):
        return None


def _labelled(text: str, labels: str, pattern: str) -> str | None:
    """Value after a label on the same line, or on the next line (PDF tables often split them)."""
    m = re.search(rf"(?im)\b(?:{labels})\b[^\n\d£$€-]{{0,30}}(?:\n[^\n\d£$€-]{{0,5}})?{pattern}", text)
    return m.group(1).strip() if m else None


def _vat_amount(text: str) -> float | None:
    """Sum of 'VAT @ 20% [on £x]  £y' lines; else the first plain 'VAT £y' (ignoring 'inc VAT' totals)."""
    rated = re.findall(r"(?im)\bvat\s*@\s*\d+(?:\.\d+)?%(?:\s+on\s+£?[\d,]+\.\d{2})?[ \t:=]*(?:\n\s*)?" + _MONEY, text)
    if rated:
        return round(sum(_money(v) or 0 for v in rated), 2)
    for m in re.finditer(r"(?im)^(.*?)\b(?:total vat|of which vat|vat)\b[^\n\d£$€-]{0,20}(?:\n\s*)?" + _MONEY, text):
        if not re.search(r"(?i)\b(inc|incl|including)\.?\s*\(?$", m.group(1).strip()):
            return _money(m.group(2))
    return None


def pattern_extract(doc: DocText) -> dict:
    """Best-effort field extraction without AI (mock mode / fallback)."""
    text = doc.text
    low = text.lower()
    if "credit note" in low:
        doc_type = "credit_note"
    elif re.search(r"\b(receipt|thank you for your (order|purchase)|paid with|card ending)\b|card\s*\*{3,}", low):
        doc_type = "receipt"
    elif "statement" in low and "balance" in low:
        doc_type = "statement"
    elif "invoice" in low:
        doc_type = "invoice"
    elif re.search(r"\b(agreement|contract|terms and conditions)\b", low):
        doc_type = "contract"
    elif doc.kind == "email":
        doc_type = "correspondence"
    else:
        doc_type = "other"

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    counterparty = ""
    attached = text.split("--- Attachment:", 1)
    if doc.kind == "email" and len(attached) == 2:  # an invoice attached to an email: the PDF names the supplier
        first = [ln.strip() for ln in attached[1].splitlines()[1:] if ln.strip()]
        counterparty = first[0] if first else ""
    if not counterparty and doc.kind == "email" and doc.sender:
        counterparty = re.sub(r"\s*<.*?>", "", doc.sender).strip().strip('"')
    if not counterparty:
        skip = re.compile(r"(?i)^(from|to|date|subject|invoice|tax invoice|receipt|credit note|statement|page)\b")
        counterparty = next((ln for ln in lines if not skip.match(ln) and re.search(r"[A-Za-z]{3}", ln)), "")
    number = None
    for pattern in (r"(?i)\b(?:invoice|credit note|receipt|order|document|booking)\s*(?:no\.?|number|#|ref(?:erence)?)\s*[:#.]?\s*"
                    r"([A-Z0-9][A-Z0-9\-/]*\d[A-Z0-9\-/]*)",
                    r"(?i)\b(?:invoice|credit note|receipt|order)\s+#?([A-Z]*-?[A-Z0-9\-]*\d[A-Z0-9\-/]*)"):
        m = re.search(pattern, text)
        if m:
            number = m.group(1)
            break
    gross = _money(_labelled(text, "total due|amount due|balance due|grand total|total to pay|total paid|total", _MONEY) or "")
    net = _money(_labelled(text, "subtotal|sub-total|net total|total net|net amount|total excl[a-z. ]*vat|net", _MONEY) or "")
    vat = _vat_amount(text)
    vat_no = re.search(r"(?i)\b(GB\s?\d{3}\s?\d{4}\s?\d{2}(?:\s?\d{3})?)\b", text)
    sort_code = re.search(r"(?i)sort\s*code[^\d]{0,5}(\d{2}[- ]\d{2}[- ]\d{2})", text)
    account = re.search(r"(?i)account\s*(?:no\.?|number)[^\d]{0,5}(\d{8})\b", text)
    card = re.search(r"(?i)(?:card|ending|ending in|x{4}|\*{4})\s*(?:ending\s*(?:in)?)?\s*[:\s]*(\d{4})\b", text)
    po = re.search(r"(?i)\b(?:PO|P\.O\.|purchase order|order ref)\s*(?:no\.?|number|#)?\s*[:#]?\s*([A-Z0-9][\w\-/]*\d[\w\-/]*)", text)
    currency = "GBP"
    if re.search(r"\$\s?\d|\bUSD\b", text):
        currency = "USD"
    elif re.search(r"€\s?\d|\bEUR\b", text):
        currency = "EUR"
    vat_lines = []
    if net is not None and vat is not None and net:
        vat_lines = [{"rate": round(100 * vat / net, 1), "net": net, "vat": vat}]
    out = {
        "doc_type": doc_type,
        "counterparty": counterparty[:80],
        "counterparty_vat_number": vat_no.group(1) if vat_no else "",
        "document_number": number or "",
        "document_date": (_labelled(text, "invoice date|date of issue|tax point|receipt date|order date|date", _DATE)
                          or (re.search(_DATE, text).group(1) if re.search(_DATE, text) else "")),
        "due_date": _labelled(text, "due date|payment due|due by|pay by", _DATE) or "",
        "po_number": po.group(1) if po else "",
        "project_reference": "",
        "currency": currency,
        "net_total": net,
        "vat_total": vat,
        "gross_total": gross,
        "vat_lines": vat_lines,
        "line_items": [],
        "payment_status": "paid" if doc_type == "receipt" or re.search(r"(?i)\bpaid\b", text) else "unknown",
        "card_last4": card.group(1) if card and doc_type == "receipt" else "",
        "bank_sort_code": sort_code.group(1).replace(" ", "-") if sort_code else "",
        "bank_account_number": account.group(1) if account else "",
        "service_period_start": "",
        "service_period_end": "",
        "statement_lines": [],
        "summary": f"{doc_type.replace('_', ' ').capitalize()} read by the pattern reader (no AI).",
        "confidence": "low",
        "uncertain_fields": [],
        "notes": "Read without AI: check every field.",
    }
    out["uncertain_fields"] = [k for k in ("counterparty", "document_number", "document_date", "gross_total")
                               if out[k] in ("", None)]
    return out

# ---------------------------------------------------------- normalisation


def parse_date(value) -> pd.Timestamp | None:
    if value in (None, "") or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.normalize()
    text = str(value).strip()
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):
            ts = pd.to_datetime(text[:10], format="%Y-%m-%d")
        else:
            ts = pd.to_datetime(text, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None
    return None if pd.isna(ts) else ts.normalize()


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    return _money(str(value))


def normalise(raw: dict, doc: DocText, doc_id: str, source: str) -> dict:
    """Turn an extraction (Claude or pattern reader) into a clean record.

    Amounts on credit notes are stored positive; ``doc_type`` carries the sign.
    """
    raw = raw or {}
    doc_type = str(raw.get("doc_type") or "other").strip().lower().replace(" ", "_")
    doc_type = doc_type if doc_type in DOC_TYPES else "other"
    net, vat, gross = (_num(raw.get(k)) for k in ("net_total", "vat_total", "gross_total"))
    if doc_type == "credit_note":
        net, vat, gross = (abs(x) if x is not None else None for x in (net, vat, gross))
    vat_lines = []
    for line in raw.get("vat_lines") or []:
        rate, lnet, lvat = _num(line.get("rate")), _num(line.get("net")), _num(line.get("vat"))
        if lnet is None:
            continue
        lnet = abs(lnet) if doc_type == "credit_note" else lnet
        lvat = (abs(lvat) if doc_type == "credit_note" and lvat is not None else lvat) or 0.0
        if rate is None:
            rate = round(100 * lvat / lnet, 1) if lnet else 0.0
        vat_lines.append({"rate": float(rate), "net": round(lnet, 2), "vat": round(lvat, 2)})
    if not vat_lines and net is not None:
        v = vat or 0.0
        vat_lines = [{"rate": round(100 * v / net, 1) if net else 0.0, "net": round(net, 2), "vat": round(v, 2)}]
    items = []
    for it in raw.get("line_items") or []:
        items.append({"description": str(it.get("description") or "").strip(), "quantity": _num(it.get("quantity")),
                      "unit_price": _num(it.get("unit_price")), "net": _num(it.get("net")),
                      "vat_rate": _num(it.get("vat_rate"))})
    statement = [{"date": parse_date(s.get("date")), "reference": str(s.get("reference") or "").strip(),
                  "description": str(s.get("description") or "").strip(), "amount": _num(s.get("amount"))}
                 for s in raw.get("statement_lines") or []]
    rec = {
        "doc_id": doc_id,
        "file": doc.name,
        "kind": doc.kind,
        "doc_type": doc_type,
        "counterparty": str(raw.get("counterparty") or "").strip(),
        "counterparty_vat_number": re.sub(r"\s", "", str(raw.get("counterparty_vat_number") or "")).upper(),
        "document_number": str(raw.get("document_number") or "").strip(),
        "document_date": parse_date(raw.get("document_date")),
        "due_date": parse_date(raw.get("due_date")),
        "po_number": str(raw.get("po_number") or "").strip(),
        "project_reference": str(raw.get("project_reference") or "").strip(),
        "currency": (str(raw.get("currency") or "GBP").strip().upper() or "GBP")[:3],
        "net_total": net,
        "vat_total": vat,
        "gross_total": gross,
        "vat_lines": vat_lines,
        "line_items": items,
        "payment_status": str(raw.get("payment_status") or "unknown").strip().lower(),
        "card_last4": re.sub(r"\D", "", str(raw.get("card_last4") or ""))[-4:],
        "bank_sort_code": re.sub(r"[^\d]", "", str(raw.get("bank_sort_code") or "")),
        "bank_account_number": re.sub(r"[^\d]", "", str(raw.get("bank_account_number") or "")),
        "service_period_start": parse_date(raw.get("service_period_start")),
        "service_period_end": parse_date(raw.get("service_period_end")),
        "statement_lines": statement,
        "summary": str(raw.get("summary") or "").strip(),
        "confidence": str(raw.get("confidence") or "low").strip().lower(),
        "uncertain_fields": [str(f) for f in raw.get("uncertain_fields") or []],
        "notes": str(raw.get("notes") or "").strip(),
        "extracted_by": source,
        "email_subject": doc.subject,
    }
    return rec

# ---------------------------------------------------------------- checks


def arithmetic_problems(rec: dict, *, allowed_rates=(0.0, 5.0, 20.0)) -> list[tuple[str, str]]:
    """Deterministic arithmetic checks on one document.

    Returns ``(check_id, message)`` pairs; check ids: ``arithmetic``,
    ``vat_rate``, ``missing_fields``.
    """
    out: list[tuple[str, str]] = []
    if rec["doc_type"] not in ("invoice", "credit_note", "receipt"):
        return out
    missing = [label for key, label in (("counterparty", "supplier name"), ("gross_total", "total"),
                                        ("document_date", "date")) if rec.get(key) in (None, "")]
    if rec["doc_type"] in ("invoice", "credit_note") and not rec.get("document_number"):
        missing.append("invoice number")
    if missing:
        out.append(("missing_fields", f"Could not find the {', '.join(missing)} on the document."))
    net, vat, gross = rec.get("net_total"), rec.get("vat_total"), rec.get("gross_total")
    if net is not None and gross is not None:
        calc = round(net + (vat or 0.0), 2)
        if abs(calc - gross) > 0.02:
            out.append(("arithmetic", f"Net £{net:,.2f} + VAT £{(vat or 0):,.2f} = £{calc:,.2f}, "
                                      f"but the total shown is £{gross:,.2f} (difference £{gross - calc:,.2f})."))
    lines = rec.get("vat_lines") or []
    if lines and net is not None and abs(sum(l["net"] for l in lines) - net) > 0.02:
        out.append(("arithmetic", f"The VAT analysis adds up to £{sum(l['net'] for l in lines):,.2f} net, "
                                  f"but the net total shown is £{net:,.2f}."))
    item_nets = [i["net"] for i in rec.get("line_items") or [] if i.get("net") is not None]
    if item_nets and net is not None and len(item_nets) == len(rec["line_items"]) and abs(sum(item_nets) - net) > 0.02:
        out.append(("arithmetic", f"The line items add up to £{sum(item_nets):,.2f}, but the net total is £{net:,.2f}."))
    for line in lines:
        expected = round(line["net"] * line["rate"] / 100, 2)
        tolerance = max(0.05, abs(line["net"]) * 0.002)
        if line["rate"] not in allowed_rates and line["net"]:
            out.append(("vat_rate", f"VAT of £{line['vat']:,.2f} on £{line['net']:,.2f} is {line['rate']:g}%, "
                                    f"which is not a UK VAT rate ({', '.join(f'{r:g}%' for r in allowed_rates)})."))
        elif abs(expected - line["vat"]) > tolerance:
            out.append(("arithmetic", f"VAT at {line['rate']:g}% on £{line['net']:,.2f} should be £{expected:,.2f}, "
                                      f"but £{line['vat']:,.2f} is shown."))
    return out


def documents_frame(docs: list[dict]) -> pd.DataFrame:
    """One row per document, for display and export."""
    rows = []
    for d in docs:
        rows.append({
            "Doc": d["doc_id"], "File": d["file"], "Type": d["doc_type"].replace("_", " ").capitalize(),
            "From / to": d["counterparty"], "Number": d["document_number"],
            "Date": d["document_date"], "Due": d["due_date"], "Currency": d["currency"],
            "Net": d["net_total"], "VAT": d["vat_total"], "Total": d["gross_total"],
            "VAT number": d["counterparty_vat_number"], "PO": d["po_number"],
            "Card": d["card_last4"], "Confidence": d["confidence"].capitalize(),
            "Read by": d["extracted_by"], "Summary": d["summary"],
        })
    return pd.DataFrame(rows)
