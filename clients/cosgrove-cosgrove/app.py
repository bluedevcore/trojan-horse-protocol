"""QuickBooks Bookkeeping Agent — prototype demo for Cosgrove & Cosgrove Ltd.

Run locally:      streamlit run clients/cosgrove-cosgrove/app.py
Streamlit Cloud:  main file path = clients/cosgrove-cosgrove/app.py

Everything client-specific is in config.yaml and sample_data/; the app itself
is the generic bookkeeping tool.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:  # make core/ and tools/ importable on Streamlit Cloud
    sys.path.insert(0, str(ROOT))

from tools.bookkeeping.views import run_app  # noqa: E402

run_app(HERE)
