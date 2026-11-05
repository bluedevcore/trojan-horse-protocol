"""Streamlit screens for the data-validation tool (generic, no client names).

A client's ``app.py`` only needs:

    from tools.data_validation.views import run_app
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
from tools.data_validation import pipeline
from tools.data_validation.pipeline import PipelineError, RunInputs, RunResult
from tools.data_validation.reports import public

RESULT_KEY, STEPS_KEY = "dv_result", "dv_steps"


def load_config(client_dir: Path) -> dict:
    return yaml.safe_load((client_dir / "config.yaml").read_text(encoding="utf-8"))


def run_app(client_dir: Path) -> None:
    client_dir = Path(client_dir)
    try:
        config = load_config(client_dir)
    except (OSError, yaml.YAMLError) as exc:
        st.set_page_config(page_title="Configuration error")
        ui.friendly_error(f"This demo's config.yaml could not be read ({exc}).")
        return

    client = ClaudeClient(fixtures_dir=client_dir / "fixtures")
    ui.page_shell(page_title=config.get("tool_name", "Data checker"), headline=config["headline"],
                  replaces=config.get("replaces", ""), mock=client.mock, mode_label=client.mode_label,
                  badges=config.get("badges"))

    run_demo, upload_inputs = _landing(config)
    progress_area = st.container()
    inputs = None
    if run_demo:
        try:
            inputs = pipeline.sample_inputs(client_dir, config)
        except PipelineError as exc:
            ui.friendly_error(str(exc))
    elif upload_inputs is not None:
        inputs = upload_inputs

    if inputs is not None:
        st.session_state.pop(RESULT_KEY, None)
        progress = ui.StepProgress(progress_area, delay=float(config.get("step_delay_seconds", 0) or 0))
        try:
            result = pipeline.run(inputs, config, client, progress)
        except PipelineError as exc:
            ui.friendly_error(str(exc), "Check the file and try again, or run the demo with sample data.")
            return
        except Exception as exc:  # last-resort guard: never show a stack trace to a prospect
            progress.fail("Something went wrong", type(exc).__name__)
            ui.friendly_error("Sorry, the check could not finish on these files.",
                              f"Technical detail: {type(exc).__name__}: {exc}")
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


def _landing(config: dict) -> tuple[bool, RunInputs | None]:
    left, right = st.columns([0.42, 0.58], vertical_alignment="top")
    with left:
        run_demo = st.button("▶  Run demo with sample data", type="primary", width="stretch")
        sample = config.get("sample_data", {})
        n = len(sample.get("readings", []))
        st.caption(f"Uses {n} synthetic meter exports" + (", a site register" if sample.get("reference") else "")
                   + (" and a reporting calendar" if sample.get("calendar") else "") + ". No setup needed.")
    upload_inputs = None
    with right:
        with st.expander("…or check your own files"):
            st.caption(config.get("upload_help", "Upload CSV or Excel files."))
            readings = st.file_uploader("Data exports (CSV / Excel)", type=["csv", "xlsx", "xls", "txt"],
                                        accept_multiple_files=True, key="up_readings")
            c1, c2 = st.columns(2)
            with c1:
                reference = st.file_uploader("Reference list (optional)", type=["csv", "xlsx"], key="up_ref")
            with c2:
                calendar = st.file_uploader("Reporting calendar (optional)", type=["csv", "xlsx"], key="up_cal")
            if st.button("Check my files", disabled=not readings):
                upload_inputs = RunInputs(
                    readings=[(f.name, f.getvalue()) for f in readings],
                    reference=(reference.name, reference.getvalue()) if reference else None,
                    calendar=(calendar.name, calendar.getvalue()) if calendar else None,
                    label="uploaded files",
                )
    return run_demo, upload_inputs

# --------------------------------------------------------------------- results


def render_results(r: RunResult) -> None:
    spec, f = r.spec, r.facts
    exc = public(r.exceptions)

    ui.section("Summary", f"{r.inputs_label.capitalize()} · data period {f['period']} · as at {f['as_of']} · "
                          f"finished in {r.seconds:.1f}s")
    n_high = int(f["by_severity"].get("High", 0))
    totals = f.get("validated_totals") or {}
    total_sub = " · ".join(f"{k}: {v}" for k, v in totals.items())
    metrics = [
        ui.Metric("Readings checked", f"{f['readings_checked']:,}", f"{f['records']} {spec.key_label.lower()}s · {f['files']} files"),
        ui.Metric("Passed every check", f"{f['pass_rate_pct']}%", f"{f['readings_held_from_totals']} readings held for review"),
        ui.Metric("Exceptions", str(f["exceptions"]), f"{n_high} high severity", tone="alert" if n_high else ""),
        ui.Metric("Need a human check", str(f["needs_human_check"]), "listed below", tone="alert" if f["needs_human_check"] else "good"),
        ui.Metric("Time saved (est.)", r.time_estimate.saved_label,
                  f"{format_minutes(r.time_estimate.manual_minutes)} by hand vs {format_minutes(r.time_estimate.with_tool_minutes)}",
                  tone="good"),
    ]
    ui.summary_panel(metrics, r.summary, r.summary_source)
    if total_sub:
        st.caption(f"Validated totals ({r.period_label}): {total_sub}")
    for w in r.warnings:
        st.warning(w, icon="⚠️")

    ui.section(f"Needs human check ({len([c for c in r.human_checks if c.id != 'AI'])})",
               "Items the checker will not guess about. Tick each one once a person has reviewed it.")
    reviewed = ui.human_check_list(r.human_checks, key_prefix="dv")
    if r.human_checks:
        st.caption(f"{reviewed} of {len(r.human_checks)} reviewed")

    ui.section("Detailed results")
    tabs = st.tabs([f"Exceptions & notes ({len(exc)})", "Deadline tracker", "Monthly totals", "Validated data"])
    with tabs[0]:
        _exceptions_tab(exc, spec)
    with tabs[1]:
        _tracker_tab(r)
    with tabs[2]:
        _totals_tab(r)
    with tabs[3]:
        _data_tab(r)

    ui.section("Downloads", "Every output from this run.")
    ui.download_buttons(r.downloads)
    with st.expander("How the time-saved estimate is worked out"):
        for line in r.time_estimate.assumptions:
            st.markdown(f"- {line}")
        st.caption("Assumptions are set in the client's config.yaml and can be changed to match real timings.")


def _exceptions_tab(exc: pd.DataFrame, spec) -> None:
    if exc.empty:
        st.success("No exceptions found.")
        return
    cols = ["ID", "Severity", "Check", spec.key_label, *spec.display_columns.values(), "Date(s)", "Value",
            "Needs human check"]
    st.dataframe(exc[[c for c in cols if c in exc]], hide_index=True, width="stretch",
                 column_config={"ID": st.column_config.TextColumn(width="small"),
                                "Severity": st.column_config.TextColumn(width="small"),
                                "Needs human check": st.column_config.TextColumn("Human check", width="small")})
    st.markdown("**Discrepancy notes**")
    for _, e in exc.iterrows():
        where = " · ".join(str(e[h]) for h in spec.display_columns.values() if h in e and e[h])
        with st.expander(f"{e['ID']} · {e['Severity']} · {e['Check']} · {where or e[spec.key_label]} · {e['Date(s)']}"):
            st.markdown(f"**Finding** — {e['Finding']}")
            if e.get("Note"):
                st.markdown(f"**Note** — {e['Note']}")
                st.markdown(f"**Likely cause** — {e['Likely cause']}")
                st.markdown(f"**Suggested action** — {e['Suggested action']}")
            st.caption(f"{spec.key_label} {e[spec.key_label]} · source: {e['Source']} · note drafted by: {e.get('Note source', '')}")


def _tracker_tab(r: RunResult) -> None:
    tracker = public(r.tracker)
    if tracker.empty:
        st.info("No reporting calendar was provided, so there is no deadline tracker for this run.")
        return
    colours = {"Red": "background-color:#FDE8E7;color:#8A1C12", "Amber": "background-color:#FFF4E0;color:#7A4A00",
               "Green": "background-color:#E8F6EE;color:#0F5A34"}
    styled = tracker.style.map(lambda v: colours.get(v, ""), subset=["RAG"])
    st.dataframe(styled, hide_index=True, width="stretch")
    st.caption(f"As at {r.facts['as_of']}. “Blocked” means open exceptions affect data that report depends on "
               "(same data type and period). Deadlines in the sample are illustrative.")


def _totals_tab(r: RunResult) -> None:
    if not r.totals_by_category.empty:
        st.markdown("**By type**")
        st.dataframe(r.totals_by_category, hide_index=True, width="stretch")
    st.markdown(f"**By {r.spec.key_label.lower()}**")
    st.dataframe(r.totals_by_key, hide_index=True, width="stretch", height=420)
    st.caption("Validated totals exclude readings held for review. 'Valid days' counts days with a usable reading.")


def _data_tab(r: RunResult) -> None:
    from tools.data_validation.reports import validated_data_frame

    data = validated_data_frame(r)
    only_flagged = st.toggle("Show flagged readings only", value=True)
    if only_flagged:
        data = data[data["Status"] != "OK"]
    st.dataframe(data, hide_index=True, width="stretch", height=380)
    st.caption(f"{len(data):,} rows shown. The full table is in the Excel report pack.")
