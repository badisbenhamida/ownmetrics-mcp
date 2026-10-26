"""Insight tools I1-I4 (SPEC 4.2). They fetch within Garmin's limits (R2, R12) and do the
arithmetic in the server, so one call answers a question that would otherwise take many
data-tool calls plus manual math. Every average says how many days it rests on, and a
period without data is "not recorded", never zero (C4)."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ownmetrics_mcp.dates import MAX_INSIGHT_RANGE_DAYS, parse_range
from ownmetrics_mcp.errors import InvalidInputError
from ownmetrics_mcp.garmin import GarminSource
from ownmetrics_mcp.tools.shape import (
    NOT_APPLICABLE,
    NOT_RECORDED,
    by_date,
    envelope,
    get,
    sport_kind,
)

MAX_INSIGHT_ACTIVITIES = 1000
EVENING_HOUR = 18
MIN_PAIRED_DAYS = 14
FLAT_THRESHOLD = 0.02  # fitted change over the range under 2% of the average = flat
MIN_TREND_POINTS = 7
ROLLING_DAYS = 7
ROLLING_MIN_VALUES = 4
CORRELATION_NOTE = (
    "Correlation shows whether two things tend to move together, not that one causes the "
    "other. Travel, illness, work and season can drive both."
)

Series = dict[date, float]


# -- metrics -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    name: str
    daily_suffix: str  # unit of one day's value
    period_suffix: str  # unit of a period's value
    source: str  # sleep | hrv | daily | activities
    digits: int
    training: bool = False  # period value is a weekly rate; days without training count as 0


METRICS: dict[str, Metric] = {
    m.name: m
    for m in [
        Metric("sleep_score", "_0_100", "_0_100", "sleep", 1),
        Metric("sleep_hours", "_hours", "_hours", "sleep", 2),
        Metric("deep_sleep_minutes", "_minutes", "_minutes", "sleep", 0),
        Metric("hrv_ms", "_ms", "_ms", "hrv", 1),
        Metric("resting_hr_bpm", "_bpm", "_bpm", "daily", 1),
        Metric("stress_avg", "_0_100", "_0_100", "daily", 1),
        Metric("body_battery_high", "_0_100", "_0_100", "daily", 1),
        Metric("steps", "_steps", "_steps", "daily", 0),
        Metric("training_hours", "_hours", "_hours_per_week", "activities", 1, training=True),
        Metric(
            "training_sessions", "_sessions", "_sessions_per_week", "activities", 1, training=True
        ),
    ]
}


def _check_metrics(names: Iterable[str]) -> list[Metric]:
    out = []
    for n in names:
        if n not in METRICS:
            raise InvalidInputError(f"Unknown metric {n!r}. Choose from: {', '.join(METRICS)}.")
        out.append(METRICS[n])
    return out


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value > 0 else None


def _rnd(value: float | None, digits: int) -> Any:
    if value is None:
        return NOT_RECORDED
    r = round(value, digits)
    return int(r) if digits == 0 else r


# -- fetching ------------------------------------------------------------------------------


@dataclass
class Activity:
    day: date
    hour: int | None
    type_key: str
    minutes: float
    distance_km: float | None
    aerobic_te: float | None


def _activities(src: GarminSource, first: date, last: date) -> tuple[list[Activity], bool]:
    raw = src.activities(first, last, None, MAX_INSIGHT_ACTIVITIES)
    out = []
    for a in raw:
        start = get(a, "startTimeLocal")
        try:
            day = date.fromisoformat(str(start)[:10])
        except ValueError:
            continue
        if not first <= day <= last:
            continue
        try:
            hour: int | None = int(str(start)[11:13])
        except ValueError:
            hour = None
        seconds = _positive(get(a, "duration")) or 0.0
        dist = _positive(get(a, "distance"))
        te = get(a, "aerobicTrainingEffect")
        out.append(
            Activity(
                day=day,
                hour=hour,
                type_key=str(get(a, "activityType", "typeKey") or "unknown"),
                minutes=seconds / 60,
                distance_km=dist / 1000 if dist is not None else None,
                aerobic_te=float(te) if isinstance(te, int | float) and te >= 0 else None,
            )
        )
    return out, len(raw) >= MAX_INSIGHT_ACTIVITIES


def _sleep_record(r: Any) -> Any:
    return get(r, "dailySleepDTO") or r


def _daily_values(
    src: GarminSource, metrics: list[Metric], first: date, last: date
) -> tuple[dict[str, Series], bool]:
    """One value per day per metric. Sleep and HRV are keyed by the day the night ended."""
    sources = {m.source for m in metrics}
    out: dict[str, Series] = {m.name: {} for m in metrics}
    truncated = False

    def put(name: str, day_s: str, value: float | None) -> None:
        if name in out and value is not None:
            out[name][date.fromisoformat(day_s)] = value

    if "sleep" in sources:
        records = [_sleep_record(r) for r in src.sleep_summaries(first, last)]
        nights = by_date(records, prefer=lambda r: _positive(get(r, "sleepTimeSeconds")) or 0)
        for day_s, n in nights.items():
            secs = _positive(get(n, "sleepTimeSeconds"))
            if secs is None:
                continue
            put("sleep_hours", day_s, secs / 3600)
            put("sleep_score", day_s, _positive(get(n, "sleepScores", "overall", "value")))
            deep = get(n, "deepSleepSeconds")
            if isinstance(deep, int | float) and deep >= 0:
                put("deep_sleep_minutes", day_s, deep / 60)
    if "hrv" in sources:
        for day_s, h in by_date(src.hrv_summaries(first, last)).items():
            put("hrv_ms", day_s, _positive(get(h, "lastNightAvg")))
    if "daily" in sources:
        for day_s, s in by_date(src.daily_summaries(first, last)).items():
            put("resting_hr_bpm", day_s, _positive(get(s, "heartRate", "restingValue")))
            put("stress_avg", day_s, _positive(get(s, "stress", "avgLevel")))
            put("body_battery_high", day_s, _positive(get(s, "bodyBattery", "maxValue")))
            put("steps", day_s, _positive(get(s, "movement", "steps", "value")))
    if "activities" in sources:
        acts, truncated = _activities(src, first, last)
        hours: Series = {first + timedelta(days=i): 0.0 for i in range((last - first).days + 1)}
        sessions = dict.fromkeys(hours, 0.0)
        for a in acts:
            hours[a.day] += a.minutes / 60
            sessions[a.day] += 1
        if "training_hours" in out:
            out["training_hours"] = hours
        if "training_sessions" in out:
            out["training_sessions"] = sessions
    return out, truncated


def _period_value(m: Metric, series: Series, first: date, last: date) -> tuple[Any, int]:
    """(value, days with data). Training metrics: weekly rate over all days in the period."""
    days = (last - first).days + 1
    values = [v for d, v in series.items() if first <= d <= last]
    if m.training:
        return _rnd(sum(values) / days * 7, m.digits), days
    if not values:
        return NOT_RECORDED, 0
    return _rnd(sum(values) / len(values), m.digits), len(values)


# -- grouping ------------------------------------------------------------------------------


def _periods(first: date, last: date, group_by: str) -> list[tuple[str, date, date, int]]:
    """(label, start, end, full length in days), clipped to [first, last]."""
    out = []
    cur = first
    while cur <= last:
        if group_by == "day":
            start, end, label = cur, cur, cur.isoformat()
        elif group_by == "week":
            start = cur - timedelta(days=cur.weekday())
            end = start + timedelta(days=6)
            label = f"week of {start.isoformat()}"
        elif group_by == "month":
            start = cur.replace(day=1)
            nxt = (start + timedelta(days=32)).replace(day=1)
            end = nxt - timedelta(days=1)
            label = start.strftime("%Y-%m")
        else:
            raise InvalidInputError("`group_by` must be one of: day, week, month.")
        full = (end - start).days + 1
        out.append((label, max(start, first), min(end, last), full))
        cur = min(end, last) + timedelta(days=1)
    return out


def _period_label(label: str, start: date, end: date, full: int) -> dict[str, Any]:
    days = (end - start).days + 1
    row: dict[str, Any] = {"period": label, "first_day": start.isoformat()}
    row["last_day"] = end.isoformat()
    if days < full:
        row["partial"] = True
        row["days_in_range"] = days
    return row


# -- I1 ------------------------------------------------------------------------------------


def _training_block(acts: list[Activity], days: int) -> dict[str, Any]:
    minutes = sum(a.minutes for a in acts)
    te = [a.aerobic_te for a in acts if a.aerobic_te is not None]
    by_sport: dict[str, list[Activity]] = defaultdict(list)
    for a in acts:
        by_sport[a.type_key].append(a)
    sports = {}
    for key, items in sorted(by_sport.items(), key=lambda kv: -sum(a.minutes for a in kv[1])):
        row: dict[str, Any] = {
            "sessions": len(items),
            "total_hours": round(sum(a.minutes for a in items) / 60, 1),
        }
        if sport_kind(key) == "no_distance":
            row["distance_km"] = NOT_APPLICABLE
        else:
            dists = [a.distance_km for a in items if a.distance_km is not None]
            row["distance_km"] = round(sum(dists), 1) if dists else NOT_RECORDED
        sports[key] = row
    return {
        "sessions": len(acts),
        "total_hours": round(minutes / 60, 1),
        "hours_per_week": round(minutes / 60 / days * 7, 1),
        "evening_sessions": sum(1 for a in acts if a.hour is not None and a.hour >= EVENING_HOUR),
        "avg_aerobic_training_effect_0_5": round(sum(te) / len(te), 1) if te else NOT_APPLICABLE,
        "by_sport": sports or {"status": "no activities recorded"},
    }


def training_summary(
    src: GarminSource, start: str, end: str, group_by: str = "week"
) -> dict[str, Any]:
    first, last = parse_range(start, end, MAX_INSIGHT_RANGE_DAYS)
    if group_by not in ("week", "month"):
        raise InvalidInputError("`group_by` must be 'week' or 'month'.")
    acts, truncated = _activities(src, first, last)
    periods = []
    for label, p_start, p_end, full in _periods(first, last, group_by):
        in_period = [a for a in acts if p_start <= a.day <= p_end]
        periods.append(
            {
                **_period_label(label, p_start, p_end, full),
                **_training_block(in_period, (p_end - p_start).days + 1),
            }
        )
    data: dict[str, Any] = {
        "evening_means": f"sessions starting at {EVENING_HOUR}:00 or later, local time",
        "totals": _training_block(acts, (last - first).days + 1),
        "periods": periods,
    }
    if truncated:
        data["warning"] = f"Only the first {MAX_INSIGHT_ACTIVITIES} activities were counted."
    return envelope(
        "training_summary", data, start=first.isoformat(), end=last.isoformat(), group_by=group_by
    )


# -- I2 ------------------------------------------------------------------------------------


def compare_periods(
    src: GarminSource,
    a_start: str,
    a_end: str,
    b_start: str,
    b_end: str,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    a = parse_range(a_start, a_end, MAX_INSIGHT_RANGE_DAYS)
    b = parse_range(b_start, b_end, MAX_INSIGHT_RANGE_DAYS)
    chosen = _check_metrics(metrics or list(METRICS))
    va, trunc_a = _daily_values(src, chosen, *a)
    vb, trunc_b = _daily_values(src, chosen, *b)
    rows = {}
    for m in chosen:
        val_a, n_a = _period_value(m, va[m.name], *a)
        val_b, n_b = _period_value(m, vb[m.name], *b)
        row: dict[str, Any] = {
            "period_a": {f"average{m.period_suffix}": val_a, "days_with_data": n_a},
            "period_b": {f"average{m.period_suffix}": val_b, "days_with_data": n_b},
        }
        if isinstance(val_a, int | float) and isinstance(val_b, int | float):
            row[f"change{m.period_suffix}"] = _rnd(val_b - val_a, m.digits or 1)
            row["change_percent"] = (
                round((val_b - val_a) / abs(val_a) * 100, 1) if val_a else NOT_APPLICABLE
            )
        else:
            row[f"change{m.period_suffix}"] = NOT_RECORDED
            row["change_percent"] = NOT_RECORDED
        rows[m.name] = row
    data: dict[str, Any] = {
        "period_a": {"start": a[0].isoformat(), "end": a[1].isoformat()},
        "period_b": {"start": b[0].isoformat(), "end": b[1].isoformat()},
        "how_to_read": (
            "Change is period B minus period A. Sleep and HRV belong to the day the night "
            "ended. Training figures are per week, counting rest days."
        ),
        "metrics": rows,
    }
    if trunc_a or trunc_b:
        data["warning"] = f"Only the first {MAX_INSIGHT_ACTIVITIES} activities were counted."
    return envelope("compare_periods", data)


# -- I3 ------------------------------------------------------------------------------------


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return sxy / math.sqrt(sxx * syy)


def strength(r: float) -> str:
    a = abs(r)
    if a < 0.1:
        return "none"
    if a < 0.3:
        return "weak"
    if a < 0.5:
        return "moderate"
    return "strong"


OUTCOMES = {"sleep_score": "_0_100", "sleep_hours": "_hours", "hrv_ms": "_ms"}
OUTCOME_DIGITS = {"sleep_score": 1, "sleep_hours": 2, "hrv_ms": 1}


def recovery_correlations(src: GarminSource, start: str, end: str) -> dict[str, Any]:
    first, last = parse_range(start, end, MAX_INSIGHT_RANGE_DAYS)
    # The night after day D ends on D+1, so outcomes are read one day later.
    outcomes, _ = _daily_values(
        src,
        [METRICS[n] for n in OUTCOMES],
        first + timedelta(days=1),
        last + timedelta(days=1),
    )
    acts, truncated = _activities(src, first, last)
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    hours = dict.fromkeys(days, 0.0)
    te = dict.fromkeys(days, 0.0)
    evening = dict.fromkeys(days, False)
    for a in acts:
        hours[a.day] += a.minutes / 60
        te[a.day] += a.aerobic_te or 0.0
        if a.hour is not None and a.hour >= EVENING_HOUR:
            evening[a.day] = True
    predictors: dict[str, dict[date, float]] = {
        "training_hours": hours,
        "aerobic_training_effect_sum": te,
    }

    correlations = []
    for p_name, p_vals in predictors.items():
        for o_name in OUTCOMES:
            series = outcomes[o_name]
            pairs = [
                (p_vals[d], series[d + timedelta(days=1)])
                for d in days
                if d + timedelta(days=1) in series
            ]
            row: dict[str, Any] = {
                "training": p_name,
                "outcome": o_name,
                "paired_days": len(pairs),
            }
            r = pearson([x for x, _ in pairs], [y for _, y in pairs])
            if len(pairs) < MIN_PAIRED_DAYS:
                row["status"] = f"not enough data (need at least {MIN_PAIRED_DAYS} paired days)"
            elif r is None:
                row["status"] = "not enough variation to measure"
            else:
                row["correlation_r"] = round(r, 2)
                row["strength"] = strength(r)
                row["direction"] = (
                    "no clear direction"
                    if strength(r) == "none"
                    else f"more training goes with {'higher' if r > 0 else 'lower'} "
                    f"{o_name.replace('_', ' ')}"
                )
            correlations.append(row)

    def group(selected: list[date]) -> dict[str, Any]:
        out: dict[str, Any] = {"days": len(selected)}
        for o_name, suffix in OUTCOMES.items():
            vals = [
                outcomes[o_name][d + timedelta(days=1)]
                for d in selected
                if d + timedelta(days=1) in outcomes[o_name]
            ]
            out[f"next_{o_name.removesuffix('_ms')}{suffix}"] = _rnd(
                sum(vals) / len(vals) if vals else None, OUTCOME_DIGITS[o_name]
            )
            out[f"nights_with_{o_name.removesuffix('_ms')}"] = len(vals)
        return out

    trained = [d for d in days if hours[d] > 0]
    data: dict[str, Any] = {
        "how_to_read": (
            "Each day's training is paired with the night that followed it (the sleep that "
            "ended the next morning) and the next morning's HRV. Strength of r: under 0.1 "
            "none, under 0.3 weak, under 0.5 moderate, otherwise strong. " + CORRELATION_NOTE
        ),
        "correlations": correlations,
        "groups": {
            "training_days": group(trained),
            "rest_days": group([d for d in days if hours[d] == 0]),
            "evening_session_days": group([d for d in trained if evening[d]]),
            "earlier_session_days": group([d for d in trained if not evening[d]]),
        },
        "evening_means": f"a session starting at {EVENING_HOUR}:00 or later, local time",
    }
    if truncated:
        data["warning"] = f"Only the first {MAX_INSIGHT_ACTIVITIES} activities were counted."
    return envelope("recovery_correlations", data, start=first.isoformat(), end=last.isoformat())


# -- I4 ------------------------------------------------------------------------------------


def least_squares_slope(points: list[tuple[float, float]]) -> float | None:
    n = len(points)
    if n < 2:
        return None
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in points) / sxx


def trend(
    src: GarminSource, metric: str, start: str, end: str, group_by: str = "week"
) -> dict[str, Any]:
    first, last = parse_range(start, end, MAX_INSIGHT_RANGE_DAYS)
    (m,) = _check_metrics([metric])
    if group_by not in ("day", "week", "month"):
        raise InvalidInputError("`group_by` must be one of: day, week, month.")
    values, truncated = _daily_values(src, [m], first, last)
    series = values[m.name]

    rows = []
    if group_by == "day":
        for i in range((last - first).days + 1):
            d = first + timedelta(days=i)
            window = [
                series[d - timedelta(days=k)]
                for k in range(ROLLING_DAYS)
                if d - timedelta(days=k) in series
            ]
            rows.append(
                {
                    "date": d.isoformat(),
                    f"value{m.daily_suffix}": _rnd(series.get(d), m.digits),
                    f"rolling_7day_avg{m.daily_suffix}": _rnd(
                        sum(window) / len(window) if len(window) >= ROLLING_MIN_VALUES else None,
                        m.digits,
                    ),
                }
            )
    else:
        for label, p_start, p_end, full in _periods(first, last, group_by):
            val, n = _period_value(m, series, p_start, p_end)
            rows.append(
                {
                    **_period_label(label, p_start, p_end, full),
                    f"average{m.period_suffix}": val,
                    "days_with_data": n,
                }
            )

    # Fit on daily values; training metrics are reported as a change in the weekly rate.
    points = [(float((d - first).days), v) for d, v in sorted(series.items())]
    slope = least_squares_slope(points) if len(points) >= MIN_TREND_POINTS else None
    scale = 7.0 if m.training else 1.0
    summary: dict[str, Any] = {"days_with_data": len(points)}
    if slope is None:
        summary["direction"] = (
            f"not enough data (need at least {MIN_TREND_POINTS} days)"
            if len(points) < MIN_TREND_POINTS
            else "flat"
        )
        summary[f"change_per_30_days{m.period_suffix}"] = NOT_RECORDED
    else:
        mean = sum(v for _, v in points) / len(points)
        span = (last - first).days
        fitted_change = slope * span
        if mean == 0 or abs(fitted_change) < FLAT_THRESHOLD * abs(mean):
            direction = "flat"
        else:
            direction = "up" if slope > 0 else "down"
        summary["direction"] = direction
        summary[f"change_per_30_days{m.period_suffix}"] = _rnd(slope * 30 * scale, max(m.digits, 1))
        summary[f"average{m.period_suffix}"] = _rnd(mean * scale, m.digits)
    data: dict[str, Any] = {
        "metric": m.name,
        "how_to_read": (
            "Direction comes from a straight-line fit through every day with data; 'flat' means "
            "the fitted change over the whole range is under 2% of the average. Sleep and HRV "
            "belong to the day the night ended."
            + (" Training figures are per week, counting rest days." if m.training else "")
        ),
        "summary": summary,
        "series": rows,
    }
    if truncated:
        data["warning"] = f"Only the first {MAX_INSIGHT_ACTIVITIES} activities were counted."
    return envelope("trend", data, start=first.isoformat(), end=last.isoformat(), group_by=group_by)


__all__ = [
    "METRICS",
    "compare_periods",
    "least_squares_slope",
    "pearson",
    "recovery_correlations",
    "strength",
    "training_summary",
    "trend",
]
