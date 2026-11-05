"""Deterministic validation rules. Pure pandas, no I/O, no AI.

Every rule takes the full table, its own config dict and a shared context, and
returns a list of ``Finding`` objects. Rules are configured in a client's
``config.yaml``; see ``RULE_TYPES`` for what each type accepts.

Common rule options:
    id, label, severity (high|medium|low), needs_human_check (bool),
    exclude_from_totals (bool), where ({column: [allowed values]})
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd


@dataclass
class Finding:
    rule_id: str
    rule_type: str
    check: str
    severity: str
    needs_human_check: bool
    exclude_from_totals: bool
    detail: str
    group: str | None = None
    date_from: pd.Timestamp | None = None
    date_to: pd.Timestamp | None = None
    column: str | None = None
    value: Any = None
    expected: str | None = None
    rids: list[int] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    also_flagged_by: list[str] = field(default_factory=list)


@dataclass
class RuleContext:
    key: str  # grouping column, e.g. meter serial
    date: str
    value: str
    unit: str = ""
    working: pd.DataFrame | None = None  # de-duplicated rows with valid dates, sorted
    period_start: pd.Timestamp | None = None
    period_end: pd.Timestamp | None = None
    reference: pd.DataFrame | None = None
    parse_cells: set = field(default_factory=set)  # {(rid, column)} already reported as unreadable
    labels: dict = field(default_factory=dict)  # column -> plain-English name
    key_noun: str = "record"

    def label(self, column: str) -> str:
        return self.labels.get(column, column.replace("_", " "))

    def fmt(self, value: Any) -> str:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return "blank"
        if isinstance(value, (int, float, np.integer, np.floating)):
            return f"{float(value):,.1f}{(' ' + self.unit) if self.unit else ''}"
        return str(value)


def _finding(rule: dict, rule_type: str, **kwargs) -> Finding:
    return Finding(
        rule_id=rule.get("id", rule_type),
        rule_type=rule_type,
        check=rule.get("label", rule_type.replace("_", " ").title()),
        severity=kwargs.pop("severity", rule.get("severity", "medium")),
        needs_human_check=kwargs.pop("needs_human_check", bool(rule.get("needs_human_check", False))),
        exclude_from_totals=kwargs.pop("exclude_from_totals", bool(rule.get("exclude_from_totals", False))),
        **kwargs,
    )


def _where(df: pd.DataFrame, rule: dict) -> pd.DataFrame:
    for col, allowed in (rule.get("where") or {}).items():
        if col in df:
            allowed = allowed if isinstance(allowed, list) else [allowed]
            df = df[df[col].isin(allowed)]
    return df


def _date(value) -> pd.Timestamp | None:
    return None if pd.isna(value) else pd.Timestamp(value)


def fmt_date(value) -> str:
    return "" if value is None or pd.isna(value) else pd.Timestamp(value).strftime("%d %b %Y")


def _neighbours(series_df: pd.DataFrame, idx_pos: int, ctx: RuleContext, n: int = 3) -> dict:
    """Values either side of a position in a group's sorted series (for context)."""
    def pick(rows):
        return [{"date": fmt_date(r[ctx.date]), ctx.value: None if pd.isna(r[ctx.value]) else round(float(r[ctx.value]), 1)}
                for _, r in rows.iterrows()]
    return {"before": pick(series_df.iloc[max(idx_pos - n, 0):idx_pos]),
            "after": pick(series_df.iloc[idx_pos + 1:idx_pos + 1 + n])}


def _row_context(row: pd.Series, extra_cols: list[str]) -> dict:
    out = {"source_file": row.get("_source"), "source_row": int(row["_row"]) if "_row" in row and pd.notna(row["_row"]) else None}
    for c in extra_cols:
        if c in row and pd.notna(row[c]):
            v = row[c]
            out[c] = round(float(v), 1) if isinstance(v, (float, np.floating)) else (fmt_date(v) if isinstance(v, pd.Timestamp) else v)
    return out


