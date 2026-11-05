"""End-to-end: the Chapel Properties demo on its sample data, in mock mode."""

import io
import time
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from core.claude import ClaudeClient
from core.ui import StepProgress
from tools.bookkeeping import pipeline, reports
from tools.bookkeeping.pipeline import PipelineError, RunInputs
from tools.bookkeeping.views import load_config

CLIENT = Path(__file__).resolve().parent.parent / "clients" / "chapel-properties"

# (check, who) for each problem planted by sample_data/generate.py
EXPECTED = {
    ("Supplier bank details changed", "Willowmere Grounds Maintenance Ltd"),
    ("Totals don't add up", "Sallowfield Roofing Ltd"),
    ("VAT number fails HMRC check", "Clearflow Drainage Ltd"),
    ("New supplier", "Clearflow Drainage Ltd"),
    ("New supplier", "Oakmere Kitchens & Joinery Ltd"),
    ("Coding needs a decision", "Oakmere Kitchens & Joinery Ltd"),
    ("VAT charged without a VAT number", "G Lowe Property Maintenance"),
    ("Duplicate invoice", "Marlowe & Finch Plumbing & Heating Ltd"),
    ("Dated before this period", "Brightcote Electrical Services Ltd"),
    ("Dated after this period", "Emberguard Fire & Gas Safety Ltd"),
    ("Prepayment to spread", "Tallis & Penn Insurance Brokers Ltd"),
    ("Prepayment to spread", "Harbourline Block Management Ltd"),
    ("On supplier statement, not in our records", "Corndell Building Supplies Ltd"),
    ("Statement amount differs", "Corndell Building Supplies Ltd"),
    ("Could not tell which property", "Turnwell Locks & Security Ltd"),
}


@pytest.fixture(scope="module")
def config():
    return load_config(CLIENT)


@pytest.fixture(scope="module")
def result(config):
    client = ClaudeClient(fixtures_dir=CLIENT / "fixtures", mock=True)
    progress = StepProgress()
    started = time.perf_counter()
    res = pipeline.run(pipeline.sample_inputs(CLIENT, config), config, client, progress)
    res.test_seconds = time.perf_counter() - started
    res.test_steps = progress.steps
    res.test_calls = client.calls
    return res


def test_runs_well_under_a_minute(result):
    assert result.test_seconds < 20


def test_finds_exactly_the_planted_problems(result):
    exc = result.exceptions
    assert sorted(zip(exc["Check"], exc["Who"])) == sorted(EXPECTED)
    assert len(exc) == 15 and list(exc["ID"]) == [f"EX-{i:02d}" for i in range(1, 16)]
    assert result.facts["by_severity"] == {"High": 3, "Medium": 9, "Low": 3}
    by_check = {f.check_id: f for f in result.findings}
    assert "£1,416.00, but the total shown is £1,461.00" in by_check["arithmetic"].finding
    assert "£264.00 on the statement but £246.00" in by_check["statement_amount_mismatch"].finding
    assert "matches the property register" in by_check["unfiled_document"].finding


def test_human_check_list(result):
    checks = [c.title.split(" — ")[0] for c in result.human_checks]
    assert len(result.human_checks) == 12 and result.facts["needs_human_check"] == 12
    assert checks[0] == "Supplier bank details changed" and "Could not tell which property" in checks
    assert "Duplicate invoice" not in checks and "Prepayment to spread" not in checks  # handled without a person
    assert all(c.why and c.action for c in result.human_checks)


def test_every_claude_call_is_served_from_fixtures(result):
    """If this fails, prompts/config/data changed: run
    python -m tools.bookkeeping.refresh_fixtures clients/chapel-properties"""
    assert {c.source for c in result.test_calls} == {"fixture"}
    assert result.ai_sources == {"fixture": 24 + 1 + 2 + 1}  # documents, coding, email batches, summary
    assert "Willowmere" in result.summary and "Pre-recorded" in result.summary_source
    assert {d["extracted_by"] for d in result.documents} == {"AI (pre-recorded)"}
    assert all(l["source"] == "fixture" for l in result.letters)


