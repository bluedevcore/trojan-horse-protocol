"""End-to-end: the Somerset Solders demo on its sample data, in mock mode."""

import io
import time
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from core.claude import ClaudeClient
from core.ui import StepProgress
from tools.bookkeeping import pipeline
from tools.bookkeeping.pipeline import PipelineError, RunInputs
from tools.bookkeeping.views import load_config

CLIENT = Path(__file__).resolve().parent.parent / "clients" / "somerset-solders"

# (check, who) for each problem planted by sample_data/generate.py
EXPECTED = {
    ("Supplier bank details changed", "Penhallow Assay Laboratories Ltd"),
    ("Totals don't add up", "Coldharbour Industrial Gases Ltd"),
    ("Dated before this period", "Brackenford Reels & Spools Ltd"),
    ("Duplicate invoice", "Larkmoor Freight Ltd"),
    ("Coding needs a decision", "Harrowden Safety Supplies Ltd"),
    ("New supplier", "Brenwick Lab Supplies Ltd"),
    ("VAT number fails HMRC check", "Brenwick Lab Supplies Ltd"),
    ("Prepayment to spread", "Fernbrook Calibration Services Ltd"),
    ("VAT charged without a VAT number", "Combe Electrical Services"),
    ("VAT not reclaimable", "Wellsbrook Manor Hotel Ltd"),
    ("Customer PO missing", "Kingsdown Circuits Ltd"),
    ("Seriously overdue", "Saltmarsh Marine Electronics Ltd"),
    ("Disputed invoice", "Ashwick Heating Supplies Ltd"),
    ("Payment not matched to an invoice", "BACS TRELAWNEY CONTROLS LTD"),
    ("Part payment", "Harbourside Plumbers' Merchants Ltd"),
    ("Invoice exceeds the PO", "Carrowdene Metals Ltd"),
    ("On supplier statement, not in our records", "Hollowmere Chemicals Ltd"),
}
HELD_BILLS = {"CM-118377", "PAL-6620", "CIG-55190", "0347", "BLS-1043"}


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
    assert set(zip(exc["Check"], exc["Who"])) == EXPECTED
    assert len(exc) == 17 and list(exc["ID"]) == [f"EX-{i:02d}" for i in range(1, 18)]
    assert result.facts["by_severity"] == {"High": 5, "Medium": 9, "Low": 3}


def test_human_check_list(result):
    checks = {c.title.split(" — ")[0] for c in result.human_checks}
    assert len(result.human_checks) == 13 and result.facts["needs_human_check"] == 13
    assert {"Supplier bank details changed", "Invoice exceeds the PO", "Seriously overdue"} <= checks
    assert not checks & {"Duplicate invoice", "Part payment", "Prepayment to spread"}  # handled without a person
    assert all(c.why and c.action for c in result.human_checks)


def test_every_claude_call_is_served_from_fixtures(result):
    """If this fails, prompts/config/data changed: run
    python -m tools.bookkeeping.refresh_fixtures clients/somerset-solders"""
    assert {c.source for c in result.test_calls} == {"fixture"}
    assert result.ai_sources == {"fixture": 19 + 1 + 4 + 1}  # documents, coding, email batches, summary
    assert "Penhallow" in result.summary and "Pre-recorded" in result.summary_source
    assert {d["extracted_by"] for d in result.documents} == {"AI (pre-recorded)"}
    assert all(l["source"] == "fixture" for l in result.letters)


def test_documents_are_read(result):
    types = result.facts["documents_by_type"]
    assert result.facts["documents"] == 19 and types == {"invoice": 18, "statement": 1}


def test_coding_and_vat_treatment(result):
    e = result.entries
    by_payee = e.groupby("counterparty")
    hotel = by_payee.get_group("Wellsbrook Manor Hotel Ltd")
    assert set(hotel["vat_code"]) == {"O"} and hotel["gross"].sum() == 216.00  # entertainment: VAT blocked
    freight = by_payee.get_group("Larkmoor Freight Ltd").set_index("vat_code")
    assert freight.loc["S", "vat"] == 115.20 and freight.loc["Z", "net"] == 695.00  # export freight zero-rated
    brenwick = by_payee.get_group("Brenwick Lab Supplies Ltd")
    assert brenwick["account"].tolist() == ["Production consumables"] and brenwick["coded_by"].tolist() == ["Claude"]
    harrowden = by_payee.get_group("Harrowden Safety Supplies Ltd")
    assert harrowden["confidence"].tolist() == ["low"]
    coded_by = e.drop_duplicates("group")["coded_by"].value_counts().to_dict()
    assert coded_by == {"supplier list": 15, "Claude": 2}


