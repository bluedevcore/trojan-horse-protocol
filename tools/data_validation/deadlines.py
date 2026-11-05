"""Recurring-report deadline tracker.

Input: a calendar table (one row per obligation) with at least ``obligation``
and ``due_date``. Optional: ``recipient``, ``period`` (label), ``period_start``
and ``period_end`` (the data the report covers), ``scope`` (which categories of
data it depends on, ``;``-separated or ``All``), ``owner``, ``submitted_on``.

Status is computed against an as-of date. An obligation is "blocked" by open
exceptions (needing a human check, or high severity) that are in its scope and
overlap its data period; exceptions with no date count as overlapping.
"""

from __future__ import annotations

import pandas as pd

from tools.data_validation.loader import coerce_dates


def build_tracker(calendar: pd.DataFrame, *, as_of: pd.Timestamp, exceptions: pd.DataFrame,
                  category_heading: str | None, soon_days: int = 7) -> pd.DataFrame:
    if calendar is None or calendar.empty:
        return pd.DataFrame()
    cal = calendar.copy()
    cal.columns = [c.strip().lower().replace(" ", "_") for c in cal.columns]
    if "obligation" not in cal or "due_date" not in cal:
        return pd.DataFrame()
    cal["due_date"], _ = coerce_dates(cal["due_date"])
    for col in ("submitted_on", "period_start", "period_end"):
        if col in cal:
            cal[col], _ = coerce_dates(cal[col])
    as_of = pd.Timestamp(as_of).normalize()

    open_ex = exceptions
    if exceptions is not None and not exceptions.empty:
        open_ex = exceptions[(exceptions["Needs human check"] == "Yes") | (exceptions["Severity"] == "High")]

    rows = []
    for _, ob in cal.sort_values("due_date").iterrows():
        due = ob["due_date"]
        days = (due - as_of).days if pd.notna(due) else None
        submitted = ob.get("submitted_on")
        is_submitted = submitted is not None and pd.notna(submitted)
        if is_submitted:
            status, rag = f"Submitted {pd.Timestamp(submitted):%d %b}", "Green"
        elif days is None:
            status, rag = "No due date", "Amber"
        elif days < 0:
            status, rag = f"Overdue by {-days} day{'s' if days != -1 else ''}", "Red"
        elif days <= soon_days:
            status, rag = f"Due in {days} day{'s' if days != 1 else ''}", "Amber"
        else:
            status, rag = f"On track ({days} days)", "Green"

        blocking: list[str] = []
        if not is_submitted and open_ex is not None and not open_ex.empty:
            scope = str(ob.get("scope", "All") or "All").strip()
            hits = open_ex
            if scope.lower() != "all" and category_heading and category_heading in hits:
                hits = hits[hits[category_heading].isin({c.strip() for c in scope.split(";")})]
            start, end = ob.get("period_start"), ob.get("period_end")
            if "_from" in hits and start is not None and end is not None and pd.notna(start) and pd.notna(end):
                undated = hits["_from"].isna()
                overlaps = (hits["_from"] <= end) & (hits["_to"].fillna(hits["_from"]) >= start)
                hits = hits[undated | overlaps]
            blocking = hits["ID"].tolist()
        if blocking:
            more = "…" if len(blocking) > 4 else ""
            readiness = f"Blocked: {len(blocking)} open exception{'s' if len(blocking) != 1 else ''} ({', '.join(blocking[:4])}{more})"
            if rag == "Green":
                rag = "Amber"
            elif rag == "Amber" and days is not None and days <= soon_days:
                rag = "Red"  # due soon and the data is not ready
        else:
            readiness = "—" if is_submitted else "Data ready"
        rows.append({
            "Obligation": ob["obligation"],
            "Recipient": ob.get("recipient", ""),
            "Period": ob.get("period", ""),
            "Due": due.strftime("%d %b %Y") if pd.notna(due) else "",
            "Status": status,
            "Data readiness": readiness,
            "RAG": rag,
            "Owner": ob.get("owner", ""),
            "_days": days,
            "_blocking": blocking,
        })
    return pd.DataFrame(rows)