def test_documents_and_properties(result):
    assert result.facts["documents"] == 24
    assert result.facts["documents_by_type"] == {"invoice": 22, "credit note": 1, "statement": 1}
    e = result.entries
    assert len(e) == 22 and set(e["kind"]) == {"bill", "supplier_credit"}
    assert e[e["tracking"] == ""]["reference"].tolist() == ["TLS-6120"]  # the lock change: property unknown
    by_property = reports.tracking_totals(result).groupby("Property")["Gross"].sum().round(2).to_dict()
    assert by_property == {"14 Lantern Row": 976.92, "22 Thistle Close": 1578.00, "3 Quayside Court": 1140.00,
                           "31 Heron Walk": 6193.80,  # gas safety + fencing - returned panels (credit) + kitchen
                           "8 Seagate Parade": 1416.00, "Brickfield Yard": 101.40, "Granary Court": 1130.57,
                           "Head office": 5166.00}
    filing = result.filing.set_index("Original file")
    assert filing.loc["2026-10-31_corndell_statement.pdf", "Property"] == "Head office"  # by keyword
    assert filing.loc["2026-10-14_turnwell_TLS-6120.pdf", "Folder"] == "_To file"


def test_coding_and_vat_treatment(result):
    e = result.entries.set_index("reference")
    assert e.loc["NES-448120", "vat_code"] == "R" and e.loc["NES-448120", "vat"] == 13.61  # domestic electricity, 5%
    assert e.loc["MW-55871", "vat_code"] == "Z" and e.loc["TPI-26-3381", "vat_code"] == "E"
    assert e.loc["SC-2026-0427", "account"] == "Service charges payable"
    assert e.loc["OKJ-1043", "confidence"] == "low" and e.loc["OKJ-1043", "status"] == "Held"  # repair or capital?
    assert e.loc["CD-0912", "coded_by"] == "rule"
    coded_by = result.entries.drop_duplicates("group")["coded_by"].value_counts().to_dict()
    assert coded_by == {"supplier list": 17, "Claude": 4, "rule": 1}


def test_totals_cross_check(result):
    e = result.entries
    # one bill per unique invoice (duplicate copy left out), at net + VAT, not the mis-added printed total
    bills = e[e["kind"] == "bill"].groupby("doc_id")["gross"].sum()
    invoices = [288.00, 1140.00, 4716.00, 264.00, 342.00, 285.84, 154.97, 93.60, 151.08, 1416.00, 201.60, 246.00, 114.00,
                198.00, 375.00, 408.00, 5820.00, 924.00, 101.40, 450.00, 222.00]
    assert len(bills) == 21 and round(bills.sum(), 2) == round(sum(invoices), 2) == 17911.49
    assert e[e["reference"] == "SR-1186"]["gross"].sum() == 1416.00
    # the Xero bills file holds exactly the ready entries, with the credit note negative
    xero = {x.key: x.frame for x in result.exports}["xero_bills"]
    ready = e[e["status"] == "Ready"]
    sign = ready["kind"].map({"bill": 1, "supplier_credit": -1})
    assert round((xero["*UnitAmount"] + xero["TaxAmount"]).sum(), 2) == round((ready["gross"] * sign).sum(), 2) == 9374.69
    assert not set(xero["*InvoiceNumber"]) & {"WGM-2210", "SR-1186", "CD-0912", "0412", "OKJ-1043", "TLS-6120",
                                               "EFS-2026-318"}  # held
    assert set(xero["TrackingName1"]) == {"Property"} and "" not in set(xero["TrackingOption1"])
    # property totals add back to the coded lines: every bill except the Turnwell lock change (£114.00, property
    # unknown), less the £94.80 credit note
    tracking = reports.tracking_totals(result)
    assert round(tracking["Gross"].sum(), 2) == round(17911.49 - 114.00 - 94.80, 2) == 17702.69
    accounts = reports.account_totals(result).set_index("Account")
    assert round(accounts["Gross"].sum(), 2) == round(17911.49 - 94.80, 2)
    assert accounts.loc["Repairs and maintenance", "Gross"] == round(288 + 342 + 1416 + 246 + 114 + 198 + 375 + 408 - 94.80
                                                                     + 5820 + 101.40, 2)
    assert result.facts["entries_ready"] == 15 and result.facts["entries_held"] == 7


def test_statement_reconciliation(result):
    status = dict(zip(result.statements["Statement ref"], result.statements["Status"]))
    assert status == {"CBS-54960": "Not in our records", "CBS-55102": "Amount differs", "CBS-55187": "Agrees",
                      "CN-2291": "Agrees"}


def test_emails_and_month_end_checklist(result):
    keys = [l["key"] for l in result.letters]
    assert keys == ["supplier:Clearflow Drainage Ltd", "supplier:Corndell Building Supplies Ltd",
                    "supplier:G Lowe Property Maintenance", "supplier:Sallowfield Roofing Ltd",
                    "supplier:Willowmere Grounds Maintenance Ltd"]
    bank = result.letters[-1]["body"]
    assert "phone" in bank and "never change bank details" in bank.lower()
    corndell = result.letters[1]["body"]
    assert "CBS-54960" in corndell and "£246.00" in corndell
    status = dict(zip(result.checklist["Item"], result.checklist["Status"]))
    assert status["Duplicate invoices removed"] == "Done"
    assert status["Supplier statements reconciled"] == "Action needed"
    assert status["Documents filed by property"] == "Action needed"
    assert list(status.values()).count("To do") == 4


