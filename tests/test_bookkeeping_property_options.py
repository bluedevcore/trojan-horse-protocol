"""Optional config keys for property (or project) analysis, on tiny in-memory inputs in mock mode:
analysis.entries_column, analysis.in_report, filing.noun and a table label override.
Without these keys the engine behaves as before (checked at the end)."""

import io

import pandas as pd
import pytest
from pypdf import PdfReader

from core.claude import ClaudeClient
from core.ui import StepProgress
from tools.bookkeeping import ai, pipeline, reports
from tools.bookkeeping.pipeline import RunInputs
from tools.bookkeeping.vat import format_vat_number, make_gb_vat_number


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


VAT = format_vat_number(make_gb_vat_number("3124570"))
REPAIR = _pdf(["Acme Repairs Ltd", f"VAT Reg No: {VAT}", "INVOICE", "Invoice number: AR-1", "Invoice date: 05/10/2026",
               "Site: 4 Mill Lane", "Subtotal £100.00", "VAT @ 20% £20.00", "Total due £120.00"])
LOCKS = _pdf(["Acme Repairs Ltd", f"VAT Reg No: {VAT}", "INVOICE", "Invoice number: AR-2", "Invoice date: 06/10/2026",
              "Job: Flat 2", "Subtotal £50.00", "VAT @ 20% £10.00", "Total due £60.00"])
CHART = _csv(pd.DataFrame({"Account Name": ["Repairs and maintenance", "Suspense"], "Account Type": ["Property costs", "Suspense"]}))
SUPPLIERS = _csv(pd.DataFrame({"Supplier": ["Acme Repairs Ltd"], "Default Account": ["Repairs and maintenance"],
                               "VAT Number": [VAT], "Sort Code": [""], "Account Number": [""]}))
REGISTER = _csv(pd.DataFrame({"Property Ref": ["Mill Lane"], "Property Name": ["4 Mill Lane, Ipswich"], "Site": ["4 Mill Lane"]}))
PROPERTY_CONFIG = {
    "headline": "X: built as a prototype for Y", "company": {"name": "Demo Ltd"}, "accounting_system": "xero",
    "modules": {"filing": True, "card_matching": False},
    "tables": {"projects": {"label": "property register", "aliases": {"project_ref": ["Property Ref"],
                                                                      "project_name": ["Property Name"]}}},
    "filing": {"noun": "property"},
    "analysis": {"tracking_label": "Property", "entries_column": True, "in_report": True},
}


@pytest.fixture
def property_extract(monkeypatch):
    real = ai.pattern_extract

    def fake(doc):  # stand in for Claude: it reads the property from the "Site:" line when there is one
        out = real(doc)
        out["project_reference"] = "Mill Lane" if "Mill Lane" in doc.text else ""
        return out

    monkeypatch.setattr(ai, "pattern_extract", fake)


def _run(config: dict, progress=None):
    inputs = RunInputs(documents=[("repair.pdf", REPAIR), ("locks.pdf", LOCKS)],
                       tables={"chart_of_accounts": [("chart.csv", CHART)], "suppliers": [("suppliers.csv", SUPPLIERS)],
                               "projects": [("register.csv", REGISTER)]},
                       period=(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31")))
    return pipeline.run(inputs, config, ClaudeClient(mock=True), progress)


def test_property_wording_column_and_report(property_extract):
    progress = StepProgress()
    r = _run(PROPERTY_CONFIG, progress)
    assert "property register (1 rows)" in progress.steps[0].detail  # the config label, not "project register"
    unfiled = [f for f in r.findings if f.check_id == "unfiled_document"]
    assert len(unfiled) == 1 and "matches the property register" in unfiled[0].finding
    assert {"Property", "Property name"} <= set(r.filing.columns) and "Project" not in r.filing.columns
    entries = reports.entries_frame(r)
    cols = list(entries.columns)
    assert cols[cols.index("Supplier / payee") + 1] == "Property"
    assert sorted(entries["Property"]) == ["", "Mill Lane"]
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(reports.pdf_report(r))).pages)
    assert "Totals by property" in text and "Mill Lane" in text
    xero = {x.key: x.frame for x in r.exports}["xero_bills"]
    assert "Mill Lane" in set(xero["TrackingOption1"])


def test_defaults_are_unchanged_without_the_keys(property_extract):
    config = {k: v for k, v in PROPERTY_CONFIG.items() if k not in ("filing", "analysis", "tables")}
    config["tables"] = {"projects": {"aliases": PROPERTY_CONFIG["tables"]["projects"]["aliases"]}}
    progress = StepProgress()
    r = _run(config, progress)
    assert "project register (1 rows)" in progress.steps[0].detail
    assert any("matches the project register" in f.finding for f in r.findings if f.check_id == "unfiled_document")
    assert "Project" in r.filing.columns
    assert "Tracking" not in reports.entries_frame(r).columns and "Property" not in reports.entries_frame(r).columns
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(reports.pdf_report(r))).pages)
    assert "Totals by" not in text
