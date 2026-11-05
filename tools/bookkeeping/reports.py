"""Output files for a bookkeeping run: the accounting-system import CSVs, an
Excel bookkeeping pack, a PDF month-end report, the drafted emails as an
editable Word file, the exceptions CSV and (with filing on) a zip of the
documents in their project folders."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from core import downloads as dl
from core.ui import DownloadFile
from tools.bookkeeping.vat import CODE_LABELS

if TYPE_CHECKING:  # pragma: no cover
    from tools.bookkeeping.pipeline import RunResult

KIND_LABELS = {"bill": "Bill", "supplier_credit": "Supplier credit", "card_expense": "Card expense",
               "expense_claim": "Expense claim?", "sales_invoice": "Sales invoice"}


def entries_frame(r: "RunResult") -> pd.DataFrame:
    e = r.entries
    if e is None or e.empty:
        return pd.DataFrame()
    out = pd.DataFrame({
        "Entry": e["entry"], "Type": e["kind"].map(KIND_LABELS).fillna(e["kind"]), "Date": e["date"],
        "Reference": e["reference"], "Supplier / payee": e["counterparty"], "Account": e["account"],
        "Description": e["description"], "Net": e["net"], "VAT": e["vat"],
        "VAT code": e["vat_code"].map(lambda c: f"{c} · {CODE_LABELS.get(c, c)}"), "Gross": e["gross"],
        "Status": e["status"], "Held by": e["hold_reason"], "Coded by": e["coded_by"],
        "Why this account": e["coding_reason"], "Doc": e["doc_id"], "Card txn": e["txn_id"], "Source": e["source"],
    })
    return out


def account_totals(r: "RunResult") -> pd.DataFrame:
    e = r.entries
    if e is None or e.empty:
        return pd.DataFrame()
    t = e.groupby("account").agg(Lines=("entry", "count"), Net=("net", "sum"), VAT=("vat", "sum"),
                                 Gross=("gross", "sum")).reset_index().rename(columns={"account": "Account"})
    held = e[e["status"] == "Held"].groupby("account")["gross"].sum()
    t["Held (gross)"] = t["Account"].map(held).fillna(0.0)
    return t.sort_values("Gross", ascending=False).round(2).reset_index(drop=True)


def tracking_totals(r: "RunResult") -> pd.DataFrame:
    """Totals per tracking value (property, project or cardholder), for analysis by site."""
    e = r.entries
    if e is None or e.empty or not (e["tracking"].astype(str).str.strip() != "").any():
        return pd.DataFrame()
    label = (r.config.get("analysis") or {}).get("tracking_label", "Tracking")
    t = e[e["tracking"].astype(str).str.strip() != ""].groupby(["tracking", "account"]).agg(
        Lines=("entry", "count"), Net=("net", "sum"), VAT=("vat", "sum"), Gross=("gross", "sum")).reset_index()
    return t.rename(columns={"tracking": label, "account": "Account"}).round(2)


def journal_frame(r: "RunResult") -> pd.DataFrame:
    j = r.journal
    if j is None or j.empty:
        return pd.DataFrame()
    return pd.DataFrame({"Date": j["date"], "Reference": j["reference"], "Account": j["account"],
                         "Debit": j["debit"].where(j["debit"] != 0), "Credit": j["credit"].where(j["credit"] != 0),
                         "Description": j["description"], "Department": j["class"]})


def payroll_frame(r: "RunResult") -> pd.DataFrame:
    p = r.payroll
    if p is None or p.empty:
        return pd.DataFrame()
    cols = {"employee_id": "Employee ID", "employee": "Employee", "department": "Department", "gross": "Gross",
            "paye": "PAYE", "employee_ni": "Employee NI", "employee_pension": "Employee pension",
            "student_loan": "Student loan", "net_pay": "Net pay (report)", "calculated_net": "Net pay (checked)",
            "net_difference": "Difference", "employer_ni": "Employer NI", "employer_pension": "Employer pension"}
    return p[[c for c in cols if c in p]].rename(columns=cols)


def sales_frame(r: "RunResult") -> pd.DataFrame:
    s = r.sales
    if s is None or s.empty:
        return pd.DataFrame()
    return pd.DataFrame({"Invoice": s["invoice_number"], "Customer": s["customer"], "Date": s["date"], "Due": s["due_date"],
                         "Customer PO": s["po_number"], "Job": s["job"], "Description": s["description"],
                         "Qty": s["quantity"], "Unit price": s["unit_price"], "Net": s["net"], "VAT code": s["vat_code"],
                         "VAT": s["vat"], "Gross": s["gross"], "Status": s["status"], "Held because": s["hold_reason"]})


def debtors_frame(r: "RunResult") -> pd.DataFrame:
    d = r.debtors
    if d is None or d.empty:
        return pd.DataFrame()
    cols = {"customer": "Customer", "invoice_number": "Invoice", "invoice_date": "Invoice date", "due_date": "Due",
            "amount": "Amount", "paid": "Paid (ledger)", "received": "Received (bank)", "outstanding": "Outstanding",
            "days_overdue": "Days overdue", "bucket": "Age", "chase_tier": "Chase", "status": "Notes",
            "project_ref": "Project"}
    return d[[c for c in cols if c in d]].rename(columns=cols)


HOURS_COLUMNS = ["Employee", "Employee ID", "Week commencing", "Days worked", "Basic hours", "Overtime hours",
                 "Weekend hours", "Total hours", "Hourly rate", "Overtime multiplier", "Gross pay (est.)", "Status",
                 "Held because"]


def hours_frame(r: "RunResult") -> pd.DataFrame:
    h = r.hours
    if h is None or h.empty:
        return pd.DataFrame()
    return h[[c for c in HOURS_COLUMNS if c in h]]


def timesheet_lines_frame(r: "RunResult") -> pd.DataFrame:
    t = getattr(r, "timesheet_lines", None)
    if t is None or t.empty:
        return pd.DataFrame()
    cols = {"employee_id": "Employee ID", "employee": "Employee", "date": "Date", "job": "Job", "job_status": "Job status",
            "start": "Start", "finish": "Finish", "break_minutes": "Break (mins)", "hours": "Hours entered",
            "calculated_hours": "Hours (from times)", "paid_hours": "Hours counted", "approved_by": "Signed off by",
            "duplicate": "Duplicate (not counted)"}
    out = t[[c for c in cols if c in t]].rename(columns=cols)
    if "Duplicate (not counted)" in out:
        out["Duplicate (not counted)"] = out["Duplicate (not counted)"].map({True: "Yes", False: ""})
    return out


def hours_job_frame(r: "RunResult") -> pd.DataFrame:
    from tools.bookkeeping.payroll import hours_by_job

    return hours_by_job(getattr(r, "timesheet_lines", None))


def letters_frame(r: "RunResult") -> pd.DataFrame:
    return pd.DataFrame([{"To": l["to"], "Type": l["recipient_type"].replace("_", " "), "Contact": l.get("contact", ""),
                          "Email": l.get("email", ""), "Subject": l["subject"], "Body": l["body"],
                          "Exceptions": ", ".join(l.get("exceptions", [])), "Drafted by": _source_label(l.get("source"))}
                         for l in r.letters])


def _source_label(source: str | None) -> str:
    return {"api": "Claude", "cache": "Claude (cached)", "fixture": "Pre-recorded AI (mock mode)", "mock": "Template",
            "fallback": "Template", "template": "Template"}.get(source or "", "")


def summary_frame(r: "RunResult") -> pd.DataFrame:
    f = r.facts
    rows = [("Report", f"{r.config.get('tool_name', 'Bookkeeping')} — month-end pack"), ("Period", f["period"]),
            ("Prepared as at", f["as_of"]), ("Input", r.inputs_label), ("Documents read", f["documents"]),
            ("Ledger lines", f["entries"]), ("Ready to import", f"{f['entries_ready']} lines, £{f['value_ready']:,.2f}"),
            ("Held for a check", f"{f['entries_held']} lines, £{f['value_held']:,.2f}")]
    if f.get("card_txns"):
        rows.append(("Card transactions matched", f"{f['card_matched']} of {f['card_txns']}"))
    if f.get("payroll_employees"):
        rows.append(("Payroll", f"{f['payroll_employees']} employees, gross £{f['payroll_gross']:,.2f}"))
    if f.get("sales_invoices"):
        rows.append(("Sales invoices", f"{f['sales_ready']} of {f['sales_invoices']} ready, £{f['sales_value']:,.2f}"))
    if f.get("debtor_items"):
        rows.append(("Debtors outstanding", f"£{f['debtors_outstanding']:,.2f} (£{f['debtors_overdue']:,.2f} overdue)"))
    if f.get("timesheet_rows") and "hours_total" in f:
        rows.append(("Hours for payroll", f"{f['hours_ready']:,.2f} of {f['hours_total']:,.2f} hours ready; "
                                          f"{len(f.get('hours_held', []))} employee-week(s) held"))
    rows += [("Exceptions", f["exceptions"]), ("Need a human check", f["needs_human_check"]), ("Emails drafted", f["emails"]),
             ("Manager summary", r.summary), ("Summary source", r.summary_source),
             ("Estimated time saved", f"{r.time_estimate.saved_label} (assumptions below)")]
    rows += [("Assumption", a) for a in r.time_estimate.assumptions]
    return pd.DataFrame(rows, columns=["Item", "Value"])


def public(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    return df.drop(columns=[c for c in df.columns if str(c).startswith("_")])


def sheets(r: "RunResult") -> dict[str, pd.DataFrame]:
    exc = r.exceptions
    out = {
        "Summary": summary_frame(r),
        "Month-end checklist": r.checklist,
        "Exceptions": exc,
        "Needs human check": exc[exc["Needs human check"] == "Yes"] if not exc.empty else exc,
        "Coded entries": entries_frame(r),
        "Totals by account": account_totals(r),
        "Totals by " + str((r.config.get("analysis") or {}).get("tracking_label", "tracking")).lower(): tracking_totals(r),
        "Card matching": r.card,
        "Payroll journal": journal_frame(r),
        "Payroll check": payroll_frame(r),
        "Sales invoices": sales_frame(r),
        "Aged debtors": debtors_frame(r),
        "Debtors by customer": r.debtors_summary,
        "Hours for payroll": hours_frame(r),
        "Hours by job": hours_job_frame(r),
        "Timesheet lines": timesheet_lines_frame(r),
        "PO matching": r.po_table,
        "Supplier statements": r.statements,
        "Filing index": r.filing,
        "VAT return workings": r.vat_return,
        "Documents read": r.documents_table,
        "Emails drafted": letters_frame(r),
    }
    return {k: public(v) for k, v in out.items() if v is not None and (not v.empty or k in ("Exceptions",))}


def build_downloads(r: "RunResult") -> list[DownloadFile]:
    stem = r.exports[0].file_name.rsplit("_", 1)[0] + "_" if r.exports else "bookkeeping_"
    files = [DownloadFile(x.label, dl.csv_bytes(x.frame), x.file_name, x.help) for x in r.exports]
    xlsx = dl.excel_bytes(sheets(r), wrap_columns=["Finding", "Suggested action", "Body", "Description", "Why this account",
                                                   "Summary", "Detail", "Value", "How it is worked out"])
    files.append(DownloadFile("Bookkeeping pack (Excel)", xlsx, f"{stem}bookkeeping-pack.xlsx",
                              "Every table from this run: entries, matching, exceptions, checklist and more"))
    files.append(DownloadFile("Month-end report (PDF)", pdf_report(r), f"{stem}month-end-report.pdf",
                              "Manager summary, checklist, human checks and exceptions, ready to circulate"))
    if r.letters:
        files.append(DownloadFile("Drafted emails (Word)", letters_docx(r), f"{stem}drafted-emails.docx",
                                  "Supplier queries, receipt requests and other emails, editable"))
    files.append(DownloadFile("Exceptions list (CSV)", dl.csv_bytes(r.exceptions), f"{stem}exceptions.csv",
                              "All exceptions, for another system or a tracker"))
    if r.filing is not None and not r.filing.empty:
        from tools.bookkeeping.filing import filing_zip

        files.append(DownloadFile("Filed documents (ZIP)", filing_zip(r.filing, r.originals), f"{stem}filed-documents.zip",
                                  "The documents renamed and sorted into project folders"))
    return files


def _pounds(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Money as text with pence for PDF/Word tables (the generic formatter rounds floats to 1 dp)."""
    out = df.copy()
    for c in cols:
        if c in out:
            out[c] = out[c].map(lambda v: "" if v is None or pd.isna(v) else f"{'−' if v < 0 else ''}£{abs(v):,.2f}")
    return out


