"""Bookkeeping engine: VAT helpers, document reading and arithmetic checks."""

import io
from email.message import EmailMessage

import pandas as pd
import pytest

from tools.bookkeeping.documents import (DocText, DocumentError, arithmetic_problems, normalise, pattern_extract,
                                         read_document)
from tools.bookkeeping.vat import (check_gb_vat_number, code_for_rate, format_vat_number, make_gb_vat_number,
                                   normalise_code, vat_return)

# ---------------------------------------------------------------------- VAT


def test_vat_number_check_digits():
    good = make_gb_vat_number("3124570")
    assert check_gb_vat_number(good) is True
    assert check_gb_vat_number(format_vat_number(good)) is True  # spaces are fine
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert check_gb_vat_number(bad) is False
    assert check_gb_vat_number("GB12345") is False
    assert check_gb_vat_number("") is None
    assert check_gb_vat_number("GBGD123") is True  # government department


def test_vat_codes_and_rates():
    assert [normalise_code(x) for x in ("S", "20%", "T1", "zero rated", "T2", "No VAT", "5", "rc")] == \
        ["S", "S", "S", "Z", "E", "O", "R", "RC"]
    assert code_for_rate(20) == "S" and code_for_rate(5) == "R"
    assert code_for_rate(0, zero_default="E") == "E"


