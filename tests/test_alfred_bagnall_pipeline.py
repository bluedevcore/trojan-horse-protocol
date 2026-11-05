"""End-to-end: the Alfred Bagnall (Debtor & Filing Agent) demo on its sample data, in mock mode."""

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

CLIENT = Path(__file__).resolve().parent.parent / "clients" / "alfred-bagnall"

# (check, who) for each problem planted by sample_data/generate.py
EXPECTED = {
    ("Seriously overdue", "Ambleford Property Management Ltd"),
    ("Disputed invoice", "Lessmoor Academy Trust"),
    ("Payment not matched to an invoice", "BANK GIRO CREDIT 000418"),
    ("Part payment", "Riverholt Housing Association"),
    ("Over credit limit", "Corvel Logistics Ltd"),
    ("No contact email", "Quarrendon Court RMC Ltd"),
    ("Customer in credit", "Oakmere Medical Centre"),
    ("Could not tell which project", "Riverholt Housing Association"),
    ("Could not tell which project", "Brightline Trade Paints Ltd"),
    ("Could not tell which project", "Pelham Rise Management Ltd"),
    ("Document could not be read", "2026-10-29_quarrendon_signed-completion-photo.jpg"),
}
CHASE = {"Ambleford Property Management Ltd": "Final notice", "Corvel Logistics Ltd": "Second reminder",
         "Quarrendon Court RMC Ltd": "Second reminder", "Riverholt Housing Association": "Second reminder",
         "Grayling & Fosse Lettings Ltd": "Reminder", "Larkhollow Hotels Ltd": "Reminder", "Lessmoor Academy Trust": "Reminder"}


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
    assert len(exc) == 11 and list(exc["ID"]) == [f"EX-{i:02d}" for i in range(1, 12)]
    assert result.facts["by_severity"] == {"High": 1, "Medium": 4, "Low": 6}


def test_human_check_list(result):
    checks = {c.title.split(" — ")[0] for c in result.human_checks}
    assert len(result.human_checks) == 10 and result.facts["needs_human_check"] == 10
    assert "Seriously overdue" in checks and "Part payment" not in checks  # the balance is simply chased
    assert all(c.why and c.action for c in result.human_checks)


def test_every_claude_call_is_served_from_fixtures(result):
    """If this fails, prompts/config/data changed: run
    python -m tools.bookkeeping.refresh_fixtures clients/alfred-bagnall"""
    assert {c.source for c in result.test_calls} == {"fixture"}
    assert result.ai_sources == {"fixture": 23 + 3 + 1}  # documents, email batches, summary (no coding)
    assert "Ambleford" in result.summary and "Pre-recorded" in result.summary_source
    assert {d["extracted_by"] for d in result.documents} == {"AI (pre-recorded)"}
    assert all(l["source"] == "fixture" for l in result.letters)


def test_documents_are_read_but_not_posted(result):
    assert result.facts["documents"] == 23
    assert result.facts["documents_by_type"] == {"correspondence": 11, "contract": 4, "other": 3, "purchase order": 3,
                                                 "remittance": 2}
    assert result.entries.empty and not result.exports  # no purchase ledger: nothing is coded or exported


def test_receipts_are_matched_and_debtors_aged(result):
    d = result.debtors.set_index("invoice_number")
    cleared = set(d[(d["outstanding"].abs() < 0.005) & (d["received"] > 0)].index)
    assert cleared == {"SI-30341", "SI-30364", "SI-30377", "SI-30392", "SI-30361", "SI-30404"}
    assert d.loc["SI-30372", "received"] == 12000.0 and d.loc["SI-30372", "outstanding"] == 4350.0  # part payment
    assert d.loc["SI-30318", "days_overdue"] == 83 and d.loc["SI-30318", "chase_tier"] == "Final notice"
    assert d.loc["SI-30388", "chase_tier"] == "" and bool(d.loc["SI-30388", "disputed"])
    assert d.loc["SI-30407", "bucket"] == "Current" and d.loc["CN-0412", "outstanding"] == -540.0
    tiers = d[d["chase_tier"] != ""].groupby("customer")["chase_tier"].agg(
        lambda s: max(s, key=["Reminder", "Second reminder", "Final notice"].index)).to_dict()
    assert tiers == CHASE


