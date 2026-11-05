"""Meter Data Checker — prototype demo for NFU Energy.

Run locally:      streamlit run clients/nfu-energy/app.py
Streamlit Cloud:  main file path = clients/nfu-energy/app.py

Everything client-specific is in config.yaml and sample_data/; the app itself
is the generic data-validation tool.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:  # make core/ and tools/ importable on Streamlit Cloud
    sys.path.insert(0, str(ROOT))

from tools.data_validation.views import run_app  # noqa: E402

run_app(HERE)
