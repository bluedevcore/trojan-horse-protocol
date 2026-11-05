"""End-to-end: the Complete Fixing Solutions demo on its sample data, in mock mode."""

import io
import time
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from core.claude import ClaudeClient
from core.ui import StepProgress
from tools.bookkeeping import pipeline, reports
from tools.bookkeeping.pipeline import PipelineError, RunInputs
from tools.bookkeeping.views import load_config

CLIENT = Path(__file__).resolve().parent.parent / "clients" / "complete-fixing-solutions"

# (check, who) for each problem planted by sample_data/generate.py
EXPECTED = {
    ("Supplier bank details changed", "Dee Valley Fixings Ltd"),
    ("Totals don't add up", "Pandy Timber & Sheet Ltd"),
    ("Duplicate invoice", "Clwyd Board & Stud Supplies Ltd"),
    ("New supplier", "Ridgeway Safety & Workwear Ltd"),
    ("Not on the employee list (new starter?)", "Rhys Talbot"),
    ("Timesheet not signed off", "Kieran Molloy"),
    ("Overlapping timesheet lines", "Callum Rees"),
    ("Duplicate timesheet entry", "Siân Edwards"),
    ("Hours don't match start/finish", "Aled Parry"),
    ("Over the daily hours limit", "Josh Kendrick"),
    ("Hours on a closed job", "Liam Carney"),
    ("Job not on the job list", "Huw Jarman"),
    ("No timesheet", "Patryk Zielinski"),
    ("Invoice exceeds the PO", "Clwyd Board & Stud Supplies Ltd"),
    ("Invoice exceeds the PO", "Alyn Access & Plant Hire Ltd"),
    ("PO number not recognised", "Border Ceiling Systems Ltd"),
    ("PO raised with a different supplier", "Cestrian Tool Hire Ltd"),
    ("Invoice without a PO", "Ridgeway Safety & Workwear Ltd"),
}
HELD_REFS = {"DVF-55187", "PTS-6604", "CBS-30922", "AAP-7731", "BCS-11820", "CTH-09126", "RSW-2208"}


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
    assert len(exc) == 18 and list(exc["ID"]) == [f"EX-{i:02d}" for i in range(1, 19)]
    assert result.facts["by_severity"] == {"High": 4, "Medium": 14}


def test_human_check_list(result):
    checks = {c.title.split(" — ")[0] for c in result.human_checks}
    assert len(result.human_checks) == 15 and result.facts["needs_human_check"] == 15
    assert {"Supplier bank details changed", "Overlapping timesheet lines", "Timesheet not signed off"} <= checks
    assert not {"No timesheet", "Duplicate timesheet entry", "Duplicate invoice"} & checks  # chased or handled
    assert all(c.why and c.action for c in result.human_checks)
    overlap = next(c for c in result.human_checks if c.title.startswith("Overlapping"))
    assert "Wed 28 Oct 2026" in overlap.why and "1.5 hours" in overlap.why


def test_every_claude_call_is_served_from_fixtures(result):
    """If this fails, prompts/config/data changed: run
    python -m tools.bookkeeping.refresh_fixtures clients/complete-fixing-solutions"""
    assert {c.source for c in result.test_calls} == {"fixture"}
    assert result.ai_sources == {"fixture": 18 + 1 + 3 + 1}  # documents, coding, email batches, summary
    assert "636.5 of 768 hours" in result.summary and "Pre-recorded" in result.summary_source
    assert {d["extracted_by"] for d in result.documents} == {"AI (pre-recorded)"}
    assert all(l["source"] == "fixture" for l in result.letters)


def test_hours_for_payroll(result):
    h = result.hours.set_index("Employee")
    assert len(h) == 18 and result.facts["timesheet_rows"] == 95
    assert set(h[h["Status"] == "Held"].index) == {"Callum Rees", "Kieran Molloy", "Rhys Talbot"}
    assert h.loc["Siân Edwards", "Total hours"] == 43.0  # the line keyed twice counts once
    assert h.loc["Aled Parry", "Total hours"] == 39.0  # 8 hours from the times, not the 10 keyed
    assert (h.loc["Josh Kendrick", "Basic hours"], h.loc["Josh Kendrick", "Overtime hours"]) == (40.0, 7.5)
    assert h.loc["Tomasz Nowicki", "Weekend hours"] == 5.0 and h.loc["Kieran Molloy", "Weekend hours"] == 5.0
    assert pd.isna(h.loc["Rhys Talbot", "Gross pay (est.)"])  # no rate: not on the employee list
    f = result.facts
    assert (f["hours_total"], f["hours_ready"], f["hours_overtime"], f["hours_weekend"]) == (768.0, 636.5, 39.0, 15.0)
    # gross pay is basic + time and a half for overtime and weekend hours, at each person's rate
    ready = h[h["Status"] == "Ready"]
    expect = (ready["Hourly rate"] * (ready["Basic hours"] + 1.5 * (ready["Overtime hours"] + ready["Weekend hours"]))).round(2)
    assert (abs(expect - ready["Gross pay (est.)"]) < 0.006).all() and f["gross_pay_ready_est"] == round(expect.sum(), 2)
    jobs = reports.hours_job_frame(result).set_index("Job")
    assert jobs["Hours"].sum() == 768.0
    assert jobs.loc["J-2588", "Job status"] == "Closed 16/10/2026" and jobs.loc["J-2416", "Job status"] == "Not on job list"


