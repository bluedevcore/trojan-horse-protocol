"""Streamlit screens for the bookkeeping tool (generic, no client names).

A client's ``app.py`` only needs:

    from tools.bookkeeping.views import run_app
    run_app(Path(__file__).parent)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from core import ui
from core.claude import ClaudeClient
from core.estimates import format_minutes
from tools.bookkeeping import pipeline, reports
from tools.bookkeeping.pipeline import PipelineError, RunInputs, RunResult

RESULT_KEY, STEPS_KEY = "bk_result", "bk_steps"
STATUS_COLOURS = {"Done": "background-color:#E8F6EE;color:#0F5A34", "Action needed": "background-color:#FFF4E0;color:#7A4A00",
                  "To do": "background-color:#EEF1F5;color:#344054", "Held": "background-color:#FFF4E0;color:#7A4A00",
                  "Ready": "background-color:#E8F6EE;color:#0F5A34", "Matched": "background-color:#E8F6EE;color:#0F5A34",
                  "Receipt missing": "background-color:#FDE8E7;color:#8A1C12",
                  "Amount differs": "background-color:#FFF4E0;color:#7A4A00"}


def load_config(client_dir: Path) -> dict:
    return yaml.safe_load((Path(client_dir) / "config.yaml").read_text(encoding="utf-8"))


def run_app(client_dir: Path) -> None:
    client_dir = Path(client_dir)
    try:
        config = load_config(client_dir)
    except (OSError, yaml.YAMLError) as exc:
        st.set_page_config(page_title="Configuration error")
        ui.friendly_error(f"This demo's config.yaml could not be read ({exc}).")
        return

    client = ClaudeClient(fixtures_dir=client_dir / "fixtures")
    ui.page_shell(page_title=config.get("tool_name", "Bookkeeping agent"), headline=config["headline"],
                  replaces=config.get("replaces", ""), mock=client.mock, mode_label=client.mode_label,
                  badges=config.get("badges"))

    run_demo, uploads = _landing(config)
    progress_area = st.container()
    inputs = None
    if run_demo:
        try:
            inputs = pipeline.sample_inputs(client_dir, config)
        except PipelineError as exc:
            ui.friendly_error(str(exc))
    elif uploads:
        inputs = pipeline.upload_inputs(uploads, config, client_dir)

    if inputs is not None:
        st.session_state.pop(RESULT_KEY, None)
        progress = ui.StepProgress(progress_area, delay=float(config.get("step_delay_seconds", 0) or 0))
        try:
            result = pipeline.run(inputs, config, client, progress)
        except PipelineError as exc:
            ui.friendly_error(str(exc), "Check the files and try again, or run the demo with sample data.")
            return
        except Exception as exc:  # last-resort guard: never show a stack trace to a prospect
            progress.fail("Something went wrong", type(exc).__name__)
            ui.friendly_error("Sorry, the run could not finish on these files.", f"Technical detail: {type(exc).__name__}: {exc}")
            return
        st.session_state[RESULT_KEY] = result
        st.session_state[STEPS_KEY] = progress.steps
    elif RESULT_KEY in st.session_state:
        with progress_area:
            ui.show_steps(st.session_state.get(STEPS_KEY, []))

    result: RunResult | None = st.session_state.get(RESULT_KEY)
    if result is not None:
        render_results(result)
    if config.get("footer"):
        st.markdown(f'<div class="th-caption" style="margin-top:2.5rem">{ui.esc(config["footer"])}</div>',
                    unsafe_allow_html=True)


def _landing(config: dict):
    left, right = st.columns([0.42, 0.58], vertical_alignment="top")
    with left:
        run_demo = st.button("▶  Run demo with sample data", type="primary", width="stretch")
        st.caption(config.get("sample_caption", "Uses synthetic sample documents and spreadsheets. No setup needed."))
    uploads = None
    with right:
        with st.expander("…or upload your own files"):
            st.caption(config.get("upload_help", "Upload PDFs, emails (.eml) and CSV/Excel exports."))
            files = st.file_uploader("Invoices, receipts, statements and spreadsheets",
                                     type=["pdf", "eml", "txt", "csv", "xlsx", "xls", "jpg", "jpeg", "png"],
                                     accept_multiple_files=True, key="bk_uploads")
            if st.button("Process my files", disabled=not files):
                uploads = [(f.name, f.getvalue()) for f in files]
    return run_demo, uploads

# --------------------------------------------------------------------- results


def render_results(r: RunResult) -> None:
    f = r.facts
    ui.section("Summary", f"{r.inputs_label.capitalize()} · period {f['period']} · as at {f['as_of']} · "
                          f"finished in {r.seconds:.1f}s")
    by_type = f.get("documents_by_type", {})
    doc_sub = " · ".join(f"{n} {t}{'s' if n != 1 else ''}" for t, n in sorted(by_type.items(), key=lambda x: -x[1])[:3])
    metrics = [ui.Metric("Documents read", str(f["documents"]), doc_sub)]
    if f.get("entries"):
        metrics.append(ui.Metric(f"Ready to import into {r.system_label}", f"£{f['value_ready']:,.0f}",
                                 f"{f['entries_ready']} lines · {f['entries_held']} held for a check", tone="good"))
    if f.get("card_txns"):
        missing = len(f.get("missing_receipts", []))
        metrics.append(ui.Metric("Card spend matched", f"{f['card_matched']} of {f['card_txns']}",
                                 f"{missing} receipt{'s' if missing != 1 else ''} missing", tone="alert" if missing else ""))
    elif f.get("debtor_items"):
        metrics.append(ui.Metric("Overdue", f"£{f['debtors_overdue']:,.0f}", f"of £{f['debtors_outstanding']:,.0f} outstanding",
                                 tone="alert"))
    elif f.get("timesheet_rows"):
        metrics.append(ui.Metric("Timesheet lines", str(f["timesheet_rows"]), f"{f['timesheet_employees']} employees"))
    n_high = int(f["by_severity"].get("High", 0))
    metrics += [
        ui.Metric("Exceptions", str(f["exceptions"]), f"{n_high} high severity", tone="alert" if n_high else ""),
        ui.Metric("Need a human check", str(f["needs_human_check"]), f"{f['emails']} emails drafted",
                  tone="alert" if f["needs_human_check"] else "good"),
        ui.Metric("Time saved (est.)", r.time_estimate.saved_label,
                  f"{format_minutes(r.time_estimate.manual_minutes)} by hand vs {format_minutes(r.time_estimate.with_tool_minutes)}",
                  tone="good"),
    ]
    ui.summary_panel(metrics, r.summary, r.summary_source)
    extras = []
    if f.get("payroll_employees"):
        extras.append(f"Payroll: {f['payroll_employees']} employees, gross £{f['payroll_gross']:,.2f}")
    if f.get("sales_invoices"):
        extras.append(f"Sales invoices: {f['sales_ready']} of {f['sales_invoices']} ready (£{f['sales_value']:,.2f})")
    if f.get("debtor_items") and f.get("card_txns"):
        extras.append(f"Debtors: £{f['debtors_overdue']:,.2f} overdue")
    if extras:
        st.caption(" · ".join(extras))
    for w in r.warnings:
        st.warning(w, icon="⚠️")

    ui.section(f"Needs human check ({len([c for c in r.human_checks if c.id != 'AI'])})",
               "Items the agent will not guess about. Tick each one once a person has reviewed it.")
    reviewed = ui.human_check_list(r.human_checks, key_prefix="bk")
    if r.human_checks:
        st.caption(f"{reviewed} of {len(r.human_checks)} reviewed")

    ui.section("Detailed results")
    tabs = _tabs(r)
    for tab, (_, render) in zip(st.tabs([t[0] for t in tabs]), tabs):
        with tab:
            render(r)

    ui.section("Downloads", f"Every output from this run. Import files are for {r.system_label}; held entries are left out.")
    ui.download_buttons(r.downloads)
    with st.expander("How the time-saved estimate is worked out"):
        for line in r.time_estimate.assumptions:
            st.markdown(f"- {line}")
        st.caption("Assumptions are set in the client's config.yaml and can be changed to match real timings.")


def _tabs(r: RunResult) -> list[tuple[str, callable]]:
    available = {
        "entries": (f"Coded entries ({len(r.entries)})", _entries_tab, not r.entries.empty),
        "card": ("Card matching", _card_tab, not r.card.empty),
        "payroll": ("Payroll journal", _payroll_tab, not r.journal.empty),
        "sales": ("Sales invoices", _sales_tab, not r.sales.empty),
        "debtors": ("Aged debtors", _debtors_tab, not r.debtors.empty),
        "hours": ("Hours for payroll", _hours_tab, not r.hours.empty),
        "po": ("PO matching", lambda x: _table(x.po_table), not r.po_table.empty),
        "statements": ("Supplier statements", lambda x: _table(x.statements), not r.statements.empty),
        "filing": ("Filing", lambda x: _table(x.filing, wide=["Summary", "Folder"]), not r.filing.empty),
        "vat": ("VAT return", _vat_tab, not r.vat_return.empty),
        "emails": (f"Emails ({len(r.letters)})", _emails_tab, bool(r.letters)),
        "checklist": ("Month-end checklist", _checklist_tab, not r.checklist.empty),
        "exceptions": (f"Exceptions ({len(r.exceptions)})", _exceptions_tab, True),
        "documents": (f"Documents read ({len(r.documents)})", _documents_tab, bool(r.documents)),
    }
    order = (r.config.get("views") or {}).get("tabs") or list(available)
    return [(available[k][0], available[k][1]) for k in order if k in available and available[k][2]]


def _style_status(df: pd.DataFrame, column: str = "Status"):
    if column not in df:
        return df
    return df.style.map(lambda v: STATUS_COLOURS.get(v, ""), subset=[column])


def _money_cols(df: pd.DataFrame) -> dict:
    cfg = {}
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]) and c not in ("Qty", "Days overdue", "Overtime multiplier") and "hours" not in c.lower():
            cfg[c] = st.column_config.NumberColumn(c, format="£%.2f" if c not in ("Box",) else "%d")
        elif pd.api.types.is_datetime64_any_dtype(df[c]):
            cfg[c] = st.column_config.DateColumn(c, format="DD MMM YYYY")
    return cfg


def _height(rows: int, cap: int = 16) -> int:
    return 38 + 35 * min(max(rows, 1), cap)


def _table(df: pd.DataFrame, *, wide: list[str] | None = None, status: str | None = "Status", cap: int = 16) -> None:
    if df is None or df.empty:
        st.info("Nothing to show.")
        return
    shown = reports.public(df)
    cfg = _money_cols(shown)
    for c in wide or []:
        if c in shown:
            cfg[c] = st.column_config.TextColumn(c, width="large")
    data = _style_status(shown, status) if status else shown
    st.dataframe(data, hide_index=True, width="stretch", height=_height(len(shown), cap), column_config=cfg)


def _entries_tab(r: RunResult) -> None:
    e = reports.entries_frame(r)
    only_held = st.toggle("Show held entries only", value=False, key="bk_held_only")
    if only_held:
        e = e[e["Status"] == "Held"]
    cols = ["Entry", "Type", "Date", "Supplier / payee", "Reference", "Account", "Net", "VAT", "VAT code", "Gross",
            "Status", "Held by", "Coded by"]
    _table(e[cols], status="Status")
    st.caption("One line per VAT rate. “Coded by” shows whether the account came from the supplier list, a keyword "
               "rule or a Claude suggestion. The full table, with descriptions and reasons, is in the Excel pack.")
    totals = reports.account_totals(r)
    if not totals.empty:
        st.markdown("**Totals by account**")
        _table(totals, status=None, cap=20)


def _card_tab(r: RunResult) -> None:
    _table(r.card[["Txn", "Date", "Cardholder", "Merchant", "Amount", "Status", "Receipt", "Receipt total"]])
    st.caption("Matched on amount, date (within a week) and merchant name. Card fees need no receipt. "
               "A receipt in another currency is matched on merchant and date.")


def _payroll_tab(r: RunResult) -> None:
    j = reports.journal_frame(r)
    _table(j, status=None)
    debit, credit = j["Debit"].sum(), j["Credit"].sum()
    st.caption(f"Debits £{debit:,.2f} · credits £{credit:,.2f} · "
               + ("balanced." if abs(debit - credit) < 0.005 else "OUT OF BALANCE."))
    with st.expander("Payroll check by employee"):
        _table(reports.payroll_frame(r), status=None, cap=20)


def _sales_tab(r: RunResult) -> None:
    _table(reports.sales_frame(r), wide=["Description"])
    st.caption("Invoices are numbered in sequence and dated at the period end. Held invoices are left out of the import file.")


def _debtors_tab(r: RunResult) -> None:
    st.markdown("**By customer**")
    _table(r.debtors_summary, status=None)
    st.markdown("**Open invoices**")
    _table(reports.debtors_frame(r), status=None)


def _hours_tab(r: RunResult) -> None:
    _table(r.hours, status=None)


def _vat_tab(r: RunResult) -> None:
    _table(r.vat_return, status=None, wide=["How it is worked out"])
    st.caption("Draft workings from the entries ready to post. A person must review them before the return is filed.")


def _emails_tab(r: RunResult) -> None:
    st.caption("Drafts only: nothing is sent. Amounts and references come from the checked data.")
    for l in r.letters:
        to = l["to"] + (f" · {l['contact']}" if l.get("contact") else "")
        with st.expander(f"{l['subject']}  —  to {to}"):
            st.caption(f"To: {l.get('email') or 'no email on file'} · about {', '.join(l.get('exceptions', [])) or 'overdue invoices'}"
                       f" · drafted by {reports._source_label(l.get('source'))}")
            st.text(l["body"])


def _checklist_tab(r: RunResult) -> None:
    c = r.checklist
    st.dataframe(_style_status(c), hide_index=True, width="stretch", height=_height(len(c), 20),
                 column_config={"Item": st.column_config.TextColumn(width=280), "Status": st.column_config.TextColumn(width=120),
                                "Detail": st.column_config.TextColumn(width="large"),
                                "Exceptions": st.column_config.TextColumn(width=150)})
    st.caption("Automatic items are set from this run. Manual items stay “To do” for the team.")


def _exceptions_tab(r: RunResult) -> None:
    exc = r.exceptions
    if exc.empty:
        st.success("No exceptions found.")
        return
    cols = ["ID", "Severity", "Area", "Check", "Who", "Reference", "Amount", "Needs human check", "Held from import"]
    st.dataframe(exc[cols], hide_index=True, width="stretch", height=_height(len(exc), 20),
                 column_config={"ID": st.column_config.TextColumn(width=60), "Severity": st.column_config.TextColumn(width=70),
                                "Area": st.column_config.TextColumn(width=85),
                                "Amount": st.column_config.NumberColumn(format="£%.2f", width=90),
                                "Needs human check": st.column_config.TextColumn("Review", width=65),
                                "Held from import": st.column_config.TextColumn("Held", width=55)})
    for e in exc.to_dict("records"):
        with st.expander(f"{e['ID']} · {e['Severity']} · {e['Check']} · {e['Who']}"):
            st.markdown(f"**Finding** — {e['Finding']}")
            st.markdown(f"**Suggested action** — {e['Suggested action']}")
            st.caption(f"Source: {e['Source'] or '—'}" + (f" · email drafted to {e['Email drafted to']}" if e["Email drafted to"] else ""))


def _documents_tab(r: RunResult) -> None:
    d = r.documents_table
    _table(d[["Doc", "File", "Type", "From / to", "Number", "Date", "Total", "Currency", "Confidence", "Read by"]], status=None)
    st.caption("Fields read from each document. The Excel pack has every field, including VAT numbers and summaries.")
