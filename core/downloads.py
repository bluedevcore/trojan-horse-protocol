"""Turn results into downloadable files (bytes), ready for ``st.download_button``.

Documents (PDF / Word) are described with a tiny block model so tools don't
need to know reportlab or python-docx:

    blocks = [heading("Summary"), para("..."), metrics([("Rows", "2,208")]),
              table(df), bullets(["...", "..."]), note("Small print")]
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

# ---------------------------------------------------------------- block model


def heading(text: str, level: int = 1) -> dict:
    return {"kind": "heading", "text": text, "level": level}


def para(text: str) -> dict:
    return {"kind": "para", "text": text}


def bullets(items: Iterable[str]) -> dict:
    return {"kind": "bullets", "items": [str(i) for i in items]}


def table(df: pd.DataFrame, *, max_rows: int | None = None, widths: list[float] | None = None) -> dict:
    """``widths`` are relative column weights (e.g. ``[1, 3, 1]``)."""
    return {"kind": "table", "df": df if max_rows is None else df.head(max_rows), "widths": widths,
            "truncated": max_rows is not None and len(df) > max_rows, "total_rows": len(df)}


def metrics(pairs: Iterable[tuple[str, Any]]) -> dict:
    return {"kind": "metrics", "pairs": [(str(k), _fmt(v)) for k, v in pairs]}


def note(text: str) -> dict:
    return {"kind": "note", "text": text}


def page_break() -> dict:
    return {"kind": "page_break"}


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%d %b %Y")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.1f}" if abs(value) < 1e15 else str(value)
    return str(value)


def _display_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.apply(lambda col: col.map(_fmt)) if not df.empty else df

# ---------------------------------------------------------------- CSV / Excel


def csv_bytes(df: pd.DataFrame) -> bytes:
    """UTF-8 with BOM so Excel opens it with the right encoding."""
    return df.to_csv(index=False).encode("utf-8-sig")


def excel_bytes(sheets: dict[str, pd.DataFrame], *, wrap_columns: Iterable[str] = ()) -> bytes:
    """One formatted sheet per DataFrame: bold header, filters, frozen header,
    sensible column widths, long-text columns wrapped."""
    wrap = set(wrap_columns)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as writer:
        book = writer.book
        header_fmt = book.add_format({"bold": True, "bg_color": "#E8ECF1", "border": 1, "border_color": "#C9D1DB",
                                      "text_wrap": True, "valign": "top"})
        wrap_fmt = book.add_format({"text_wrap": True, "valign": "top"})
        top_fmt = book.add_format({"valign": "top"})
        for name, df in sheets.items():
            sheet_name = _safe_sheet_name(name)
            frame = df.copy()
            for col in frame.columns:  # Excel cannot store tz-aware datetimes
                if isinstance(frame[col].dtype, pd.DatetimeTZDtype):
                    frame[col] = frame[col].dt.tz_localize(None)
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
            ws = writer.sheets[sheet_name]
            for idx, col in enumerate(frame.columns):
                ws.write(0, idx, str(col), header_fmt)
                sample = [str(col)] + [str(v) for v in frame[col].head(200).tolist()]
                width = min(max(len(s) for s in sample) + 2, 60)
                if col in wrap:
                    ws.set_column(idx, idx, 60, wrap_fmt)
                else:
                    ws.set_column(idx, idx, max(width, 10), top_fmt)
            if len(frame.columns):
                ws.autofilter(0, 0, max(len(frame), 1), len(frame.columns) - 1)
            ws.freeze_panes(1, 0)
    return buffer.getvalue()


def _safe_sheet_name(name: str) -> str:
    for ch in '[]:*?/\\':
        name = name.replace(ch, "-")
    return name[:31] or "Sheet"

# ----------------------------------------------------------------------- Word


def docx_bytes(title: str, blocks: list[dict], *, subtitle: str | None = None) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10.5)
    doc.add_heading(title, level=0)
    if subtitle:
        p = doc.add_paragraph(subtitle)
        p.runs[0].font.color.rgb = RGBColor(0x5B, 0x67, 0x75)
    for block in blocks:
        kind = block["kind"]
        if kind == "heading":
            doc.add_heading(block["text"], level=min(block.get("level", 1), 3))
        elif kind == "para":
            doc.add_paragraph(block["text"])
        elif kind == "note":
            p = doc.add_paragraph(block["text"])
            for run in p.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0x5B, 0x67, 0x75)
        elif kind == "bullets":
            for item in block["items"]:
                doc.add_paragraph(item, style="List Bullet")
        elif kind == "metrics":
            tbl = doc.add_table(rows=0, cols=2)
            tbl.style = "Table Grid"
            for label, value in block["pairs"]:
                row = tbl.add_row().cells
                row[0].text, row[1].text = label, value
                row[0].paragraphs[0].runs[0].bold = True
        elif kind == "table":
            df = _display_frame(block["df"])
            tbl = doc.add_table(rows=1, cols=len(df.columns))
            tbl.style = "Table Grid"
            for cell, col in zip(tbl.rows[0].cells, df.columns):
                cell.text = str(col)
                cell.paragraphs[0].runs[0].bold = True
            for _, values in df.iterrows():
                cells = tbl.add_row().cells
                for cell, value in zip(cells, values):
                    cell.text = str(value)
            if block.get("truncated"):
                doc.add_paragraph(f"Showing {len(df)} of {block['total_rows']} rows; see the Excel pack for all rows.")
        elif kind == "page_break":
            doc.add_page_break()
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()

# ------------------------------------------------------------------------ PDF


def pdf_bytes(title: str, blocks: list[dict], *, subtitle: str | None = None, footer: str | None = None,
              landscape_pages: bool = True) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    ink, muted, rule, fill = (colors.HexColor(c) for c in ("#1F2933", "#5B6775", "#C9D1DB", "#EEF1F5"))
    base = getSampleStyleSheet()
    s_title = ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=ink,
                             alignment=TA_LEFT, spaceAfter=2)
    s_sub = ParagraphStyle("s", parent=base["Normal"], fontSize=9.5, textColor=muted, spaceAfter=8)
    s_h1 = ParagraphStyle("h1", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=ink,
                          spaceBefore=10, spaceAfter=4)
    s_h2 = ParagraphStyle("h2", parent=s_h1, fontSize=11)
    s_body = ParagraphStyle("b", parent=base["Normal"], fontSize=9.5, leading=13, textColor=ink, spaceAfter=4)
    s_note = ParagraphStyle("n", parent=s_body, fontSize=8, leading=10, textColor=muted)
    s_cell = ParagraphStyle("c", parent=s_body, fontSize=7.6, leading=9.4, spaceAfter=0)
    s_head = ParagraphStyle("hc", parent=s_cell, fontName="Helvetica-Bold")

    pagesize = landscape(A4) if landscape_pages else A4
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=pagesize, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title=title)
    usable = pagesize[0] - 28 * mm

    def esc(text: str) -> str:
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

    story: list = [Paragraph(esc(title), s_title)]
    if subtitle:
        story.append(Paragraph(esc(subtitle), s_sub))
    for block in blocks:
        kind = block["kind"]
        if kind == "heading":
            story.append(Paragraph(esc(block["text"]), s_h1 if block.get("level", 1) == 1 else s_h2))
        elif kind == "para":
            story.append(Paragraph(esc(block["text"]), s_body))
        elif kind == "note":
            story.append(Paragraph(esc(block["text"]), s_note))
        elif kind == "bullets":
            for item in block["items"]:
                story.append(Paragraph("&bull;&nbsp;" + esc(item), s_body))
        elif kind == "metrics":
            pairs = block["pairs"]
            per_row = min(len(pairs), 5) or 1
            cells, row = [], []
            for label, value in pairs:
                row.append([Paragraph(f"<font size=14><b>{esc(value)}</b></font>", s_body),
                            Paragraph(esc(label), s_note)])
                if len(row) == per_row:
                    cells.append(row)
                    row = []
            if row:
                cells.append(row + [""] * (per_row - len(row)))
            tbl = Table(cells, colWidths=[usable / per_row] * per_row)
            tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fill), ("BOX", (0, 0), (-1, -1), 0.5, rule),
                                     ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                                     ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            story += [tbl, Spacer(1, 6)]
        elif kind == "table":
            df = _display_frame(block["df"])
            if df.empty:
                story.append(Paragraph("None.", s_body))
                continue
            weights = block.get("widths") or [max(4, min(40, max(len(str(c)), *(len(str(v)) for v in df[c].head(50))))) for c in df.columns]
            total = float(sum(weights))
            col_widths = [usable * w / total for w in weights]
            data = [[Paragraph(esc(c), s_head) for c in df.columns]]
            data += [[Paragraph(esc(v), s_cell) for v in row] for row in df.itertuples(index=False)]
            tbl = Table(data, colWidths=col_widths, repeatRows=1)
            tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), fill), ("LINEBELOW", (0, 0), (-1, 0), 0.8, rule),
                                     ("LINEBELOW", (0, 1), (-1, -1), 0.3, rule), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.append(tbl)
            if block.get("truncated"):
                story.append(Paragraph(f"Showing {len(df)} of {block['total_rows']} rows; see the Excel pack for all rows.", s_note))
            story.append(Spacer(1, 6))
        elif kind == "page_break":
            story.append(PageBreak())

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        text = f"{footer}  ·  page {canvas.getPageNumber()}" if footer else f"Page {canvas.getPageNumber()}"
        canvas.drawString(14 * mm, 8 * mm, text)
        canvas.restoreState()

    doc.build([KeepTogether(story[:2])] + story[2:], onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
