"""Payroll: check a payroll bureau summary and build the payroll journal;
turn approved timesheets into payroll hours. Deterministic; no AI."""

from __future__ import annotations

import re

import pandas as pd

from tools.bookkeeping.checks import Finding

DEDUCTIONS = ["paye", "employee_ni", "employee_pension", "student_loan", "other_deductions"]
JOURNAL_DEFAULTS = {
    "wages": "Wages and salaries",
    "employer_ni": "Employer's NI",
    "employer_pension": "Employer pension contributions",
    "paye_ni_liability": "PAYE and NI payable",
    "pension_liability": "Pension payable",
    "net_wages": "Net wages payable",
    "other_deductions": "Other payroll deductions payable",
    "suspense": "Suspense",
}


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name].fillna(0.0).astype(float) if name in df else pd.Series(0.0, index=df.index)


def check_payroll(df: pd.DataFrame, *, total_labels=("total", "totals", "grand total")) -> tuple[pd.DataFrame, list[Finding], dict]:
    """Split off any totals row, check each employee's net pay and the report totals.

    Returns (employee rows with a ``calculated_net`` column, findings, totals dict).
    """
    findings: list[Finding] = []
    is_total = df["employee"].astype(str).str.strip().str.lower().isin(total_labels)
    totals_row = df[is_total]
    emp = df[~is_total & (df["employee"].astype(str).str.strip() != "")].copy()
    emp["calculated_net"] = (_col(emp, "gross") - sum(_col(emp, c) for c in DEDUCTIONS)).round(2)
    emp["net_difference"] = (_col(emp, "net_pay") - emp["calculated_net"]).round(2)
    for r in emp[emp["net_difference"].abs() > 0.01].to_dict("records"):
        findings.append(Finding(
            "payroll_net_mismatch", subject=str(r["employee"]), reference=str(r.get("employee_id", "") or ""),
            amount=float(r["net_difference"]), source=str(r.get("_source", "")),
            finding=(f"Net pay on the report is £{r['net_pay']:,.2f}, but gross £{r['gross']:,.2f} less deductions "
                     f"comes to £{r['calculated_net']:,.2f} (difference £{r['net_difference']:,.2f})."),
            ask=f"Please confirm {r['employee']}'s net pay: the report shows £{r['net_pay']:,.2f} but gross less "
                f"deductions is £{r['calculated_net']:,.2f}."))
    totals = {c: round(float(_col(emp, c).sum()), 2) for c in ["gross", *DEDUCTIONS, "employer_ni", "employer_pension", "net_pay"]}
    totals["employees"] = len(emp)
    if not totals_row.empty:
        t = totals_row.iloc[0]
        for c in ("gross", "net_pay"):
            if c in t and pd.notna(t[c]) and abs(float(t[c]) - totals[c]) > 0.01:
                findings.append(Finding(
                    "payroll_total_mismatch", subject="Payroll report", reference=c.replace("_", " "),
                    amount=round(float(t[c]) - totals[c], 2),
                    finding=f"The report's total {c.replace('_', ' ')} is £{float(t[c]):,.2f}, but the employee rows "
                            f"add up to £{totals[c]:,.2f}.",
                    ask=f"The total {c.replace('_', ' ')} on the report doesn't match the employee lines; which is right?"))
    return emp, findings, totals