def test_purchase_totals_cross_check(result):
    e = result.entries
    # bills: one per unique invoice (the copy is not posted), at net + VAT (not the mis-added printed total)
    bills = e[e["kind"] == "bill"].groupby("doc_id")["gross"].sum()
    invoices = [977.40, 2592.00, 198.00, 1350.00, 292.61, 6234.00, 1386.20, 6277.18, 14460.00, 484.80, 438.60,
                216.00, 362.88, 699.54, 408.00, 267.72, 351.60]
    assert len(bills) == 17 and round(bills.sum(), 2) == round(sum(invoices), 2)
    assert e[e["counterparty"] == "Coldharbour Industrial Gases Ltd"]["gross"].sum() == 438.60
    assert set(e[e["status"] == "Held"]["reference"]) == HELD_BILLS
    # the Xero bills file holds exactly the ready bills
    xero = {x.key: x.frame for x in result.exports}["xero_bills"]
    ready = e[e["status"] == "Ready"]
    assert round((xero["*UnitAmount"] + xero["TaxAmount"]).sum(), 2) == round(ready["gross"].sum(), 2) == 20842.25
    assert not set(xero["*InvoiceNumber"]) & HELD_BILLS
    assert set(xero["*AccountCode"]) <= set(result.entries["account_code"])  # chart codes, not names
    assert result.facts["value_ready"] == round(ready["gross"].sum(), 2) == 20842.25


def test_sales_invoices(result):
    s = result.sales
    assert s["invoice_number"].nunique() == 6 and round(s["gross"].sum(), 2) == 41543.60
    assert set(s[s["status"] == "Held"]["customer"]) == {"Kingsdown Circuits Ltd"}
    assert set(s[s["vat_code"] == "Z"]["customer"]) == {"Ballykeel Electronics Ltd", "Verhoeven Elektronica B.V."}
    xero = {x.key: x.frame for x in result.exports}["xero_sales_invoices"]
    assert "INV-3142" not in set(xero["*InvoiceNumber"]) and xero["*InvoiceNumber"].nunique() == 5
    assert set(xero.loc[xero["*ContactName"] == "Verhoeven Elektronica B.V.", "*TaxType"]) == {"Zero Rated Income"}


def test_debtors_allocation_and_chasing(result):
    d = result.debtors.set_index("invoice_number")
    assert result.facts["debtor_items"] == 14
    assert result.facts["debtors_outstanding"] == 15003.40 and result.facts["debtors_overdue"] == 9791.40
    assert d.loc["INV-3127", "outstanding"] == 0  # no reference on the receipt: matched on name and amount
    assert d.loc["INV-3091", "outstanding"] == 1414.20  # part payment
    assert d.loc["INV-3094", "chase_tier"] == ""  # disputed: not chased
    tiers = d[d["chase_tier"] != ""].groupby("customer")["chase_tier"].agg(set).to_dict()
    assert tiers == {"Saltmarsh Marine Electronics Ltd": {"Final notice", "Reminder"},
                     "Harbourside Plumbers' Merchants Ltd": {"Second reminder", "Reminder"},
                     "Ashwick Heating Supplies Ltd": {"Reminder"}}


def test_vat_return_workings(result):
    box = dict(zip(result.vat_return["Box"], result.vat_return["Amount (£)"]))
    s, e = result.sales, result.entries
    assert box[1] == round(s[s["status"] == "Ready"]["vat"].sum(), 2) == 3378.60
    october = e[(e["status"] == "Ready") & (e["date"] >= "2026-10-01")]  # BRS-40877 is dated in September
    reclaim = october[october["vat_code"] == "S"]
    assert box[4] == round(reclaim["vat"].sum(), 2) == 3158.98
    assert box[5] == round(box[3] - box[4], 2) == 219.62
    assert box[6] == 28949 and box[7] == 16489  # whole pounds; the hotel lunch (no VAT) is outside box 7


def test_purchase_orders_and_statement(result):
    po = result.po_table
    assert po["Status"].value_counts().to_dict() == {"Matched": 3, "Over PO value": 1, "Awaiting invoice": 2}
    assert po.loc[po["Status"] == "Over PO value", "Difference"].tolist() == [450.00]
    stmt = result.statements.set_index("Statement ref")
    assert stmt.loc["HC-7741", "Status"] == "Agrees" and stmt.loc["HC-7769", "Status"] == "Not in our records"


def test_emails_and_month_end_checklist(result):
    keys = [l["key"] for l in result.letters]
    assert keys == ["supplier:Brenwick Lab Supplies Ltd", "supplier:Carrowdene Metals Ltd",
                    "supplier:Coldharbour Industrial Gases Ltd", "supplier:Combe Electrical Services",
                    "supplier:Hollowmere Chemicals Ltd", "supplier:Penhallow Assay Laboratories Ltd",
                    "customer:Ashwick Heating Supplies Ltd", "customer:Harbourside Plumbers' Merchants Ltd",
                    "customer:Kingsdown Circuits Ltd", "customer:Saltmarsh Marine Electronics Ltd"]
    letters = {l["key"]: l for l in result.letters}
    bank = letters["supplier:Penhallow Assay Laboratories Ltd"]["body"]
    assert "phone" in bank and "never change bank details" in bank.lower()
    final = letters["customer:Saltmarsh Marine Electronics Ltd"]
    assert "Final notice" in final["subject"] and "INV-3051" in final["body"] and "INV-3133" in final["body"]
    assert "INV-3094" not in letters["customer:Ashwick Heating Supplies Ltd"]["body"]  # disputed, not chased
    status = dict(zip(result.checklist["Item"], result.checklist["Status"]))
    detail = dict(zip(result.checklist["Item"], result.checklist["Detail"]))
    assert status["Duplicate invoices removed"] == "Done"
    assert status["Supplier bank detail changes verified"] == "Action needed"
    assert detail["VAT return workings prepared"] == "Box 5 £219.62 (draft for review)"
    assert list(status.values()).count("To do") == 4