def pdf_report(r: "RunResult") -> bytes:
    f = r.facts
    blocks = [dl.heading("Summary"),
              dl.metrics([("Documents read", f["documents"]), ("Ready to import", f"£{f['value_ready']:,.2f}"),
                          ("Held for a check", f["entries_held"]), ("Exceptions", f["exceptions"]),
                          ("Need a human check", f["needs_human_check"])]),
              dl.para(r.summary), dl.note(r.summary_source)]
    if not r.checklist.empty:
        blocks += [dl.heading("Month-end checklist"), dl.table(r.checklist, widths=[22, 10, 48, 14])]
    exc = r.exceptions
    if not exc.empty:
        human = exc[exc["Needs human check"] == "Yes"]
        if not human.empty:
            blocks += [dl.heading("Needs human check"),
                       dl.table(human[["ID", "Severity", "Check", "Who", "Reference", "Finding", "Suggested action"]],
                                widths=[5, 6, 12, 12, 10, 32, 24])]
        blocks += [dl.heading("All exceptions"),
                   dl.table(_pounds(exc[["ID", "Severity", "Area", "Check", "Who", "Reference", "Amount", "Finding"]], ["Amount"]),
                            widths=[5, 6, 7, 12, 12, 10, 7, 40])]
    hours = hours_frame(r)
    if not hours.empty:
        h = hours[[c for c in ["Employee", "Week commencing", "Basic hours", "Overtime hours", "Weekend hours", "Total hours",
                               "Gross pay (est.)", "Status", "Held because"] if c in hours]].copy()
        h["Week commencing"] = pd.to_datetime(h["Week commencing"]).dt.strftime("%d %b %Y")
        blocks += [dl.heading("Hours for payroll"), dl.table(_pounds(h, ["Gross pay (est.)"]))]
    totals = account_totals(r)
    if not totals.empty:
        blocks += [dl.heading("Coded entries by account"),
                   dl.table(_pounds(totals, ["Net", "VAT", "Gross", "Held (gross)"]))]
    if not r.journal.empty:
        blocks += [dl.heading("Payroll journal"), dl.table(_pounds(journal_frame(r), ["Debit", "Credit"]),
                                                            widths=[8, 12, 18, 8, 8, 30, 10])]
    if not r.vat_return.empty:
        blocks += [dl.heading("VAT return workings (draft)"),
                   dl.table(_pounds(r.vat_return, ["Amount (£)"]), widths=[4, 30, 10, 40])]
    if not r.debtors_summary.empty:
        money = [c for c in r.debtors_summary.columns if c != "Customer"]
        blocks += [dl.heading("Debtors by customer"), dl.table(_pounds(r.debtors_summary, money))]
    blocks += [dl.heading("Method"), dl.bullets([
        "Claude read each document and returned its fields; code then checked the arithmetic, VAT rates, VAT numbers, "
        "bank details, duplicates and dates.",
        "Matching, totals, the payroll journal and every figure in this report were calculated in code. Claude only "
        "suggested account codes where no rule applied, and drafted the emails and the summary.",
        "Nothing is posted automatically. Entries with an open exception are held out of the import files.",
    ])]
    cfg = r.config
    subtitle = f"Period {f['period']} · prepared {f['as_of']} · {r.inputs_label}" + (
        f" · {cfg.get('client_name')} prototype" if cfg.get("client_name") else "")
    return dl.pdf_bytes(f"{cfg.get('tool_name', 'Bookkeeping')} — month-end report", blocks, subtitle=subtitle,
                        footer=cfg.get("footer_short") or "Prototype — synthetic data")


def letters_docx(r: "RunResult") -> bytes:
    blocks = [dl.note("Drafts for a person to check before sending. Amounts and references were checked by code; "
                      "the wording was drafted by " + ("Claude." if any(l.get("source") in ("api", "cache") for l in r.letters)
                                                       else "AI (pre-recorded in mock mode) or a template."))]
    for l in r.letters:
        to = l["to"] + (f" ({l['contact']})" if l.get("contact") else "") + (f" <{l['email']}>" if l.get("email") else "")
        blocks += [dl.heading(l["subject"], level=2), dl.note(f"To: {to} · about {', '.join(l.get('exceptions', [])) or 'overdue invoices'} "
                                                               f"· drafted by {_source_label(l.get('source'))}")]
        blocks += [dl.para(p) for p in l["body"].split("\n\n") if p.strip()]
    return dl.docx_bytes("Drafted emails", blocks,
                         subtitle=f"{r.config.get('tool_name', '')} · {r.facts['period']} · prepared {r.facts['as_of']}")
