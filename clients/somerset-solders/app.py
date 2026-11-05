"""Bookkeeping Agent — prototype demo for Somerset Solders Ltd.

Run locally:      streamlit run clients/somerset-solders/app.py
Streamlit Cloud:  main file path = clients/somerset-solders/app.py

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