def payroll_journal(emp: pd.DataFrame, *, date: pd.Timestamp, accounts: dict | None = None, by_department: bool = True,
                    reference: str = "PAYROLL") -> tuple[pd.DataFrame, float]:
    """Balanced payroll journal from the employee rows, using the report's own
    figures. Any imbalance (a net pay that doesn't reconcile) goes to Suspense
    so it is visible and the journal can still be posted.

    Returns (journal lines, difference posted to suspense).
    """
    acc = {**JOURNAL_DEFAULTS, **(accounts or {})}
    lines = []

    def add(account, debit=0.0, credit=0.0, desc="", cls=""):
        if round(debit, 2) or round(credit, 2):
            lines.append({"date": date, "reference": reference, "account": account, "debit": round(debit, 2),
                          "credit": round(credit, 2), "description": desc, "class": cls})

    dept = emp["department"].replace("", "General") if by_department and "department" in emp else pd.Series("", index=emp.index)
    for d, grp in emp.groupby(dept, sort=True):
        add(acc["wages"], debit=_col(grp, "gross").sum(), desc=f"Gross pay{' – ' + d if d else ''}", cls=d)
    for d, grp in emp.groupby(dept, sort=True):
        add(acc["employer_ni"], debit=_col(grp, "employer_ni").sum(), desc=f"Employer's NI{' – ' + d if d else ''}", cls=d)
    for d, grp in emp.groupby(dept, sort=True):
        add(acc["employer_pension"], debit=_col(grp, "employer_pension").sum(),
            desc=f"Employer pension{' – ' + d if d else ''}", cls=d)
    add(acc["paye_ni_liability"], credit=sum(_col(emp, c).sum() for c in ("paye", "employee_ni", "employer_ni", "student_loan")),
        desc="PAYE, NI and student loan due to HMRC")
    add(acc["pension_liability"], credit=_col(emp, "employee_pension").sum() + _col(emp, "employer_pension").sum(),
        desc="Pension contributions due to the scheme")
    add(acc["other_deductions"], credit=_col(emp, "other_deductions").sum(), desc="Other deductions")
    add(acc["net_wages"], credit=_col(emp, "net_pay").sum(), desc="Net pay due to employees")
    journal = pd.DataFrame(lines, columns=["date", "reference", "account", "debit", "credit", "description", "class"])
    difference = round(journal["debit"].sum() - journal["credit"].sum(), 2)
    if abs(difference) > 0.005:
        add(acc["suspense"], debit=max(-difference, 0), credit=max(difference, 0),
            desc="Payroll difference to investigate (net pay does not reconcile)")
        journal = pd.DataFrame(lines, columns=journal.columns)
    return journal, difference

# --------------------------------------------------------------- timesheets


def _time_to_hours(value) -> float | None:
    s = str(value or "").strip().replace(".", ":")
    if not s:
        return None
    try:
        if ":" in s:
            h, m = s.split(":")[:2]
            return int(h) + int(m) / 60
        num = float(s)
        return num if num < 24 else int(num // 100) + (num % 100) / 60  # 0730 style
    except ValueError:
        return None


CLOSED_JOB_STATUSES = ("closed", "complete", "completed", "finished", "archived", "cancelled")


def hours_key(employee, week) -> str:
    """Key tying a timesheet finding to one row of the weekly hours summary (used for holds)."""
    wk = pd.Timestamp(week)
    return f"hours:{str(employee).strip()}|{'' if pd.isna(wk) else f'{wk:%Y-%m-%d}'}"


def _day(d) -> str:
    return "" if d is None or pd.isna(d) else f"{pd.Timestamp(d):%a %d %b %Y}"


def _job_key(job) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(job or "").upper())


