"""Settings lookup: environment variables first, then Streamlit secrets.

Streamlit Community Cloud exposes root-level secrets as environment variables,
but we also read ``st.secrets`` directly so a local ``.streamlit/secrets.toml``
works the same way. Keys are never hard-coded.
"""

from __future__ import annotations

import os

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "low"
_TRUTHY = {"1", "true", "yes", "on"}


def get_setting(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    try:  # Streamlit may not be installed/initialised (tests, scripts)
        import streamlit as st

        if name in st.secrets:
            secret = st.secrets[name]
            if secret not in (None, ""):
                return str(secret)
    except Exception:
        pass
    return default


def flag(name: str) -> bool:
    return (get_setting(name, "") or "").strip().lower() in _TRUTHY


def api_key() -> str | None:
    return get_setting("ANTHROPIC_API_KEY")


def claude_model() -> str:
    return get_setting("CLAUDE_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


def claude_effort() -> str | None:
    """Effort level sent to the API (low | medium | high | xhigh | max).

    Named DEMO_CLAUDE_EFFORT (not CLAUDE_EFFORT) so it never picks up a value
    meant for another Claude tool on the same machine. Set it to ``none`` to
    omit the parameter, e.g. for an older model that does not support effort.
    """
    value = (get_setting("DEMO_CLAUDE_EFFORT", DEFAULT_EFFORT) or "").strip().lower()
    return None if value in ("", "none", "default") else value


def is_mock_mode() -> bool:
    """Mock mode: no API key, or DEMO_MOCK=1. Canned responses, no network."""
    return flag("DEMO_MOCK") or not api_key()
