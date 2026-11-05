import io

import pandas as pd
from openpyxl import load_workbook

from core import downloads as dl
from core.estimates import estimate, format_minutes


def _df():
    return pd.DataFrame({"Meter": ["A1", "B2"], "kWh": [1234.5, 99.0], "Date": pd.to_datetime(["2026-08-01", "2026-08-02"]),
                         "Note": ["short", "a much longer note " * 10]})


def test_excel_has_all_sheets():
    data = dl.excel_bytes({"Exceptions": _df(), "Totals": _df().head(1)}, wrap_columns=["Note"])
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Exceptions", "Totals"]
    assert wb["Exceptions"]["A1"].value == "Meter"
    assert wb["Exceptions"].max_row == 3


def test_sheet_names_are_sanitised():
    data = dl.excel_bytes({"Bad/name:with*chars and far too long for excel": _df()})
    assert load_workbook(io.BytesIO(data)).sheetnames[0] == "Bad-name-with-chars and far too"


def test_csv_has_bom_for_excel():
    assert dl.csv_bytes(_df()).startswith(b"\xef\xbb\xbfMeter,kWh")


def test_pdf_and_docx_render_every_block():
    blocks = [dl.heading("Summary"), dl.para("Hello & <welcome>"), dl.metrics([("Rows", 2208), ("Saved", "8 hours")]),
              dl.bullets(["one", "two"]), dl.table(_df(), max_rows=1), dl.note("small print"), dl.page_break(),
              dl.table(_df().iloc[0:0])]
    pdf = dl.pdf_bytes("Report", blocks, subtitle="sub", footer="foot")
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500
    docx = dl.docx_bytes("Report", blocks, subtitle="sub")
    assert docx[:2] == b"PK"


def test_time_estimate():
    est = estimate([("check meter-months", 72, 4), ("write notes", 15, 12)], [("review flags", 9, 5)])
    assert est.manual_minutes == 72 * 4 + 15 * 12
    assert est.with_tool_minutes == 45
    assert est.saved_label == "7.0 hours"
    assert format_minutes(45) == "45 min"
    assert len(est.assumptions) == 3