def timesheet_hours(ts: pd.DataFrame, employees: pd.DataFrame | None, cfg: dict | None = None, *,
                    jobs: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame, list[Finding]]:
    """Validate timesheet rows and summarise hours per employee per week.

    Config (``timesheets``): ``overtime_after_weekly_hours`` (default 40, or the
    employee's contracted hours), ``overtime_multiplier`` (1.5),
    ``weekend_multiplier`` (null = weekend hours count as normal hours),
    ``max_daily_hours`` (12), ``require_approval`` (true), ``expected_days`` (Mon–Fri),
    ``closed_job_statuses`` (job-list statuses that mean no more hours, default closed/complete/...).
    ``jobs`` (optional, the ``projects`` table): lines booked to a job that is not on the
    list, or is closed, are flagged. Lines on the same day whose times overlap are flagged.
    Every finding carries ``entry_keys`` (see ``hours_key``) so holds can be applied to the
    summary with ``hold_hours`` once findings are finalised.
    Returns (checked rows, weekly summary, findings).
    """
    cfg = cfg or {}
    findings: list[Finding] = []
    rows = ts.copy()
    rows["week_commencing"] = rows["date"] - pd.to_timedelta(rows["date"].dt.weekday, unit="D")
    emp_by_name = {}
    if employees is not None and not employees.empty:
        for rec in employees.to_dict("records"):
            emp_by_name[str(rec.get("employee", "")).strip().lower()] = rec
            if rec.get("employee_id"):
                emp_by_name[str(rec["employee_id"]).strip().lower()] = rec
    calc = []
    for r in rows.to_dict("records"):
        start, finish = _time_to_hours(r.get("start", "")), _time_to_hours(r.get("finish", ""))
        brk = r.get("break_minutes") or 0
        brk = 0.0 if pd.isna(brk) else float(brk)
        hours = None
        if start is not None and finish is not None:
            span = finish - start if finish >= start else finish + 24 - start
            hours = round(span - brk / 60, 2)
        calc.append(hours)
    rows["calculated_hours"] = calc
    stated = rows["hours"] if "hours" in rows else pd.Series(float("nan"), index=rows.index)
    rows["paid_hours"] = rows["calculated_hours"].where(rows["calculated_hours"].notna(), stated)
    max_daily = float(cfg.get("max_daily_hours", 12))
    dup_keys = ["employee", "date"] + (["start"] if "start" in rows else [])
    rows["duplicate"] = rows.duplicated(dup_keys, keep="first")

    def add(check: str, r: dict, finding: str, ask: str = "", **kw) -> None:
        who, day = str(r["employee"]), r["date"]
        keys = kw.pop("entry_keys", [hours_key(who, r["week_commencing"])])
        findings.append(Finding(check, subject=who, date=day, source=str(r.get("_source", "")), finding=finding, ask=ask,
                                ref_text=kw.pop("ref_text", " · ".join(x for x in [who, _day(day)] if x)),
                                entry_keys=keys, **kw))

    def line(r: dict) -> str:  # "Tue 27 Oct 2026 (07:30–16:00, J-2614)"
        times = f"{r.get('start')}–{r.get('finish')}" if str(r.get("start", "")).strip() else ""
        bits = ", ".join(x for x in [times, str(r.get("job", "") or "").strip()] if x)
        return _day(r["date"]) + (f" ({bits})" if bits else "")

    unknown_seen = set()
    for idx, r in zip(rows.index, rows.to_dict("records")):
        who = str(r["employee"])
        calc_h, paid = r["calculated_hours"], r["paid_hours"]
        known = who.strip().lower() in emp_by_name or str(r.get("employee_id", "")).strip().lower() in emp_by_name
        if emp_by_name and not known and who not in unknown_seen:
            unknown_seen.add(who)
            theirs = rows[(rows["employee"] == r["employee"]) & ~rows["duplicate"]]
            weeks = theirs["week_commencing"].dropna().unique()
            add("unknown_employee", r, f"{who} is not on the employee list: {len(theirs)} timesheet line(s), "
                                       f"{theirs['paid_hours'].sum():g} hours, from {_day(theirs['date'].min())}.",
                f"Is {who} a new starter? We need their starter paperwork before they can be paid.",
                entry_keys=[hours_key(who, w) for w in weeks], ref_text=who)
        given = stated.get(idx)
        if given is not None and pd.notna(given) and calc_h is not None and pd.notna(calc_h) and abs(given - calc_h) > 0.1:
            add("hours_mismatch", r, f"{line(r)}: hours entered {given:g}, but {r.get('start')} to {r.get('finish')} "
                                     f"less break is {calc_h:g}; {calc_h:g} is counted.", "Which figure is right?")
        if paid is not None and pd.notna(paid) and paid > max_daily:
            add("excess_hours", r, f"{line(r)}: {paid:g} hours in one day (limit set at {max_daily:g}).",
                "Could you confirm these hours are right?")
        if cfg.get("require_approval", True) and "approved_by" in rows and not str(r.get("approved_by", "")).strip():
            add("missing_approval", r, f"{line(r)}: no supervisor approval on this timesheet line.",
                "Could you sign this line off?")
    for (who, day, *_), grp in rows[rows.duplicated(dup_keys, keep=False)].groupby(dup_keys):
        add("duplicate_timesheet", grp.iloc[0].to_dict(),
            f"{line(grp.iloc[0].to_dict())}: {len(grp)} identical entries for the same day and start time; only one is counted.")

    unique = rows[~rows["duplicate"]]
    # lines on the same day whose times overlap (an operative booked to two places at once)
    if {"start", "finish"} <= set(rows.columns):
        for _, grp in unique.groupby(["employee", "date"]):
            spans = []
            for r in grp.to_dict("records"):
                s, f = _time_to_hours(r.get("start")), _time_to_hours(r.get("finish"))
                if s is not None and f is not None:
                    spans.append((s, f if f >= s else f + 24, r))
            spans.sort(key=lambda x: x[0])
            for (s1, e1, r1), (s2, e2, r2) in zip(spans, spans[1:]):
                if s2 < e1 - 1e-9:
                    overlap = round(min(e1, e2) - s2, 2)
                    jobs_txt = [f" ({x['job']})" if str(x.get("job", "")).strip() else "" for x in (r1, r2)]
                    add("overlapping_shifts", r1,
                        f"Two lines on {_day(r1['date'])} overlap by {overlap:g} hours: {r1.get('start')}–{r1.get('finish')}"
                        f"{jobs_txt[0]} and {r2.get('start')}–{r2.get('finish')}{jobs_txt[1]}. Both are counted in the hours.",
                        "Which times are right?")

    # hours booked to a job that is not on the job list, or is closed
    if jobs is not None and not jobs.empty and "job" in rows and "project_ref" in jobs:
        closed = tuple(str(s).strip().lower() for s in cfg.get("closed_job_statuses", CLOSED_JOB_STATUSES))
        by_key = {_job_key(j): rec for j, rec in zip(jobs["project_ref"], jobs.to_dict("records")) if _job_key(j)}

        def job_status(job) -> str:
            if not str(job or "").strip():
                return ""
            rec = by_key.get(_job_key(job))
            return "Not on job list" if rec is None else (str(rec.get("status", "")).strip() or "On job list")

        rows["job_status"] = rows["job"].map(job_status)
        booked = rows[~rows["duplicate"] & (rows["job"].astype(str).str.strip() != "")]
        for (who, key), grp in booked.groupby([booked["employee"], booked["job"].map(_job_key)], sort=False):
            job, rec = str(grp["job"].iloc[0]).strip(), by_key.get(key)
            status = str((rec or {}).get("status", "")).strip()
            if rec is not None and not status.lower().startswith(closed):
                continue
            hrs = round(float(grp["paid_hours"].sum()), 2)
            days = ", ".join(f"{d:%a %d %b}" for d in sorted(grp["date"].dropna().unique()))
            if rec is None:
                check, msg = "unknown_job", f"{hrs:g} hours on {days} booked to job {job}, which is not on the job list."
            else:
                check, msg = "closed_job", (f"{hrs:g} hours on {days} booked to {job} ({rec.get('project_name', '')}), "
                                            f"which is marked “{status}” on the job list.")
            add(check, grp.iloc[0].to_dict(), msg,
                "Which job should these hours be booked to?", reference=str(job),
                entry_keys=[hours_key(who, w) for w in grp["week_commencing"].dropna().unique()],
                ref_text=f"{who} · {days} · job {job}")

    summary = []
    weekend_mult = cfg.get("weekend_multiplier")
    for (who, wk), grp in rows.groupby(["employee", "week_commencing"]):
        rec = emp_by_name.get(str(who).strip().lower(), {})
        threshold = float(rec.get("contracted_hours") or cfg.get("overtime_after_weekly_hours", 40))
        ot_mult = float(rec.get("overtime_multiplier") or cfg.get("overtime_multiplier", 1.5))
        rate = rec.get("hourly_rate")
        g = grp.drop_duplicates(dup_keys)
        weekend = g[g["date"].dt.weekday >= 5]["paid_hours"].sum() if weekend_mult else 0.0
        weekday_total = g["paid_hours"].sum() - weekend
        basic = min(weekday_total, threshold)
        overtime = max(weekday_total - threshold, 0)
        gross = None
        if rate not in (None, "") and not pd.isna(rate):
            gross = round(basic * rate + overtime * rate * ot_mult + weekend * rate * float(weekend_mult or 1), 2)
        summary.append({"Employee": who, "Employee ID": rec.get("employee_id", ""), "Week commencing": wk,
                        "Days worked": int(g["date"].nunique()), "Basic hours": round(basic, 2),
                        "Overtime hours": round(overtime, 2), "Weekend hours": round(weekend, 2),
                        "Total hours": round(g["paid_hours"].sum(), 2), "Hourly rate": rate,
                        "Overtime multiplier": ot_mult, "Gross pay (est.)": gross})
    summary_df = pd.DataFrame(summary)
    expected = cfg.get("expected_days")
    if expected and emp_by_name and not rows.empty:
        weeks = sorted(rows["week_commencing"].dropna().unique())
        names = sorted({str(rec.get("employee")) for rec in employees.to_dict("records")})
        for wk in weeks:
            for name in names:
                if rows[(rows["employee"] == name) & (rows["week_commencing"] == wk)].empty:
                    findings.append(Finding("missing_timesheet", subject=name, date=pd.Timestamp(wk),
                                            finding=f"No timesheet for the week commencing {pd.Timestamp(wk):%d %b %Y}.",
                                            ask=f"Could you send {name}'s timesheet before the payroll cut-off?",
                                            ref_text=f"{name} · week commencing {pd.Timestamp(wk):%d %b %Y}"))
    return rows, summary_df, findings


