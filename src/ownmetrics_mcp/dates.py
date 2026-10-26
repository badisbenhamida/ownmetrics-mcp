"""Date parsing, range validation (R1) and request windowing (R2)."""

from __future__ import annotations

import re
from datetime import date, timedelta

from ownmetrics_mcp.errors import InvalidInputError

MAX_TOOL_RANGE_DAYS = 90
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_day(value: str, field: str = "date") -> date:
    try:
        cleaned = value.strip()
        if not _ISO_DAY.fullmatch(cleaned):  # fromisoformat also accepts 20261025, 2026-W43-7
            raise ValueError(cleaned)
        return date.fromisoformat(cleaned)
    except (ValueError, AttributeError) as exc:
        raise InvalidInputError(
            f"`{field}` must be a date like 2026-10-25, got {value!r}."
        ) from exc


def parse_range(start: str, end: str, max_days: int = MAX_TOOL_RANGE_DAYS) -> tuple[date, date]:
    first, last = parse_day(start, "start"), parse_day(end, "end")
    if last < first:
        raise InvalidInputError("`end` must be on or after `start`.")
    days = (last - first).days + 1
    if days > max_days:
        raise InvalidInputError(
            f"That range is {days} days; the limit is {max_days} per question. "
            "Ask about a shorter period, or split it."
        )
    return first, last


def windows(first: date, last: date, size_days: int) -> list[tuple[date, date]]:
    """Split [first, last] (inclusive) into consecutive windows of at most size_days."""
    if size_days < 1:
        raise ValueError("size_days must be >= 1")
    out: list[tuple[date, date]] = []
    cur = first
    while cur <= last:
        stop = min(cur + timedelta(days=size_days - 1), last)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out
