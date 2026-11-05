"""Optional engine settings for clients whose job is not bookkeeping: ``modules.purchases``
(read and file invoices without checking or coding them) and ``reports:`` (names of the
Excel pack and PDF report). Without them, behaviour is unchanged."""

import io

import pandas as pd
from openpyxl import load_workbook

from core.claude import ClaudeClient
from tools.bookkeeping import pipeline, reports
from tools.bookkeeping.pipeline import RunInputs


def _pdf(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    for i, line in enumerate(lines):
        c.drawString(50, 800 - 15 * i, line)
    c.save()
    return buf.getvalue()


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


INVOICE = _pdf(["Acme Supplies Ltd", "INVOICE", "Invoice number: AC-1001", "Invoice date: 05/10/2026", "Job: P-2041",
                "Subtotal £100.00", "VAT @ 20% £20.00", "Total due £120.00"])
LETTER = b"From: Site Office <s@x.example>\nSubject: P-2050 access\n\nScaffold at Oak Lane comes down on Friday.\n"
LEDGER = _csv(pd.DataFrame({"Customer": ["Kent Build Ltd", "Weald Homes"], "Invoice No": ["5001", "5003"],
                            "Invoice Date": ["01/07/2026", "01/10/2026"], "Due Date": ["31/07/2026", "31/10/2026"],
                            "Amount": [1200.0, 300.0], "Project": ["P-2041", "P-2050"]}))
PROJECTS = _csv(pd.DataFrame({"Project Ref": ["P-2041", "P-2050"], "Project Name": ["Riverside Flats", "School Roof"],
                              "Site": ["Riverside Road", "Oak Lane"]}))
BASE = {"headline": "X: built as a prototype for Y", "tool_name": "Debtor Agent", "company": {"name": "Demo Ltd"},
        "accounting_system": "xero", "filing": {"reference_pattern": r"P-\d{4}"}}
REPORTS = {"pack_label": "Debtors pack (Excel)", "pack_file": "debtors-pack", "report_label": "Credit report (PDF)",
           "report_file": "credit-report", "report_title": "Debtor Agent — credit report", "method": ["Done in code."]}


def _run(config: dict):
    inputs = RunInputs(documents=[("acme.pdf", INVOICE), ("site.eml", LETTER)], as_of=pd.Timestamp("2026-11-05"),
                       period=(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31")),
                       tables={"open_invoices": [("ledger.csv", LEDGER)], "projects": [("projects.csv", PROJECTS)]})
    return pipeline.run(inputs, {**BASE, **config}, ClaudeClient(mock=True))


def test_purchases_off_reads_and_files_invoices_without_coding_them():
    r = _run({"modules": {"filing": True, "purchases": False}, "reports": REPORTS})
    assert r.entries.empty and not r.exports
    assert {f.area for f in r.findings} <= {"Debtors", "Sales", "Filing", "Documents"}  # no purchase or VAT checks
    assert set(r.filing["Project"]) == {"P-2041", "P-2050"}  # the invoice by reference, the letter by site
    assert (r.facts["filing_filed"], r.facts["filing_to_file"]) == (2, 0)
    assert [i["id"] for i in r.facts["debtor_issues"]] == [f.id for f in r.findings if f.area == "Debtors"]


def test_reports_settings_name_the_outputs_and_skip_empty_ledger_figures():
    r = _run({"modules": {"filing": True, "purchases": False}, "reports": REPORTS})
    names = {f.label: f.file_name for f in r.downloads}
    assert names["Debtors pack (Excel)"] == "debtor-agent_2026-10_debtors-pack.xlsx"
    assert names["Credit report (PDF)"] == "debtor-agent_2026-10_credit-report.pdf"
    assert names["Filed documents (ZIP)"] == "debtor-agent_2026-10_filed-documents.zip"
    items = dict(zip(*reports.summary_frame(r).T.values))
    assert "Ledger lines" not in items and items["Documents filed"] == "2 of 2 (0 left to file)"
    assert r.downloads[1].data.startswith(b"%PDF")
    wb = load_workbook(io.BytesIO(r.downloads[0].data))
    assert {"Aged debtors", "Filing index"} <= set(wb.sheetnames)


def test_defaults_are_unchanged():
    r = _run({"modules": {"filing": True}})
    assert not r.entries.empty  # the invoice is coded as before
    labels = [f.label for f in r.downloads]
    assert "Bookkeeping pack (Excel)" in labels and "Month-end report (PDF)" in labels
    assert "Ledger lines" in set(reports.summary_frame(r)["Item"])
    assert all(f.file_name.startswith("debtor-agent_2026-10_") for f in r.downloads)  # stem from the Xero export


def test_document_type_counts_read_naturally():
    from tools.bookkeeping.documents import type_count

    assert [type_count("invoice", 15), type_count("credit_note", 1), type_count("credit note", 2)] == [
        "15 invoices", "1 credit note", "2 credit notes"]
    assert [type_count("correspondence", 11), type_count("other", 1)] == ["11 letters and emails", "1 other document"]