def hold_hours(summary: pd.DataFrame, findings: list[Finding]) -> pd.DataFrame:
    """Mark each employee-week Ready or Held. Run after ``checks.finalise`` so each
    finding has its id and its ``hold`` setting; held weeks stay out of the payroll file."""
    if summary is None or summary.empty:
        return summary
    out = summary.copy()
    held = {}
    for f in findings:
        if f.hold:
            for key in f.entry_keys:
                held.setdefault(key, []).append(f.id)
    why = [", ".join(held.get(hours_key(e, w), [])) for e, w in zip(out["Employee"], out["Week commencing"])]
    out["Status"] = ["Held" if w else "Ready" for w in why]
    out["Held because"] = why
    return out


def hours_by_job(rows: pd.DataFrame) -> pd.DataFrame:
    """Hours per job from checked timesheet lines (duplicates left out), for job costing."""
    if rows is None or rows.empty or "job" not in rows:
        return pd.DataFrame()
    r = rows[~rows["duplicate"]] if "duplicate" in rows else rows
    r = r.assign(job=r["job"].astype(str).str.strip().replace("", "(no job)"))
    out = r.groupby("job", sort=True).agg(Lines=("employee", "size"), Employees=("employee", "nunique"),
                                          Hours=("paid_hours", "sum")).reset_index().rename(columns={"job": "Job"})
    if "job_status" in r:
        out.insert(1, "Job status", out["Job"].map(r.groupby("job")["job_status"].first()).fillna(""))
    out["Hours"] = out["Hours"].round(2)
    return out
