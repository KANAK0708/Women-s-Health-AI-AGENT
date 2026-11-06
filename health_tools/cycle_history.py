"""Date arithmetic only: no diagnosis, clinical classification, or prediction."""

import re
from datetime import date
from statistics import mean, median

from .contracts import ToolError, ToolResult


LIMITATIONS = (
    "Intervals assume each supplied date is the start of a separate period; missing entries can lengthen an interval.",
    "These calculations do not diagnose PCOS, establish ovulation, predict fertility, or determine contraceptive safety.",
    "No clinical normal/abnormal classification is made.",
)
MAX_ENTRIES = 366


def analyze_cycle_history(
    period_start_dates: list[str], *, as_of: str | None = None
) -> ToolResult:
    """Summarize explicit period start dates without reading or saving memory.

    Dates must be unique, ascending YYYY-MM-DD strings on or before as_of.
    as_of defaults to today's local date; callers should supply the user's local
    date explicitly when available. Input is never silently sorted or deduplicated.
    """
    def invalid(code: str, message: str) -> ToolResult:
        return ToolResult(
            tool="analyze_cycle_history", status="error",
            error=ToolError(code=code, message=message), limitations=LIMITATIONS,
        )

    def parse(value: str) -> date:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("Expected YYYY-MM-DD")
        return date.fromisoformat(value)

    try:
        reference_date = date.today() if as_of is None else parse(as_of)
    except ValueError:
        return invalid("invalid_as_of", "as_of must be a valid YYYY-MM-DD date.")

    if not isinstance(period_start_dates, list):
        return invalid("invalid_input", "period_start_dates must be a list of YYYY-MM-DD strings.")
    if len(period_start_dates) > MAX_ENTRIES:
        return invalid("too_many_entries", f"Supply at most {MAX_ENTRIES} period start dates.")
    try:
        dates = [parse(value) for value in period_start_dates]
    except ValueError:
        return invalid("invalid_date", "Each period start must be a valid YYYY-MM-DD date.")
    if len(set(dates)) != len(dates):
        return invalid("duplicate_dates", "Confirm duplicate period start dates before calculating.")
    if dates != sorted(dates):
        return invalid("unordered_dates", "Supply confirmed period start dates from oldest to newest.")
    if any(value > reference_date for value in dates):
        return invalid("future_date", "Period start dates cannot be after as_of.")

    intervals = [(end - start).days for start, end in zip(dates, dates[1:])]
    data = {
        "as_of": reference_date.isoformat(),
        "period_start_dates": list(period_start_dates),
        "recorded_period_count": len(dates),
        "completed_interval_count": len(intervals),
        "cycle_lengths_days": intervals,
        "mean_cycle_length_days": round(mean(intervals), 2) if intervals else None,
        "median_cycle_length_days": median(intervals) if intervals else None,
        "shortest_interval_days": min(intervals) if intervals else None,
        "longest_interval_days": max(intervals) if intervals else None,
        "interval_range_days": max(intervals) - min(intervals) if intervals else None,
        # Elapsed time is not a completed cycle and is excluded from statistics.
        "days_since_last_recorded_start": (reference_date - dates[-1]).days if dates else None,
    }
    limitations = LIMITATIONS
    if len(intervals) < 2:
        limitations += ("Fewer than two completed intervals cannot describe variability across intervals.",)
    return ToolResult(
        tool="analyze_cycle_history",
        status="ok" if intervals else "insufficient_data",
        data=data, limitations=limitations,
    )
