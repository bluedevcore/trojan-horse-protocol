"""Streamlit screens for the bookkeeping tool (generic, no client names).

A client's ``app.py`` only needs:

    from tools.bookkeeping.views import run_app
    run_app(Path(__file__).parent)
"""

from __future__ import annotations

import re
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
        metrics.append(ui.Metric(f"Purchases ready for {r.system_label.split()[0]}", f"£{f['value_ready']:,.0f}",
                                 f"{f['entries_ready']} lines · {f['entries_held']} held for a check", tone="good"))
    if f.get("card_txns"):
        missing = len(f.get("missing_receipts", []))
        metrics.append(ui.Metric("Card spend matched", f"{f['card_matched']} of {f['card_txns']}",
                                 f"{missing} receipt{'s' if missing != 1 else ''} missing", tone="alert" if missing else ""))
    elif f.get("debtor_items"):
        metrics.append(ui.Metric("Overdue", f"£{f['debtors_overdue']:,.0f}", f"of £{f['debtors_outstanding']:,.0f} outstanding",
                                 tone="alert"))
    elif f.get("timesheet_rows") and "hours_total" in f:
        held = len(f.get("hours_held", []))
        metrics.append(ui.Metric("Hours ready for payroll", f"{f['hours_ready']:,.1f}",
                                 f"of {f['hours_total']:,.1f} h · {held} employee{'s' if held != 1 else ''} held",
                                 tone="alert" if held else "good"))
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
        "po": ("PO matching", _po_tab, not r.po_table.empty),
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


def _money(v, currency: str = "GBP") -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return ""
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency or "GBP", f"{currency} ")
    return f"{'−' if v < 0 else ''}{symbol}{abs(float(v)):,.2f}"


def _date(v) -> str:
    return "" if v is None or pd.isna(v) else pd.Timestamp(v).strftime("%d %b %Y")


def _text(v) -> str:
    return "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v)


def _qty(v) -> str:
    return "" if v is None or pd.isna(v) else f"{float(v):g}"


FORMATTERS = {"money": _money, "date": _date, "text": _text, "qty": _qty}
STATUS_STYLE = [("Held", "background-color:#FFF4E0;color:#7A4A00"), ("Ready", "background-color:#E8F6EE;color:#0F5A34"),
                ("Over PO", "background-color:#FDE8E7;color:#8A1C12"), ("PO not found", "background-color:#FFF4E0;color:#7A4A00"),
                ("No PO", "background-color:#FFF4E0;color:#7A4A00"), ("Supplier differs", "background-color:#FFF4E0;color:#7A4A00"),
                ("Matched", "background-color:#E8F6EE;color:#0F5A34"), ("Done", "background-color:#E8F6EE;color:#0F5A34"),
                ("Receipt missing", "background-color:#FDE8E7;color:#8A1C12"),
                ("Amount differs", "background-color:#FFF4E0;color:#7A4A00"),
                ("Action needed", "background-color:#FFF4E0;color:#7A4A00")]


def _status_css(value: str) -> str:
    return next((css for prefix, css in STATUS_STYLE if str(value).startswith(prefix)), "")


def _height(rows: int, cap: int = 16) -> int:
    return 38 + 35 * min(max(rows, 1), cap)


def _grid(df: pd.DataFrame, spec: list[tuple], *, status: str | None = None, cap: int = 16) -> None:
    """Show selected columns as formatted text with fixed widths (fits 1280px).

    ``spec`` items: (column, kind, width) or (column, kind, width, label); kind is
    money | date | text | qty. Money and qty columns are right-aligned.
    """
    if df is None or df.empty:
        st.info("Nothing to show.")
        return
    out, cfg = pd.DataFrame(index=df.index), {}
    for item in spec:
        col, kind, width = item[:3]
        label = item[3] if len(item) > 3 else col
        if col not in df:
            continue
        out[label] = [FORMATTERS[kind](v) for v in df[col]]
        cfg[label] = st.column_config.TextColumn(label, width=width,
                                                 alignment="right" if kind in ("money", "qty") else "left")
    data = out.style.map(_status_css, subset=[status]) if status and status in out else out
    st.dataframe(data, hide_index=True, width="stretch", height=_height(len(out), cap), column_config=cfg)


