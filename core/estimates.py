"""Transparent "time saved vs doing it by hand" estimate.

Every assumption is passed in (usually from a client's config.yaml) and shown
next to the number, so the claim can be checked rather than taken on trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TimeEstimate:
    manual_minutes: float
    with_tool_minutes: float
    assumptions: list[str] = field(default_factory=list)

    @property
    def saved_minutes(self) -> float:
        return max(self.manual_minutes - self.with_tool_minutes, 0.0)

    @property
    def saved_label(self) -> str:
        return format_minutes(self.saved_minutes)


def format_minutes(minutes: float) -> str:
    if minutes < 90:
        return f"{minutes:.0f} min"
    return f"{minutes / 60:.1f} hours"


def estimate(manual_tasks: list[tuple[str, float, float]], review_tasks: list[tuple[str, float, float]]) -> TimeEstimate:
    """Each task is ``(label, count, minutes_each)``.

    ``manual_tasks`` is the by-hand process; ``review_tasks`` is what a person
    still does when using the tool (e.g. reviewing flagged items).
    """
    manual = sum(count * each for _, count, each in manual_tasks)
    review = sum(count * each for _, count, each in review_tasks)
    lines = [f"By hand: {label} — {count:,.0f} × {each:g} min" for label, count, each in manual_tasks]
    lines += [f"With the tool: {label} — {count:,.0f} × {each:g} min" for label, count, each in review_tasks]
    return TimeEstimate(manual_minutes=manual, with_tool_minutes=review, assumptions=lines)
