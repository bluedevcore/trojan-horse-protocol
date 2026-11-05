"""Timesheet-to-Payroll Agent — prototype demo for Complete Fixing Solutions.

Run locally:      streamlit run clients/complete-fixing-solutions/app.py
Streamlit Cloud:  main file path = clients/complete-fixing-solutions/app.py

Everything client-specific is in config.yaml and sample_data/; the app itself
is the generic bookkeeping tool (timesheets, purchase orders, Sage 50).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:  # make core/ and tools/ importable on Streamlit Cloud
    sys.path.insert(0, str(ROOT))

from tools.bookkeeping.views import run_app  # noqa: E402

run_app(HERE)
