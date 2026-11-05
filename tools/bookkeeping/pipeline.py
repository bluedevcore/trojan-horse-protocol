"""End-to-end bookkeeping run: files in, coded entries, checks, import files
and a month-end pack out.

    result = run(inputs, config, client, progress)

Every module is switched on by ``modules.<name>`` in the client config (and
only runs when its inputs are present). Deterministic code does all maths,
matching and validation; Claude reads documents, suggests account codes for
items no rule covers, and writes the emails and the summary.
"""

from __future__ import annotations

import glob
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from core.claude import ClaudeClient, ClaudeResult
from core.estimates import TimeEstimate, estimate
from core.ui import CheckItem, DownloadFile, StepProgress
from tools.bookkeeping import ai, month_end
from tools.bookkeeping.checks import Finding, finalise, findings_frame
from tools.bookkeeping.coding import (Chart, Rules, SupplierBook, chart_from_frame, code_from_rules, code_from_supplier,
                                      supplier_vat_checks)
from tools.bookkeeping.documents import (DOC_SUFFIXES, IMAGE_SUFFIXES, DocText, DocumentError, arithmetic_problems,
                                         documents_frame, normalise, read_document, type_count)
from tools.bookkeeping.exports import SYSTEM_LABELS, build_exports
from tools.bookkeeping.filing import file_documents
from tools.bookkeeping.matching import MatchSettings, match_card_to_documents, name_similarity, reconcile_statement
from tools.bookkeeping.orders import match_invoices_to_pos
from tools.bookkeeping.payroll import check_payroll, payroll_journal, timesheet_hours
from tools.bookkeeping.sales import aged_debtors, chase_groups, raise_invoices
from tools.bookkeeping.tables import DataFileError, TABLE_SPECS, detect_role, load_table, norm_name, table_spec
from tools.bookkeeping.vat import code_for_rate, format_vat_number, normalise_code, vat_return

FileInput = tuple[str, bytes]
PURCHASE_TYPES = ("invoice", "credit_note", "receipt")
MASTER_ROLES = ("suppliers", "customers", "chart_of_accounts", "employees", "projects")
DEFAULT_MODULES = {"documents": True, "purchases": True, "card_matching": True, "coding": True, "payroll_journal": True,
                   "sales_invoices": True, "debtors": True, "timesheets": True, "purchase_orders": True,
                   "statements": True, "filing": False, "vat_return": False, "letters": True, "month_end": True}

ASKS = {
    "arithmetic": "Could you send a corrected invoice?",
    "vat_rate": "Could you confirm the VAT rate that applies?",
    "vat_without_number": "Could you send a VAT invoice showing your VAT registration number, or, if you are not "
                          "VAT registered, a corrected invoice without VAT?",
    "vat_number_invalid": "Could you confirm your VAT registration number? The one on the invoice does not pass "
                          "HMRC's check.",
    "bank_details_changed": "We will phone you on the number we already hold to confirm the change before any "
                            "payment is made. We never change bank details from an email.",
    "missing_receipt": "Could you send the receipt (a photo or PDF is fine)?",
    "statement_missing_invoice": "Could you send a copy of this invoice?",
    "statement_amount_mismatch": "Could you confirm the correct amount?",
}


class PipelineError(Exception):
    """Stops the run; the message is shown to the user as-is."""


@dataclass
class RunInputs:
    documents: list[FileInput] = field(default_factory=list)
    tables: dict[str, list[FileInput]] = field(default_factory=dict)
    as_of: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.today().normalize())
    label: str = "uploaded files"
    period: tuple[pd.Timestamp, pd.Timestamp] | None = None
    notes: list[str] = field(default_factory=list)  # routing messages for uploads
    fallback_roles: list[str] = field(default_factory=list)  # reference lists taken from the demo, not uploaded