def _table(df: pd.DataFrame, *, wide: list[str] | None = None, status: str | None = "Status", cap: int = 16) -> None:
    """Generic table for the less common tabs: money-like floats formatted, blanks shown blank."""
    if df is None or df.empty:
        st.info("Nothing to show.")
        return
    shown = reports.public(df).copy()
    spec = []
    for c in shown.columns:
        if pd.api.types.is_datetime64_any_dtype(shown[c]):
            spec.append((c, "date", 95))
        elif pd.api.types.is_float_dtype(shown[c]):
            spec.append((c, "qty" if any(w in c.lower() for w in ("hours", "qty", "days", "multiplier", "box")) else "money", 95))
        else:
            spec.append((c, "text", "large" if c in (wide or []) else "medium"))
    _grid(shown, spec, status=status, cap=cap)


def _entries_tab(r: RunResult) -> None:
    e = r.entries.copy()
    if st.toggle("Show held entries only", value=False, key="bk_held_only"):
        e = e[e["status"] == "Held"]
    e["Type"] = e["kind"].map(reports.KIND_LABELS).fillna(e["kind"])
    e["Status"] = [f"Held · {h}" if s == "Held" and h else s for s, h in zip(e["status"], e["hold_reason"])]
    _grid(e, [("Type", "text", 100), ("date", "date", 90, "Date"), ("counterparty", "text", 190, "Supplier / payee"),
              ("account", "text", 175, "Account"), ("net", "money", 80, "Net"), ("vat", "money", 70, "VAT"),
              ("vat_code", "text", 45, "Code"), ("gross", "money", 82, "Gross"), ("Status", "text", 100),
              ("coded_by", "text", 95, "Coded by")], status="Status")
    st.caption("One line per VAT rate. Code: S standard 20%, R reduced 5%, Z zero rated, E exempt, O no VAT, RC reverse "
               "charge. “Coded by” shows whether the account came from the supplier list, a keyword rule or a Claude "
               "suggestion. References, descriptions and reasons are in the Excel pack.")
    totals = reports.account_totals(r)
    if not totals.empty:
        with st.expander("Totals by account"):
            _grid(totals, [("Account", "text", 280), ("Lines", "qty", 70), ("Net", "money", 120), ("VAT", "money", 110),
                           ("Gross", "money", 120), ("Held (gross)", "money", 120)], cap=25)
    tracking = reports.tracking_totals(r)
    label = (r.config.get("analysis") or {}).get("tracking_label", "Tracking")
    if not tracking.empty:
        with st.expander(f"Totals by {label.lower()}"):
            _grid(tracking, [(label, "text", 200), ("Account", "text", 260), ("Lines", "qty", 70), ("Net", "money", 120),
                             ("VAT", "money", 110), ("Gross", "money", 120)], cap=25)


def _card_tab(r: RunResult) -> None:
    c = r.card.copy()
    c["Receipt total"] = [_money(v, cur) for v, cur in zip(c["Receipt total"], c["Receipt currency"])]
    _grid(c, [("Txn", "text", 55), ("Date", "date", 88), ("Cardholder", "text", 105), ("Merchant", "text", 255),
              ("Amount", "money", 80), ("Status", "text", 140), ("Receipt from", "text", 210), ("Receipt total", "text", 90)],
          status="Status", cap=20)
    st.caption("Matched on amount, date (within a week) and merchant name. Card fees and parking need no receipt. "
               "A receipt in another currency is matched on merchant, date and the original amount.")


def _payroll_tab(r: RunResult) -> None:
    j = r.journal
    _grid(reports.journal_frame(r), [("Account", "text", 230), ("Debit", "money", 110), ("Credit", "money", 110),
                                     ("Description", "text", 400), ("Department", "text", 120)], cap=20)
    debit, credit = j["debit"].sum(), j["credit"].sum()
    st.caption(f"Journal {j['reference'].iloc[0]} dated {j['date'].iloc[0]:%d %b %Y}. Debits £{debit:,.2f}, credits "
               f"£{credit:,.2f}: " + ("balanced." if abs(debit - credit) < 0.005 else "OUT OF BALANCE."))
    with st.expander("Payroll check by employee"):
        _grid(r.payroll, [("employee_id", "text", 75, "ID"), ("employee", "text", 140, "Employee"), ("gross", "money", 90, "Gross"),
                          ("paye", "money", 85, "PAYE"), ("employee_ni", "money", 85, "Employee NI"),
                          ("employee_pension", "money", 85, "Pension"), ("student_loan", "money", 85, "Student loan"),
                          ("net_pay", "money", 110, "Net (report)"), ("calculated_net", "money", 110, "Net (checked)"),
                          ("net_difference", "money", 90, "Difference")], cap=20)


