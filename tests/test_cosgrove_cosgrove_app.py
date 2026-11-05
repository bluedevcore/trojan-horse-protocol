"""Drive the real Cosgrove & Cosgrove Streamlit app headlessly (streamlit.testing)."""

import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "clients" / "cosgrove-cosgrove" / "app.py"


def test_landing_page_and_demo_run_end_to_end(monkeypatch):
    monkeypatch.setenv("DEMO_MOCK", "1")
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "QuickBooks Bookkeeping Agent: built as a prototype for Cosgrove &amp; Cosgrove Ltd" in page
    assert "Mock mode" in page
    assert at.button[0].label.endswith("Run demo with sample data")

    started = time.perf_counter()
    at.button[0].click().run()
    assert time.perf_counter() - started < 60
    assert not at.exception and not at.error
    page = " ".join(m.value for m in at.markdown)
    for text in ("Read 28 documents and 6 spreadsheets", "Found 17 exceptions", "Needs human check (12)", "Downloads",
                 "Purchases ready for QuickBooks", "Supplier bank details changed"):
        assert text in page, text
    assert [t.label for t in at.tabs] == ["Coded entries (34)", "Card matching", "Payroll journal", "Sales invoices",
                                          "Emails (8)", "Month-end checklist", "Exceptions (17)", "Documents read (28)"]
    assert len(at.checkbox) == 12

    # Ticking a review box re-runs the script; results must survive the rerun
    at.checkbox[0].check().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Needs human check (12)" in page and "1 of 12 reviewed" in " ".join(c.value for c in at.caption)
