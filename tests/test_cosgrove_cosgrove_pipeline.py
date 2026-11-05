"""End-to-end: the Cosgrove & Cosgrove demo on its sample data, in mock mode."""

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

CLIENT = Path(__file__).resolve().parent.parent / "clients" / "cosgrove-cosgrove"

# (check, who) for each problem planted by sample_data/generate.py
EXPECTED = {
    ("Supplier bank details changed", "Brindlecote IT Services Ltd"),
    ("Totals don't add up", "Coalbrook Waste Services Ltd"),
    ("Dated before this period", "Stirling Lane Packaging Ltd"),
    ("Duplicate invoice", "Severnvale Office Supplies Ltd"),
    ("Coding needs a decision", "Parcelbay Marketplace"),
    ("New supplier", "Norbridge Tool Supplies Ltd"),
    ("Prepayment to spread", "Marchmont Insurance Brokers Ltd"),
    ("VAT number fails HMRC check", "Norbridge Tool Supplies Ltd"),
    ("Overseas supplier: reverse charge", "Layoutly Inc."),
    ("VAT charged without a VAT number", "Hadley Brook Cleaning"),
    ("VAT not reclaimable", "Ember & Oak Café"),
    ("Missing receipt", "Alex Morgan"),
    ("Missing receipt", "Ravi Shah"),
    ("Receipt with no card transaction", "Forgeway Trade Counter"),
    ("Receipt and card amounts differ", "Alex Morgan"),
    ("Net pay doesn't reconcile", "Jordan Hale"),
    ("Customer PO missing", "Castlegate Developments Ltd"),
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
    assert set(zip(exc["Check"], exc["Who"])) == EXPECTED
    assert len(exc) == 17 and list(exc["ID"]) == [f"EX-{i:02d}" for i in range(1, 18)]
    assert result.facts["by_severity"] == {"High": 4, "Medium": 10, "Low": 3}


def test_human_check_list(result):
    checks = {c.title.split(" — ")[0] for c in result.human_checks}
    assert len(result.human_checks) == 12 and result.facts["needs_human_check"] == 12
    assert "Supplier bank details changed" in checks and "Missing receipt" not in checks  # receipts are chased by email
    assert all(c.why and c.action for c in result.human_checks)


def test_every_claude_call_is_served_from_fixtures(result):
    """If this fails, prompts/config/data changed: run
    python -m tools.bookkeeping.refresh_fixtures clients/cosgrove-cosgrove"""
    assert {c.source for c in result.test_calls} == {"fixture"}
    assert result.ai_sources == {"fixture": 28 + 1 + 3 + 1}  # documents, coding, email batches, summary
    assert "Brindlecote" in result.summary and "Pre-recorded" in result.summary_source
    assert {d["extracted_by"] for d in result.documents} == {"AI (pre-recorded)"}
    assert all(l["source"] == "fixture" for l in result.letters)


def test_documents_are_read_and_matched(result):
    types = result.facts["documents_by_type"]
    assert result.facts["documents"] == 28 and types == {"invoice": 15, "receipt": 12, "credit note": 1}
    card = result.card.set_index("Txn")
    assert result.facts["card_matched"] == 13 and result.facts["card_txns"] == 17
    assert card.loc["T-04", "Status"] == "Amount differs" and card.loc["T-08", "Receipt currency"] == "USD"
    assert set(card[card["Status"] == "Receipt missing"]["Merchant"]) == {"MERECROFT TYRE & AUTO", "STOCKFRAME IMAGES"}
    assert set(card[card["Status"] == "No receipt needed"]["Merchant"]) == {"NON-STERLING TRANSACTION FEE", "TELFORD CENTRE CAR PARK"}


def test_coding_and_vat_treatment(result):
    e = result.entries
    by_payee = e.groupby("counterparty")
    assert set(by_payee.get_group("Ember & Oak Café")["vat_code"]) == {"O"}  # entertainment: VAT blocked
    assert set(by_payee.get_group("Ember & Oak Café")["account"]) == {"Entertainment"}
    assert by_payee.get_group("Layoutly Inc.")["vat_code"].tolist() == ["RC"]
    dawbury = by_payee.get_group("Dawbury Print & Signs Ltd").set_index("vat_code")
    assert dawbury.loc["Z", "net"] == 540.0 and dawbury.loc["S", "vat"] == 36.0  # mixed-rate invoice split
    assert by_payee.get_group("Marchmont Insurance Brokers Ltd")["vat_code"].tolist() == ["E"]
    coded_by = e.drop_duplicates("group")["coded_by"].value_counts().to_dict()
    assert coded_by == {"supplier list": 12, "Claude": 11, "rule": 8}


def test_totals_cross_check(result):
    e = result.entries
    # every card payment is fully posted, including tips and payments without a receipt
    card_total = round(e[e["kind"] == "card_expense"]["gross"].sum(), 2)
    assert card_total == result.facts["card_spend"] == 779.66
    # bills: one per unique on-account invoice, at net + VAT (not the mis-added printed total)
    bills = e[e["kind"] == "bill"].groupby("doc_id")["gross"].sum()
    invoices = [1488.00, 540.00, 1846.20, 223.68, 171.00, 772.50, 252.00, 467.04, 756.00, 228.00, 384.00, 222.00]
    assert len(bills) == 12 and round(bills.sum(), 2) == round(sum(invoices), 2)
    assert e[(e["counterparty"] == "Coalbrook Waste Services Ltd")]["gross"].sum() == 252.00
    # the QuickBooks bills file holds exactly the ready bills
    files = {x.key: x.frame for x in result.exports}
    qb = files["quickbooks_bills"]
    ready = e[(e["kind"] == "bill") & (e["status"] == "Ready")]
    assert round((qb["Line Amount"] + qb["Line Tax Amount"]).sum(), 2) == round(ready["gross"].sum(), 2)
    assert not set(qb["Bill No"]) & {"BIT-2026-1043", "CWS-40218", "118", "NTS-5521"}  # held
    ready = e[e["status"] == "Ready"]
    credits = ready["kind"] == "supplier_credit"
    # credit notes are stored positive and subtracted
    assert result.facts["value_ready"] == round(ready.loc[~credits, "gross"].sum() - ready.loc[credits, "gross"].sum(), 2) == 6679.88


def test_payroll_journal_and_sales_invoices(result):
    j = result.journal
    assert round(j["debit"].sum(), 2) == round(j["credit"].sum(), 2)
    assert j.set_index("account").loc["Suspense", "debit"] == 100.0
    assert result.facts["payroll_gross"] == 34330.0 and result.facts["payroll_employees"] == 14
    s = result.sales
    assert s["invoice_number"].nunique() == 5 and round(s["gross"].sum(), 2) == 6806.58
    assert set(s[s["status"] == "Held"]["customer"]) == {"Castlegate Developments Ltd"}
    qb_inv = {x.key: x.frame for x in result.exports}["quickbooks_invoices"]
    assert "INV-4823" not in set(qb_inv["Invoice No"]) and qb_inv["Invoice No"].nunique() == 4


def test_emails_and_month_end_checklist(result):
    keys = [l["key"] for l in result.letters]
    assert keys == ["supplier:Brindlecote IT Services Ltd", "supplier:Coalbrook Waste Services Ltd",
                    "supplier:Hadley Brook Cleaning", "supplier:Norbridge Tool Supplies Ltd",
                    "payroll_bureau:Kettlewell Payroll & Accounts Ltd", "cardholder:Alex Morgan", "cardholder:Ravi Shah",
                    "customer:Castlegate Developments Ltd"]
    bank = result.letters[0]["body"]
    assert "phone" in bank and "never change bank details" in bank.lower()
    status = dict(zip(result.checklist["Item"], result.checklist["Status"]))
    assert status["Duplicate invoices removed"] == "Done"
    assert status["Supplier bank detail changes verified"] == "Action needed"
    assert list(status.values()).count("To do") == 4


def test_progress_steps_tell_the_story(result):
    labels = [s.label for s in result.test_steps]
    assert labels[0] == "Read 28 documents and 6 spreadsheets"
    assert "Matched 13 of 17 card transactions to receipts" in labels
    assert any(l.startswith("Found 17 exceptions") for l in labels)
    assert all(s.status != "running" for s in result.test_steps)


def test_every_output_file_is_valid(result):
    files = {f.file_name.split("_", 2)[-1]: f for f in result.downloads}
    assert set(files) == {"quickbooks-bills.csv", "quickbooks-supplier-credits.csv", "quickbooks-card-expenses.csv",
                          "quickbooks-payroll-journal.csv", "quickbooks-sales-invoices.csv", "bookkeeping-pack.xlsx",
                          "month-end-report.pdf", "drafted-emails.docx", "exceptions.csv"}
    for name, f in files.items():
        if name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(f.data), encoding="utf-8-sig")
            assert len(df) > 0, name
    wb = load_workbook(io.BytesIO(files["bookkeeping-pack.xlsx"].data))
    assert {"Summary", "Month-end checklist", "Exceptions", "Coded entries", "Card matching", "Payroll journal",
            "Sales invoices", "Documents read", "Emails drafted"} <= set(wb.sheetnames)
    assert wb["Exceptions"].max_row == 18 and wb["Coded entries"].max_row == 35
    assert not any(str(c.value).startswith("_") for c in wb["Card matching"][1])
    assert files["month-end-report.pdf"].data.startswith(b"%PDF")
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(files["drafted-emails.docx"].data)).namelist()
    journal = pd.read_csv(io.BytesIO(files["quickbooks-payroll-journal.csv"].data), encoding="utf-8-sig")
    assert round(journal["Debits"].fillna(0).sum(), 2) == round(journal["Credits"].fillna(0).sum(), 2)


