"""Streamlit building blocks shared by every client demo.

    page_shell(...)              headline, "what this replaces", mode badge
    StepProgress(...)            visible step-by-step progress list
    summary_panel(...)           metric cards + 20-second plain-English summary
    human_check_list(...)        "needs human check" list with Reviewed ticks
    download_buttons(...)        one button per output file
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field

import streamlit as st

from core.styling import CSS

MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "csv": "text/csv",
    "json": "application/json",
}


def esc(text) -> str:
    return html.escape(str(text))

# ------------------------------------------------------------------ page shell


def page_shell(*, page_title: str, headline: str, replaces: str, mock: bool, mode_label: str,
               badges: list[str] | None = None) -> None:
    st.set_page_config(page_title=page_title, page_icon="▦", layout="wide", initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    badge_html = "".join(f'<span class="th-badge">{esc(b)}</span>' for b in (badges or []))
    if mock:
        badge_html += ('<span class="th-badge mock" title="No ANTHROPIC_API_KEY set (or DEMO_MOCK=1): '
                       'AI text comes from recorded responses, no network calls.">Mock mode</span>')
    else:
        badge_html += f'<span class="th-badge live">{esc(mode_label)}</span>'
    st.markdown(
        f'<div class="th-headline">{esc(headline)}</div>'
        f'<div class="th-replaces">{esc(replaces)}</div>'
        f'<div class="th-badges">{badge_html}</div>',
        unsafe_allow_html=True,
    )


def section(title: str, caption: str | None = None) -> None:
    st.markdown(f'<div class="th-section">{esc(title)}</div>', unsafe_allow_html=True)
    if caption:
        st.markdown(f'<div class="th-caption">{esc(caption)}</div>', unsafe_allow_html=True)


def friendly_error(message: str, hint: str | None = None) -> None:
    st.error(message + (f"\n\n{hint}" if hint else ""), icon="⚠️")

# --------------------------------------------------------------- step progress


@dataclass
class Step:
    label: str
    status: str = "running"  # running | done | warn | fail
    detail: str = ""


@dataclass
class StepProgress:
    """A visible checklist that updates as the pipeline runs.

    Pass ``container=None`` to collect steps without drawing (tests, scripts).
    ``delay`` adds a short pause after each completed step so a screen
    recording can follow along; it does not change any results.
    """

    container: object | None = None
    delay: float = 0.0
    steps: list[Step] = field(default_factory=list)

    def __post_init__(self):
        self._slot = self.container.empty() if self.container is not None else None

    def start(self, label: str) -> None:
        self.steps.append(Step(label))
        self._draw()

    def update(self, label: str) -> None:
        if self.steps and self.steps[-1].status == "running":
            self.steps[-1].label = label
            self._draw()

    def done(self, label: str | None = None, detail: str = "") -> None:
        self._finish("done", label, detail)

    def warn(self, label: str | None = None, detail: str = "") -> None:
        self._finish("warn", label, detail)

    def fail(self, label: str | None = None, detail: str = "") -> None:
        self._finish("fail", label, detail)

    def _finish(self, status: str, label: str | None, detail: str) -> None:
        if not self.steps or self.steps[-1].status != "running":
            self.steps.append(Step(label or ""))
        step = self.steps[-1]
        step.status, step.detail = status, detail
        if label:
            step.label = label
        self._draw()
        if self.delay and self._slot is not None:
            time.sleep(self.delay)

    def _draw(self) -> None:
        if self._slot is not None:
            self._slot.markdown(render_steps_html(self.steps), unsafe_allow_html=True)


def render_steps_html(steps: list[Step]) -> str:
    icons = {"done": "✓", "warn": "!", "fail": "✕"}
    items = []
    for s in steps:
        icon = '<span class="th-spin"></span>' if s.status == "running" else icons.get(s.status, "•")
        detail = f' <span class="detail">— {esc(s.detail)}</span>' if s.detail else ""
        items.append(f'<li class="{s.status}"><span class="ic">{icon}</span><span>{esc(s.label)}{detail}</span></li>')
    return f'<ul class="th-steps">{"".join(items)}</ul>'


def show_steps(steps: list[Step]) -> None:
    """Redraw a finished step list (e.g. after a Streamlit rerun)."""
    if steps:
        st.markdown(render_steps_html(steps), unsafe_allow_html=True)

# --------------------------------------------------------------- summary panel


@dataclass
class Metric:
    label: str
    value: str
    sub: str = ""
    tone: str = ""  # "" | "alert" | "good"


def summary_panel(metrics: list[Metric], summary_text: str | None = None, summary_source: str | None = None) -> None:
    cards = "".join(
        f'<div class="th-metric {m.tone}"><div class="v">{esc(m.value)}</div><div class="l">{esc(m.label)}</div>'
        + (f'<div class="s">{esc(m.sub)}</div>' if m.sub else "")
        + "</div>"
        for m in metrics
    )
    st.markdown(f'<div class="th-metrics">{cards}</div>', unsafe_allow_html=True)
    if summary_text:
        src = f'<div class="src">{esc(summary_source)}</div>' if summary_source else ""
        body = "<br/>".join(esc(p) for p in summary_text.strip().split("\n") if p.strip())
        st.markdown(f'<div class="th-summary">{body}{src}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------ needs human check


@dataclass
class CheckItem:
    id: str
    title: str
    why: str
    action: str = ""
    severity: str = "medium"  # high | medium | low | info


def human_check_list(items: list[CheckItem], *, key_prefix: str = "check") -> int:
    """Render the review list; returns how many items are ticked as reviewed."""
    if not items:
        st.success("Nothing needs a human check.")
        return 0
    reviewed = 0
    for item in items:
        tick, body = st.columns([0.07, 0.93], vertical_alignment="center")
        with tick:
            done = st.checkbox("Reviewed", key=f"{key_prefix}-{item.id}", label_visibility="collapsed",
                               help="Tick once a person has checked this item")
        reviewed += int(done)
        with body:
            sev = item.severity if item.severity in ("high", "medium", "low", "info") else "info"
            style = ' style="opacity:.55"' if done else ""
            action = f'<div class="a">Suggested action: {esc(item.action)}</div>' if item.action else ""
            st.markdown(
                f'<div class="th-check"{style}><div class="t"><span class="th-pill {sev}">{esc(sev)}</span>'
                f'{esc(item.id)} · {esc(item.title)}</div><div class="w">{esc(item.why)}</div>{action}</div>',
                unsafe_allow_html=True,
            )
    return reviewed

# ------------------------------------------------------------------- downloads


@dataclass
class DownloadFile:
    label: str
    data: bytes
    file_name: str
    help: str = ""

    @property
    def mime(self) -> str:
        return MIME.get(self.file_name.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def download_buttons(files: list[DownloadFile], *, per_row: int = 4) -> None:
    for start in range(0, len(files), per_row):
        row = files[start:start + per_row]
        cols = st.columns(per_row)
        for col, f in zip(cols, row):
            with col:
                st.download_button(f.label, data=f.data, file_name=f.file_name, mime=f.mime,
                                   help=f.help or None, key=f"dl-{f.file_name}", width="stretch")
