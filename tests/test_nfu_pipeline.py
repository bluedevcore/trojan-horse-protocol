"""End-to-end: the NFU Energy demo on its sample data, in mock mode."""

import io
import time
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from core.claude import ClaudeClient
from core.ui import StepProgress
from tools.data_validation import pipeline
from tools.data_validation.pipeline import PipelineError, RunInputs
from tools.data_validation.views import load_config

CLIENT = Path(__file__).resolve().parent.parent / "clients" / "nfu-energy"

# (check, meter) for each problem planted by sample_data/generate.py
EXPECTED = {
    ("Missing reading", "E21UK00314"), ("Missing reading", "G15PV02790"),
    ("Impossible value", "E15UK09184"), ("Impossible value", "G13PV00845"),
    ("Duplicate reading", "E19UK03391"), ("Duplicate reading", "E18UK06673"),
    ("Sudden spike", "E20UK04419"), ("Sudden spike", "HM-2017-0951"),
    ("Missing days", "E16UK07720"), ("Missing days", "HM-2018-0203"), ("Missing days", "HM-2015-0177"),
    ("Unreadable value", "HM-2015-0177"), ("Zero generation run", "G16PV00412"),
    ("Meter not in site register", "E17UP04521"), ("Register mismatch", "E17UK05562"),
}


@pytest.fixture(scope="module")
def config():
    return load_config(CLIENT)


@pytest.fixture(scope="module")
def result(config):
    client = ClaudeClient(fixtures_dir=CLIENT / "fixtures", mock=True)
    progress = StepProgress()
    started = time.perf_counter()
    res = pipeline.run(pipeline.sample_inputs(CLIENT, config), config, client, progress)
    res.test_seconds = time.perf_counter() - started
    res.test_steps = progress.steps
    return res


def test_runs_well_under_a_minute(result):
    assert result.test_seconds < 20


def test_finds_exactly_the_planted_problems(result):
    exc = result.exceptions
    assert set(zip(exc["Check"], exc["Meter"])) == EXPECTED
    assert len(exc) == 15
    assert list(exc["ID"]) == [f"EX-{i:02d}" for i in range(1, 16)]


def test_human_check_list(result):
    assert result.facts["needs_human_check"] == 9
    assert [c.id for c in result.human_checks] == ["EX-01", "EX-03", "EX-04", "EX-05", "EX-06", "EX-08", "EX-09", "EX-12", "EX-14"]
    assert all(c.why and c.action for c in result.human_checks)


def test_mock_mode_replays_recorded_fixtures(result):
    """If this fails, prompts/rules/data changed: run
    python -m tools.data_validation.refresh_fixtures clients/nfu-energy"""
    assert result.ai_sources == {"fixture": 4}
    assert (result.exceptions["Note source"] == "Pre-recorded (mock mode)").all()
    assert "EX-05" in result.summary and "Pre-recorded" in result.summary_source
    assert result.exceptions.set_index("ID").loc["EX-12", "Note"].count("01 Oct") >= 1


def test_totals_match_an_independent_sum(result):
    data = result.validation.data
    ok = data[data["read_date"].notna() & data["kwh"].notna() & ~data["_held"]]
    ok = ok.drop_duplicates(subset=["meter_serial", "read_date"])  # identical duplicate counted once
    expected = round(ok["kwh"].sum(), 0)
    got = round(result.totals_by_key["Total validated (kWh)"].sum(), 0)
    assert got == expected
    by_type = result.totals_by_category.set_index("meter_type")
    assert by_type.loc["Solar PV generation", "Meters"] == 7
    assert by_type.loc["Biomass heat", "Meters"] == 5


def test_totals_status_per_meter(result):
    t = result.totals_by_key.set_index("Meter")
    assert t.loc["E17UP04512", "Status"] == "No data"  # registered meter whose readings had the wrong serial
    assert t.loc["E16UK07720", "Status"] == "Incomplete" and t.loc["E16UK07720", "Valid days"] == "85/92"
    assert t.loc["G13PV00845", "Status"] == "Held for review"
    assert t.loc["G16PV00412", "Status"] == "Check flags"
    assert t.loc["E19UK08231", "Status"] == "Complete"


def test_deadline_tracker(result):
    t = result.tracker.set_index("Obligation")
    fit = t.loc["FIT generation meter readings to FIT licensees"]
    assert fit["Status"] == "Due in 5 days" and fit["RAG"] == "Red"
    assert fit["_blocking"] == ["EX-05", "EX-06"]
    assert t.loc["Supplier consumption & bill validation report — September", "Status"].startswith("Submitted")
    assert t.loc["Supplier consumption & bill validation report — October", "_blocking"] == ["EX-04", "EX-08"]


def test_progress_steps_tell_the_story(result):
    labels = [s.label for s in result.test_steps]
    assert labels[0] == "Read 3 files"
    assert any(l.startswith("Found 15 exceptions") for l in labels)
    assert any("discrepancy notes" in l for l in labels)
    assert all(s.status != "running" for s in result.test_steps)


def test_every_output_file_is_valid(result):
    files = {f.file_name.rsplit(".", 1)[1]: f for f in result.downloads}
    assert set(files) == {"xlsx", "pdf", "docx", "csv"}
    wb = load_workbook(io.BytesIO(files["xlsx"].data))
    assert wb.sheetnames == ["Summary", "Exceptions", "Needs human check", "Monthly totals", "Totals by type",
                             "Deadline tracker", "Validated data", "Rules applied"]
    assert wb["Exceptions"].max_row == 16 and wb["Validated data"].max_row == 2194
    assert not any(str(c.value).startswith("_") for c in wb["Exceptions"][1])  # no internal columns leak
    assert files["pdf"].data.startswith(b"%PDF")
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(files["docx"].data)).namelist()
    csv = pd.read_csv(io.BytesIO(files["csv"].data), encoding="utf-8-sig")
    assert len(csv) == 15 and "Note" in csv.columns


def test_time_saved_is_positive_and_explained(result):
    est = result.time_estimate
    assert est.saved_minutes > 60 and len(est.assumptions) == 5


# ----------------------------------------------------------- unhappy paths


def _run(config, readings, **kw):
    return pipeline.run(RunInputs(readings=readings, **kw), config, ClaudeClient(mock=True))


def test_no_files_is_a_friendly_error(config):
    with pytest.raises(PipelineError, match="No files to check"):
        _run(config, [])


def test_only_bad_files_is_a_friendly_error(config):
    with pytest.raises(PipelineError, match="None of the files could be read"):
        _run(config, [("empty.csv", b""), ("photo.png", b"\x89PNG")])


def test_wrong_columns_are_explained(config):
    with pytest.raises(PipelineError, match="missing required column"):
        _run(config, [("other.csv", b"Name,Amount\nA,1\n")])


def test_upload_without_register_or_calendar_still_works(config):
    data = (CLIENT / "sample_data" / "electricity_import_daily_aug-oct-2026.csv").read_bytes()
    res = _run(config, [("export.csv", data), ("junk.txt", b"")])
    assert res.file_errors and res.tracker.empty
    assert len(res.exceptions) > 0 and res.downloads
    assert set(res.ai_sources) == {"mock"}  # template text, no network


def test_missing_sample_folder_is_a_friendly_error(config, tmp_path):
    with pytest.raises(PipelineError, match="sample data files could not be found"):
        pipeline.sample_inputs(tmp_path, config)
