"""Drive the real Complete Fixing Solutions Streamlit app headlessly (streamlit.testing)."""

import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "clients" / "complete-fixing-solutions" / "app.py"


def test_landing_page_and_demo_run_end_to_end(monkeypatch):
    monkeypatch.setenv("DEMO_MOCK", "1")
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Timesheet-to-Payroll Agent: built as a prototype for Complete Fixing Solutions" in page
    assert "Mock mode" in page
    assert at.button[0].label.endswith("Run demo with sample data")

    started = time.perf_counter()
    at.button[0].click().run()
    assert time.perf_counter() - started < 60
    assert not at.exception and not at.error
    page = " ".join(m.value for m in at.markdown)
    for text in ("Read 18 documents and 6 spreadsheets", "Summarised hours for 18 employees", "Found 18 exceptions",
                 "Needs human check (15)", "Hours ready for payroll", "636.5", "Purchases ready for Sage",
                 "Overlapping timesheet lines", "Supplier bank details changed", "Downloads"):
        assert text in page, text
    assert [t.label for t in at.tabs] == ["Hours for payroll", "PO matching", "Coded entries (17)", "Emails (7)",
                                          "Month-end checklist", "Exceptions (18)", "Documents read (18)"]
    assert len(at.checkbox) == 15

    # Ticking a review box re-runs the script; results must survive the rerun
    at.checkbox[0].check().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Needs human check (15)" in page and "1 of 15 reviewed" in " ".join(c.value for c in at.caption)
