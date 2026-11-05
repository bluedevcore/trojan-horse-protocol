"""Read CSV / Excel files into one tidy table, with friendly errors.

* Column names are matched to canonical names via configurable aliases
  (case, spaces and punctuation are ignored).
* Numbers like ``"1,224.8"`` or ``"245 kWh"`` are coerced; dates are parsed
  UK-style (day first). Anything that cannot be parsed is kept as a
  ``ParseIssue`` so it shows up as an exception instead of silently vanishing.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class DataFileError(Exception):
    """A problem with an input file, phrased for a non-technical user."""


@dataclass
class ParseIssue:
    source: str
    row: int  # row number as seen in the file (header = row 1)
    column: str
    raw_value: str
    kind: str  # "date" | "number"
    rid: int | None = None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def read_table(name: str, data: bytes) -> pd.DataFrame:
    """Read one uploaded file (CSV or Excel) into a DataFrame of strings/values."""
    suffix = Path(name).suffix.lower()
    if not data:
        raise DataFileError(f"“{name}” is empty.")
    try:
        if suffix in (".csv", ".txt"):
            df = _read_csv(data)
        elif suffix in (".xlsx", ".xlsm", ".xls"):
            df = pd.read_excel(io.BytesIO(data), sheet_name=0)
        else:
            raise DataFileError(f"“{name}” is a {suffix or 'file'} file. Please upload CSV or Excel (.xlsx) files.")
    except DataFileError:
        raise
    except Exception as exc:  # pandas/openpyxl raise many different types
        raise DataFileError(f"“{name}” could not be read as a {suffix.lstrip('.').upper()} table ({type(exc).__name__}).") from exc
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty or len(df.columns) < 2:
        raise DataFileError(f"“{name}” has no data rows.")
    return df


def _read_csv(data: bytes) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, skipinitialspace=True)


def map_columns(df: pd.DataFrame, aliases: dict[str, list[str]], required: list[str], source: str) -> pd.DataFrame:
    """Rename columns to canonical names using ``aliases``."""
    lookup = {}
    for canonical, names in aliases.items():
        for alias in [canonical, *names]:
            lookup.setdefault(_norm(alias), canonical)
    renamed, seen = {}, set()
    for col in df.columns:
        canonical = lookup.get(_norm(col))
        if canonical and canonical not in seen:
            renamed[col] = canonical
            seen.add(canonical)
    missing = [c for c in required if c not in seen]
    if missing:
        wanted = "; ".join(f"{c} (e.g. {', '.join(aliases.get(c, [c])[:3])})" for c in missing)
        raise DataFileError(f"“{source}” is missing required column(s): {wanted}. Found: {', '.join(df.columns)}.")
    return df.rename(columns=renamed)[[*renamed.values()]]


_NUM_CLEAN = re.compile(r"[,\s£]|kwh|kw|mwh", re.IGNORECASE)


def coerce_numeric(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Returns (numbers, bad_mask) where bad_mask marks non-empty unparseable cells."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float), pd.Series(False, index=series.index)
    raw = _as_text(series)
    cleaned = raw.str.replace(_NUM_CLEAN, "", regex=True)
    numbers = pd.to_numeric(cleaned.where(cleaned != "", None), errors="coerce").astype(float)
    blank = raw.str.lower().isin(["", "nan", "none", "null", "-", "n/a"])
    return numbers, numbers.isna() & ~blank


def coerce_dates(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series).dt.normalize(), pd.Series(False, index=series.index)
    raw = _as_text(series)
    iso = raw.str.match(r"^\d{4}-\d{2}-\d{2}")
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if iso.any():
        parsed[iso] = pd.to_datetime(raw[iso].str[:10], format="%Y-%m-%d", errors="coerce")
    other = ~iso & (raw != "")
    if other.any():
        parsed[other] = pd.to_datetime(raw[other], dayfirst=True, errors="coerce", format="mixed")
    return parsed.dt.normalize(), parsed.isna() & (raw != "")


def _as_text(series: pd.Series) -> pd.Series:
    """Plain stripped strings, with blanks/NaN/NA as "" (no nullable-NA surprises)."""
    return pd.Series([("" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip())
                      for v in series], index=series.index, dtype=object).astype(str)


def load_files(
    files: list[tuple[str, bytes]],
    *,
    aliases: dict[str, list[str]],
    required: list[str],
    numeric: list[str],
    dates: list[str],
) -> tuple[pd.DataFrame, list[ParseIssue], list[str]]:
    """Load and combine files. Returns (data, parse_issues, per-file errors).

    A bad file does not stop the others: its error is returned for display.
    """
    frames, issues, errors = [], [], []
    for name, data in files:
        try:
            df = map_columns(read_table(name, data), aliases, required, name)
        except DataFileError as exc:
            errors.append(str(exc))
            continue
        df = df.reset_index(drop=True)
        df["_source"] = name
        df["_row"] = df.index + 2  # +1 header, +1 to be 1-based
        for col in numeric:
            if col in df:
                raw = df[col].copy()
                df[col], bad = coerce_numeric(df[col])
                issues += [ParseIssue(name, int(r), col, str(v), "number") for r, v in zip(df.loc[bad, "_row"], raw[bad])]
        for col in dates:
            if col in df:
                raw = df[col].copy()
                df[col], bad = coerce_dates(df[col])
                issues += [ParseIssue(name, int(r), col, str(v), "date") for r, v in zip(df.loc[bad, "_row"], raw[bad])]
        frames.append(df)
    if not frames:
        return pd.DataFrame(), issues, errors
    combined = pd.concat(frames, ignore_index=True)
    combined.insert(0, "_rid", range(len(combined)))
    # Attach the combined row id to each parse issue
    rid_lookup = {(s, r): rid for rid, s, r in combined[["_rid", "_source", "_row"]].itertuples(index=False)}
    for issue in issues:
        issue.rid = rid_lookup.get((issue.source, issue.row))
    return combined, issues, errors

