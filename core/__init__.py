"""Shared building blocks for every client demo.

- ``core.claude``    Claude client wrapper (disk cache, mock mode, fixtures)
- ``core.ui``        Streamlit page shell, step-progress widget, summary panel,
                     "needs human check" list, download buttons
- ``core.downloads`` Excel / CSV / Word / PDF builders that return bytes
- ``core.settings``  environment + Streamlit secrets lookup
- ``core.estimates`` transparent "time saved" estimate
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
