"""Each rule on a small hand-made table."""

import numpy as np
import pandas as pd

from tools.data_validation.engine import DatasetSpec, period_totals, validate
from tools.data_validation.loader import ParseIssue

SPEC = DatasetSpec(key="meter", date="date", value="kwh", unit="kWh", key_label="Meter",
                   numeric=["kwh", "register"], column_labels={"kwh": "daily kWh"})


def table(rows):
    """rows: list of (meter, 'YYYY-MM-DD', kwh, register)"""
    df = pd.DataFrame(rows, columns=["meter", "date", "kwh", "register"])
    df["date"] = pd.to_datetime(df["date"])
    df["_source"], df["_row"] = "t.csv", range(2, len(df) + 2)
    df.insert(0, "_rid", range(len(df)))
    return df


def series(meter, start, values, register_start=1000.0):
    days = pd.date_range(start, periods=len(values))
    reg = register_start + np.nancumsum(values)
    return [(meter, d.strftime("%Y-%m-%d"), v, r) for d, v, r in zip(days, values, reg)]


def run(rows, rules, **kw):
    return validate(table(rows), SPEC, rules, **kw)


def checks(result):
    return sorted(result.exceptions["Check"]) if not result.exceptions.empty else []


def test_clean_data_has_no_exceptions():
    rules = [{"type": "missing", "columns": ["kwh"]}, {"type": "range", "column": "kwh", "min": 0},
             {"type": "spike", "window": 7, "factor": 3}, {"type": "date_gap"}, {"type": "duplicates"}]
    assert run(series("A", "2026-08-01", [100.0 + i % 5 for i in range(30)]), rules).exceptions.empty


def test_missing_values():
    rows = series("A", "2026-08-01", [10.0, 11.0, 12.0])
    rows[1] = ("A", rows[1][1], np.nan, rows[1][3])
    res = run(rows, [{"type": "missing", "label": "Missing", "columns": ["kwh", "register"]}])
    assert checks(res) == ["Missing"]
    assert "daily kWh" in res.exceptions["Finding"].iloc[0] and "present" in res.exceptions["Finding"].iloc[0]


def test_range_with_per_row_maximum():
    df_rows = series("A", "2026-08-01", [10.0, 500.0, -3.0])
    df = table(df_rows)
    df["max_kwh"] = 100.0
    res = validate(df, SPEC, [{"type": "range", "label": "Range", "column": "kwh", "min": 0, "max_column": "max_kwh"}])
    assert len(res.exceptions) == 2
    assert {"above the maximum", "below the minimum"} <= {
        "above the maximum" if "above" in f else "below the minimum" for f in res.exceptions["Finding"]}


def test_duplicates_exact_vs_conflicting():
    rows = series("A", "2026-08-01", [10.0, 11.0, 12.0])
    rows += [rows[0], ("A", rows[1][1], 22.0, rows[1][3])]
    res = run(rows, [{"type": "duplicates", "label": "Dup", "severity": "high", "needs_human_check": True,
                      "exclude_from_totals": True}])
    exc = res.exceptions.set_index("Severity")
    assert exc.loc["Low", "Needs human check"] == "No"  # identical copy auto-resolved
    assert exc.loc["High", "Needs human check"] == "Yes"  # conflicting values need a person
    held = res.data[res.data["_held"]]
    assert set(held["date"].dt.day) == {2}  # both copies of the conflicting day held, identical ones not


def test_isolated_spike_flagged_but_step_change_is_not():
    values = [100.0] * 20 + [600.0] + [100.0] * 10 + [400.0] * 20  # one spike, then a sustained step up
    res = run(series("A", "2026-08-01", values), [{"type": "spike", "label": "Spike", "window": 7, "factor": 3}])
    assert len(res.exceptions) == 1
    assert res.findings[0].date_from == pd.Timestamp("2026-08-21")


def test_date_gaps_inside_and_at_period_end():
    a = series("A", "2026-08-01", [1.0] * 30)
    b = [r for r in series("B", "2026-08-01", [1.0] * 30) if not ("2026-08-10" <= r[1] <= "2026-08-12")][:-5]
    res = run(a + b, [{"type": "date_gap", "label": "Gap", "high_if_days_at_least": 5, "cumulative_column": "register"}])
    gaps = {(f.value, f.severity) for f in res.findings}
    assert gaps == {(3, "medium"), (5, "high")}
    inner = next(f for f in res.findings if f.value == 3)
    assert inner.context["register_advance_across_gap"] == 4.0  # 3 missing days + the day after