def _sales_tab(r: RunResult) -> None:
    s = r.sales.copy()
    s["Status"] = [f"Held · {', '.join(re.findall(r'EX-[0-9]+', h)) or h}" if st_ == "Held" else st_
                   for st_, h in zip(s["status"], s["hold_reason"])]
    _grid(s, [("invoice_number", "text", 80, "Invoice"), ("customer", "text", 185, "Customer"), ("po_number", "text", 105, "Customer PO"),
              ("description", "text", 255, "Description"), ("quantity", "qty", 45, "Qty"), ("unit_price", "money", 80, "Price"),
              ("net", "money", 80, "Net"), ("gross", "money", 85, "Gross"), ("Status", "text", 110)], status="Status")
    st.caption("Invoices are numbered in sequence and dated at the period end, with each customer's payment terms. "
               "Held invoices are left out of the import file.")


def _debtors_tab(r: RunResult) -> None:
    st.markdown("**By customer**")
    _table(r.debtors_summary, status=None)
    st.markdown("**Open invoices**")
    _table(reports.debtors_frame(r), status=None)


def _hours_tab(r: RunResult) -> None:
    h = r.hours.copy()
    if "Status" not in h:
        _table(h, status=None)
        return
    h["Status"] = [f"Held · {b}" if s == "Held" and b else s for s, b in zip(h["Status"], h["Held because"])]
    _grid(h, [("Employee", "text", 160), ("Employee ID", "text", 70, "ID"), ("Week commencing", "date", 95, "Week of"),
              ("Days worked", "qty", 50, "Days"), ("Basic hours", "qty", 65, "Basic"), ("Overtime hours", "qty", 75, "Overtime"),
              ("Weekend hours", "qty", 75, "Weekend"), ("Total hours", "qty", 60, "Total"), ("Hourly rate", "money", 70, "Rate"),
              ("Gross pay (est.)", "money", 95, "Gross (est.)"), ("Status", "text", 150)], status="Status", cap=25)
    st.caption("Hours worked out from start and finish times less breaks; duplicate lines are counted once. Overtime is "
               "weekday hours over each person's contracted hours; weekend hours are shown separately. Held weeks are "
               "left out of the payroll hours file until the exception is cleared. Gross pay is an estimate for checking only.")
    jobs = reports.hours_job_frame(r)
    if not jobs.empty:
        with st.expander("Hours by job"):
            spec = [("Job", "text", 120)] + ([("Job status", "text", 140)] if "Job status" in jobs else []) + [
                ("Lines", "qty", 70), ("Employees", "qty", 90), ("Hours", "qty", 90)]
            _grid(jobs, spec, cap=20)
    lines = reports.timesheet_lines_frame(r)
    if not lines.empty:
        with st.expander(f"Timesheet lines checked ({len(lines)})"):
            _grid(lines, [("Employee", "text", 150), ("Date", "date", 90), ("Job", "text", 75), ("Job status", "text", 110),
                          ("Start", "text", 55), ("Finish", "text", 55), ("Break (mins)", "qty", 55, "Break"),
                          ("Hours entered", "qty", 70, "Entered"), ("Hours counted", "qty", 70, "Counted"),
                          ("Signed off by", "text", 110), ("Duplicate (not counted)", "text", 80, "Duplicate")], cap=20)


def _po_tab(r: RunResult) -> None:
    po = r.po_table.copy()
    # one PO column: the PO matched, or else the number the invoice quoted (e.g. one that isn't on the list)
    po["PO"] = [m if _text(m) else _text(q) for m, q in zip(po["Matched PO"], po["PO on invoice"])]
    po["Matched by"] = po["Matched by"].replace({"supplier and amount": "supplier + amount"})
    _grid(po, [("Supplier", "text", 195), ("Invoice", "text", 90), ("Invoice date", "date", 85, "Date"),
               ("PO", "text", 75), ("Matched by", "text", 120), ("Invoice net", "money", 85, "Invoice net"),
               ("PO net", "money", 85), ("Invoiced to date", "money", 85, "Invoiced"),
               ("Difference", "money", 85, "Difference"), ("Status", "text", 120)], status="Status", cap=25)
    st.caption("Matched on the PO number quoted, or on supplier and amount when no PO is quoted. “Invoiced” is the "
               "running total against the PO and “Difference” is that total less the PO value (negative: not fully "
               "invoiced yet). An invoice that takes a PO over its value, beyond the tolerance, is held. POs with no "
               "invoice yet are listed as awaiting invoice; the Excel pack also shows the PO number each invoice quoted.")