def test_totals_cross_check(result):
    d = result.debtors
    bank = pd.read_csv(CLIENT / "sample_data" / "bank_statement_oct-2026.csv")
    money_in = round(bank["Money in"].fillna(0).sum(), 2)
    assert money_in == 52380.0
    # every pound received is either allocated to an invoice or flagged as unallocated
    assert round(d["received"].sum(), 2) == money_in - 1950.0
    ledger = pd.read_excel(CLIENT / "sample_data" / "sales_ledger_open_invoices.xlsx")
    assert round(ledger["Amount"].sum() - ledger["Paid"].sum() - d["received"].sum(), 2) == 94346.0
    assert result.facts["debtors_outstanding"] == round(d["outstanding"].sum(), 2) == 94346.0
    assert result.facts["debtors_overdue"] == round(d[d["days_overdue"] > 0]["outstanding"].sum(), 2) == 68220.0
    summary = result.debtors_summary.set_index("Customer")
    assert round(summary["Total outstanding"].sum(), 2) == 94346.0
    assert summary.loc["Riverholt Housing Association", "Total outstanding"] == 24420.0
    buckets = [c for c in summary.columns if c != "Total outstanding"]
    assert (summary[buckets].sum(axis=1).round(2) == summary["Total outstanding"].round(2)).all()


def test_chase_emails(result):
    letters = {l["to"]: l for l in result.letters}
    assert [l["key"] for l in result.letters] == [f"customer:{c}" for c in sorted(CHASE)]
    assert {k: l["tone_label"] for k, l in letters.items()} == CHASE
    lessmoor = letters["Lessmoor Academy Trust"]
    assert "SI-30389" in lessmoor["body"] and "SI-30388" not in lessmoor["body"]  # disputed: not chased
    assert "final notice" in letters["Ambleford Property Management Ltd"]["body"].lower()
    assert "£4,350.00" in letters["Riverholt Housing Association"]["body"]  # the balance after the part payment
    assert letters["Quarrendon Court RMC Ltd"]["email"] == ""
    assert all(l["body"].startswith("Hello ") and "Kind regards," in l["body"] for l in result.letters)


def test_documents_are_filed_to_project_folders(result):
    f = result.filing.set_index("Original file")
    assert (result.facts["filing_filed"], result.facts["filing_to_file"]) == (20, 3)
    assert f["Filed by"].value_counts().to_dict() == {"reference on the document": 15, "site / keyword match": 5,
                                                      "needs a person": 3}
    assert f.loc["2026-10-14_kestrelgate_remittance-advice.eml", "Folder"] == \
        "J-4126 New-build painting package - Wharfside Quarter/Payments"
    assert f.loc["2026-10-27_riverholt_new-invoicing-address.eml", "Folder"] == "_To file"  # two Riverholt projects
    assert f.loc["2026-10-21_brightline_delivery-note-DN-60417.pdf", "Project"] == ""  # J-4211 is not on the register
    assert set(f["Project"]) - {""} <= set(pd.read_csv(CLIENT / "sample_data" / "project_register.csv")["Project Ref"])


def test_checklist(result):
    status = dict(zip(result.checklist["Item"], result.checklist["Status"]))
    assert status["Overdue accounts chased"] == "Action needed"
    assert status["Documents filed to project folders"] == "Action needed"
    assert list(status.values()).count("To do") == 4


def test_progress_steps_tell_the_story(result):
    labels = [s.label for s in result.test_steps]
    assert labels[0] == "Read 23 documents and 4 spreadsheets"
    assert "Aged 26 open invoices: £94,346.00 outstanding" in labels
    assert "Filed 20 of 23 documents" in labels and labels[-1] == "Built 5 output files"
    assert any(l.startswith("Found 11 exceptions") for l in labels)
    assert not any("invoices and receipts" in l for l in labels)  # purchases are switched off
    assert all(s.status != "running" for s in result.test_steps)