@dataclass
class RunResult:
    config: dict
    inputs_label: str
    as_of: pd.Timestamp
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    documents: list[dict]
    documents_table: pd.DataFrame
    entries: pd.DataFrame
    card: pd.DataFrame
    journal: pd.DataFrame
    payroll: pd.DataFrame
    sales: pd.DataFrame
    debtors: pd.DataFrame
    debtors_summary: pd.DataFrame
    hours: pd.DataFrame
    po_table: pd.DataFrame
    statements: pd.DataFrame
    filing: pd.DataFrame
    vat_return: pd.DataFrame
    findings: list[Finding]
    exceptions: pd.DataFrame
    letters: list[dict]
    checklist: pd.DataFrame
    exports: list
    summary: str
    summary_source: str
    facts: dict
    human_checks: list[CheckItem]
    time_estimate: TimeEstimate
    files_read: dict
    originals: dict = field(default_factory=dict)
    downloads: list[DownloadFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ai_sources: dict = field(default_factory=dict)
    seconds: float = 0.0

    @property
    def period_label(self) -> str:
        return period_label(self.period_start, self.period_end)

    @property
    def system_label(self) -> str:
        return SYSTEM_LABELS.get(self.config.get("accounting_system", "quickbooks"), "accounting system")


def period_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
    if start.year == end.year and start.month == end.month:
        return start.strftime("%B %Y")
    return f"{start:%d %b %Y} to {end:%d %b %Y}"

# ------------------------------------------------------------------ inputs


def _module_on(config: dict, name: str) -> bool:
    return bool({**DEFAULT_MODULES, **(config.get("modules") or {})}.get(name, False))


def sample_inputs(client_dir: Path, config: dict) -> RunInputs:
    sample = config.get("sample_data") or {}
    client_dir = Path(client_dir)
    docs: list[FileInput] = []
    try:
        for pattern in sample.get("documents", []):
            paths = sorted(glob.glob(str(client_dir / pattern))) if any(c in pattern for c in "*?[") else [str(client_dir / pattern)]
            if not paths:
                raise FileNotFoundError(2, "No files match", pattern)
            docs += [(Path(p).name, Path(p).read_bytes()) for p in paths]
        tables = {role: [(Path(p).name, (client_dir / p).read_bytes()) for p in ([paths] if isinstance(paths, str) else paths)]
                  for role, paths in (sample.get("tables") or {}).items()}
    except OSError as exc:
        raise PipelineError(f"The sample data files could not be found ({exc.filename}). "
                            "Check that the sample_data folder was deployed with the app.") from exc
    as_of = pd.Timestamp(config.get("sample_as_of") or pd.Timestamp.today()).normalize()
    period = None
    if config.get("period"):
        period = (pd.Timestamp(config["period"]["start"]), pd.Timestamp(config["period"]["end"]))
    return RunInputs(documents=docs, tables=tables, as_of=as_of, label="sample data", period=period)


def upload_inputs(files: list[FileInput], config: dict, client_dir: Path | None = None) -> RunInputs:
    """Route uploaded files: PDFs/emails are documents; spreadsheets are
    recognised from their column headings. Missing reference lists (chart of
    accounts, supplier list...) fall back to the demo's sample ones."""
    inputs = RunInputs(label="uploaded files")
    allowed = [r for r in TABLE_SPECS]
    for name, data in files:
        suffix = Path(name).suffix.lower()
        if suffix in DOC_SUFFIXES or suffix in IMAGE_SUFFIXES:
            inputs.documents.append((name, data))
            continue
        role = detect_role(name, data, config, allowed)
        if role is None:
            inputs.notes.append(f"“{name}”: could not tell what this spreadsheet is from its column headings, so it was "
                                f"skipped. Expected e.g. a card statement (Date, Description, Amount, Card) or a supplier list.")
            continue
        inputs.tables.setdefault(role, []).append((name, data))
    if client_dir is not None:
        sample_tables = (config.get("sample_data") or {}).get("tables") or {}
        for role in MASTER_ROLES:
            if role not in inputs.tables and role in sample_tables:
                paths = sample_tables[role] if isinstance(sample_tables[role], list) else [sample_tables[role]]
                try:
                    inputs.tables[role] = [(Path(p).name, (Path(client_dir) / p).read_bytes()) for p in paths]
                    inputs.fallback_roles.append(role)
                except OSError:
                    pass
    return inputs


def infer_period(dates: list, as_of: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    months = Counter(pd.Timestamp(d).to_period("M") for d in dates if d is not None and not pd.isna(d))
    month = months.most_common(1)[0][0] if months else (as_of - pd.offsets.MonthBegin(1)).to_period("M")
    return month.start_time.normalize(), month.end_time.normalize()

# ------------------------------------------------------------------- run


def run(inputs: RunInputs, config: dict, client: ClaudeClient, progress: StepProgress | None = None) -> RunResult:
    started = time.perf_counter()
    progress = progress or StepProgress()
    warnings: list[str] = list(inputs.notes)
    findings: list[Finding] = []
    calls: list[ClaudeResult] = []
    source_word = "pre-recorded AI text (mock mode)" if client.mock else f"Claude ({client.model})"
    n_docs = len(inputs.documents)
    n_tables = sum(len(v) for v in inputs.tables.values())
    if not n_docs and not n_tables:
        raise PipelineError("No files to process. Upload invoices, receipts or statements, or run the demo with sample data.")

    # 1. Read files ------------------------------------------------------------------
    progress.start(f"Reading {_plural(n_docs, 'document')} and {_plural(n_tables, 'spreadsheet')}…")
    texts: list[DocText] = []
    originals: dict[str, bytes] = {}
    for name, data in sorted(inputs.documents, key=lambda f: f[0].lower()):
        originals[name] = data
        try:
            texts.append(read_document(name, data))
        except DocumentError as exc:
            findings.append(Finding("unreadable_document", subject=name, reference=name, source=name, finding=str(exc)))
    tables: dict[str, pd.DataFrame] = {}
    files_read: dict[str, list[str]] = {}
    for role, files in inputs.tables.items():
        if role not in TABLE_SPECS:
            continue
        spec = table_spec(role, config)
        frames = []
        for name, data in files:
            try:
                df = load_table(name, data, spec)
                frames.append(df)
                files_read.setdefault(role, []).append(name)
                if df.attrs.get("bad_cells"):
                    warnings.append(f"“{name}”: some values could not be read and were left blank: "
                                    + "; ".join(df.attrs["bad_cells"][:4]) + ("…" if len(df.attrs["bad_cells"]) > 4 else ""))
            except DataFileError as exc:
                warnings.append(str(exc))
        if frames:
            tables[role] = pd.concat(frames, ignore_index=True)
    if not texts and not (set(tables) - set(inputs.fallback_roles)):
        progress.fail("Could not read any of the files")
        problems = [f.finding for f in findings] + warnings
        raise PipelineError("None of the files could be read:\n\n" + "\n".join(f"- {p}" for p in problems))
    if inputs.fallback_roles:
        labels = [table_spec(r, config).label for r in inputs.fallback_roles]
        listed = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " or " + labels[-1]
        warnings.append(f"No {listed} uploaded: using the demo's sample {'one' if len(labels) == 1 else 'ones'}.")
    table_bits = ", ".join(f"{table_spec(r, config).label} ({len(df)} rows)" for r, df in tables.items())
    unread = len([f for f in findings if f.check_id == "unreadable_document"])
    (progress.warn if unread or warnings else progress.done)(
        f"Read {_plural(len(texts), 'document')} and {_plural(len(tables), 'spreadsheet')}",
        "; ".join(x for x in [table_bits, f"{unread} document(s) could not be read" if unread else ""] if x))

    chart = chart_from_frame(tables["chart_of_accounts"]) if "chart_of_accounts" in tables else _default_chart(config)
    book = SupplierBook(tables.get("suppliers"), float((config.get("matching") or {}).get("supplier_name_threshold", 0.85)))
    rules = Rules((config.get("coding") or {}).get("rules") or [])
    fallback_account = chart.resolve((config.get("coding") or {}).get("fallback_account", "Suspense")) or chart.names[-1]

    # 2. Extract documents -------------------------------------------------------------
    docs: list[dict] = []
    if texts and _module_on(config, "documents"):
        progress.start(f"Reading {_plural(len(texts), 'document')} with {source_word}…")
        projects = tables["projects"].to_dict("records") if "projects" in tables else None
        extracted = ai.extract_documents(client, texts, config, projects=projects,
                                         on_done=lambda d, t: progress.update(f"Reading documents with {source_word}… ({d}/{t})"))
        for i, (doc, (data, result)) in enumerate(zip(texts, extracted), 1):
            calls.append(result)
            src = {"api": "Claude", "cache": "Claude (cached)", "fixture": "AI (pre-recorded)",
                   "mock": "Pattern reader", "fallback": "Pattern reader"}.get(result.source, result.source)
            docs.append(normalise(data, doc, f"D-{i:02d}", src))
        by_type = Counter(d["doc_type"] for d in docs)
        progress.done(f"Extracted the details from {_plural(len(docs), 'document')}",
                      ", ".join(type_count(t, n) for t, n in by_type.most_common())
                      + f" · {_source_phrase(Counter(c.source for c in calls))}")
        if any(c.source in ("mock", "fallback") for c in calls):
            warnings.append("Some documents were read by the pattern reader (no AI), which is less reliable: "
                            "check the extracted fields in the Documents tab.")

    # period ------------------------------------------------------------------------
    if inputs.period:
        p_start, p_end = inputs.period
    else:
        dates = [d["document_date"] for d in docs] + (list(tables["card_statement"]["date"]) if "card_statement" in tables else [])
        p_start, p_end = infer_period(dates, inputs.as_of)

    # 3. Document checks ----------------------------------------------------------------
    # modules.purchases: false -> invoices, receipts and credit notes are read (and filed) but not checked or coded
    purchase_docs = [d for d in docs if d["doc_type"] in PURCHASE_TYPES] if _module_on(config, "purchases") else []
    duplicates: set[str] = set()
    if purchase_docs:
        progress.start(f"Checking {_plural(len(purchase_docs), 'invoice and receipt', 'invoices and receipts')} "
                       f"for arithmetic, VAT, duplicates and supplier details…")
        before = len(findings)
        duplicates = _document_checks(purchase_docs, book, config, p_start, p_end, findings)
        n = len(findings) - before
        (progress.warn if n else progress.done)(
            f"Checked {_plural(len(purchase_docs), 'document')} for arithmetic, VAT, duplicates and supplier details",
            f"{_plural(n, 'issue')} found" if n else "all clear")

    # 4. Card matching ------------------------------------------------------------------
    card_view = pd.DataFrame()
    matches: dict[str, tuple[str, dict]] = {}
    txns = pd.DataFrame()
    no_receipt_needed: set[str] = set()
    if "card_statement" in tables and _module_on(config, "card_matching"):
        txns, credits = _card_transactions(tables["card_statement"])
        progress.start(f"Matching {_plural(len(txns), 'card transaction')} to receipts…")
        settings = MatchSettings.from_config(config.get("matching"))
        candidates = [d for d in purchase_docs if d["doc_id"] not in duplicates
                      and (d["doc_type"] == "receipt" or d["payment_status"] == "paid" or d["card_last4"])]
        for tid, did, info in match_card_to_documents(txns, candidates, settings):
            matches[tid] = (did, info)
        for t in txns.to_dict("records"):
            rule = rules.match(f"{t['description']}")
            if rule is not None and not rule.get("receipt_needed", True):
                no_receipt_needed.add(t["txn_id"])
        missing_before = len(findings)
        _card_findings(txns, candidates, matches, no_receipt_needed, config, findings)
        card_view = _card_view(txns, credits, docs, matches, no_receipt_needed)
        n_missing = len([f for f in findings[missing_before:] if f.check_id == "missing_receipt"])
        progress.done(f"Matched {len(matches)} of {_plural(len(txns), 'card transaction')} to receipts",
                      f"{_plural(n_missing, 'receipt')} missing" + (f", {len(no_receipt_needed)} need no receipt" if no_receipt_needed else ""))

    # 5. Entries + coding ----------------------------------------------------------------
    entries = pd.DataFrame()
    if purchase_docs or not txns.empty:
        progress.start("Coding entries to the chart of accounts…")
        entries, code_calls, coded_counts = _build_entries(
            purchase_docs, duplicates, txns, matches, no_receipt_needed, book, rules, chart, fallback_account,
            client, config, findings, p_start, p_end)
        calls += code_calls
        progress.done(f"Coded {_plural(entries['group'].nunique() if not entries.empty else 0, 'item')} into "
                      f"{_plural(len(entries), 'ledger line')}",
                      ", ".join(f"{n} by {k}" for k, n in coded_counts.items() if n))

    # 6. Payroll journal -----------------------------------------------------------------
    journal, payroll_rows, payroll_totals, payroll_diff = pd.DataFrame(), pd.DataFrame(), {}, 0.0
    if "payroll" in tables and _module_on(config, "payroll_journal"):
        progress.start("Checking the payroll report and building the payroll journal…")
        payroll_rows, pf, payroll_totals = check_payroll(tables["payroll"])
        findings += pf
        pcfg = config.get("payroll") or {}
        journal, payroll_diff = payroll_journal(payroll_rows, date=p_end, accounts=pcfg.get("accounts"),
                                                by_department=pcfg.get("by_department", True),
                                                reference=pcfg.get("journal_reference", f"PAYROLL-{p_end:%b-%Y}".upper()))
        (progress.warn if abs(payroll_diff) > 0.005 else progress.done)(
            f"Payroll journal for {payroll_totals['employees']} employees: gross £{payroll_totals['gross']:,.2f}",
            f"£{abs(payroll_diff):,.2f} held in Suspense: net pay doesn't reconcile" if abs(payroll_diff) > 0.005 else "balanced")

    # 7. Sales invoices ------------------------------------------------------------------
    sales = pd.DataFrame()
    if "sales_to_invoice" in tables and _module_on(config, "sales_invoices"):
        progress.start("Raising sales invoices…")
        scfg = config.get("sales") or {}
        sales, sf = raise_invoices(tables["sales_to_invoice"], tables.get("customers"), invoice_date=p_end,
                                   first_number=int(scfg.get("first_invoice_number", 1001)),
                                   prefix=scfg.get("invoice_prefix", "INV-"),
                                   default_terms_days=int(scfg.get("default_terms_days", 30)),
                                   default_vat_code=normalise_code(scfg.get("default_vat_code", "S")) or "S",
                                   group_by=scfg.get("group_by", "job"))
        findings += sf
        n_inv = sales["invoice_number"].nunique() if not sales.empty else 0
        held = sales[sales["status"] == "Held"]["invoice_number"].nunique() if not sales.empty else 0
        (progress.warn if held else progress.done)(
            f"Raised {_plural(n_inv, 'sales invoice')} worth £{sales['gross'].sum():,.2f}" if n_inv else "No sales invoices to raise",
            f"{held} held for a check" if held else "")

    # 8. Debtors -------------------------------------------------------------------------
    debtors, debtors_summary, chase = pd.DataFrame(), pd.DataFrame(), []
    if "open_invoices" in tables and _module_on(config, "debtors"):
        dcfg = config.get("debtors") or {}
        progress.start("Ageing the sales ledger and matching payments received…")
        receipts = tables.get("bank_statement")
        debtors, debtors_summary, df_ = aged_debtors(
            tables["open_invoices"], as_of=inputs.as_of, customers=tables.get("customers"), receipts=receipts,
            buckets=dcfg.get("buckets"), tiers=dcfg.get("tiers"), default_terms_days=int(dcfg.get("default_terms_days", 30)))
        findings += df_
        chase = chase_groups(debtors, tables.get("customers"), dcfg.get("tiers"))
        overdue = debtors[debtors["days_overdue"] > 0]["outstanding"].clip(lower=0).sum()
        progress.done(f"Aged {_plural(len(debtors), 'open invoice')}: £{debtors['outstanding'].sum():,.2f} outstanding",
                      f"£{overdue:,.2f} overdue; {_plural(len(chase), 'customer')} to chase")

    # 9. Timesheets ------------------------------------------------------------------------
    hours, ts_rows = pd.DataFrame(), pd.DataFrame()
    if "timesheets" in tables and _module_on(config, "timesheets"):
        progress.start(f"Checking {_plural(len(tables['timesheets']), 'timesheet line')}…")
        ts_rows, hours, tf = timesheet_hours(tables["timesheets"], tables.get("employees"), config.get("timesheets"))
        findings += tf
        progress.done(f"Summarised hours for {_plural(hours['Employee'].nunique() if not hours.empty else 0, 'employee')}",
                      f"{hours['Overtime hours'].sum():g} overtime hours" if not hours.empty else "")

    # 10. Purchase orders ------------------------------------------------------------------
    po_table = pd.DataFrame()
    if "purchase_orders" in tables and _module_on(config, "purchase_orders"):
        progress.start("Matching supplier invoices to purchase orders…")
        pcfg = config.get("purchase_orders") or {}
        po_table, pof = match_invoices_to_pos([d for d in purchase_docs if d["doc_id"] not in duplicates],
                                              tables["purchase_orders"], tolerance_pct=float(pcfg.get("tolerance_pct", 2)),
                                              tolerance_abs=float(pcfg.get("tolerance_abs", 5)),
                                              require_po=bool(pcfg.get("require_po", True)))
        findings += pof
        matched = int((po_table["Status"] == "Matched").sum()) if not po_table.empty else 0
        progress.done(f"Matched {matched} invoice(s) to purchase orders", f"{_plural(len(pof), 'issue')}" if pof else "")

    # 11. Supplier statements -----------------------------------------------------------------
    statements = pd.DataFrame()
    stmt_docs = [d for d in docs if d["doc_type"] == "statement" and d["statement_lines"]]
    if stmt_docs and _module_on(config, "statements"):
        progress.start(f"Reconciling {_plural(len(stmt_docs), 'supplier statement')}…")
        frames = []
        for s in stmt_docs:
            table = reconcile_statement(s, docs)
            frames.append(table)
            for r in table.to_dict("records"):
                if r["Status"] == "Not in our records":
                    findings.append(Finding("statement_missing_invoice", subject=s["counterparty"], reference=str(r["Statement ref"]),
                                            date=r["Statement date"], amount=r["Statement amount"], source=s["file"], doc_ids=[s["doc_id"]],
                                            finding=f"{r['Statement ref']} (£{r['Statement amount']:,.2f}) is on the statement but no matching invoice was received.",
                                            ask=f"Could you send a copy of invoice {r['Statement ref']}?"))
                elif r["Status"] == "Amount differs":
                    findings.append(Finding("statement_amount_mismatch", subject=s["counterparty"], reference=str(r["Statement ref"]),
                                            date=r["Statement date"], amount=r["Statement amount"], source=s["file"],
                                            finding=f"{r['Statement ref']} is £{r['Statement amount']:,.2f} on the statement but "
                                                    f"£{r['Our amount']:,.2f} on the invoice received."))
        statements = pd.concat(frames, ignore_index=True) if frames else statements
        progress.done(f"Reconciled {_plural(len(stmt_docs), 'supplier statement')}")

    # 12. Filing ---------------------------------------------------------------------------
    filing = pd.DataFrame()
    if docs and _module_on(config, "filing"):
        progress.start(f"Filing {_plural(len(docs), 'document')} into project folders…")
        fcfg = config.get("filing") or {}
        filing, ff = file_documents(docs, {d["doc_id"]: t.text for d, t in zip(docs, texts)},
                                    tables.get("projects"), ref_pattern=fcfg.get("reference_pattern"),
                                    unfiled_folder=fcfg.get("unfiled_folder", "_To file"),
                                    noun=fcfg.get("noun", "project"))
        findings += ff
        (progress.warn if ff else progress.done)(f"Filed {len(docs) - len(ff)} of {_plural(len(docs), 'document')}",
                                                 f"{len(ff)} need{'s' if len(ff) == 1 else ''} a person to choose the folder"
                                                 if ff else "")

    # 13. Exceptions, holds -------------------------------------------------------------------
    findings = finalise(findings, config)
    entries = _apply_holds(entries, findings)
    if not sales.empty:
        for f in findings:
            for key in f.entry_keys:
                if key.startswith("sales:"):
                    mask = sales["invoice_number"] == key.split(":", 1)[1]
                    sales.loc[mask, "hold_reason"] = sales.loc[mask, "hold_reason"].map(
                        lambda r, fid=f.id: f"{r} ({fid})" if fid not in str(r) else r)
    exceptions = findings_frame(findings)
    n_high = sum(f.severity == "High" for f in findings)
    n_check = sum(f.needs_human_check for f in findings)
    (progress.warn if findings else progress.done)(
        f"Found {_plural(len(findings), 'exception')}",
        f"{n_high} high severity, {n_check} need a human check" if findings else "all clear")

    # 14. VAT return workings ----------------------------------------------------------------
    vat_box = pd.DataFrame()
    if _module_on(config, "vat_return"):
        vcfg = config.get("vat_return") or {}
        vs, ve = pd.Timestamp(vcfg.get("start", p_start)), pd.Timestamp(vcfg.get("end", p_end))
        vat_box = vat_return(_with_sales(entries, sales), vs, ve)

    # 15. Exports + month-end facts -------------------------------------------------------------
    chart_codes = dict(zip(chart.accounts["name"], chart.accounts["code"].astype(str)))
    exports = build_exports(config, entries, journal=journal, sales=sales, hours=hours, chart_codes=chart_codes,
                            stem=_slug(config.get("tool_name", "bookkeeping")) + f"_{p_end:%Y-%m}_")
    letter_requests = _letter_requests(findings, chase, book, tables, config) if _module_on(config, "letters") else []
    facts = _facts(config, docs, entries, txns, matches, no_receipt_needed, payroll_totals, payroll_diff, sales, debtors,
                   ts_rows, po_table, stmt_docs, filing, vat_box, findings, letter_requests, p_start, p_end, inputs)
    by_check: dict[str, list[str]] = {}
    for f in findings:
        by_check.setdefault(f.check_id, []).append(f.id)
    checklist = month_end.checklist(config, facts, by_check) if _module_on(config, "month_end") else pd.DataFrame()
    if not checklist.empty:
        facts["month_end_open_items"] = checklist[checklist["Status"] == month_end.ACTION]["Item"].tolist()

    # 16. Claude: emails + summary ---------------------------------------------------------------
    progress.start(f"Drafting {_plural(len(letter_requests), 'email')} and the manager summary with {source_word}…")
    from concurrent.futures import ThreadPoolExecutor

    lcfg = config.get("ai") or {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        letters_future = pool.submit(ai.draft_letters, client, letter_requests, config,
                                     batch_size=int(lcfg.get("letters_per_request", 3)))
        summary_future = pool.submit(ai.write_summary, client, facts, config)
        letter_texts, letter_calls = letters_future.result()
        summary_call = summary_future.result()
    calls += letter_calls + [summary_call]
    letters = []
    for req in letter_requests:
        t = letter_texts.get(req["key"], {})
        letters.append({**req, "subject": t.get("subject", ""), "body": t.get("body", ""), "source": t.get("source", "")})
    summary = summary_call.text.strip() or ai.template_summary(facts)
    gen_calls = letter_calls + [summary_call]
    ai_ok = all(c.from_ai for c in gen_calls)
    (progress.done if ai_ok else progress.warn)(f"Drafted {_plural(len(letters), 'email')} and the manager summary",
                                                _source_phrase(Counter(c.source for c in gen_calls)))
    ai_warnings = [c.warning for c in calls if c.warning]
    if ai_warnings:
        more = f" ({len(ai_warnings)} of {len(calls)} AI requests affected; template text used.)" if len(ai_warnings) > 1 else ""
        warnings.append(ai_warnings[0] + more)

    # 17. Human checks + time estimate ------------------------------------------------------------
    human = [CheckItem(id=f.id, title=f"{f.label} — {f.subject}" + (f" · {f.reference}" if f.reference and f.reference != f.subject else ""),
                       why=f.finding, action=f.action, severity=f.severity.lower()) for f in findings if f.needs_human_check]
    if not all(c.from_ai for c in calls) and calls:
        human.append(CheckItem(id="AI", title="Some text came from templates, not Claude",
                               why="Claude was not available for every step, so the pattern reader and template wording "
                                   "were used. The checks and totals are unaffected; extracted fields and wording should be reviewed.",
                               action="Re-run with an API key, or check the Documents tab and the drafted emails.", severity="info"))
    est = _time_saved(config, facts, len(findings), sum(f.needs_human_check for f in findings), len(letters))

    summary_source = {
        "api": f"Written by Claude ({summary_call.model}) from the checked figures.",
        "cache": "Written by Claude from the checked figures (cached).",
        "fixture": "Pre-recorded AI text for the sample data (mock mode: no API key set, no network calls).",
        "mock": "Template summary (mock mode: no recorded Claude response for these files).",
        "fallback": "Template summary (Claude unavailable).",
    }.get(summary_call.source, "")

    progress.start("Building the import files and the month-end pack…")
    result = RunResult(
        config=config, inputs_label=inputs.label, as_of=inputs.as_of, period_start=p_start, period_end=p_end,
        documents=docs, documents_table=documents_frame(docs), entries=entries, card=card_view, journal=journal,
        payroll=payroll_rows, sales=sales, debtors=debtors, debtors_summary=debtors_summary, hours=hours,
        po_table=po_table, statements=statements, filing=filing, vat_return=vat_box, findings=findings,
        exceptions=exceptions, letters=letters, checklist=checklist, exports=exports, summary=summary,
        summary_source=summary_source, facts=facts, human_checks=human, time_estimate=est, files_read=files_read,
        originals=originals, warnings=warnings, ai_sources=dict(Counter(c.source for c in calls)),
    )
    from tools.bookkeeping import reports

    result.downloads = reports.build_downloads(result)
    built = (f"Built {_plural(len(exports), SYSTEM_LABELS.get(config.get('accounting_system', 'quickbooks'), '') + ' import file')} "
             f"and the month-end pack" if exports else "Built the month-end pack (nothing is ready to import yet)"
             if not entries.empty else f"Built {_plural(len(result.downloads), 'output file')}")
    progress.done(built, ", ".join(f.file_name.rsplit(".", 1)[-1].upper() for f in result.downloads[len(exports):]))
    result.seconds = round(time.perf_counter() - started, 2)
    return result

# --------------------------------------------------------------- stages


def _document_checks(docs: list[dict], book: SupplierBook, config: dict, p_start, p_end, findings: list[Finding]) -> set[str]:
    rates = tuple(float(r) for r in (config.get("vat") or {}).get("allowed_rates", [0, 5, 20]))
    prepay_min = float((config.get("checks_settings") or {}).get("prepayment_min_amount", 500))
    has_book = book.suppliers is not None and not book.suppliers.empty
    duplicates: set[str] = set()
    seen: dict[tuple, dict] = {}
    for d in docs:
        label = _doc_label(d)
        common = dict(subject=d["counterparty"] or d["file"], reference=d["document_number"] or d["file"],
                      date=d["document_date"], amount=d["gross_total"], source=d["file"], doc_ids=[d["doc_id"]])
        # duplicates
        if d["document_number"] and d["doc_type"] in ("invoice", "credit_note"):
            number = re.sub(r"\W", "", d["document_number"]).upper()
            key = (norm_name(d["counterparty"]), number, d["doc_type"])
            alt = ("*amount*", number, d["doc_type"], d["gross_total"])  # same number and total, name read differently
            if key in seen or alt in seen:
                first = seen.get(key) or seen[alt]
                duplicates.add(d["doc_id"])
                same = first["gross_total"] == d["gross_total"]
                findings.append(Finding("duplicate_document" if same else "possible_duplicate", **common,
                                        finding=f"{label} was received twice: “{first['file']}” and “{d['file']}”"
                                                + ("; same amount, so only the first copy is posted." if same
                                                   else f", but the totals differ (£{first['gross_total']:,.2f} and £{d['gross_total']:,.2f}).")))
                continue
            seen[key] = d
            seen[alt] = d
        supplier = book.find(d["counterparty"]) if d["doc_type"] in ("invoice", "credit_note") else None
        for check, msg in arithmetic_problems(d, allowed_rates=rates):
            findings.append(Finding(check, **common, finding=msg, ask=ASKS.get(check, "")))
        for check, msg in supplier_vat_checks(d, supplier if d["doc_type"] != "receipt" else None):
            if d["doc_type"] == "receipt" and check == "bank_details_changed":
                continue
            ask = ASKS.get(check, "")
            if check == "bank_details_changed":
                ask = f"We received new bank details with {label}. " + ask
            findings.append(Finding(check, **common, finding=msg, ask=ask))
        on_account = d["payment_status"] != "paid" and not d["card_last4"]  # card-paid one-offs need no supplier record
        if has_book and d["doc_type"] in ("invoice", "credit_note") and on_account and supplier is None:
            findings.append(Finding("new_supplier", **common,
                                    finding=f"{d['counterparty'] or 'The supplier'} is not on the supplier list"
                                            + (f" (VAT number {format_vat_number(d['counterparty_vat_number'])})."
                                               if d["counterparty_vat_number"] else ".")))
        if d["document_date"] is not None and d["doc_type"] in ("invoice", "credit_note"):
            if d["document_date"] < p_start:
                findings.append(Finding("prior_period", **common,
                                        finding=f"{label} is dated {d['document_date']:%d %b %Y}, before this period "
                                                f"({p_start:%d %b} to {p_end:%d %b %Y})."))
            elif d["document_date"] > p_end:
                findings.append(Finding("future_dated", **common,
                                        finding=f"{label} is dated {d['document_date']:%d %b %Y}, after the period end."))
        end = d.get("service_period_end")
        if end is not None and end > p_end + pd.Timedelta(days=31) and (d["gross_total"] or 0) >= prepay_min:
            start = d.get("service_period_start") or d["document_date"] or p_start
            months = max(1, round((end - start).days / 30.44))
            per_month = (d["net_total"] if d["net_total"] is not None else d["gross_total"]) / months
            findings.append(Finding("prepayment", **common,
                                    finding=f"{label} covers {start:%d %b %Y} to {end:%d %b %Y} ({months} months). "
                                            f"About £{per_month:,.2f} a month should be released from prepayments."))
        if d["currency"] != "GBP":
            findings.append(Finding("foreign_currency", **{**common, "amount": None},
                                    finding=f"{label} is in {d['currency']} ({d['currency']} {d['gross_total'] or 0:,.2f}) from an overseas "
                                            f"supplier, so no UK VAT is charged and reverse-charge VAT may apply."))
    return duplicates


def _card_transactions(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    t = df.copy().reset_index(drop=True)
    for col in ("card_last4", "cardholder", "reference", "original_currency"):
        if col not in t:
            t[col] = ""
    if "original_amount" not in t:
        t["original_amount"] = float("nan")
    t["card_last4"] = t["card_last4"].astype(str).str.replace(r"\D", "", regex=True).str[-4:]
    spend_positive = (t["amount"] > 0).sum() >= (t["amount"] < 0).sum()
    if not spend_positive:
        t["amount"] = -t["amount"]
    t["txn_id"] = [f"T-{i:02d}" for i in range(1, len(t) + 1)]
    spend = t[t["amount"] > 0].copy()
    credits = t[t["amount"] <= 0].copy()
    return spend, credits


def _card_findings(txns, candidates, matches, no_receipt_needed, config, findings):
    ccfg = config.get("card") or {}
    min_amount = float(ccfg.get("missing_receipt_min_amount", 0))
    matched_docs = {did for did, _ in matches.values()}
    for t in txns.to_dict("records"):
        who = t["cardholder"] or (f"card ending {t['card_last4']}" if t["card_last4"] else "Cardholder")
        common = dict(subject=who, reference=t["txn_id"], date=t["date"], amount=t["amount"],
                      source=t.get("_source", ""), txn_ids=[t["txn_id"]])
        if t["txn_id"] in matches:
            did, info = matches[t["txn_id"]]
            doc = next(d for d in candidates if d["doc_id"] == did)
            if info.get("near") and info.get("difference"):
                diff = info["difference"]
                findings.append(Finding("amount_mismatch", **common,
                                        finding=f"Card payment to {t['description']} is £{t['amount']:,.2f} but the receipt "
                                                f"from {doc['counterparty'] or doc['file']} totals £{doc['gross_total']:,.2f}: £{abs(diff):,.2f} "
                                                f"{'more' if diff > 0 else 'less'} on the card."))
            continue
        if t["txn_id"] in no_receipt_needed or t["amount"] < min_amount:
            continue
        findings.append(Finding("missing_receipt", **common, ref_text=f"{t['date']:%d %b %Y} · {t['description']} · £{t['amount']:,.2f}",
                                finding=f"No receipt or invoice found for £{t['amount']:,.2f} to {t['description']} on "
                                        f"{t['date']:%d %b %Y} ({who}).",
                                ask=ASKS["missing_receipt"],
                                contact=who))
    cards = set(txns["card_last4"]) - {""}
    for d in candidates:
        if d["doc_id"] in matched_docs or d["doc_type"] != "receipt":
            continue
        how = (f"It was paid with a card ending {d['card_last4']}, which is not a company card on this statement."
               if d["card_last4"] and d["card_last4"] not in cards else "No matching payment is on the card statement.")
        findings.append(Finding("receipt_unmatched", subject=d["counterparty"] or d["file"], reference=d["document_number"] or d["file"],
                                date=d["document_date"], amount=d["gross_total"], source=d["file"], doc_ids=[d["doc_id"]],
                                finding=f"Receipt from {d['counterparty']} for £{d['gross_total'] or 0:,.2f} "
                                        f"({d['document_date']:%d %b %Y}). {how}" if d["document_date"] is not None else
                                        f"Receipt from {d['counterparty']} for £{d['gross_total'] or 0:,.2f}. {how}"))


def _card_view(txns, credits, docs, matches, no_receipt_needed) -> pd.DataFrame:
    by_id = {d["doc_id"]: d for d in docs}
    rows = []
    for t in txns.to_dict("records"):
        match = matches.get(t["txn_id"])
        d = by_id.get(match[0]) if match else None
        if d:
            status = "Matched" if match[1].get("exact") else ("Matched (foreign currency)" if match[1].get("foreign") else "Amount differs")
        else:
            status = "No receipt needed" if t["txn_id"] in no_receipt_needed else "Receipt missing"
        rows.append({"Txn": t["txn_id"], "Date": t["date"], "Card": t["card_last4"], "Cardholder": t["cardholder"],
                     "Merchant": t["description"], "Amount": t["amount"], "Status": status,
                     "Receipt from": d["counterparty"] if d else "", "Receipt": d["file"] if d else "",
                     "Receipt total": d["gross_total"] if d else None,
                     "Receipt currency": d["currency"] if d else ""})
    for t in credits.to_dict("records"):
        rows.append({"Txn": t["txn_id"], "Date": t["date"], "Card": t["card_last4"], "Cardholder": t["cardholder"],
                     "Merchant": t["description"], "Amount": t["amount"], "Status": "Payment / refund (not an expense)",
                     "Receipt from": "", "Receipt": "", "Receipt total": None, "Receipt currency": ""})
    return pd.DataFrame(rows)


def _build_entries(purchase_docs, duplicates, txns, matches, no_receipt_needed, book, rules, chart, fallback, client,
                   config, findings, p_start, p_end):
    """One row per ledger line. Groups (a document or a card transaction) share a code."""
    vcfg = config.get("vat") or {}
    blocked = set(vcfg.get("blocked_accounts", []))
    doc_by_id = {d["doc_id"]: d for d in purchase_docs}
    matched_doc_ids = {did for did, _ in matches.values()}
    groups = []  # (group, kind, doc, txn)
    for d in purchase_docs:
        if d["doc_id"] in duplicates or d["doc_id"] in matched_doc_ids:
            continue
        if d["doc_type"] == "invoice":  # on account (or paid some other way): a bill
            groups.append((f"doc:{d['doc_id']}", "bill", d, None))
        elif d["doc_type"] == "credit_note":
            groups.append((f"doc:{d['doc_id']}", "supplier_credit", d, None))
        elif d["doc_type"] == "receipt":
            groups.append((f"doc:{d['doc_id']}", "expense_claim", d, None))
    for t in (txns.to_dict("records") if not txns.empty else []):
        did = matches.get(t["txn_id"], (None,))[0]
        groups.append((f"txn:{t['txn_id']}", "card_expense", doc_by_id.get(did), t))

    # code each group: supplier list, rules, then Claude
    codes, to_ai = {}, []
    for gkey, kind, d, t in groups:
        payee = (d or {}).get("counterparty") or (t or {}).get("description", "")
        text = " ".join(x for x in [payee, (t or {}).get("description", "")] if x)
        code = code_from_supplier(book.find(payee), chart) or code_from_rules(text, rules, chart)
        if code is None and t is not None:
            code = code_from_supplier(book.find(t["description"]), chart)
        if code is not None:
            codes[gkey] = code
            continue
        item = {"id": d["doc_id"] if t is None else t["txn_id"], "payee": payee,
                "card_description": (t or {}).get("description", ""), "amount_gbp": (t or {}).get("amount") or (d or {}).get("gross_total"),
                "document": (d or {}).get("summary", ""),
                "items": [i["description"] for i in (d or {}).get("line_items", [])][:10],
                "notes": (d or {}).get("notes", "")}
        to_ai.append((gkey, item))
    calls = []
    if to_ai and _module_on(config, "coding"):
        offered = chart.for_prompt((config.get("coding") or {}).get("account_types"))
        names = [a["account"] for a in offered] + ([fallback] if fallback not in [a["account"] for a in offered] else [])
        ai_codes, calls = ai.code_entries(client, [i for _, i in to_ai], offered, names, config, fallback=fallback,
                                          batch_size=int((config.get("coding") or {}).get("items_per_request", 12)))
        from tools.bookkeeping.coding import Code

        for gkey, item in to_ai:
            c = ai_codes[item["id"]]
            by = "Claude" if c.get("source") in ("api", "cache", "fixture") else "fallback"
            codes[gkey] = Code(c["account"], "", by, c.get("confidence", "low"), c.get("reason", ""))
    else:
        from tools.bookkeeping.coding import Code

        for gkey, _ in to_ai:
            codes[gkey] = Code(fallback, "", "fallback", "low", "No rule matched; needs coding by hand.")

    rows = []
    counts = Counter()
    for gkey, kind, d, t in groups:
        code = codes[gkey]
        counts[{"supplier list": "supplier list", "rule": "keyword rule", "Claude": "Claude"}.get(code.coded_by, "fallback")] += 1
        payee = (d or {}).get("counterparty") or (t or {}).get("description", "")
        supplier = book.find(payee) or {}
        if code.confidence == "low" and code.coded_by in ("Claude", "fallback"):
            findings.append(Finding("low_confidence_coding", subject=payee, reference=(d or {}).get("document_number") or (t or {}).get("txn_id", ""),
                                    date=(t or {}).get("date") if t else (d or {}).get("document_date"),
                                    amount=(t or {}).get("amount") if t else (d or {}).get("gross_total"),
                                    source=(d or {}).get("file", "") or (t or {}).get("_source", ""),
                                    doc_ids=[d["doc_id"]] if d else [], txn_ids=[t["txn_id"]] if t else [],
                                    finding=f"Suggested account “{code.account}”, but with low confidence: {code.reason}"))
        base = {"group": gkey, "kind": kind, "doc_id": (d or {}).get("doc_id", ""), "txn_id": (t or {}).get("txn_id", ""),
                "counterparty": payee, "supplier_ref": supplier.get("account_ref", ""),
                "reference": (d or {}).get("document_number") or (t or {}).get("reference") or (t or {}).get("txn_id", ""),
                "date": (t or {}).get("date") if t else (d or {}).get("document_date"),
                "due_date": (d or {}).get("due_date") if kind == "bill" else None,
                "terms_days": supplier.get("terms_days") if supplier.get("terms_days") not in ("", None) else None,
                "account": code.account, "account_code": chart.code(code.account), "coded_by": code.coded_by,
                "confidence": code.confidence, "coding_reason": code.reason,
                "tracking": (t or {}).get("cardholder", "") if t else (d or {}).get("project_reference", ""), "memo": "",
                "source": (d or {}).get("file", "") or (t or {}).get("_source", ""), "status": "Ready", "hold_reason": ""}
        if base["date"] is None or pd.isna(base["date"]):
            base["date"] = p_end
        if kind == "bill" and (base["due_date"] is None or pd.isna(base["due_date"])) and base["terms_days"]:
            base["due_date"] = base["date"] + pd.Timedelta(days=int(base["terms_days"]))
        lines = []
        if d is not None and d["currency"] == "GBP" and d["vat_lines"]:
            items = d.get("line_items") or []
            supplier_code = normalise_code(supplier.get("vat_code"))
            zero_default = (code.vat_code if code.vat_code in ("Z", "E", "O")
                            else supplier_code if supplier_code in ("Z", "E", "O") else "Z")
            for vl in d["vat_lines"]:
                vcode = code_for_rate(vl["rate"], zero_default=zero_default)
                desc_items = [i["description"] for i in items if i.get("vat_rate") is None or abs((i.get("vat_rate") or 0) - vl["rate"]) < 0.6]
                desc = "; ".join(desc_items)[:120] if desc_items else (d.get("summary") or code.account)
                lines.append({"description": desc, "net": vl["net"], "vat": vl["vat"], "vat_code": vcode})
        elif d is not None and d["currency"] != "GBP" and t is not None:
            lines.append({"description": f"{d.get('summary') or d['counterparty']} ({d['currency']} {d['gross_total'] or 0:,.2f})",
                          "net": t["amount"], "vat": 0.0, "vat_code": "RC"})
        elif d is not None:
            amount = d["gross_total"] or 0.0
            lines.append({"description": d.get("summary") or code.account, "net": amount, "vat": 0.0,
                          "vat_code": code.vat_code if code.vat_code in ("Z", "E", "O") else "O"})
        if t is not None:
            if not lines:
                lines.append({"description": f"{t['description']} (no VAT receipt)" if t["txn_id"] not in no_receipt_needed else t["description"],
                              "net": t["amount"], "vat": 0.0, "vat_code": code.vat_code if code.vat_code in ("E", "O", "Z") else "O"})
            else:
                diff = round(t["amount"] - sum(l["net"] + l["vat"] for l in lines), 2)
                if abs(diff) > 0.009:
                    lines.append({"description": "Difference between card payment and receipt (no VAT)", "net": diff,
                                  "vat": 0.0, "vat_code": "O"})
        if code.account in blocked:
            vat_total = sum(l["vat"] for l in lines)
            if vat_total:
                findings.append(Finding("blocked_vat", subject=payee, reference=base["reference"], date=base["date"],
                                        amount=round(vat_total, 2), source=base["source"],
                                        doc_ids=[d["doc_id"]] if d else [], txn_ids=[t["txn_id"]] if t else [],
                                        finding=f"£{vat_total:,.2f} VAT on {code.account.lower()} is not reclaimable, so "
                                                f"the full amount is posted with no VAT."))
            for l in lines:
                l["net"], l["vat"], l["vat_code"] = round(l["net"] + l["vat"], 2), 0.0, "O"
        for l in lines:
            rows.append({**base, **l, "gross": round(l["net"] + l["vat"], 2)})
    cols = ["entry", "group", "kind", "doc_id", "txn_id", "date", "due_date", "terms_days", "reference", "counterparty",
            "supplier_ref", "account", "account_code", "description", "net", "vat", "vat_code", "gross", "tracking",
            "coded_by", "confidence", "coding_reason", "memo", "source", "status", "hold_reason"]
    entries = pd.DataFrame(rows)
    if entries.empty:
        return pd.DataFrame(columns=cols), calls, counts
    entries.insert(0, "entry", [f"E-{i:03d}" for i in range(1, len(entries) + 1)])
    return entries[cols], calls, counts


def _apply_holds(entries: pd.DataFrame, findings: list[Finding]) -> pd.DataFrame:
    if entries.empty:
        return entries
    e = entries.copy()
    e.loc[e["kind"] == "expense_claim", "status"] = "Held"
    for f in findings:
        if not f.hold:
            continue
        mask = e["doc_id"].isin(f.doc_ids) | e["txn_id"].isin(f.txn_ids) | e["group"].isin(f.entry_keys)
        e.loc[mask, "status"] = "Held"
        e.loc[mask, "hold_reason"] = e.loc[mask, "hold_reason"].map(lambda r, fid=f.id: ", ".join(x for x in [r, fid] if x))
    # a duplicate document's lines never exist; held claims without a finding say why
    claim = (e["kind"] == "expense_claim") & (e["hold_reason"] == "")
    e.loc[claim, "hold_reason"] = "receipt not on a company card"
    return e


def _with_sales(entries: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    if sales is None or sales.empty:
        return entries
    s = pd.DataFrame({"kind": "sales_invoice", "date": sales["date"], "net": sales["net"], "vat": sales["vat"],
                      "vat_code": sales["vat_code"], "status": sales["status"]})
    return pd.concat([entries[["kind", "date", "net", "vat", "vat_code", "status"]], s], ignore_index=True) if not entries.empty else s


def _letter_requests(findings, chase, book, tables, config) -> list[dict]:
    contacts = config.get("contacts") or {}
    cardholders = {str(c.get("name", "")).lower(): c for c in contacts.get("cardholders", [])}
    cardholders.update({str(c.get("card", "")): c for c in contacts.get("cardholders", []) if c.get("card")})
    customers = {r.get("name"): r for r in (tables["customers"].to_dict("records") if "customers" in tables else [])}
    groups: dict[str, dict] = {}
    for f in findings:
        if not f.letter:
            continue
        rtype = f.letter
        name = f.contact or f.subject
        info = {}
        if rtype == "supplier":
            rec = book.find(name) or {}
            info = {"contact": rec.get("contact", ""), "email": rec.get("email", "")}
        elif rtype == "cardholder":
            rec = cardholders.get(name.lower()) or next((v for k, v in cardholders.items() if k and k in name), {})
            info = {"contact": rec.get("name", name), "email": rec.get("email", "")}
        elif rtype == "customer":
            rec = next((v for k, v in customers.items() if name_similarity(k, name) >= 0.85), {})
            info = {"contact": rec.get("contact", ""), "email": rec.get("email", "")}
        elif rtype == "payroll_bureau":
            rec = contacts.get("payroll_bureau") or {}
            name = rec.get("name", "Payroll bureau")
            info = {"contact": rec.get("contact", ""), "email": rec.get("email", "")}
        key = f"{rtype}:{name}"
        g = groups.setdefault(key, {"key": key, "recipient_type": rtype, "to": name, **info, "tone": "", "points": [],
                                    "exceptions": []})
        ref = _point_ref(f)
        g["points"].append({"ref": ref, "issue": f.finding, "ask": f.ask})
        g["exceptions"].append(f.id)
    for c in chase:
        key = f"customer:{c['customer']}"
        g = groups.setdefault(key, {"key": key, "recipient_type": "customer", "to": c["customer"], "contact": c["contact"],
                                    "email": c["email"], "tone": "", "points": [], "exceptions": []})
        g["tone"] = c["tone"] or c["tier"]
        g["tone_label"] = c["tier"]
        for inv in c["invoices"]:
            g["points"].append({"ref": f"Invoice {inv['invoice']}",
                                "issue": f"£{inv['outstanding']:,.2f} was due on {inv['due']} and is {inv['days_overdue']} days overdue.",
                                "ask": ""})
    out = list(groups.values())
    order = {"supplier": 0, "payroll_bureau": 1, "cardholder": 2, "customer": 3}
    out.sort(key=lambda g: (order.get(g["recipient_type"], 9), g["to"]))
    return out


def _point_ref(f: Finding) -> str:
    if f.ref_text:
        return f.ref_text
    if f.check_id.startswith("payroll_") and f.reference:
        return f"{f.subject} ({f.reference})"
    bits = []
    if f.check_id in ("missing_receipt", "amount_mismatch"):
        return f"{f.date:%d %b %Y} · £{f.amount:,.2f}" if f.date is not None and f.amount is not None else f.reference
    if f.reference and f.reference != f.subject:
        bits.append(("Invoice " if f.area in ("Purchases", "VAT", "Orders") and not f.reference.lower().startswith(("invoice", "inv")) else "") + f.reference)
    if f.date is not None:
        bits.append(f"{f.date:%d %b %Y}")
    if f.amount is not None and f.check_id not in ("payroll_net_mismatch",):
        bits.append(f"£{f.amount:,.2f}")
    return " · ".join(bits)


def _facts(config, docs, entries, txns, matches, no_receipt_needed, payroll_totals, payroll_diff, sales, debtors, ts_rows,
           po_table, stmt_docs, filing, vat_box, findings, letters, p_start, p_end, inputs) -> dict:
    ready = entries[entries["status"] == "Ready"] if not entries.empty else entries
    held = entries[entries["status"] == "Held"] if not entries.empty else entries
    purchase_groups = entries[entries["kind"].isin(["bill", "supplier_credit"])] if not entries.empty else entries
    letters_by_type = Counter(l["recipient_type"] for l in letters)
    facts = {
        "company": (config.get("company") or {}).get("name", ""),
        "period": period_label(p_start, p_end),
        "as_of": f"{inputs.as_of:%d %b %Y}",
        "documents": len(docs),
        "documents_by_type": dict(Counter(d["doc_type"].replace("_", " ") for d in docs)),
        "entries": len(entries),
        "entries_ready": len(ready),
        "entries_held": len(held),
        "value_ready": round(float(ready["gross"].sum()), 2) if not ready.empty else 0.0,
        "value_held": round(float(held["gross"].sum()), 2) if not held.empty else 0.0,
        "purchase_docs": purchase_groups["group"].nunique() if not purchase_groups.empty else 0,
        "purchase_ready": purchase_groups[purchase_groups["status"] == "Ready"]["group"].nunique() if not purchase_groups.empty else 0,
        "purchase_held": purchase_groups[purchase_groups["status"] == "Held"]["group"].nunique() if not purchase_groups.empty else 0,
        "letters_by_type": dict(letters_by_type),
        "emails": len(letters),
        "exceptions": len(findings),
        "by_severity": dict(Counter(f.severity for f in findings)),
        "needs_human_check": sum(f.needs_human_check for f in findings),
        "high_severity": [{"id": f.id, "check": f.label, "who": f.subject, "finding": f.finding}
                          for f in findings if f.severity == "High"],
    }
    if not txns.empty:
        facts.update({"card_txns": len(txns), "card_matched": len(matches), "card_no_receipt_needed": len(no_receipt_needed),
                      "card_spend": round(float(txns["amount"].sum()), 2),
                      "missing_receipts": [f"{f.subject}: £{f.amount:,.2f} {f.finding.split(' to ', 1)[-1].split(' on ')[0]}"
                                           for f in findings if f.check_id == "missing_receipt"]})
    if payroll_totals:
        facts.update({"payroll_employees": payroll_totals["employees"], "payroll_gross": payroll_totals["gross"],
                      "payroll_net": payroll_totals["net_pay"], "payroll_difference": payroll_diff})
    if not sales.empty:
        facts.update({"sales_invoices": sales["invoice_number"].nunique(),
                      "sales_ready": sales[sales["status"] == "Ready"]["invoice_number"].nunique(),
                      "sales_held": sales[sales["status"] == "Held"]["invoice_number"].nunique(),
                      "sales_value": round(float(sales["gross"].sum()), 2)})
    if not debtors.empty:
        facts.update({"debtor_items": len(debtors), "debtors_outstanding": round(float(debtors["outstanding"].sum()), 2),
                      "debtors_overdue": round(float(debtors[debtors["days_overdue"] > 0]["outstanding"].clip(lower=0).sum()), 2),
                      "debtor_issues": [{"id": f.id, "check": f.label, "who": f.subject, "finding": f.finding}
                                        for f in findings if f.area == "Debtors" or f.check_id == "over_credit_limit"]})
    if not ts_rows.empty:
        facts.update({"timesheet_rows": len(ts_rows), "timesheet_employees": ts_rows["employee"].nunique()})
    if not po_table.empty:
        facts.update({"po_lines": len(po_table), "po_matched": int((po_table["Status"] == "Matched").sum())})
    if stmt_docs:
        facts["statements"] = len(stmt_docs)
    if not filing.empty:
        ref_col = str((config.get("filing") or {}).get("noun", "project")).capitalize()  # "Project", "Property"...
        unfiled = int((filing[ref_col].astype(str) == "").sum()) if ref_col in filing else 0
        facts.update({"filing_docs": len(filing), "filing_filed": len(filing) - unfiled, "filing_to_file": unfiled})
    if not vat_box.empty:
        facts["vat_return"] = True
        facts["vat_return_box5"] = float(vat_box.loc[vat_box["Box"] == 5, "Amount (£)"].iloc[0])
    return facts


def _time_saved(config, facts, n_exc, n_checks, n_letters) -> TimeEstimate:
    cfg = config.get("time_estimate") or {}
    by_type = facts.get("documents_by_type", {})
    counts = {"documents": facts.get("documents", 0), "invoices": by_type.get("invoice", 0) + by_type.get("credit note", 0),
              "receipts": by_type.get("receipt", 0), "card_txns": facts.get("card_txns", 0),
              "entries": facts.get("entries", 0), "exceptions": n_exc, "human_checks": n_checks, "emails": n_letters,
              "employees": facts.get("payroll_employees", 0), "sales_invoices": facts.get("sales_invoices", 0),
              "debtor_items": facts.get("debtor_items", 0), "timesheet_rows": facts.get("timesheet_rows", 0),
              "fixed": 1}

    def expand(rows):
        return [(label, counts.get(what, 0), float(minutes)) for label, what, minutes in rows]

    return estimate(expand(cfg.get("manual", [])), expand(cfg.get("with_tool", [])))

# ------------------------------------------------------------------ helpers


def _default_chart(config: dict) -> Chart:
    names = (config.get("coding") or {}).get("accounts") or ["Purchases", "General expenses", "Suspense"]
    return chart_from_frame(pd.DataFrame({"name": names}))


def _doc_label(d: dict) -> str:
    kind = {"invoice": "Invoice", "credit_note": "Credit note", "receipt": "Receipt"}.get(d["doc_type"], "Document")
    who = f" from {d['counterparty']}" if d["counterparty"] else ""
    num = f" {d['document_number']}" if d["document_number"] else ""
    return f"{kind}{num}{who}"


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def _source_phrase(sources: Counter) -> str:
    labels = {"api": "written by Claude", "cache": "from cache", "fixture": "pre-recorded AI text (mock mode)",
              "mock": "template / pattern reader (mock mode)", "fallback": "template (Claude unavailable)"}
    return ", ".join(f"{labels.get(k, k)} ×{v}" if v > 1 else labels.get(k, k) for k, v in sources.items())