def test_purchase_orders(result):
    po = result.po_table
    assert po["Status"].value_counts().to_dict() == {"Matched": 11, "Awaiting invoice": 5, "Over PO value": 2,
                                                     "PO not found": 1, "Supplier differs": 1, "No PO": 1}
    assert set(po[po["Status"] == "Awaiting invoice"]["Matched PO"]) == {"PO-4407", "PO-4408", "PO-4414", "PO-4417", "PO-4419"}
    by_inv = po.set_index("Invoice")
    assert by_inv.loc["BSW-20417", "Matched PO"] == "PO-4410" and by_inv.loc["BSW-20417", "Matched by"] == "supplier and amount"
    # the second copy of CBS-30871 is not counted against PO-4404: 3,960 + 2,480, not 3,960 x 2 + 2,480
    assert by_inv.loc["CBS-30922", "Invoiced to date"] == 6440.0 and by_inv.loc["CBS-30922", "Difference"] == 190.0
    assert by_inv.loc["AAP-7731", "Difference"] == 320.0


def test_totals_cross_check(result):
    e = result.entries
    assert e.drop_duplicates("group")["coded_by"].value_counts().to_dict() == {"supplier list": 16, "Claude": 1}
    assert e.set_index("counterparty").loc["Ridgeway Safety & Workwear Ltd", "account"] == "Protective clothing and PPE"
    # bills: one per unique invoice, at net + VAT (not Pandy's mis-added printed total)
    bills = e[e["kind"] == "bill"].groupby("doc_id")["gross"].sum()
    invoices = [1423.68, 4752.00, 462.00, 2657.52, 735.00, 288.00, 891.36, 1814.40, 216.00, 2976.00, 1137.60, 667.20,
                476.10, 1291.68, 1152.00, 180.00]
    assert len(bills) == 16 and round(bills.sum(), 2) == round(sum(invoices), 2)
    assert set(e[e["status"] == "Held"]["reference"]) == HELD_REFS
    assert result.facts["value_ready"] == round(e[e["status"] == "Ready"]["gross"].sum(), 2) == 12369.66
    assert result.facts["value_held"] == 8854.56
    # the Sage file holds exactly the ready entries, with the job as the project reference
    sage = {x.key: x.frame for x in result.exports}["sage50_transactions"]
    ready = e[e["status"] == "Ready"]
    assert len(sage) == len(ready) == 10 and set(sage["Type"]) == {"PI", "PC"}
    assert round((sage["Net Amount"] + sage["Tax Amount"]).sum(), 2) == round(ready["gross"].sum(), 2)
    assert not set(sage["Reference"]) & HELD_REFS
    assert set(sage["Project Refn"]) == {"J-2601", "J-2607", "J-2614", "J-2619"} and set(sage["Department Code"]) == {""}
    assert set(sage["Tax Code"]) == {"T1"}


def test_payroll_hours_file_leaves_held_weeks_out(result):
    hours = {x.key: x.frame for x in result.exports}["payroll_hours"]
    assert len(hours) == 15 and hours["Total hours"].sum() == 636.5
    assert not {"Callum Rees", "Kieran Molloy", "Rhys Talbot"} & set(hours["Employee"])
    assert set(hours["Week Commencing"]) == {"26/10/2026"}


def test_emails_and_checklist(result):
    keys = [l["key"] for l in result.letters]
    assert keys == ["supplier:Alyn Access & Plant Hire Ltd", "supplier:Border Ceiling Systems Ltd",
                    "supplier:Clwyd Board & Stud Supplies Ltd", "supplier:Dee Valley Fixings Ltd",
                    "supplier:Pandy Timber & Sheet Ltd", "supplier:Ridgeway Safety & Workwear Ltd",
                    "contracts_manager:Contracts manager"]
    bank = result.letters[3]["body"]
    assert "phone" in bank and "never change bank details" in bank.lower()
    site = result.letters[-1]
    assert site["email"] == "dylan.hughes@demo-fixings.example" and len(site["points"]) == 8
    assert "Rhys Talbot" in site["body"] and "J-2416" in site["body"]
    drafted_to = dict(zip(result.exceptions["Who"], result.exceptions["Email drafted to"]))
    assert drafted_to["Kieran Molloy"] == "Contracts manager"
    status = dict(zip(result.checklist["Item"], result.checklist["Status"]))
    assert status["Timesheets checked and signed off"] == "Action needed"
    assert status["Duplicate invoices removed"] == "Done" and status["Nominal coding reviewed"] == "Done"
    assert list(status.values()).count("To do") == 4
    detail = dict(zip(result.checklist["Item"], result.checklist["Detail"]))
    assert "3 employee-weeks held" in detail["Timesheets checked and signed off"]


