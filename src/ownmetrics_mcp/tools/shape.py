"""Helpers that turn Garmin JSON into unit-labelled, never-zero-when-missing values (C4, R5)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

NOT_RECORDED = "not recorded"
NOT_PROVIDED = "not provided by Garmin's Personal API"
SOURCE = "Garmin Connect Personal API (unofficial client: ownmetrics-mcp)"
DISCLAIMER = "Informational only, not medical advice."

Json = Any


def get(obj: Json, *path: str | int) -> Any:
    """Safe nested lookup. Returns None when any step is missing."""
    cur = obj
    for step in path:
        if isinstance(step, int):
            if not isinstance(cur, list) or step >= len(cur):
                return None
            cur = cur[step]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(step)
        if cur is None:
            return None
    return cur


def num(value: Any, *, scale: float = 1.0, digits: int = 1, allow_negative: bool = False) -> Any:
    """A rounded number, or NOT_RECORDED. Garmin uses negatives (e.g. -1, -2) for 'no data'."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return NOT_RECORDED
    if value < 0 and not allow_negative:
        return NOT_RECORDED
    result = round(value * scale, digits)
    return int(result) if digits == 0 else result


def text(value: Any) -> Any:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return NOT_RECORDED


def seconds_to_hours(value: Any) -> Any:
    return num(value, scale=1 / 3600, digits=2)


def seconds_to_minutes(value: Any) -> Any:
    return num(value, scale=1 / 60, digits=1)


def meters_to_km(value: Any) -> Any:
    return num(value, scale=1 / 1000, digits=2)


def weight_kg(value: Any) -> Any:
    """Garmin documents kilograms but the live API returns grams; values > 1000 are grams."""
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 1000:
        return num(value, scale=1 / 1000, digits=1)
    return num(value, digits=1)


def pace_min_per_km(speed_m_s: Any) -> Any:
    if not isinstance(speed_m_s, int | float) or isinstance(speed_m_s, bool) or speed_m_s <= 0:
        return NOT_RECORDED
    total = 1000 / speed_m_s / 60
    minutes = int(total)
    seconds = round((total - minutes) * 60)
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}:{seconds:02d}"


def envelope(tool: str, data: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"tool": tool, **extra, **data, "source": SOURCE, "note": DISCLAIMER}


def by_date(
    items: list[Json],
    key: str = "calendarDate",
    prefer: Callable[[Json], float] | None = None,
) -> dict[str, Json]:
    """Index records by date. With duplicates for one day, keep the one `prefer` scores
    highest (default: the record with the most fields), so the choice is deterministic (R10)."""
    score = prefer or (lambda r: float(len(r)) if isinstance(r, dict) else 0.0)
    out: dict[str, Json] = {}
    for item in items:
        day = get(item, key)
        if not isinstance(day, str):
            continue
        day = day[:10]
        if day not in out or score(item) > score(out[day]):
            out[day] = item
    return out
