"""End-to-end run: files in, validated results + report files out.

    result = run(inputs, config, client, progress)

``progress`` is a ``core.ui.StepProgress`` (it draws nothing when created
without a container, which is how tests and scripts use it).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from core.claude import ClaudeClient
from core.estimates import TimeEstimate, estimate
from core.ui import CheckItem, DownloadFile, StepProgress
from tools.data_validation import ai, reports
from tools.data_validation.deadlines import build_tracker
from tools.data_validation.engine import DatasetSpec, ValidationResult, period_totals, validate
from tools.data_validation.loader import DataFileError, load_files, read_table
from tools.data_validation.rules import RULE_TYPES

FileInput = tuple[str, bytes]


class PipelineError(Exception):
    """Stops the run; the message is shown to the user as-is."""


@dataclass
class RunInputs:
    readings: list[FileInput]
    reference: FileInput | None = None
    calendar: FileInput | None = None
    as_of: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.today().normalize())
    label: str = "uploaded files"


@dataclass
class RunResult:
    config: dict
    spec: DatasetSpec
    inputs_label: str
    as_of: pd.Timestamp
    files_read: list[str]
    file_errors: list[str]
    validation: ValidationResult
    exceptions: pd.DataFrame  # with notes
    totals_by_key: pd.DataFrame
    totals_by_category: pd.DataFrame
    tracker: pd.DataFrame
    summary: str
    summary_source: str
    facts: dict
    human_checks: list[CheckItem]
    time_estimate: TimeEstimate
    downloads: list[DownloadFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ai_sources: dict = field(default_factory=dict)
    seconds: float = 0.0

    @property
    def period_label(self) -> str:
        return period_label(self.validation.period_start, self.validation.period_end)


def period_label(start, end) -> str:
    if start is None or end is None:
        return "no dated readings"
    if start.year == end.year:
        if start.month == end.month:
            return start.strftime("%B %Y")
        return f"{start:%b}–{end:%b %Y}"
    return f"{start:%b %Y}–{end:%b %Y}"


def sample_inputs(client_dir: Path, config: dict) -> RunInputs:
    sample = config.get("sample_data") or {}
    try:
        readings = [(Path(p).name, (client_dir / p).read_bytes()) for p in sample.get("readings", [])]
        reference = ((Path(sample["reference"]).name, (client_dir / sample["reference"]).read_bytes())
                     if sample.get("reference") else None)
        calendar = ((Path(sample["calendar"]).name, (client_dir / sample["calendar"]).read_bytes())
                    if sample.get("calendar") else None)
    except OSError as exc:
        raise PipelineError(f"The sample data files could not be found ({exc.filename}). "
                            "Check that the sample_data folder was deployed with the app.") from exc
    as_of = pd.Timestamp(config.get("sample_as_of") or pd.Timestamp.today()).normalize()
    return RunInputs(readings=readings, reference=reference, calendar=calendar, as_of=as_of, label="sample data")


def check_config(config: dict) -> None:
    for rule in config.get("rules", []):
        if rule.get("type") not in RULE_TYPES:
            raise PipelineError(f"Config error: unknown rule type “{rule.get('type')}” (rule {rule.get('id')}).")
    if not config.get("dataset"):
        raise PipelineError("Config error: the dataset section is missing.")


def run(inputs: RunInputs, config: dict, client: ClaudeClient, progress: StepProgress | None = None) -> RunResult:
    started = time.perf_counter()
    progress = progress or StepProgress()
    check_config(config)
    spec = DatasetSpec.from_config(config["dataset"])
    noun = spec.key_label.lower()
    warnings: list[str] = []

    # 1. Read files -----------------------------------------------------------------
    n = len(inputs.readings)
    if not n:
        raise PipelineError("No files to check. Upload at least one CSV or Excel export, or run the demo with sample data.")
    progress.start(f"Reading {n} file{'s' if n != 1 else ''}…")
    data, parse_issues, file_errors = load_files(inputs.readings, aliases=spec.aliases, required=spec.required,
                                                 numeric=spec.numeric, dates=spec.dates)
    if data.empty:
        progress.fail("Could not read any of the files")
        raise PipelineError("None of the files could be read:\n\n" + "\n".join(f"- {e}" for e in file_errors))
    files_read = sorted(data["_source"].unique().tolist())
    n_keys = data[spec.key].nunique()
    detail = f"{len(data):,} readings from {n_keys} {noun}s"
    if file_errors:
        progress.warn(f"Read {len(files_read)} of {n} files", detail + f"; skipped: {'; '.join(file_errors)}")
        warnings += file_errors
    else:
        progress.done(f"Read {n} file{'s' if n != 1 else ''}", detail)

    # 2. Reference data -------------------------------------------------------------
    reference = None
    ref_cfg = config.get("reference") or {}
    if inputs.reference:
        progress.start(f"Matching {noun}s to the {ref_cfg.get('label', 'reference list')}…")
        try:
            reference = read_table(*inputs.reference)
            reference.columns = [c.strip() for c in reference.columns]
            if spec.key not in reference:
                raise DataFileError(f"“{inputs.reference[0]}” has no {spec.key} column.")
            for col in reference.columns:
                if col != spec.key:
                    converted = pd.to_numeric(reference[col], errors="coerce")
                    if converted.notna().sum() == reference[col].notna().sum():
                        reference[col] = converted
            known = set(reference[spec.key].astype(str).str.strip())
            matched = sum(1 for k in data[spec.key].dropna().astype(str).str.strip().unique() if k in known)
            unknown = n_keys - matched
            label = f"Matched {matched} of {n_keys} {noun}s to the {ref_cfg.get('label', 'reference list')}"
            (progress.warn if unknown else progress.done)(label, f"{unknown} not recognised" if unknown else "")
        except DataFileError as exc:
            reference = None
            warnings.append(str(exc))
            progress.warn(f"Could not use the {ref_cfg.get('label', 'reference list')}", str(exc))

    # 3. Validation -----------------------------------------------------------------
    rules = config.get("rules", [])
    progress.start(f"Checking {len(data):,} readings against {len(rules) + 1} rules…")
    result = validate(data, spec, rules, reference=reference, parse_issues=parse_issues,
                      parse_rule=config.get("parse_errors"))
    exc = result.exceptions
    row_types = {"missing", "duplicates", "range", "unreadable", "reference"}
    row_level = [f for f in result.findings if f.rule_type in row_types]
    series_level = [f for f in result.findings if f.rule_type not in row_types]
    progress.done(f"Checked every reading for missing, duplicate, unreadable and impossible values",
                  f"{len(row_level)} found")
    progress.done(f"Checked each {noun} for spikes, flat-lines, gaps and register mismatches",
                  f"{len(series_level)} found")
    n_high = int((exc["Severity"] == "High").sum()) if not exc.empty else 0
    n_check = int((exc["Needs human check"] == "Yes").sum()) if not exc.empty else 0
    (progress.warn if len(exc) else progress.done)(
        f"Found {len(exc)} exception{'s' if len(exc) != 1 else ''}",
        f"{n_high} high severity, {n_check} need a human check" if len(exc) else "all clear")

    # 4. Totals ---------------------------------------------------------------------
    progress.start("Calculating validated monthly totals…")
    label_cols = list(spec.display_columns.keys())
    by_key, by_cat = period_totals(result, spec, label_columns=label_cols, reference=reference)
    by_key = by_key.rename(columns=spec.display_columns)
    by_cat = by_cat.rename(columns=spec.display_columns)
    held = int(result.data["_held"].sum())
    total_col = next((c for c in by_key.columns if c.startswith("Total validated")), None)
    grand_total = float(by_key[total_col].sum()) if total_col else 0.0
    progress.done(f"Validated totals for {period_label(result.period_start, result.period_end)}",
                  f"{_fmt_energy(grand_total, spec.unit)} validated, {held:,} readings held for review")

    # 5. Deadlines ------------------------------------------------------------------
    tracker = pd.DataFrame()
    if inputs.calendar:
        progress.start("Checking reporting deadlines…")
        try:
            calendar = read_table(*inputs.calendar)
            category_heading = spec.display_columns.get(spec.category_column) if spec.category_column else None
            tracker = build_tracker(calendar, as_of=inputs.as_of, exceptions=exc, category_heading=category_heading)
            at_risk = int((tracker["RAG"] != "Green").sum()) if not tracker.empty else 0
            (progress.warn if at_risk else progress.done)(
                f"Checked {len(tracker)} reporting deadlines (as at {inputs.as_of:%d %b %Y})",
                f"{at_risk} at risk" if at_risk else "all on track")
        except DataFileError as exc_cal:
            warnings.append(str(exc_cal))
            progress.warn("Could not read the reporting calendar", str(exc_cal))

    # 6. Claude: notes + summary ------------------------------------------------------
    facts = build_facts(result, spec, by_cat, tracker, files_read, inputs, total_col)
    ai_cfg = config.get("ai") or {}
    payloads = ai.exception_payloads(exc, result.findings, spec.key_label, list(spec.display_columns.values()))
    source_word = "pre-recorded AI text (mock mode)" if client.mock else f"Claude ({client.model})"
    progress.start(f"Drafting {len(payloads)} discrepancy notes and the manager summary with {source_word}…")
    notes, summary, calls = ai.draft_notes_and_summary(
        client, payloads, facts, domain=ai_cfg.get("domain", ""), audience=ai_cfg.get("audience", "an operations team"),
        chunk_size=int(ai_cfg.get("notes_per_request", 6)),
        on_batch_done=lambda d, t: progress.update(f"Drafting discrepancy notes with {source_word}… ({d}/{t} batches)"),
    )
    sources = {}
    for c in calls:
        sources[c.source] = sources.get(c.source, 0) + 1
    ai_warnings = [c.warning for c in calls if c.warning]
    if ai_warnings:  # one message, not one per batch
        more = f" ({len(ai_warnings)} of {len(calls)} AI requests affected; template text used.)" if len(ai_warnings) > 1 else ""
        warnings.append(ai_warnings[0] + more)
    ai_ok = all(c.from_ai for c in calls)
    timing = max((c.seconds for c in calls), default=0)
    (progress.done if ai_ok else progress.warn)(
        f"Drafted {len(notes)} discrepancy notes and the manager summary",
        _source_phrase(sources, client) + (f", {timing:.1f}s" if sources.get("api") else ""))
    exc = reports.attach_notes(exc, notes)
    summary_source = _summary_source(calls[-1], client)

    # 7. Human checks + time estimate ------------------------------------------------
    human = human_check_items(exc, spec)
    if not ai_ok:
        human.append(CheckItem(id="AI", title="Some notes were written from templates",
                               why="Claude was not available for every note, so template wording was used. "
                                   "The findings are unaffected; the wording should be reviewed.",
                               action="Re-run with an API key, or edit the notes in the Word file.", severity="info"))
    est = time_saved(config, facts, len(exc), len([e for e in human if e.id != "AI"]))

    # 8. Files ---------------------------------------------------------------------
    progress.start("Building the report pack…")
    run_result = RunResult(
        config=config, spec=spec, inputs_label=inputs.label, as_of=inputs.as_of, files_read=files_read,
        file_errors=file_errors, validation=result, exceptions=exc, totals_by_key=by_key, totals_by_category=by_cat,
        tracker=tracker, summary=summary, summary_source=summary_source, facts=facts, human_checks=human,
        time_estimate=est, warnings=warnings, ai_sources=sources,
    )
    run_result.downloads = reports.build_downloads(run_result)
    progress.done(f"Built the report pack", ", ".join(f.file_name.rsplit(".", 1)[-1].upper() for f in run_result.downloads))
    run_result.seconds = round(time.perf_counter() - started, 2)
    return run_result

# ---------------------------------------------------------------------- helpers


def _fmt_energy(value: float, unit: str) -> str:
    if unit.lower() == "kwh" and abs(value) >= 10_000:
        return f"{value / 1000:,.0f} MWh" if abs(value) < 10_000_000 else f"{value / 1e6:,.2f} GWh"
    return f"{value:,.0f} {unit}".strip()


def _source_phrase(sources: dict, client: ClaudeClient) -> str:
    labels = {"api": "written by Claude", "cache": "from cache", "fixture": "pre-recorded AI text (mock mode)",
              "mock": "template text (mock mode)", "fallback": "template text (Claude unavailable)"}
    return ", ".join(f"{labels.get(k, k)} ×{v}" if v > 1 else labels.get(k, k) for k, v in sources.items())


def _summary_source(call, client: ClaudeClient) -> str:
    return {
        "api": f"Written by Claude ({call.model}) from the validated figures.",
        "cache": "Written by Claude from the validated figures (cached).",
        "fixture": "Pre-recorded AI text for the sample data (mock mode: no API key set, no network calls).",
        "mock": "Template summary (mock mode: no recorded Claude response for these files).",
        "fallback": "Template summary (Claude unavailable).",
    }.get(call.source, "")


def build_facts(result: ValidationResult, spec: DatasetSpec, by_cat: pd.DataFrame, tracker: pd.DataFrame,
                files_read: list[str], inputs: RunInputs, total_col: str | None) -> dict:
    exc = result.exceptions
    data = result.data
    flagged_rows = int((data["_exception_ids"] != "").sum())
    readings = len(data)
    facts = {
        "period": (f"{result.period_start:%d %b %Y} to {result.period_end:%d %b %Y}"
                   if result.period_start is not None else "unknown"),
        "as_of": f"{inputs.as_of:%d %b %Y}",
        "files": len(files_read),
        "readings_checked": readings,
        "records": int(data[spec.key].nunique()),
        "record_noun": spec.key_label.lower(),
        "pass_rate_pct": round(100 * (readings - flagged_rows) / readings, 1) if readings else 0.0,
        "exceptions": len(exc),
        "by_severity": exc["Severity"].value_counts().to_dict() if not exc.empty else {},
        "needs_human_check": int((exc["Needs human check"] == "Yes").sum()) if not exc.empty else 0,
        "readings_held_from_totals": int(data["_held"].sum()),
    }
    if not by_cat.empty and total_col and total_col in by_cat:
        cat = spec.display_columns.get(spec.category_column, spec.category_column)
        facts["validated_totals"] = {row[cat]: _fmt_energy(row[total_col], spec.unit)
                                     for _, row in by_cat.iterrows() if row[total_col]}
    if not tracker.empty:
        risky = tracker[(tracker["RAG"] != "Green")]
        facts["deadlines_at_risk"] = [
            {"obligation": r["Obligation"], "due": r["Due"], "status": r["Status"], "readiness": r["Data readiness"]}
            for _, r in risky.iterrows()]
    if not exc.empty:
        top = exc[exc["Severity"] == "High"]
        facts["high_severity"] = [
            {"id": r["ID"], "check": r["Check"], spec.key_label.lower(): r[spec.key_label],
             **{h.lower(): r[h] for h in spec.display_columns.values() if h in r}, "dates": r["Date(s)"]}
            for _, r in top.iterrows()]
    return facts


def human_check_items(exc: pd.DataFrame, spec: DatasetSpec) -> list[CheckItem]:
    items = []
    if exc.empty:
        return items
    site_heading = next(iter(spec.display_columns.values()), None)
    for _, r in exc[exc["Needs human check"] == "Yes"].iterrows():
        where = r.get(site_heading, "") if site_heading else ""
        title = f"{r['Check']} — {where + ' · ' if where else ''}{r[spec.key_label]}" + (f" · {r['Date(s)']}" if r["Date(s)"] else "")
        items.append(CheckItem(id=r["ID"], title=title, why=r.get("Note") or r["Finding"],
                               action=r.get("Suggested action", ""), severity=str(r["Severity"]).lower()))
    return items


def time_saved(config: dict, facts: dict, n_exceptions: int, n_checks: int) -> TimeEstimate:
    cfg = config.get("time_estimate") or {}
    months = max(len(pd.period_range(*_period_bounds(facts), freq="M")), 1) if " to " in facts.get("period", "") else 1
    counts = {"meter_months": facts.get("records", 0) * months, "records": facts.get("records", 0),
              "exceptions": n_exceptions, "human_checks": n_checks, "fixed": 1,
              "readings": facts.get("readings_checked", 0)}

    def expand(rows):
        return [(label, counts.get(what, 0), float(minutes)) for label, what, minutes in rows]

    return estimate(expand(cfg.get("manual", [])), expand(cfg.get("with_tool", [])))


def _period_bounds(facts: dict):
    start, _, end = facts["period"].partition(" to ")
    return pd.Timestamp(start), pd.Timestamp(end)