def test_progress_steps_tell_the_story(result):
    labels = [s.label for s in result.test_steps]
    assert labels[0] == "Read 19 documents and 7 spreadsheets"
    assert "Raised 6 sales invoices worth £41,543.60" in labels
    assert "Aged 14 open invoices: £15,003.40 outstanding" in labels
    assert any(l.startswith("Found 17 exceptions") for l in labels)
    assert all(s.status != "running" for s in result.test_steps)


def test_every_output_file_is_valid(result):
    files = {f.file_name.split("_", 2)[-1]: f for f in result.downloads}
    assert set(files) == {"xero-bills.csv", "xero-sales-invoices.csv", "bookkeeping-pack.xlsx", "month-end-report.pdf",
                          "drafted-emails.docx", "exceptions.csv"}
    for name, f in files.items():
        if name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(f.data), encoding="utf-8-sig")
            assert len(df) > 0, name
    wb = load_workbook(io.BytesIO(files["bookkeeping-pack.xlsx"].data))
    assert {"Summary", "Month-end checklist", "Exceptions", "Coded entries", "Sales invoices", "Aged debtors",
            "Debtors by customer", "PO matching", "Supplier statements", "VAT return workings", "Documents read",
            "Emails drafted"} <= set(wb.sheetnames)
    assert wb["Exceptions"].max_row == 18 and wb["Coded entries"].max_row == 19
    assert files["month-end-report.pdf"].data.startswith(b"%PDF")
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(files["drafted-emails.docx"].data)).namelist()


def test_time_saved_is_positive_and_explained(result):
    est = result.time_estimate
    assert est.saved_minutes > 120 and len(est.assumptions) == 12

# ------------------------------------------------------------ unhappy paths


def _run(config, **kw):
    return pipeline.run(RunInputs(**kw), config, ClaudeClient(mock=True))


def test_no_files_is_a_friendly_error(config):
    with pytest.raises(PipelineError, match="No files to process"):
        _run(config)


def test_only_unreadable_files_is_a_friendly_error(config):
    with pytest.raises(PipelineError, match="None of the files could be read"):
        _run(config, documents=[("scan.jpg", b"\xff\xd8"), ("empty.pdf", b"")])


def test_uploads_are_routed_and_run_with_templates(config):
    sample = CLIENT / "sample_data"
    files = [(p.name, p.read_bytes()) for p in sorted((sample / "inbox").iterdir())[:6]]
    files += [(name, (sample / name).read_bytes()) for name in
              ("despatches_to_invoice_oct-2026.xlsx", "open_sales_invoices_31-oct-2026.csv", "bank_statement_oct-2026.csv")]
    files += [("notes.csv", b"Colour,Size\nred,big\n"), ("photo.png", b"\x89PNG")]
    inputs = pipeline.upload_inputs(files, config, CLIENT)
    assert set(inputs.tables) == {"sales_to_invoice", "open_invoices", "bank_statement",
                                  "suppliers", "customers", "chart_of_accounts"}  # lists from the demo
    assert any("notes.csv" in n for n in inputs.notes)
    res = pipeline.run(inputs, config, ClaudeClient(mock=True))
    assert any("using the demo's sample ones" in w for w in res.warnings)
    assert set(res.ai_sources) <= {"mock"} and res.downloads
    assert any(f.check_id == "unreadable_document" for f in res.findings)  # the photo
    assert any(c.id == "AI" for c in res.human_checks)  # template text is flagged for review
    assert res.sales["invoice_number"].nunique() == 6 and not res.debtors.empty and not res.vat_return.empty


def test_upload_with_nothing_readable_is_a_friendly_error(config):
    inputs = pipeline.upload_inputs([("empty.pdf", b""), ("notes.csv", b"Colour,Size\nred,big\n")], config, CLIENT)
    assert inputs.fallback_roles and len(inputs.notes) == 1  # the skipped spreadsheet
    with pytest.raises(PipelineError, match="None of the files could be read"):
        pipeline.run(inputs, config, ClaudeClient(mock=True))


def test_malformed_spreadsheet_is_a_warning_not_a_crash(config):
    inbox = CLIENT / "sample_data" / "inbox"
    doc = sorted(inbox.iterdir())[0]
    res = _run(config, documents=[(doc.name, doc.read_bytes())],
               tables={"bank_statement": [("bank.csv", b"Date,Narrative\n01/10/2026,nothing useful\n")]})
    assert any("bank.csv" in w and "missing required column" in w for w in res.warnings)
    assert res.downloads


def test_missing_sample_folder_is_a_friendly_error(config, tmp_path):
    with pytest.raises(PipelineError, match="sample data files could not be found"):
        pipeline.sample_inputs(tmp_path, config)
