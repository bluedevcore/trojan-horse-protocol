"""Output files for a validation run: Excel report pack, PDF report, Word
discrepancy notes and an exceptions CSV."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd

from core import downloads as dl
from core.ui import DownloadFile

if TYPE_CHECKING:  # pragma: no cover
    from tools.data_validation.pipeline import RunResult


def attach_notes(exceptions: pd.DataFrame, notes: dict[str, dict]) -> pd.DataFrame:
    exc = exceptions.copy()
    if exc.empty:
        for col in ("Note", "Likely cause", "Suggested action", "Note source"):
            exc[col] = []
        return exc
    exc["Note"] = exc["ID"].map(lambda i: notes.get(i, {}).get("note", ""))
    exc["Likely cause"] = exc["ID"].map(lambda i: notes.get(i, {}).get("likely_cause", ""))
    exc["Suggested action"] = exc["ID"].map(lambda i: notes.get(i, {}).get("suggested_action", ""))
    labels = {"api": "Claude", "cache": "Claude (cached)", "fixture": "Pre-recorded (mock mode)", "mock": "Template",
              "fallback": "Template", "template": "Template"}
    exc["Note source"] = exc["ID"].map(lambda i: labels.get(notes.get(i, {}).get("source", ""), ""))
    return exc


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def file_stem(r: "RunResult") -> str:
    return f"{_slug(r.config.get('tool_name', 'data-check'))}_{_slug(r.period_label)}"


def summary_frame(r: "RunResult") -> pd.DataFrame:
    f = r.facts
    rows = [
        ("Report", f"{r.config.get('tool_name', 'Data check')} — validation report pack"),
        ("Prepared as at", f["as_of"]),
        ("Data period", f["period"]),
        ("Input", f"{r.inputs_label}: {', '.join(r.files_read)}"),
        ("Readings checked", f"{f['readings_checked']:,}"),
        (f"{r.spec.key_label}s", f["records"]),
        ("Passed every check", f"{f['pass_rate_pct']}%"),
        ("Exceptions", f["exceptions"]),
        ("Needs human check", f["needs_human_check"]),
        ("Readings held from totals", f["readings_held_from_totals"]),
    ]
    for cat, total in (f.get("validated_totals") or {}).items():
        rows.append((f"Validated total — {cat}", total))
    rows += [("Manager summary", r.summary), ("Summary source", r.summary_source),
             ("Estimated time saved", f"{r.time_estimate.saved_label} (assumptions below)")]
    rows += [("Assumption", a) for a in r.time_estimate.assumptions]
    return pd.DataFrame(rows, columns=["Item", "Value"])


def rules_frame(config: dict) -> pd.DataFrame:
    rows = []
    for rule in config.get("rules", []):
        settings = {k: v for k, v in rule.items() if k not in ("id", "type", "label", "severity", "needs_human_check",
                                                              "exclude_from_totals")}
        rows.append({"Rule": rule.get("label", rule.get("id")), "Type": rule.get("type"),
                     "Severity": str(rule.get("severity", "medium")).title(),
                     "Needs human check": "Yes" if rule.get("needs_human_check") else "No",
                     "Held from totals": "Yes" if rule.get("exclude_from_totals") else "No",
                     "Settings": "; ".join(f"{k}={v}" for k, v in settings.items())})
    return pd.DataFrame(rows)


def validated_data_frame(r: "RunResult") -> pd.DataFrame:
    spec = r.spec
    d = r.validation.data.copy()
    cols = [spec.key, *spec.display_columns.keys(), spec.date, *[c for c in spec.numeric if c != spec.value], spec.value]
    cols = [c for c in dict.fromkeys(cols) if c in d]
    out = d[cols + ["_exception_ids", "_held", "_source", "_row"]].rename(columns={
        **spec.display_columns, spec.key: spec.key_label, "_exception_ids": "Exceptions", "_source": "Source file",
        "_row": "Source row"})
    out["Status"] = d.apply(lambda x: "Held for review" if x["_held"] else ("Flagged" if x["_exception_ids"] else "OK"), axis=1)
    out = out.drop(columns=["_held"])
    labels = spec.column_labels
    def heading(c: str) -> str:
        name = labels.get(c, c)
        return name[:1].upper() + name[1:]

    out = out.rename(columns={c: heading(c) for c in out.columns if c in labels})
    return out.sort_values([spec.key_label, heading(spec.date)], na_position="last")


def public(df: pd.DataFrame) -> pd.DataFrame:
    """Drop internal columns (names starting with _) before display or export."""
    return df.drop(columns=[c for c in df.columns if str(c).startswith("_")]) if not df.empty else df


def exceptions_for_export(r: "RunResult") -> pd.DataFrame:
    return public(r.exceptions)


def tracker_for_export(r: "RunResult") -> pd.DataFrame:
    return public(r.tracker)


def build_downloads(r: "RunResult") -> list[DownloadFile]:
    stem = file_stem(r)
    exc = exceptions_for_export(r)
    human = exc[exc["Needs human check"] == "Yes"] if not exc.empty else exc
    sheets = {
        "Summary": summary_frame(r),
        "Exceptions": exc,
        "Needs human check": human,
        "Monthly totals": r.totals_by_key,
        "Totals by type": r.totals_by_category,
        "Deadline tracker": tracker_for_export(r),
        "Validated data": validated_data_frame(r),
        "Rules applied": rules_frame(r.config),
    }
    sheets = {k: v for k, v in sheets.items() if v is not None and not (v.empty and k in ("Deadline tracker", "Totals by type"))}
    xlsx = dl.excel_bytes(sheets, wrap_columns=["Value", "Finding", "Note", "Likely cause", "Suggested action", "Settings"])

    return [
        DownloadFile("Report pack (Excel)", xlsx, f"{stem}_report-pack.xlsx",
                     "Summary, exceptions, human checks, monthly totals, deadline tracker, validated data, rules"),
        DownloadFile("Validation report (PDF)", pdf_report(r), f"{stem}_validation-report.pdf",
                     "Manager summary, exceptions, deadline tracker and totals, ready to circulate"),
        DownloadFile("Discrepancy notes (Word)", notes_docx(r), f"{stem}_discrepancy-notes.docx",
                     "One editable note per exception"),
        DownloadFile("Exceptions list (CSV)", dl.csv_bytes(exc), f"{stem}_exceptions.csv",
                     "All exceptions with notes, for import into another system"),
    ]


def _document_blocks(r: "RunResult") -> list[dict]:
    f, spec = r.facts, r.spec
    site = next(iter(spec.display_columns.values()), None)
    blocks = [
        dl.heading("Summary"),
        dl.metrics([("Readings checked", f["readings_checked"]), (f"{spec.key_label}s", f["records"]),
                    ("Passed every check", f"{f['pass_rate_pct']}%"), ("Exceptions", f["exceptions"]),
                    ("Need a human check", f["needs_human_check"])]),
        dl.para(r.summary),
        dl.note(r.summary_source),
    ]
    exc = public(r.exceptions)
    if not exc.empty:
        human = exc[exc["Needs human check"] == "Yes"]
        if not human.empty:
            cols = ["ID", "Severity", "Check", spec.key_label, *([site] if site else []), "Date(s)", "Note", "Suggested action"]
            blocks += [dl.heading("Needs human check"), dl.table(human[[c for c in cols if c in human]],
                                                                 widths=[5, 6, 9, 9, 11, 10, 34, 22][:len(cols)])]
        cols = ["ID", "Severity", "Check", spec.key_label, *spec.display_columns.values(), "Date(s)", "Value", "Finding"]
        blocks += [dl.heading("All exceptions"), dl.table(exc[[c for c in cols if c in exc]],
                                                          widths=[5, 6, 9, 9, 11, 9, 10, 9, 33][:len(cols)])]
    else:
        blocks += [dl.heading("Exceptions"), dl.para("No exceptions found.")]
    tracker = tracker_for_export(r)
    if not tracker.empty:
        blocks += [dl.heading("Reporting deadline tracker"),
                   dl.table(tracker, widths=[24, 13, 9, 8, 11, 17, 5, 9]),
                   dl.note(f"Status as at {f['as_of']}. 'Blocked' means open exceptions affect data this report depends on.")]
    if not r.totals_by_category.empty:
        blocks += [dl.heading("Validated totals by type"), dl.table(r.totals_by_category)]
    if not r.totals_by_key.empty:
        blocks += [dl.page_break(), dl.heading(f"Validated monthly totals by {spec.key_label.lower()}"), dl.table(r.totals_by_key),
                   dl.note("Held readings are excluded from validated totals until a person confirms them.")]
    blocks += [dl.heading("Method"), dl.bullets([
        f"{len(r.config.get('rules', [])) + 1} deterministic rules checked every reading (see 'Rules applied' in the Excel pack).",
        "Figures, matching and totals are calculated in code. Claude only drafted the wording of notes and the summary.",
        "Nothing is corrected automatically except identical duplicate rows; uncertain items are listed for a human check.",
    ])]
    return blocks


def pdf_report(r: "RunResult") -> bytes:
    cfg = r.config
    subtitle = (f"Data period {r.facts['period']} · prepared {r.facts['as_of']} · {r.inputs_label}"
                + (f" · {cfg.get('client_name')} prototype" if cfg.get("client_name") else ""))
    return dl.pdf_bytes(f"{cfg.get('tool_name', 'Data check')} — validation report", _document_blocks(r),
                        subtitle=subtitle, footer=cfg.get("footer_short") or "Prototype — synthetic data")


def notes_docx(r: "RunResult") -> bytes:
    spec = r.spec
    blocks = [dl.para(r.summary), dl.note(r.summary_source)]
    for _, e in r.exceptions.iterrows():
        where = " · ".join(str(e[h]) for h in spec.display_columns.values() if h in e and e[h])
        blocks += [
            dl.heading(f"{e['ID']} · {e['Check']} · {e[spec.key_label]}", level=2),
            dl.note(f"{where} · {e['Date(s)']} · Severity {e['Severity']} · "
                    f"Needs human check: {e['Needs human check']} · Held from totals: {e['Held from totals']}"),
            dl.para(f"Finding: {e['Finding']}"),
            dl.para(f"Note: {e.get('Note', '')}"),
            dl.para(f"Likely cause: {e.get('Likely cause', '')}"),
            dl.para(f"Suggested action: {e.get('Suggested action', '')}"),
            dl.note(f"Source: {e['Source']} · Note drafted by: {e.get('Note source', '')}"),
        ]
    return dl.docx_bytes("Discrepancy notes", blocks,
                         subtitle=f"{r.config.get('tool_name', '')} · data period {r.facts['period']} · prepared {r.facts['as_of']}")
