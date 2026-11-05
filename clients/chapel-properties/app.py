"""Financial Data Entry Agent — prototype demo for Chapel Properties Ltd.

Run locally:      streamlit run clients/chapel-properties/app.py
Streamlit Cloud:  main file path = clients/chapel-properties/app.py

Everything client-specific is in config.yaml and sample_data/; the app itself
is the generic bookkeeping tool (tools/bookkeeping).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:  # make core/ and tools/ importable on Streamlit Cloud
    sys.path.insert(0, str(ROOT))

from tools.bookkeeping.views import run_app  # noqa: E402

run_app(HERE)