def _vat_tab(r: RunResult) -> None:
    _grid(r.vat_return, [("Box", "qty", 50), ("Description", "text", 330), ("Amount (£)", "money", 110, "Amount"),
                         ("How it is worked out", "text", 520)], cap=10)
    st.caption("Draft workings from the entries ready to post. A person must review them before the return is filed.")


def _emails_tab(r: RunResult) -> None:
    st.caption("Drafts only: nothing is sent. Amounts and references come from the checked data.")
    for l in r.letters:
        to = l["to"] + (f" · {l['contact']}" if l.get("contact") and l["contact"] != l["to"] else "")
        with st.expander(f"{l['subject']}  —  to {to}"):
            st.caption(f"To: {l.get('email') or 'no email on file'} · about {', '.join(l.get('exceptions', [])) or 'overdue invoices'}"
                       f" · drafted by {reports._source_label(l.get('source'))}")
            st.text(l["body"])


def _checklist_tab(r: RunResult) -> None:
    pills = {"Done": ("#E8F6EE", "#0F5A34"), "Action needed": ("#FFF4E0", "#7A4A00"), "To do": ("#EEF1F5", "#344054")}
    rows = []
    for item in r.checklist.to_dict("records"):
        bg, fg = pills.get(item["Status"], ("#EEF1F5", "#344054"))
        rows.append(
            f'<tr><td style="padding:.45rem .6rem;width:30%;font-weight:600">{ui.esc(item["Item"])}</td>'
            f'<td style="padding:.45rem .6rem;width:13%"><span style="background:{bg};color:{fg};padding:.1rem .5rem;'
            f'border-radius:4px;font-size:.82rem;white-space:nowrap">{ui.esc(item["Status"])}</span></td>'
            f'<td style="padding:.45rem .6rem">{ui.esc(item["Detail"])}</td>'
            f'<td style="padding:.45rem .6rem;width:15%;color:#5B6775;font-size:.85rem">{ui.esc(item["Exceptions"])}</td></tr>')
    st.markdown('<table style="width:100%;border-collapse:collapse;font-size:.92rem" class="th-checklist">'
                '<thead><tr style="text-align:left;color:#5B6775;font-size:.8rem;border-bottom:1px solid #D9DEE5">'
                '<th style="padding:.35rem .6rem">Item</th><th style="padding:.35rem .6rem">Status</th>'
                '<th style="padding:.35rem .6rem">Detail</th><th style="padding:.35rem .6rem">Exceptions</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>', unsafe_allow_html=True)
    st.caption("Automatic items are set from this run. Manual items stay “To do” for the team.")


def _exceptions_tab(r: RunResult) -> None:
    exc = r.exceptions
    if exc.empty:
        st.success("No exceptions found.")
        return
    _grid(exc, [("ID", "text", 60), ("Severity", "text", 70), ("Area", "text", 85), ("Check", "text", 215),
                ("Who", "text", 210), ("Reference", "text", 120), ("Amount", "money", 90),
                ("Needs human check", "text", 65, "Review"), ("Held from import", "text", 55, "Held")], cap=20)
    for e in exc.to_dict("records"):
        with st.expander(f"{e['ID']} · {e['Severity']} · {e['Check']} · {e['Who']}"):
            st.markdown(f"**Finding** — {e['Finding']}")
            st.markdown(f"**Suggested action** — {e['Suggested action']}")
            st.caption(f"Source: {e['Source'] or '—'}" + (f" · email drafted to {e['Email drafted to']}" if e["Email drafted to"] else ""))


def _documents_tab(r: RunResult) -> None:
    d = r.documents_table.copy()
    d["Total"] = [_money(v, c) for v, c in zip(d["Total"], d["Currency"])]
    _grid(d, [("Doc", "text", 50), ("File", "text", 255), ("Type", "text", 75), ("From / to", "text", 185),
              ("Number", "text", 105), ("Date", "date", 88), ("Total", "text", 85), ("Confidence", "text", 75),
              ("Read by", "text", 105)], cap=30)
    st.caption("Fields read from each document. The Excel pack has every field, including VAT numbers and summaries.")