def test_every_output_file_is_valid(result):
    files = {f.file_name.split("_", 2)[-1]: f for f in result.downloads}
    assert set(files) == {"debtors-and-filing-pack.xlsx", "credit-control-report.pdf", "drafted-emails.docx",
                          "exceptions.csv", "filed-documents.zip"}
    assert all(f.file_name.startswith("debtor-filing-agent_2026-10_") for f in result.downloads)
    exc = pd.read_csv(io.BytesIO(files["exceptions.csv"].data), encoding="utf-8-sig")
    assert len(exc) == 11
    wb = load_workbook(io.BytesIO(files["debtors-and-filing-pack.xlsx"].data))
    assert {"Summary", "Month-end checklist", "Exceptions", "Needs human check", "Aged debtors", "Debtors by customer",
            "Filing index", "Documents read", "Emails drafted"} <= set(wb.sheetnames)
    assert "Coded entries" not in wb.sheetnames
    assert wb["Exceptions"].max_row == 12 and wb["Aged debtors"].max_row == 27 and wb["Filing index"].max_row == 24
    items = [row[0].value for row in wb["Summary"].iter_rows(min_row=2)]
    assert "Documents filed" in items and "Ledger lines" not in items
    assert files["credit-control-report.pdf"].data.startswith(b"%PDF")
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(files["drafted-emails.docx"].data)).namelist()
    names = zipfile.ZipFile(io.BytesIO(files["filed-documents.zip"].data)).namelist()
    assert len(names) == 24 and "filing-index.csv" in names  # 23 documents + the index (the photo can't be filed)
    assert sum(n.startswith("_To file/") for n in names) == 3


def test_time_saved_is_positive_and_explained(result):
    est = result.time_estimate
    assert est.manual_minutes == 311 and est.with_tool_minutes == 64
    assert est.saved_minutes > 180 and len(est.assumptions) == 8

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
    files = [(p.name, p.read_bytes()) for p in sorted((sample / "inbox").iterdir())[:8]]
    files += [("ledger.xlsx", (sample / "sales_ledger_open_invoices.xlsx").read_bytes()),
              ("bank.csv", (sample / "bank_statement_oct-2026.csv").read_bytes()),
              ("notes.csv", b"Colour,Size\nred,big\n"), ("broken.xlsx", b"not really a spreadsheet")]
    inputs = pipeline.upload_inputs(files, config, CLIENT)
    assert set(inputs.tables) == {"open_invoices", "bank_statement", "customers", "projects"}  # lists from the demo
    assert sum("could not tell" in n for n in inputs.notes) == 2
    res = pipeline.run(inputs, config, ClaudeClient(mock=True))
    assert any("using the demo's sample ones" in w for w in res.warnings)
    assert set(res.ai_sources) <= {"mock"} and res.downloads
    assert res.entries.empty  # the pattern reader may call a letter an invoice; purchases are off, so nothing is coded
    assert len(res.debtors) == 26 and round(res.debtors["received"].sum(), 2) == 50430.0  # same matching as the sample
    assert res.filing["Project"].astype(str).str.startswith("J-").sum() >= 6  # job numbers found in the text
    assert any(c.id == "AI" for c in res.human_checks)  # template text is flagged for review


def test_upload_with_nothing_readable_is_a_friendly_error(config):
    inputs = pipeline.upload_inputs([("empty.pdf", b""), ("notes.csv", b"Colour,Size\nred,big\n")], config, CLIENT)
    assert inputs.fallback_roles and len(inputs.notes) == 1
    with pytest.raises(PipelineError, match="None of the files could be read"):
        pipeline.run(inputs, config, ClaudeClient(mock=True))


def test_missing_sample_folder_is_a_friendly_error(config, tmp_path):
    with pytest.raises(PipelineError, match="sample data files could not be found"):
        pipeline.sample_inputs(tmp_path, config)