def test_flatline_zero_run():
    values = [50.0] * 10 + [0.0] * 4 + [50.0] * 10 + [0.0] * 2
    res = run(series("A", "2026-08-01", values), [{"type": "flatline", "label": "Zero", "value": 0, "min_run": 3}])
    assert len(res.findings) == 1 and res.findings[0].context["days"] == 4
    assert res.findings[0].context["estimated_shortfall"] == 200


def test_reference_match_suggests_transposed_serial():
    ref = pd.DataFrame({"meter": ["E17UP04512", "B"], "site": ["Oakleigh", "Other"]})
    rows = series("E17UP04521", "2026-08-01", [1.0] * 3) + series("B", "2026-08-01", [1.0] * 3)
    res = run(rows, [{"type": "reference", "label": "Unknown", "column": "meter"}], reference=ref)
    assert len(res.findings) == 1  # unused E17UP04512 is folded into the suggestion, not reported twice
    assert res.findings[0].context["closest_reference_match"]["meter"] == "E17UP04512"
    assert res.findings[0].context["closest_match_has_no_data"] is True


def test_reference_reports_unused_entries():
    ref = pd.DataFrame({"meter": ["A", "ZZZ-999"]})
    res = run(series("A", "2026-08-01", [1.0] * 3), [{"type": "reference", "column": "meter"}], reference=ref)
    assert len(res.findings) == 1 and "no readings" in res.findings[0].detail


def test_register_consistency_only_on_consecutive_days():
    rows = series("A", "2026-08-01", [10.0, 10.0, 10.0, 10.0])
    rows[2] = (*rows[2][:2], 19.0, rows[2][3])  # daily says 19, register says 10
    del rows[1]  # and a gap before it must not trigger a false mismatch on the next row
    rows = series("B", "2026-08-01", [10.0, 10.0, 10.0]) + rows
    rows[-1] = (*rows[-1][:2], 5.0, rows[-1][3])
    res = run(rows, [{"type": "consistency", "label": "Mismatch", "cumulative_column": "register", "tolerance": 0.5}])
    assert len(res.findings) == 1 and res.findings[0].context["register_advance"] == 10.0


def test_overlapping_rules_are_merged_first_rule_wins():
    df = table(series("A", "2026-08-01", [100.0] * 15 + [2450.0] + [100.0] * 15))
    df["max_kwh"] = 400.0
    rules = [{"type": "range", "label": "Impossible", "column": "kwh", "min": 0, "max_column": "max_kwh"},
             {"type": "spike", "label": "Spike", "window": 7, "factor": 3}]
    res = validate(df, SPEC, rules)
    assert len(res.exceptions) == 1 and "Also flagged: Spike" in res.exceptions["Finding"].iloc[0]


def test_where_filter_limits_rule_to_matching_rows():
    df = table(series("PV", "2026-08-01", [0.0] * 5) + series("HEAT", "2026-08-01", [0.0] * 5))
    df["type"] = np.where(df["meter"] == "PV", "Solar", "Heat")
    res = validate(df, SPEC, [{"type": "flatline", "value": 0, "min_run": 3, "where": {"type": ["Solar"]}}])
    assert [f.group for f in res.findings] == ["PV"]


def test_parse_issue_becomes_exception():
    rows = series("A", "2026-08-01", [1.0, 2.0])
    df = table(rows)
    df.loc[1, "date"] = pd.NaT
    issue = ParseIssue("t.csv", 3, "date", "31/09/2026", "date", rid=1)
    res = validate(df, SPEC, [], parse_issues=[issue])
    assert res.exceptions["Value"].iloc[0] == "31/09/2026"
    assert bool(res.data.loc[1, "_held"])


def test_totals_exclude_held_rows_and_report_completeness():
    rows = series("A", "2026-08-30", [10.0, 10.0, 10.0, 999.0, 10.0])  # 30 Aug - 3 Sep
    df = table(rows)
    df["max_kwh"] = 100.0
    res = validate(df, SPEC, [{"type": "range", "column": "kwh", "max_column": "max_kwh", "exclude_from_totals": True}])
    by_key, _ = period_totals(res, SPEC)
    row = by_key.iloc[0]
    assert row["Aug 2026 (kWh)"] == 20.0 and row["Sep 2026 (kWh)"] == 20.0  # 999 held out
    assert row["Total validated (kWh)"] == 40.0
    assert row["Held readings"] == 1 and row["Valid days"] == "4/5" and row["Status"] == "Held for review"
