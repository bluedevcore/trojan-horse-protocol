import pandas as pd

from tools.data_validation.deadlines import build_tracker

AS_OF = pd.Timestamp("2026-11-05")


def calendar():
    return pd.DataFrame([
        {"obligation": "Sent already", "due_date": "01/11/2026", "submitted_on": "31/10/2026", "scope": "All"},
        {"obligation": "Overdue", "due_date": "04/11/2026", "submitted_on": "", "scope": "Heat"},
        {"obligation": "Soon PV", "due_date": "10/11/2026", "submitted_on": "", "scope": "PV",
         "period_start": "01/08/2026", "period_end": "31/10/2026"},
        {"obligation": "Later import, October only", "due_date": "30/11/2026", "submitted_on": "", "scope": "Import",
         "period_start": "01/10/2026", "period_end": "31/10/2026"},
    ])


def exceptions():
    return pd.DataFrame([
        {"ID": "EX-1", "Severity": "High", "Needs human check": "Yes", "Type": "PV",
         "_from": pd.Timestamp("2026-08-22"), "_to": pd.Timestamp("2026-08-22")},
        {"ID": "EX-2", "Severity": "Medium", "Needs human check": "Yes", "Type": "Import",
         "_from": pd.Timestamp("2026-09-14"), "_to": pd.Timestamp("2026-09-14")},  # outside October
        {"ID": "EX-3", "Severity": "Low", "Needs human check": "No", "Type": "Import",
         "_from": pd.Timestamp("2026-10-02"), "_to": pd.Timestamp("2026-10-02")},  # not "open"
    ])


def test_tracker_status_and_blocking():
    t = build_tracker(calendar(), as_of=AS_OF, exceptions=exceptions(), category_heading="Type").set_index("Obligation")
    assert t.loc["Sent already", "Status"].startswith("Submitted") and t.loc["Sent already", "RAG"] == "Green"
    assert t.loc["Overdue", "Status"] == "Overdue by 1 day" and t.loc["Overdue", "RAG"] == "Red"
    assert t.loc["Soon PV", "Status"] == "Due in 5 days"
    assert t.loc["Soon PV", "Data readiness"].startswith("Blocked: 1 open exception (EX-1")
    assert t.loc["Soon PV", "RAG"] == "Red"  # due soon and blocked
    assert t.loc["Later import, October only", "Data readiness"] == "Data ready"
    assert t.loc["Later import, October only", "RAG"] == "Green"


def test_tracker_without_calendar_is_empty():
    assert build_tracker(pd.DataFrame(), as_of=AS_OF, exceptions=exceptions(), category_heading=None).empty
