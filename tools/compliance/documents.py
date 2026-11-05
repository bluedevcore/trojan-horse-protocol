"""Unstructured inputs: get the text out of PDFs, Word files, emails and text
files, plus a deterministic *pattern reader* used in mock mode for uploaded
files and whenever Claude is unavailable. No AI in this module.

The pattern reader finds references (A-108, R-05, clause 7.5), dates and
keywords. Everything it reads is marked low confidence so a person checks it.
"""

from __future__ import annotations

import email
import io
import re
from dataclasses import dataclass, field
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import pandas as pd

MESSAGE_SUFFIXES = {".eml"}
DOC_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".eml"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".gif", ".tif", ".tiff"}
MAX_TEXT_CHARS = 14000  # per document; longer text is cut with a visible marker


class DocumentError(Exception):
    """A document that cannot be read; the message is shown to the user."""


@dataclass
class DocText:
    name: str
    kind: str  # pdf | docx | email | text
    text: str
    subject: str = ""
    sender: str = ""  # display name
    sender_email: str = ""
    received: pd.Timestamp | None = None  # email Date header (deterministic, not read by AI)
    attachments: list[str] = field(default_factory=list)
    truncated: bool = False
    data: bytes = b""  # original bytes (for evidence packs)


def read_document(name: str, data: bytes) -> DocText:
    suffix = Path(name).suffix.lower()
    if not data:
        raise DocumentError(f"“{name}” is empty.")
    if suffix in IMAGE_SUFFIXES:
        raise DocumentError(f"“{name}” is an image. This prototype reads PDFs, Word files, emails and text files; "
                            "scans and photos would need OCR (see NEXT_STEPS.md).")
    if suffix == ".pdf":
        doc = DocText(name, "pdf", pdf_text(data, name))
    elif suffix == ".docx":
        doc = DocText(name, "docx", docx_text(data, name))
    elif suffix == ".eml":
        doc = email_text(data, name)
    elif suffix in (".txt", ".md"):
        doc = DocText(name, "text", _decode(data))
    else:
        raise DocumentError(f"“{name}” is a {suffix or 'file'} file; documents must be PDF, Word (.docx), EML or TXT.")
    if not doc.text.strip():
        raise DocumentError(f"“{name}” has no readable text (it may be a scanned image, which needs OCR).")
    if len(doc.text) > MAX_TEXT_CHARS:
        doc.text = doc.text[:MAX_TEXT_CHARS] + "\n[… document continues; only the first part was read]"
        doc.truncated = True
    doc.data = data
    return doc


def pdf_text(data: bytes, name: str = "document.pdf") -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # pypdf raises many types for broken files
        raise DocumentError(f"“{name}” could not be opened as a PDF ({type(exc).__name__}).") from exc
    return "\n\n".join(p.strip() for p in pages if p.strip())


def docx_text(data: bytes, name: str = "document.docx") -> str:
    try:
        from docx import Document

        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError(f"“{name}” could not be opened as a Word document ({type(exc).__name__}).") from exc
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


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
    sender_name, sender_email = parseaddr(str(msg.get("From", "")))
    received = None
    try:
        if msg.get("Date"):
            received = pd.Timestamp(parsedate_to_datetime(str(msg["Date"]))).tz_localize(None)
    except (TypeError, ValueError):
        received = None
    parts = [f"From: {msg.get('From', '')}", f"To: {msg.get('To', '')}", f"Date: {msg.get('Date', '')}",
             f"Subject: {msg.get('Subject', '')}", "", body.strip()]
    attachments = []
    for part in msg.iter_attachments():
        fname = part.get_filename() or "attachment"
        attachments.append(fname)
        payload = part.get_payload(decode=True) or b""
        lower = fname.lower()
        try:
            if lower.endswith(".pdf"):
                parts += ["", f"--- Attachment: {fname} ---", pdf_text(payload, fname)[:3000]]
            elif lower.endswith(".docx"):
                parts += ["", f"--- Attachment: {fname} ---", docx_text(payload, fname)[:3000]]
            elif part.get_content_maintype() == "text":
                parts += ["", f"--- Attachment: {fname} ---", _decode(payload)[:3000]]
            else:
                parts += ["", f"--- Attachment: {fname} (not read: {part.get_content_type()}) ---"]
        except DocumentError:
            parts += ["", f"--- Attachment: {fname} (could not be read) ---"]
    return DocText(name, "email", "\n".join(parts).strip(), subject=str(msg.get("Subject", "")),
                   sender=sender_name or sender_email, sender_email=sender_email.lower(), received=received,
                   attachments=attachments)


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

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
DATE_RE = re.compile(r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
                     rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS})[a-z]*\.?,?\s+\d{{4}})\b", re.IGNORECASE)


def parse_date(text: str | None) -> pd.Timestamp | None:
    """A UK (day-first) or ISO date from text; None if there is none."""
    if not text:
        return None
    s = str(text).strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return pd.Timestamp(s[:10])
        s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
        value = pd.to_datetime(s, dayfirst=True, errors="coerce")
        return None if pd.isna(value) else pd.Timestamp(value).normalize()
    except (ValueError, TypeError, OverflowError):
        return None


def find_dates(text: str) -> list[pd.Timestamp]:
    out = []
    for m in DATE_RE.finditer(text or ""):
        d = parse_date(m.group(1))
        if d is not None:
            out.append(d)
    return out


def find_refs(text: str, pattern: str) -> list[str]:
    """Distinct references matching ``pattern`` in order of appearance (upper-cased)."""
    seen: list[str] = []
    for m in re.finditer(pattern, text or "", flags=re.IGNORECASE):
        ref = m.group(0).upper()
        if ref not in seen:
            seen.append(ref)
    return seen


def keyword_hit(text: str, words: list[str]) -> bool:
    low = (text or "").lower()
    return any(re.search(r"\b" + re.escape(w.lower()) + r"\b", low) for w in words)


def first_line(text: str, skip_headers: bool = True) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or (skip_headers and re.match(r"^(From|To|Date|Subject|Cc):", line)):
            continue
        return line[:120]
    return ""


def body_of(doc: DocText) -> str:
    """Email body without the header lines (the full text for other documents)."""
    if doc.kind != "email":
        return doc.text
    return doc.text.split("\n\n", 1)[1] if "\n\n" in doc.text else doc.text