def test_vat_return_boxes():
    d = pd.Timestamp("2026-10-15")
    entries = pd.DataFrame([
        {"kind": "sales_invoice", "date": d, "net": 1000.0, "vat": 200.0, "vat_code": "S", "status": "Ready"},
        {"kind": "bill", "date": d, "net": 500.0, "vat": 100.0, "vat_code": "S", "status": "Ready"},
        {"kind": "supplier_credit", "date": d, "net": 50.0, "vat": 10.0, "vat_code": "S", "status": "Ready"},
        {"kind": "card_expense", "date": d, "net": 40.0, "vat": 0.0, "vat_code": "O", "status": "Ready"},  # blocked
        {"kind": "card_expense", "date": d, "net": 100.0, "vat": 0.0, "vat_code": "RC", "status": "Ready"},
        {"kind": "bill", "date": d, "net": 999.0, "vat": 199.8, "vat_code": "S", "status": "Held"},  # held: left out
        {"kind": "bill", "date": pd.Timestamp("2026-09-30"), "net": 10.0, "vat": 2.0, "vat_code": "S", "status": "Ready"},
    ])
    boxes = vat_return(entries, pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31")).set_index("Box")["Amount (£)"]
    assert boxes[1] == 220.0  # 200 output + 20 reverse charge
    assert boxes[4] == 110.0  # 100 - 10 credit + 20 reverse charge
    assert boxes[5] == 110.0
    assert boxes[6] == 1100.0  # sales + reverse-charge services
    assert boxes[7] == 550.0  # 500 - 50 + 100; blocked "O" items excluded

# ---------------------------------------------------------------- documents


def _invoice(**kw):
    rec = {"doc_type": "invoice", "counterparty": "Acme Supplies Ltd", "document_number": "A-1",
           "document_date": "2026-10-03", "net_total": 100.0, "vat_total": 20.0, "gross_total": 120.0,
           "vat_lines": [{"rate": 20, "net": 100.0, "vat": 20.0}], "line_items": []}
    rec.update(kw)
    return normalise(rec, DocText("a.pdf", "pdf", "x"), "D-01", "test")


def test_clean_invoice_has_no_problems():
    assert arithmetic_problems(_invoice()) == []


def test_total_that_does_not_add_up():
    problems = arithmetic_problems(_invoice(gross_total=130.0))
    assert [c for c, _ in problems] == ["arithmetic"]
    assert "£120.00" in problems[0][1] and "£130.00" in problems[0][1]


def test_unusual_vat_rate_and_wrong_vat_amount():
    odd = arithmetic_problems(_invoice(vat_total=17.5, gross_total=117.5, vat_lines=[{"rate": 17.5, "net": 100, "vat": 17.5}]))
    assert "vat_rate" in [c for c, _ in odd]
    wrong = arithmetic_problems(_invoice(vat_total=25.0, gross_total=125.0, vat_lines=[{"rate": 20, "net": 100, "vat": 25}]))
    assert [c for c, _ in wrong] == ["arithmetic"]


def test_line_items_may_be_vat_inclusive():
    items = [{"description": "x", "net": 60.0}, {"description": "y", "net": 60.0}]  # add up to the gross
    assert arithmetic_problems(_invoice(line_items=items)) == []
    wrong = [{"description": "x", "net": 60.0}, {"description": "y", "net": 50.0}]
    assert [c for c, _ in arithmetic_problems(_invoice(line_items=wrong))] == ["arithmetic"]


def test_missing_key_fields():
    problems = arithmetic_problems(_invoice(document_number="", gross_total=None))
    assert problems[0][0] == "missing_fields" and "invoice number" in problems[0][1]


def test_normalise_credit_note_and_single_vat_line():
    rec = normalise({"doc_type": "credit_note", "net_total": -38.5, "vat_total": -7.7, "gross_total": -46.2,
                     "document_date": "17/10/2026", "currency": "gbp", "counterparty_vat_number": "gb 123 4567 89"},
                    DocText("cn.pdf", "pdf", "x"), "D-02", "test")
    assert (rec["net_total"], rec["vat_total"], rec["gross_total"]) == (38.5, 7.7, 46.2)
    assert rec["vat_lines"] == [{"rate": 20.0, "net": 38.5, "vat": 7.7}]
    assert rec["document_date"] == pd.Timestamp("2026-10-17") and rec["currency"] == "GBP"
    assert rec["counterparty_vat_number"] == "GB123456789"


def _pdf(lines):
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i, line in enumerate(lines):
        c.drawString(50, 800 - 15 * i, line)
    c.save()
    return buf.getvalue()


def test_read_pdf_and_pattern_reader():
    pdf = _pdf(["Acme Supplies Ltd", "VAT Reg No: GB 312 4570 42", "INVOICE", "Invoice number: AC-1001",
                "Invoice date: 03/10/2026", "Subtotal £100.00", "VAT @ 20% £20.00", "Total due £120.00",
                "Sort code 00-11-22, account number 12345678"])
    doc = read_document("acme.pdf", pdf)
    assert doc.kind == "pdf" and "AC-1001" in doc.text
    x = pattern_extract(doc)
    assert x["doc_type"] == "invoice" and x["counterparty"] == "Acme Supplies Ltd"
    assert (x["document_number"], x["net_total"], x["vat_total"], x["gross_total"]) == ("AC-1001", 100.0, 20.0, 120.0)
    assert x["bank_sort_code"] == "00-11-22" and x["bank_account_number"] == "12345678"
    assert x["confidence"] == "low"


def test_read_email_with_pdf_attachment():
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "Billing <b@x.example>", "a@y.example", "Invoice AC-1002"
    msg.set_content("Please find our invoice attached.")
    msg.add_attachment(_pdf(["Acme Supplies Ltd", "Invoice number: AC-1002", "Total due £60.00"]),
                       maintype="application", subtype="pdf", filename="AC-1002.pdf")
    doc = read_document("mail.eml", bytes(msg))
    assert doc.kind == "email" and doc.attachments == ["AC-1002.pdf"]
    assert "Attachment: AC-1002.pdf" in doc.text and "Total due" in doc.text
    assert pattern_extract(doc)["counterparty"] == "Acme Supplies Ltd"  # from the attached invoice, not the sender


@pytest.mark.parametrize("name,data,msg", [
    ("empty.pdf", b"", "is empty"),
    ("photo.jpg", b"\xff\xd8\xff", "photo"),
    ("sheet.docx", b"PK..", "must be PDF, EML or TXT"),
    ("broken.pdf", b"not a pdf at all", "could not be opened"),
])
def test_unreadable_documents_are_explained(name, data, msg):
    with pytest.raises(DocumentError, match=msg):
        read_document(name, data)
