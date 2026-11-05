"""Run configured rules over a table and turn findings into an exceptions list,
validated data and period totals. Deterministic: no AI in this module."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from tools.data_validation.loader import ParseIssue
from tools.data_validation.rules import RULE_TYPES, Finding, RuleContext, fmt_date

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


class ConfigError(Exception):
    pass


@dataclass
class DatasetSpec:
    """Which columns mean what. Built from the ``dataset`` section of config."""

    key: str
    date: str
    value: str
    unit: str = ""
    key_label: str = "Record"
    value_label: str = "Value"
    aliases: dict = field(default_factory=dict)
    required: list = field(default_factory=list)
    numeric: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    display_columns: dict = field(default_factory=dict)  # reference column -> heading
    column_labels: dict = field(default_factory=dict)  # column -> plain-English name used in findings
    category_column: str | None = None

    @classmethod
    def from_config(cls, cfg: dict) -> "DatasetSpec":
        try:
            spec = cls(**{k: v for k, v in cfg.items() if k in cls.__dataclass_fields__})
        except TypeError as exc:
            raise ConfigError(f"dataset section is incomplete: {exc}") from exc
        spec.required = spec.required or [spec.key, spec.date, spec.value]
        spec.dates = spec.dates or [spec.date]
        spec.numeric = spec.numeric or [spec.value]
        return spec


@dataclass
class ValidationResult:
    data: pd.DataFrame  # all rows, with _held and _exception_ids columns
    working: pd.DataFrame  # one row per key+date with a valid date
    findings: list[Finding]
    exceptions: pd.DataFrame
    period_start: pd.Timestamp | None
    period_end: pd.Timestamp | None


def validate(data: pd.DataFrame, spec: DatasetSpec, rules: list[dict], *, reference: pd.DataFrame | None = None,
             parse_issues: list[ParseIssue] = (), parse_rule: dict | None = None) -> ValidationResult:
    for rule in rules:
        if rule.get("type") not in RULE_TYPES:
            raise ConfigError(f"Unknown rule type “{rule.get('type')}”. Known: {', '.join(RULE_TYPES)}.")

    df = data.copy()
    if reference is not None and not reference.empty:
        extra = [c for c in reference.columns if c == spec.key or c not in df.columns]
        ref = reference[extra].drop_duplicates(subset=[spec.key])
        df[spec.key] = df[spec.key].astype("string").str.strip()
        ref = ref.assign(**{spec.key: ref[spec.key].astype("string").str.strip()})
        df = df.merge(ref, on=spec.key, how="left")
    df = df.sort_values("_rid").reset_index(drop=True)

    valid_dates = df[df[spec.date].notna() & df[spec.key].notna()]
    working = (valid_dates.sort_values([spec.key, spec.date, "_rid"])
               .drop_duplicates(subset=[spec.key, spec.date], keep="first").reset_index(drop=True))
    period_start = valid_dates[spec.date].min() if not valid_dates.empty else None
    period_end = valid_dates[spec.date].max() if not valid_dates.empty else None

    ctx = RuleContext(key=spec.key, date=spec.date, value=spec.value, unit=spec.unit, working=working,
                      period_start=period_start, period_end=period_end, reference=reference,
                      parse_cells={(i.rid, i.column) for i in parse_issues}, labels=spec.column_labels,
                      key_noun=spec.key_label.lower())

    findings = _parse_findings(df, parse_issues, spec, parse_rule or {})
    for rule in rules:
        findings += RULE_TYPES[rule["type"]](df, rule, ctx)
    findings = _dedupe(findings)
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), str(f.group), f.date_from or pd.Timestamp.min, f.rule_id))

    width = max(2, len(str(len(findings))))
    ids = [f"EX-{i:0{width}d}" for i in range(1, len(findings) + 1)]
    held, by_row = set(), {}
    for ex_id, f in zip(ids, findings):
        f.context["exception_id"] = ex_id
        for rid in f.rids:
            by_row.setdefault(rid, []).append(ex_id)
            if f.exclude_from_totals:
                held.add(rid)
    df["_held"] = df["_rid"].isin(held)
    df["_exception_ids"] = df["_rid"].map(lambda r: ", ".join(by_row.get(r, [])))
    working = working.merge(df[["_rid", "_held", "_exception_ids"]], on="_rid", how="left")

    exceptions = _exceptions_frame(findings, ids, df, spec)
    return ValidationResult(df, working, findings, exceptions, period_start, period_end)


def _parse_findings(df: pd.DataFrame, issues: list[ParseIssue], spec: DatasetSpec, rule: dict) -> list[Finding]:
    """Unreadable dates/numbers become findings with neighbouring rows as context."""
    out = []
    for issue in issues:
        row = df[df["_rid"] == issue.rid]
        group = row[spec.key].iloc[0] if not row.empty else None
        context = {"source_file": issue.source, "source_row": issue.row, "raw_value": issue.raw_value}
        if issue.kind == "date" and not row.empty:
            same = df[(df["_source"] == issue.source) & (df[spec.key] == group)]
            prev = same[same["_row"] < issue.row].tail(1)
            nxt = same[same["_row"] > issue.row].head(1)
            context["previous_row_date"] = fmt_date(prev[spec.date].iloc[0]) if not prev.empty else None
            context["next_row_date"] = fmt_date(nxt[spec.date].iloc[0]) if not nxt.empty else None
            if pd.notna(row[spec.value].iloc[0]):
                context[spec.value] = round(float(row[spec.value].iloc[0]), 1)
        what = "date" if issue.kind == "date" else "number"
        out.append(Finding(
            rule_id=rule.get("id", "unreadable_value"), rule_type="unreadable", check=rule.get("label", f"Unreadable {what}"),
            severity=rule.get("severity", "medium"), needs_human_check=bool(rule.get("needs_human_check", True)),
            exclude_from_totals=bool(rule.get("exclude_from_totals", True)),
            detail=f"“{issue.raw_value}” is not a valid {spec.column_labels.get(issue.column, issue.column)} "
                   f"({issue.source}, row {issue.row}).",
            group=group, column=issue.column, value=issue.raw_value, expected=f"a valid {what}",
            rids=[issue.rid] if issue.rid is not None else [], context=context))
    return out


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """One finding per (row, column): the first rule (config order) wins and
    records the other rules that also fired."""
    kept, seen = [], {}
    for f in findings:
        if len(f.rids) == 1:
            key = (f.rids[0], f.column)
            if key in seen:
                if f.check not in seen[key].also_flagged_by:
                    seen[key].also_flagged_by.append(f.check)
                    seen[key].context.setdefault("also_flagged", []).append(f.detail)
                continue
            seen[key] = f
        kept.append(f)
    return kept


def _exceptions_frame(findings: list[Finding], ids: list[str], df: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
    lookup = df.drop_duplicates(subset=[spec.key]).set_index(spec.key) if not df.empty else pd.DataFrame()
    rows = []
    for ex_id, f in zip(ids, findings):
        when = fmt_date(f.date_from)
        if f.date_to is not None and f.date_from is not None and f.date_to != f.date_from:
            when = f"{fmt_date(f.date_from)} – {fmt_date(f.date_to)}"
        sources = sorted({(s, int(r)) for s, r in df.loc[df["_rid"].isin(f.rids), ["_source", "_row"]].itertuples(index=False)})
        if len(sources) > 3:
            src = f"{sources[0][0]} ({len(sources)} rows)"
        else:
            src = "; ".join(f"{s} row {r}" for s, r in sources)
        row = {"ID": ex_id, "Severity": f.severity.title(), "Check": f.check, spec.key_label: f.group or ""}
        for col, heading in spec.display_columns.items():
            value = lookup[col].get(f.group) if f.group is not None and col in lookup and f.group in lookup.index else None
            if value is None or pd.isna(value):
                ref = f.context.get("closest_reference_match", {}) if isinstance(f.context, dict) else {}
                value = f.context.get(col) or (f"? (maybe {ref[col]})" if col in ref else "")
            row[heading] = value
        row.update({
            "Date(s)": when,
            "Value": _display_value(f, spec),
            "Expected": f.expected or "",
            "Finding": f.detail + (f" Also flagged: {', '.join(f.also_flagged_by)}." if f.also_flagged_by else ""),
            "Needs human check": "Yes" if f.needs_human_check else "No",
            "Held from totals": "Yes" if f.exclude_from_totals and f.rids else "No",
            "Source": src,
            "_from": f.date_from,
            "_to": f.date_to if f.date_to is not None else f.date_from,
        })
        rows.append(row)
    return pd.DataFrame(rows)

def _display_value(f: Finding, spec: DatasetSpec) -> str:
    v = f.value
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if f.rule_type == "date_gap":
        return f"{int(v)} day{'s' if int(v) != 1 else ''}"
    if isinstance(v, (int, float)):
        return f"{float(v):,.1f}" + (f" {spec.unit}" if spec.unit else "")
    return str(v)

# ---------------------------------------------------------------------- totals


def period_totals(result: ValidationResult, spec: DatasetSpec, *, label_columns: list[str] | None = None,
                  freq: str = "M", reference: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validated totals per key per month (held rows excluded), plus totals by
    category. Keys listed in ``reference`` but absent from the data are shown
    as "No data". Returns (by_key, by_category)."""
    w = result.working.copy()
    if w.empty:
        return pd.DataFrame(), pd.DataFrame()
    label_columns = [c for c in (label_columns or []) if c in w and c != spec.key]
    w["_period"] = w[spec.date].dt.to_period(freq)
    w["_ok"] = w[spec.value].notna() & ~w["_held"].fillna(False).astype(bool)
    w["_valid_value"] = w[spec.value].where(w["_ok"], 0.0)
    held_flags = w["_held"].fillna(False).astype(bool)

    periods = pd.period_range(result.period_start, result.period_end, freq=freq)
    expected_days = {p: _days_in(p, result.period_start, result.period_end) for p in periods}
    ex_ids: dict[str, list[str]] = {}
    open_ids: dict[str, list[str]] = {}
    for f in result.findings:
        if f.group is not None:
            ex_ids.setdefault(str(f.group), []).append(f.context.get("exception_id", ""))
            if f.needs_human_check or f.severity in ("high", "medium"):
                open_ids.setdefault(str(f.group), []).append(f.context.get("exception_id", ""))

    keys = w[[spec.key, *label_columns]].drop_duplicates(subset=[spec.key])
    if reference is not None and spec.key in reference:
        absent = reference[~reference[spec.key].astype(str).isin(keys[spec.key].astype(str))]
        keys = pd.concat([keys, absent[[c for c in [spec.key, *label_columns] if c in absent]]], ignore_index=True)
    unit = f" ({spec.unit})" if spec.unit else ""
    rows = []
    for _, k in keys.iterrows():
        g = w[w[spec.key] == k[spec.key]]
        row = {spec.key_label: k[spec.key], **{c: (k[c] if pd.notna(k[c]) else "Unknown") for c in label_columns}}
        good_days, total_days, total = 0, 0, 0.0
        for p in periods:
            gp = g[g["_period"] == p]
            row[p.strftime("%b %Y") + unit] = round(float(gp["_valid_value"].sum()), 1)
            total += float(gp["_valid_value"].sum())
            good_days += int(gp["_ok"].sum())
            total_days += expected_days[p]
        held = int(held_flags[g.index].sum())
        ids = ex_ids.get(str(k[spec.key]), [])
        row["Total validated" + unit] = round(total, 1)
        row["Valid days"] = f"{good_days}/{total_days}"
        row["Completeness %"] = round(100 * good_days / total_days, 1) if total_days else 0.0
        row["Held readings"] = held
        row["Exceptions"] = ", ".join(ids)
        row["Status"] = ("No data" if g.empty else "Incomplete" if good_days + held < total_days
                         else "Held for review" if held else "Check flags" if open_ids.get(str(k[spec.key])) else "Complete")
        rows.append(row)
    by_key = pd.DataFrame(rows)

    by_cat = pd.DataFrame()
    if spec.category_column and spec.category_column in by_key:
        num_cols = [c for c in by_key.columns if c.endswith(unit) and unit] + ["Held readings"]
        by_cat = by_key.groupby(spec.category_column, sort=True)[num_cols].sum().round(1).reset_index()
        counts = by_key.groupby(spec.category_column).size().rename(f"{spec.key_label}s").reset_index()
        by_cat = counts.merge(by_cat, on=spec.category_column)
    return by_key, by_cat


def _days_in(period: pd.Period, start: pd.Timestamp, end: pd.Timestamp) -> int:
    lo = max(period.start_time.normalize(), start)
    hi = min(period.end_time.normalize(), end)
    return max((hi - lo).days + 1, 0)