def test_progress_steps_tell_the_story(result):
    labels = [s.label for s in result.test_steps]
    assert labels[0] == "Read 24 documents and 3 spreadsheets"
    assert "property register (8 rows)" in result.test_steps[0].detail
    assert "Reconciled 1 supplier statement" in labels and "Filed 23 of 24 documents" in labels
    assert any(l.startswith("Found 15 exceptions") for l in labels)
    assert all(s.status != "running" for s in result.test_steps)


def test_every_output_file_is_valid(result):
    files = {f.file_name.split("_", 2)[-1]: f for f in result.downloads}
    assert set(files) == {"xero-bills.csv", "bookkeeping-pack.xlsx", "month-end-report.pdf", "drafted-emails.docx",
                          "exceptions.csv", "filed-documents.zip"}
    for name, f in files.items():
        if name.endswith(".csv"):
            assert len(pd.read_csv(io.BytesIO(f.data), encoding="utf-8-sig")) > 0, name
    wb = load_workbook(io.BytesIO(files["bookkeeping-pack.xlsx"].data))
    assert {"Summary", "Exceptions", "Coded entries", "Totals by account", "Totals by property", "Supplier statements",
            "Filing index", "Documents read", "Emails drafted"} <= set(wb.sheetnames)
    assert wb["Exceptions"].max_row == 16 and wb["Coded entries"].max_row == 23
    header = [c.value for c in wb["Coded entries"][1]]
    assert header[header.index("Supplier / payee") + 1] == "Property"
    pdf = "".join(p.extract_text() for p in PdfReader(io.BytesIO(files["month-end-report.pdf"].data)).pages)
    assert "Totals by property" in pdf and "Granary Court" in pdf
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(files["drafted-emails.docx"].data)).namelist()
    names = zipfile.ZipFile(io.BytesIO(files["filed-documents.zip"].data)).namelist()
    assert len(names) == 25 and "filing-index.csv" in names
    assert any(n.startswith("_To file/") and "Turnwell" in n for n in names)


def test_time_saved_is_positive_and_explained(result):
    est = result.time_estimate
    assert est.manual_minutes == 377 and est.with_tool_minutes == 73 and len(est.assumptions) == 10

# ------------------------------------------------------------ unhappy paths


def _run(config, **kw):
    return pipeline.run(RunInputs(**kw), config, ClaudeClient(mock=True))


def test_no_files_is_a_friendly_error(config):
    with pytest.raises(PipelineError, match="No files to process"):
        _run(config)


def test_only_unreadable_files_is_a_friendly_error(config):
    with pytest.raises(PipelineError, match="None of the files could be read"):
        _run(config, documents=[("scan.jpg", b"\xff\xd8"), ("broken.pdf", b"not a pdf")])


def test_uploads_are_routed_and_run_with_templates(config):
    inbox = CLIENT / "sample_data" / "inbox"
    files = [(p.name, p.read_bytes()) for p in sorted(inbox.iterdir())[:8]]
    files += [("notes.csv", b"Colour,Size\nred,big\n"), ("photo.png", b"\x89PNG")]
    inputs = pipeline.upload_inputs(files, config, CLIENT)
    assert set(inputs.tables) == {"suppliers", "chart_of_accounts", "projects"}  # reference lists from the demo
    assert any("notes.csv" in n for n in inputs.notes)
    res = pipeline.run(inputs, config, ClaudeClient(mock=True))
    assert any("using the demo's sample ones" in w and "property register" in w for w in res.warnings)
    assert set(res.ai_sources) <= {"mock"} and res.downloads
    assert any(f.check_id == "unreadable_document" for f in res.findings)  # the photo
    assert any(c.id == "AI" for c in res.human_checks)  # template text is flagged for review


def test_uploaded_property_register_is_recognised(config):
    register = (CLIENT / "sample_data" / "property_register.csv").read_bytes()
    inputs = pipeline.upload_inputs([("my-properties.csv", register)], config, CLIENT)
    assert "projects" in inputs.tables and "projects" not in inputs.fallback_roles


def test_missing_sample_folder_is_a_friendly_error(config, tmp_path):
    with pytest.raises(PipelineError, match="sample data files could not be found"):
        pipeline.sample_inputs(tmp_path, config)