def test_progress_steps_tell_the_story(result):
    labels = [s.label for s in result.test_steps]
    assert labels[0] == "Read 18 documents and 6 spreadsheets"
    assert "job list (7 rows)" in result.test_steps[0].detail
    assert "Summarised hours for 18 employees" in labels and "Matched 11 invoice(s) to purchase orders" in labels
    assert any(l.startswith("Found 18 exceptions") for l in labels)
    assert all(s.status != "running" for s in result.test_steps)


def test_every_output_file_is_valid(result):
    files = {f.file_name.split("_", 2)[-1]: f for f in result.downloads}
    assert set(files) == {"sage50-transactions.csv", "payroll-hours.csv", "bookkeeping-pack.xlsx", "month-end-report.pdf",
                          "drafted-emails.docx", "exceptions.csv"}
    for name, f in files.items():
        if name.endswith(".csv"):
            assert len(pd.read_csv(io.BytesIO(f.data), encoding="utf-8-sig")) > 0, name
    wb = load_workbook(io.BytesIO(files["bookkeeping-pack.xlsx"].data))
    assert {"Summary", "Month-end checklist", "Exceptions", "Coded entries", "Hours for payroll", "Hours by job",
            "Timesheet lines", "PO matching", "Totals by job", "Documents read", "Emails drafted"} <= set(wb.sheetnames)
    assert wb["Exceptions"].max_row == 19 and wb["Coded entries"].max_row == 18 and wb["Timesheet lines"].max_row == 96
    assert not any(str(c.value).startswith("_") for c in wb["PO matching"][1])
    assert files["month-end-report.pdf"].data.startswith(b"%PDF")
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(files["drafted-emails.docx"].data)).namelist()


def test_time_saved_is_positive_and_explained(result):
    est = result.time_estimate
    assert est.saved_minutes > 300 and len(est.assumptions) == 9

# ------------------------------------------------------------ unhappy paths


def _run(config, **kw):
    return pipeline.run(RunInputs(**kw), config, ClaudeClient(mock=True))


def test_no_files_is_a_friendly_error(config):
    with pytest.raises(PipelineError, match="No files to process"):
        _run(config)


def test_only_unreadable_files_is_a_friendly_error(config):
    with pytest.raises(PipelineError, match="None of the files could be read"):
        _run(config, documents=[("timesheet-photo.jpg", b"\xff\xd8"), ("empty.pdf", b"")])


def test_uploads_are_routed_and_run_with_templates(config):
    sample = CLIENT / "sample_data"
    files = [(p.name, p.read_bytes()) for p in sorted((sample / "inbox").iterdir())[:5]]
    files += [("timesheets.xlsx", (sample / "weekly_timesheets_wc-26-oct-2026.xlsx").read_bytes()),
              ("pos.csv", (sample / "purchase_orders_oct-2026.csv").read_bytes()),
              ("notes.csv", b"Colour,Size\nred,big\n"), ("site-photo.png", b"\x89PNG")]
    inputs = pipeline.upload_inputs(files, config, CLIENT)
    assert set(inputs.tables) == {"timesheets", "purchase_orders", "employees", "projects", "suppliers", "chart_of_accounts"}
    assert set(inputs.fallback_roles) == {"employees", "projects", "suppliers", "chart_of_accounts"}
    assert any("notes.csv" in n for n in inputs.notes)
    res = pipeline.run(inputs, config, ClaudeClient(mock=True))
    assert any("using the demo's sample ones" in w for w in res.warnings)
    assert set(res.ai_sources) <= {"mock"} and res.downloads
    assert len(res.hours) == 18 and {"overlapping_shifts", "closed_job"} <= {f.check_id for f in res.findings}
    assert any(f.check_id == "unreadable_document" for f in res.findings)  # the photo
    assert any(c.id == "AI" for c in res.human_checks)  # template text is flagged for review


def test_timesheets_alone_still_run(config):
    sample = CLIENT / "sample_data"
    inputs = pipeline.upload_inputs([("ts.xlsx", (sample / "weekly_timesheets_wc-26-oct-2026.xlsx").read_bytes())],
                                    config, CLIENT)
    res = pipeline.run(inputs, config, ClaudeClient(mock=True))
    assert res.facts["hours_ready"] == 636.5 and res.entries.empty
    assert {x.key for x in res.exports} == {"payroll_hours"}


def test_missing_sample_folder_is_a_friendly_error(config, tmp_path):
    with pytest.raises(PipelineError, match="sample data files could not be found"):
        pipeline.sample_inputs(tmp_path, config)
