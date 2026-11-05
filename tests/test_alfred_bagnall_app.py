"""Drive the real Alfred Bagnall (Debtor & Filing Agent) Streamlit app headlessly (streamlit.testing)."""

import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "clients" / "alfred-bagnall" / "app.py"


def test_landing_page_and_demo_run_end_to_end(monkeypatch):
    monkeypatch.setenv("DEMO_MOCK", "1")
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Debtor &amp; Filing Agent: built as a prototype for Alfred Bagnall &amp; Sons Limited" in page
    assert "Mock mode" in page
    assert at.button[0].label.endswith("Run demo with sample data")

    started = time.perf_counter()
    at.button[0].click().run()
    assert time.perf_counter() - started < 60
    assert not at.exception and not at.error
    page = " ".join(m.value for m in at.markdown)
    for text in ("Read 23 documents and 4 spreadsheets", "Aged 26 open invoices", "Filed 20 of 23 documents",
                 "Found 11 exceptions", "Needs human check (10)", "Filed to project folders", "Overdue",
                 "Seriously overdue", "Downloads", "Nothing is posted or sent automatically"):
        assert text in page, text
    assert "Purchases ready" not in page and "Import files are for" not in page
    assert [t.label for t in at.tabs] == ["Aged debtors", "Emails (7)", "Filing", "Month-end checklist",
                                          "Exceptions (11)", "Documents read (23)"]
    assert len(at.checkbox) == 10

    # Ticking a review box re-runs the script; results must survive the rerun
    at.checkbox[0].check().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Needs human check (10)" in page and "1 of 10 reviewed" in " ".join(c.value for c in at.caption)