def _groups(ctx: RuleContext, rule: dict):
    working = _where(ctx.working, rule)
    for key, grp in working.groupby(ctx.key, sort=True):
        yield key, grp.reset_index(drop=True)

# ----------------------------------------------------------------------- rules


def check_missing(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> list[Finding]:
    """Blank cells in any of ``columns``."""
    cols = [c for c in rule.get("columns", [ctx.value]) if c in df]
    out = []
    for _, row in _where(df, rule).iterrows():
        missing = [c for c in cols if pd.isna(row[c]) and (row["_rid"], c) not in ctx.parse_cells]
        if not missing:
            continue
        present = [c for c in cols if c not in missing]
        names = " or ".join(ctx.label(c) for c in missing)
        detail = f"No {names} recorded" + (f" ({', '.join(ctx.label(c) for c in present)} present)." if present else ".")
        out.append(_finding(rule, "missing", detail=detail, group=row.get(ctx.key), date_from=_date(row.get(ctx.date)),
                            column=missing[0], value=None, expected="a value", rids=[int(row["_rid"])],
                            context={**_row_context(row, cols), "missing_columns": missing}))
    return out


def check_range(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> list[Finding]:
    """Values below ``min``/``min_column`` or above ``max``/``max_column``."""
    col = rule["column"]
    sub = _where(df, rule)
    sub = sub[sub[col].notna()]
    lo = pd.Series(rule.get("min"), index=sub.index, dtype=float) if rule.get("min") is not None else pd.Series(np.nan, index=sub.index)
    hi = pd.Series(rule.get("max"), index=sub.index, dtype=float) if rule.get("max") is not None else pd.Series(np.nan, index=sub.index)
    if rule.get("min_column") in sub:
        lo = sub[rule["min_column"]].astype(float).combine(lo, lambda a, b: a if pd.notna(a) else b)
    if rule.get("max_column") in sub:
        hi = sub[rule["max_column"]].astype(float).combine(hi, lambda a, b: a if pd.notna(a) else b)
    out = []
    for idx, row in sub.iterrows():
        value = float(row[col])
        low, high = lo[idx], hi[idx]
        if pd.notna(low) and value < low:
            detail = f"{ctx.fmt(value)} is below the minimum of {ctx.fmt(low)}."
        elif pd.notna(high) and value > high:
            ratio = value / high if high else float("inf")
            detail = f"{ctx.fmt(value)} is above the maximum possible {ctx.fmt(high)} ({ratio:.1f}× the limit)."
        else:
            continue
        expected = f"{ctx.fmt(low) if pd.notna(low) else '…'} to {ctx.fmt(high) if pd.notna(high) else '…'}"
        out.append(_finding(rule, "range", detail=detail, group=row.get(ctx.key), date_from=_date(row.get(ctx.date)),
                            column=col, value=value, expected=expected, rids=[int(row["_rid"])],
                            context=_row_context(row, rule.get("context_columns", []))))
    return out


def check_duplicates(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> list[Finding]:
    """Rows sharing the same ``keys``. Identical copies are low severity and
    auto-resolved (one kept); conflicting copies need a human decision."""
    keys = rule.get("keys", [ctx.key, ctx.date])
    compare = [c for c in rule.get("compare_columns", [ctx.value]) if c in df]
    sub = _where(df, rule).dropna(subset=keys)
    dup = sub[sub.duplicated(keys, keep=False)]
    out = []
    for key_vals, grp in dup.groupby(keys, sort=True):
        key_vals = key_vals if isinstance(key_vals, tuple) else (key_vals,)
        values = grp[compare].round(6)
        exact = len(values.drop_duplicates()) == 1
        shown = "; ".join(ctx.fmt(v) for v in grp[compare[0]]) if compare else ""
        rows = ", ".join(f"row {r}" for r in grp["_row"]) + f" of {grp['_source'].iloc[0]}"
        group = dict(zip(keys, key_vals)).get(ctx.key)
        if exact:
            detail = f"{len(grp)} identical copies of the same reading ({rows}). One copy kept automatically."
            finding = _finding(rule, "duplicates", detail=detail, severity=rule.get("exact_severity", "low"),
                               needs_human_check=False, exclude_from_totals=False)
        else:
            differs = [ctx.label(c) for c in compare if grp[c].round(6).nunique(dropna=False) > 1]
            detail = (f"Loaded {len(grp)} times for the same {' and '.join(ctx.label(k) for k in keys)} with different "
                      f"{' and '.join(differs) or 'values'}: {shown} ({rows}).")
            finding = _finding(rule, "duplicates", detail=detail)
        finding.group, finding.date_from = group, _date(dict(zip(keys, key_vals)).get(ctx.date))
        finding.column, finding.value, finding.rids = compare[0] if compare else None, shown, [int(r) for r in grp["_rid"]]
        finding.context = {"copies": [_row_context(r, compare) for _, r in grp.iterrows()], "identical": exact}
        finding.expected = "one reading per key"
        out.append(finding)
    return out


def check_spike(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> list[Finding]:
    """Isolated jumps: value > ``factor`` × the median of the ``window`` values
    before *and* after it (so a sustained step change is not flagged)."""
    col = rule.get("column", ctx.value)
    window, factor = int(rule.get("window", 14)), float(rule.get("factor", 3.0))
    min_abs, min_base = float(rule.get("min_abs_change", 0)), float(rule.get("min_baseline", 1e-9))
    min_periods = max(3, window // 3)
    out = []
    for key, grp in _groups(ctx, rule):
        vals = grp[col].astype(float)
        before = vals.shift(1).rolling(window, min_periods=min_periods).median()
        after = vals[::-1].shift(1).rolling(window, min_periods=min_periods).median()[::-1]
        baseline = pd.concat([before, after], axis=1).max(axis=1, skipna=True)
        for pos in np.flatnonzero(((vals > factor * baseline) & (vals - baseline >= min_abs) & (baseline >= min_base)).to_numpy()):
            row, base = grp.iloc[pos], float(baseline.iloc[pos])
            value = float(row[col])
            detail = (f"{ctx.fmt(value)} is {value / base:.1f}× the typical level for this {ctx.key_noun} "
                      f"(median of surrounding days ≈ {ctx.fmt(base)}).")
            out.append(_finding(rule, "spike", detail=detail, group=key, date_from=_date(row[ctx.date]), column=col,
                                value=value, expected=f"around {ctx.fmt(base)}", rids=[int(row["_rid"])],
                                context={**_row_context(row, rule.get("context_columns", [])), "typical_level": round(base, 1),
                                         "ratio": round(value / base, 2), **_neighbours(grp, pos, ctx)}))
    return out


def check_date_gap(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> list[Finding]:
    """Missing dates within each group (and at the start/end of the period)."""
    freq = int(rule.get("frequency_days", 1))
    min_gap = int(rule.get("min_gap_days", 1))
    high_from = rule.get("high_if_days_at_least")
    cum = rule.get("cumulative_column")
    out = []
    for key, grp in _groups(ctx, rule):
        dates = grp[ctx.date].drop_duplicates().sort_values().reset_index(drop=True)
        if dates.empty:
            continue
        spans = []
        bounds = [ctx.period_start - pd.Timedelta(days=freq)] if rule.get("check_edges", True) and ctx.period_start is not None else []
        series = pd.concat([pd.Series(bounds, dtype="datetime64[ns]"), dates], ignore_index=True)
        if rule.get("check_edges", True) and ctx.period_end is not None:
            series = pd.concat([series, pd.Series([ctx.period_end + pd.Timedelta(days=freq)], dtype="datetime64[ns]")], ignore_index=True)
        for prev, nxt in zip(series[:-1], series[1:]):
            missing = (nxt - prev).days // freq - 1
            if missing >= min_gap:
                spans.append((prev + pd.Timedelta(days=freq), nxt - pd.Timedelta(days=freq), missing, prev, nxt))
        for start, end, days, prev, nxt in spans:
            where = "at the end of the period" if ctx.period_end is not None and end >= ctx.period_end else (
                "at the start of the period" if ctx.period_start is not None and start <= ctx.period_start else "")
            span = fmt_date(start) if days == 1 else f"{fmt_date(start)} – {fmt_date(end)}"
            detail = f"No readings for {days} day{'s' if days != 1 else ''} ({span}){' ' + where if where else ''}."
            context = {"days_missing": days, "last_reading_before": fmt_date(prev) if prev in set(dates) else None,
                       "first_reading_after": fmt_date(nxt) if nxt in set(dates) else None}
            if cum and cum in grp and context["last_reading_before"] and context["first_reading_after"]:
                a = grp.loc[grp[ctx.date] == prev, cum].iloc[0]
                b = grp.loc[grp[ctx.date] == nxt, cum].iloc[0]
                if pd.notna(a) and pd.notna(b):
                    context["register_advance_across_gap"] = round(float(b - a), 1)
            severity = "high" if high_from and days >= int(high_from) else rule.get("severity", "medium")
            out.append(_finding(rule, "date_gap", detail=detail, group=key, date_from=start, date_to=end,
                                column=ctx.date, value=days, expected=f"a reading every {freq} day{'s' if freq > 1 else ''}",
                                severity=severity, context=context))
    return out


def check_flatline(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> list[Finding]:
    """Runs of ``min_run`` or more identical values (default: zeros)."""
    col = rule.get("column", ctx.value)
    target = rule.get("value", 0)
    min_run = int(rule.get("min_run", 3))
    out = []
    for key, grp in _groups(ctx, rule):
        vals = grp[col].astype(float)
        hit = (vals - float(target)).abs() < 1e-9 if target is not None else vals.eq(vals.shift(1)) | vals.eq(vals.shift(-1))
        run_id = (hit != hit.shift()).cumsum()
        for _, run in grp[hit.to_numpy()].groupby(run_id[hit]):
            if len(run) < min_run:
                continue
            start, end = run[ctx.date].min(), run[ctx.date].max()
            around = vals[~hit & vals.notna()]
            near = grp.loc[around.index]
            near = near[(near[ctx.date] >= start - pd.Timedelta(days=14)) & (near[ctx.date] <= end + pd.Timedelta(days=14))]
            typical = float(near[col].median()) if not near.empty else None
            detail = f"{len(run)} consecutive days at {ctx.fmt(float(run[col].iloc[0]))} ({fmt_date(start)} – {fmt_date(end)})."
            context = {"days": len(run), "typical_level_nearby": round(typical, 1) if typical is not None else None}
            if typical:
                context["estimated_shortfall"] = round(typical * len(run), 0)
                detail += f" Typical nearby level ≈ {ctx.fmt(typical)}/day, so roughly {ctx.fmt(typical * len(run))} may be unrecorded."
            out.append(_finding(rule, "flatline", detail=detail, group=key, date_from=start, date_to=end, column=col,
                                value=float(run[col].iloc[0]), expected="normal variation", rids=[int(r) for r in run["_rid"]],
                                context=context))
    return out


def check_reference(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> list[Finding]:
    """Values of ``column`` that are not in the reference list (e.g. the site
    register), with a closest-match suggestion. Optionally reports reference
    entries that have no data at all."""
    col = rule.get("column", ctx.key)
    ref = ctx.reference
    if ref is None or col not in ref:
        return []
    known = [str(v) for v in ref[col].dropna().unique()]
    present = set(df[col].dropna().astype(str))
    unused = [k for k in known if k not in present]
    out, matched_unused = [], set()
    for value, grp in df[df[col].notna() & ~df[col].astype(str).isin(known)].groupby(col, sort=True):
        value = str(value)
        suggestion = (difflib.get_close_matches(value, unused, n=1, cutoff=0.75) or
                      difflib.get_close_matches(value, known, n=1, cutoff=0.75) or [None])[0]
        dates = grp[ctx.date].dropna()
        span = f"{fmt_date(dates.min())} – {fmt_date(dates.max())}" if not dates.empty else "unknown dates"
        detail = f"{len(grp)} readings ({span}) use “{value}”, which is not in the reference list."
        context = {"rows": len(grp), "source_files": sorted(grp["_source"].unique().tolist())}
        if suggestion:
            matched_unused.add(suggestion)
            ref_row = ref[ref[col].astype(str) == suggestion].iloc[0]
            context["closest_reference_match"] = {k: (v if not isinstance(v, float) else round(v, 1))
                                                  for k, v in ref_row.items() if pd.notna(v)}
            context["closest_match_has_no_data"] = suggestion in unused
            detail += f" Closest match: “{suggestion}”" + (" — which has no readings of its own in these files." if suggestion in unused else ".")
        out.append(_finding(rule, "reference", detail=detail, group=value, date_from=_date(dates.min()) if not dates.empty else None,
                            date_to=_date(dates.max()) if not dates.empty else None, column=col, value=value,
                            expected=f"one of the {len(known)} known values" + (f" (probably {suggestion})" if suggestion else ""),
                            rids=[int(r) for r in grp["_rid"]], context=context))
    if rule.get("report_unused", True):
        for value in unused:
            if value in matched_unused:
                continue
            ref_row = ref[ref[col].astype(str) == value].iloc[0]
            out.append(_finding(rule, "reference", detail=f"“{value}” is in the reference list but has no readings in these files.",
                                group=value, column=col, value=value, expected="readings for every listed value",
                                severity=rule.get("unused_severity", "medium"),
                                context={k: v for k, v in ref_row.items() if pd.notna(v)}))
    return out


def check_consistency(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> list[Finding]:
    """For consecutive readings, the change in a cumulative column (e.g. a meter
    register) should equal the per-period value (e.g. daily kWh)."""
    cum, col = rule["cumulative_column"], rule.get("column", ctx.value)
    freq = int(rule.get("frequency_days", 1))
    tol_abs, tol_pct = float(rule.get("tolerance", 0.5)), float(rule.get("tolerance_pct", 0.0))
    out = []
    for key, grp in _groups(ctx, rule):
        advance = grp[cum].diff()
        consecutive = grp[ctx.date].diff().dt.days == freq
        diff = (advance - grp[col]).abs()
        allowed = np.maximum(tol_abs, tol_pct / 100 * grp[col].abs())
        bad = consecutive & advance.notna() & grp[col].notna() & (diff > allowed)
        for pos in np.flatnonzero(bad.to_numpy()):
            row = grp.iloc[pos]
            adv = float(advance.iloc[pos])
            name = ctx.label(col)
            detail = (f"{name[:1].upper() + name[1:]} is {ctx.fmt(float(row[col]))} but the {ctx.label(cum)} advanced by {ctx.fmt(adv)} "
                      f"since the previous day (difference {ctx.fmt(abs(adv - float(row[col])))}).")
            out.append(_finding(rule, "consistency", detail=detail, group=key, date_from=_date(row[ctx.date]), column=col,
                                value=float(row[col]), expected=f"{ctx.fmt(adv)} (from {ctx.label(cum)})",
                                rids=[int(row["_rid"])],
                                context={**_row_context(row, [cum]), "previous_" + cum: round(float(grp[cum].iloc[pos - 1]), 1),
                                         "register_advance": round(adv, 1), **_neighbours(grp, pos, ctx)}))
    return out


RULE_TYPES: dict[str, Callable[[pd.DataFrame, dict, RuleContext], list[Finding]]] = {
    "missing": check_missing,
    "range": check_range,
    "duplicates": check_duplicates,
    "spike": check_spike,
    "date_gap": check_date_gap,
    "flatline": check_flatline,
    "reference": check_reference,
    "consistency": check_consistency,
}