def test_time_saved_is_positive_and_explained(result):
    est = result.time_estimate
    assert est.saved_minutes > 120 and len(est.assumptions) == 10

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
    inbox = CLIENT / "sample_data" / "inbox"
    files = [(p.name, p.read_bytes()) for p in sorted(inbox.iterdir())[:6]]
    files += [("statement.csv", (CLIENT / "sample_data" / "company_card_statement_oct-2026.csv").read_bytes()),
              ("notes.csv", b"Colour,Size\nred,big\n"), ("photo.png", b"\x89PNG")]
    inputs = pipeline.upload_inputs(files, config, CLIENT)
    assert set(inputs.tables) == {"card_statement", "suppliers", "customers", "chart_of_accounts"}  # lists from the demo
    assert any("notes.csv" in n for n in inputs.notes)
    res = pipeline.run(inputs, config, ClaudeClient(mock=True))
    assert any("using the demo's sample ones" in w for w in res.warnings)
    assert set(res.ai_sources) <= {"mock"} and res.downloads
    assert any(f.check_id == "unreadable_document" for f in res.findings)  # the photo
    assert any(c.id == "AI" for c in res.human_checks)  # template text is flagged for review


def test_upload_with_nothing_readable_is_a_friendly_error(config):
    inputs = pipeline.upload_inputs([("empty.pdf", b""), ("notes.csv", b"Colour,Size\nred,big\n")], config, CLIENT)
    assert inputs.fallback_roles and len(inputs.notes) == 1  # the skipped spreadsheet
    with pytest.raises(PipelineError, match="None of the files could be read"):
        pipeline.run(inputs, config, ClaudeClient(mock=True))


def test_missing_sample_folder_is_a_friendly_error(config, tmp_path):
    with pytest.raises(PipelineError, match="sample data files could not be found"):
        pipeline.sample_inputs(tmp_path, config)
