"""Payroll: check a payroll bureau summary and build the payroll journal;
turn approved timesheets into payroll hours. Deterministic; no AI."""

from __future__ import annotations

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


def timesheet_hours(ts: pd.DataFrame, employees: pd.DataFrame | None, cfg: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame, list[Finding]]:
    """Validate timesheet rows and summarise hours per employee per week.

    Config (``timesheets``): ``overtime_after_weekly_hours`` (default 40, or the
    employee's contracted hours), ``overtime_multiplier`` (1.5),
    ``weekend_multiplier`` (null = weekend hours count as normal hours),
    ``max_daily_hours`` (12), ``require_approval`` (true), ``expected_days`` (Mon–Fri).
    Returns (checked rows, weekly summary, findings).
    """
    cfg = cfg or {}
    findings: list[Finding] = []
    rows = ts.copy()
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
    unknown_seen = set()
    for idx, r in zip(rows.index, rows.to_dict("records")):
        who, day, src = str(r["employee"]), r["date"], str(r.get("_source", ""))
        calc_h, paid = r["calculated_hours"], r["paid_hours"]
        known = who.strip().lower() in emp_by_name or str(r.get("employee_id", "")).strip().lower() in emp_by_name
        if emp_by_name and not known and who not in unknown_seen:
            unknown_seen.add(who)
            findings.append(Finding("unknown_employee", subject=who, date=day, source=src,
                                    finding=f"{who} is not on the employee list."))
        given = stated.get(idx)
        if given is not None and pd.notna(given) and calc_h is not None and pd.notna(calc_h) and abs(given - calc_h) > 0.1:
            findings.append(Finding("hours_mismatch", subject=who, date=day, source=src,
                                    finding=f"Hours entered {given:g}, but {r.get('start')} to {r.get('finish')} "
                                            f"less break is {calc_h:g}."))
        if paid is not None and pd.notna(paid) and paid > max_daily:
            findings.append(Finding("excess_hours", subject=who, date=day, source=src,
                                    finding=f"{paid:g} hours in one day (limit set at {max_daily:g})."))
        if cfg.get("require_approval", True) and "approved_by" in rows and not str(r.get("approved_by", "")).strip():
            findings.append(Finding("missing_approval", subject=who, date=day, source=src,
                                    finding="No supervisor approval on this timesheet line."))
    dup_keys = ["employee", "date"] + (["start"] if "start" in rows else [])
    for (who, day, *_), grp in rows[rows.duplicated(dup_keys, keep=False)].groupby(dup_keys):
        findings.append(Finding("duplicate_timesheet", subject=str(who), date=day,
                                finding=f"{len(grp)} identical entries for the same day and start time."))
    rows["week_commencing"] = rows["date"] - pd.to_timedelta(rows["date"].dt.weekday, unit="D")
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
        weeks = sorted(rows["week_commencing"].unique())
        names = sorted({str(rec.get("employee")) for rec in employees.to_dict("records")})
        for wk in weeks:
            for name in names:
                if rows[(rows["employee"] == name) & (rows["week_commencing"] == wk)].empty:
                    findings.append(Finding("missing_timesheet", subject=name, date=pd.Timestamp(wk),
                                            finding=f"No timesheet for the week commencing {pd.Timestamp(wk):%d %b %Y}."))
    return rows, summary_df, findings
