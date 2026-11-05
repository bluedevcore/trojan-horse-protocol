import io

import pandas as pd
import pytest

from tools.data_validation.loader import DataFileError, coerce_dates, coerce_numeric, load_files, map_columns, read_table

ALIASES = {"meter_serial": ["MSN", "Meter ID"], "read_date": ["Read Date", "Date"], "kwh": ["Daily kWh", "kWh"]}
REQ = ["meter_serial", "read_date", "kwh"]


def test_numbers_with_separators_and_units():
    nums, bad = coerce_numeric(pd.Series(["1,224.8", "245 kWh", "", "abc", None, "-12.5"]))
    assert nums.tolist()[:2] == [1224.8, 245.0]
    assert nums.iloc[5] == -12.5
    assert bad.tolist() == [False, False, False, True, False, False]


def test_uk_dates_and_invalid_dates():
    dates, bad = coerce_dates(pd.Series(["01/10/2026", "31/09/2026", "2026-08-05", "", None]))
    assert dates.iloc[0] == pd.Timestamp("2026-10-01")  # day first
    assert dates.iloc[2] == pd.Timestamp("2026-08-05")
    assert bad.tolist() == [False, True, False, False, False]


def test_column_aliases_ignore_case_and_punctuation():
    df = pd.DataFrame({"msn": ["A"], "READ-DATE": ["2026-08-01"], "Daily kWh": ["1"], "Extra": [1]})
    out = map_columns(df, ALIASES, REQ, "f.csv")
    assert list(out.columns) == ["meter_serial", "read_date", "kwh"]


def test_missing_required_column_is_friendly():
    with pytest.raises(DataFileError, match="missing required column"):
        map_columns(pd.DataFrame({"MSN": ["A"], "Date": ["x"]}), ALIASES, REQ, "f.csv")


@pytest.mark.parametrize("name,data,msg", [
    ("empty.csv", b"", "is empty"),
    ("notes.pdf", b"%PDF-1.4", "Please upload CSV or Excel"),
    ("broken.xlsx", b"this is not a spreadsheet", "could not be read"),
    ("header_only.csv", b"MSN,Date,kWh\n", "no data rows"),
])
def test_bad_files_raise_friendly_errors(name, data, msg):
    with pytest.raises(DataFileError, match=msg):
        read_table(name, data)


def test_load_files_skips_bad_file_and_keeps_good_one():
    good = b"MSN,Read Date,Daily kWh\nA1,2026-08-01,10\nA1,31/09/2026,12\n"
    data, issues, errors = load_files([("good.csv", good), ("bad.csv", b"")], aliases=ALIASES, required=REQ,
                                      numeric=["kwh"], dates=["read_date"])
    assert len(data) == 2 and len(errors) == 1 and "bad.csv" in errors[0]
    assert len(issues) == 1 and issues[0].raw_value == "31/09/2026" and issues[0].row == 3
    assert issues[0].rid == data.loc[data["_row"] == 3, "_rid"].iloc[0]


def test_excel_upload_is_read():
    buf = io.BytesIO()
    pd.DataFrame({"Meter ID": ["X"], "Date": [pd.Timestamp("2026-08-01")], "kWh": [5.5]}).to_excel(buf, index=False)
    data, issues, errors = load_files([("x.xlsx", buf.getvalue())], aliases=ALIASES, required=REQ,
                                      numeric=["kwh"], dates=["read_date"])
    assert not errors and not issues
    assert data["read_date"].iloc[0] == pd.Timestamp("2026-08-01") and data["kwh"].iloc[0] == 5.5
