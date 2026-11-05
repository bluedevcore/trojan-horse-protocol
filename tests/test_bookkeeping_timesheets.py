"""Timesheet checks in the bookkeeping engine: overlapping lines, hours on closed or
unknown jobs, holds on the weekly hours, the payroll hours file, hours by job, and
timesheet queries emailed to a single named contact."""

import pandas as pd

from core.claude import ClaudeClient
from tools.bookkeeping import pipeline, reports
from tools.bookkeeping.checks import finalise
from tools.bookkeeping.exports import payroll_hours_csv, sage_transactions
from tools.bookkeeping.payroll import hold_hours, hours_by_job, hours_key, timesheet_hours
from tools.bookkeeping.pipeline import RunInputs
from tools.bookkeeping.tables import TABLE_SPECS, load_table

EMPLOYEES = pd.DataFrame({"employee": ["Ann Lee", "Bo Diaz"], "employee_id": ["A1", "B2"],
                          "hourly_rate": [15.0, 14.0], "contracted_hours": [40.0, 40.0]})
JOBS = pd.DataFrame({"project_ref": ["J-100", "J-090"], "project_name": ["School", "Retail unit"],
                     "status": ["Open", "Closed"]})


def _ts(rows):
    df = pd.DataFrame(rows, columns=["employee", "date", "job", "start", "finish", "break_minutes", "approved_by"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _week(name, job="J-100", approved="GH"):
    return [(name, f"2026-10-{d}", job, "07:30", "16:00", 30, approved) for d in (26, 27, 28, 29, 30)]


def test_overlapping_lines_are_flagged_but_duplicates_are_not():
    rows = _week("Ann Lee") + _week("Bo Diaz")
    rows[2] = ("Ann Lee", "2026-10-28", "J-100", "07:30", "15:30", 30, "GH")
    rows.append(("Ann Lee", "2026-10-28", "J-100", "14:00", "18:00", 0, "GH"))  # overlaps by 1.5 hours
    rows.append(rows[6])  # Bo Diaz Tue keyed twice: a duplicate, not an overlap
    lines, summary, findings = timesheet_hours(_ts(rows), EMPLOYEES, {})
    checks = [(f.check_id, f.subject) for f in findings]
    assert checks.count(("overlapping_shifts", "Ann Lee")) == 1
    assert ("duplicate_timesheet", "Bo Diaz") in checks and ("overlapping_shifts", "Bo Diaz") not in checks
    overlap = next(f for f in findings if f.check_id == "overlapping_shifts")
    assert "overlap by 1.5 hours" in overlap.finding and "07:30–15:30" in overlap.finding
    assert overlap.entry_keys == [hours_key("Ann Lee", pd.Timestamp("2026-10-26"))]
    assert overlap.ref_text == "Ann Lee · Wed 28 Oct 2026" and overlap.ask
    bo = summary.set_index("Employee").loc["Bo Diaz"]
    assert bo["Total hours"] == 40.0  # the duplicate is counted once
    assert lines["duplicate"].sum() == 1


def test_hours_on_closed_or_unknown_jobs_are_grouped_per_person_and_job():
    rows = _week("Ann Lee") + _week("Bo Diaz")
    rows[0] = ("Ann Lee", "2026-10-26", "J-090", "07:30", "16:00", 30, "GH")
    rows[1] = ("Ann Lee", "2026-10-27", "j 090", "07:30", "16:00", 30, "GH")  # same job, typed differently
    rows[9] = ("Bo Diaz", "2026-10-30", "J-910", "07:30", "16:00", 30, "GH")
    lines, _, findings = timesheet_hours(_ts(rows), EMPLOYEES, {}, jobs=JOBS)
    by = {f.check_id: f for f in findings}
    assert set(by) == {"closed_job", "unknown_job"}
    assert by["closed_job"].finding.startswith("16 hours on Mon 26 Oct, Tue 27 Oct booked to J-090 (Retail unit)")
    assert "marked “Closed” on the job list" in by["closed_job"].finding
    assert by["unknown_job"].subject == "Bo Diaz" and by["unknown_job"].reference == "J-910"
    assert set(lines["job_status"]) == {"Open", "Closed", "Not on job list"}
    # without a job list the job checks do not run
    _, _, plain = timesheet_hours(_ts(rows), EMPLOYEES, {})
    assert not {"closed_job", "unknown_job"} & {f.check_id for f in plain}


def test_held_weeks_stay_out_of_the_payroll_hours_file():
    rows = _week("Ann Lee") + _week("Bo Diaz") + _week("Cy New")
    rows[4] = ("Ann Lee", "2026-10-30", "J-100", "07:30", "16:00", 30, "")  # not signed off
    _, summary, findings = timesheet_hours(_ts(rows), EMPLOYEES, {"require_approval": True})
    findings = finalise(findings, {})
    hours = hold_hours(summary, findings).set_index("Employee")
    assert hours.loc["Bo Diaz", "Status"] == "Ready" and hours.loc["Bo Diaz", "Held because"] == ""
    assert hours.loc["Ann Lee", "Status"] == "Held" and hours.loc["Cy New", "Status"] == "Held"  # unsigned; not on list
    csv = payroll_hours_csv(None, {}, hours=hours.reset_index())
    assert csv["Employee"].tolist() == ["Bo Diaz"]
    assert payroll_hours_csv(None, {}, hours=summary)["Employee"].nunique() == 3  # no holds applied: everything


def test_hours_by_job_counts_each_line_once():
    rows = _week("Ann Lee") + _week("Bo Diaz", job="J-090")
    rows.append(rows[0])
    lines, _, _ = timesheet_hours(_ts(rows), EMPLOYEES, {}, jobs=JOBS)
    jobs = hours_by_job(lines).set_index("Job")
    assert jobs.loc["J-100", "Hours"] == 40.0 and jobs.loc["J-100", "Lines"] == 5
    assert jobs.loc["J-090", "Job status"] == "Closed"


def test_job_list_status_column_is_read():
    data = b"Job Ref,Job Name,Site,Status\nJ-100,School,Oak Lane,Open\nJ-090,Retail unit,Park Road,Closed\n"
    df = load_table("jobs.csv", data, TABLE_SPECS["projects"])
    assert df["status"].tolist() == ["Open", "Closed"]


def test_sage_can_carry_the_job_as_a_project_reference():
    entries = pd.DataFrame([{"kind": "bill", "status": "Ready", "supplier_ref": "ACME01", "counterparty": "Acme",
                             "account_code": "5000", "account": "Materials", "tracking": "J-100", "date": pd.Timestamp("2026-10-05"),
                             "reference": "A-1", "description": "Boards", "net": 100.0, "vat": 20.0, "vat_code": "S", "memo": ""}])
    default = sage_transactions(entries, {}).iloc[0]
    assert default["Department Code"] == "J-100" and default["Project Refn"] == ""
    project = sage_transactions(entries, {"tracking_as_project": True}).iloc[0]
    assert project["Department Code"] == "" and project["Project Refn"] == "J-100"


def test_timesheet_queries_go_to_one_named_contact():
    ts = pd.DataFrame({"Employee": ["Ann Lee"] * 2 + ["Bo Diaz"], "Date": ["26/10/2026", "31/10/2026", "26/10/2026"],
                       "Start": ["07:30", "08:00", "07:30"], "Finish": ["16:00", "13:00", "16:00"], "Break (mins)": [30, 0, 30],
                       "Signed Off By": ["GH", "", "GH"]}).to_csv(index=False).encode()
    emp = EMPLOYEES.rename(columns={"employee": "Employee", "employee_id": "Employee ID", "hourly_rate": "Hourly Rate",
                                    "contracted_hours": "Contracted Hours"}).to_csv(index=False).encode()
    config = {"headline": "X: built as a prototype for Y", "company": {"name": "Demo Ltd"},
              "exports": ["payroll_hours"], "timesheets": {"weekend_multiplier": 1.5},
              "checks": {"missing_approval": {"letter": "site_manager"}},
              "contacts": {"site_manager": {"name": "Contracts manager", "contact": "Gwen Hall", "email": "gh@x.example"}}}
    r = pipeline.run(RunInputs(tables={"timesheets": [("ts.csv", ts)], "employees": [("emp.csv", emp)]},
                               period=(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31"))), config, ClaudeClient(mock=True))
    [letter] = r.letters
    assert letter["key"] == "site_manager:Contracts manager" and letter["email"] == "gh@x.example"
    assert letter["points"][0]["ref"] == "Ann Lee · Sat 31 Oct 2026" and "Hello Gwen" in letter["body"]
    assert r.exceptions.set_index("Check").loc["Timesheet not approved", "Email drafted to"] == "Contracts manager"
    assert "Sat 31 Oct 2026 (08:00–13:00)" in r.findings[0].finding
    hours = r.hours.set_index("Employee")
    assert hours.loc["Ann Lee", "Status"] == "Held" and hours.loc["Ann Lee", "Weekend hours"] == 5.0
    assert r.facts["hours_ready"] == 8.0 and r.facts["hours_total"] == 21.0
    assert [x.frame["Employee"].tolist() for x in r.exports] == [["Bo Diaz"]]
    assert {"Hours for payroll", "Timesheet lines"} <= set(reports.sheets(r))
