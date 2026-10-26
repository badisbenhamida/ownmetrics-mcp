"""Data tools T1-T9 (SPEC 4.1). Each returns a JSON-ready dict with unit-labelled fields (R5)
and reports missing data explicitly, never as zero (C4)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from ownmetrics_mcp.dates import parse_day, parse_range
from ownmetrics_mcp.errors import (
    AuthError,
    GarminUnavailableError,
    InvalidInputError,
    NoKeyError,
    NotProvidedError,
    OwnMetricsError,
    RateLimitedError,
)
from ownmetrics_mcp.garmin import GarminSource
from ownmetrics_mcp.tools.shape import (
    NOT_PROVIDED,
    NOT_RECORDED,
    by_date,
    envelope,
    get,
    meters_to_km,
    num,
    pace_min_per_km,
    seconds_to_hours,
    seconds_to_minutes,
    text,
    weight_kg,
)

MAX_ACTIVITIES = 100
NO_DAY = {"status": "no data recorded"}


def _days(first: date, last: date) -> list[str]:
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def _optional[T](fn: Callable[[], T]) -> T | dict[str, str]:
    """Run a secondary lookup; a gap in one data area must not hide the rest.
    Account and rate-limit problems are never hidden."""
    try:
        return fn()
    except (AuthError, NoKeyError, RateLimitedError):
        raise
    except NotProvidedError:
        return {"status": NOT_PROVIDED}
    except GarminUnavailableError as exc:
        return {"status": "unavailable", "detail": str(exc)}


def _is_status(obj: Any) -> bool:
    return isinstance(obj, dict) and set(obj) <= {"status", "detail"} and "status" in obj


# -- T1 ------------------------------------------------------------------------------------


def get_daily_overview(src: GarminSource, day: str) -> dict[str, Any]:
    d = parse_day(day)
    summaries = by_date(src.daily_summaries(d, d))
    s = summaries.get(d.isoformat())
    sleep = _optional(lambda: src.daily_sleep(d))
    sleep_dto = sleep if _is_status(sleep) else (get(sleep, "dailySleepDTO") or sleep)

    if s is None:
        overview: dict[str, Any] = dict(NO_DAY)
    else:
        overview = {
            "steps": num(get(s, "movement", "steps", "value"), digits=0),
            "step_goal": num(get(s, "movement", "steps", "goal"), digits=0),
            "distance_km": meters_to_km(get(s, "movement", "steps", "distanceInMeters")),
            "floors_climbed": num(get(s, "movement", "floorsAscended", "value"), digits=0),
            "resting_hr_bpm": num(get(s, "heartRate", "restingValue"), digits=0),
            "min_hr_bpm": num(get(s, "heartRate", "minValue"), digits=0),
            "max_hr_bpm": num(get(s, "heartRate", "maxValue"), digits=0),
            "stress_avg_0_100": num(get(s, "stress", "avgLevel"), digits=0),
            "stress_max_0_100": num(get(s, "stress", "maxLevel"), digits=0),
            "body_battery_high_0_100": num(get(s, "bodyBattery", "maxValue"), digits=0),
            "body_battery_low_0_100": num(get(s, "bodyBattery", "minValue"), digits=0),
            "body_battery_charged": num(get(s, "bodyBattery", "chargedValue"), digits=0),
            "body_battery_drained": num(get(s, "bodyBattery", "drainedValue"), digits=0),
            "body_battery_end_of_day_0_100": num(get(s, "bodyBattery", "endOfDayValue"), digits=0),
            "calories_total_kcal": num(get(s, "calories", "burnedTotal"), digits=0),
            "calories_active_kcal": num(get(s, "calories", "burnedActive"), digits=0),
            "intensity_minutes_moderate": num(get(s, "intensityMinutes", "moderate"), digits=0),
            "intensity_minutes_vigorous": num(get(s, "intensityMinutes", "vigorous"), digits=0),
        }
    if _is_status(sleep_dto):
        overview["sleep"] = sleep_dto
    else:
        overview["sleep_hours"] = seconds_to_hours(get(sleep_dto, "sleepTimeSeconds"))
        overview["sleep_score_0_100"] = num(
            get(sleep_dto, "sleepScores", "overall", "value"), digits=0
        )
    return envelope("get_daily_overview", {"overview": overview}, date=d.isoformat())


# -- T2 ------------------------------------------------------------------------------------


def get_sleep(src: GarminSource, start: str, end: str) -> dict[str, Any]:
    first, last = parse_range(start, end)
    nights = by_date(src.sleep_summaries(first, last))
    rows = []
    for day in _days(first, last):
        n = nights.get(day)
        n = get(n, "dailySleepDTO") or n
        if n is None or not isinstance(get(n, "sleepTimeSeconds"), int | float):
            rows.append({"night_of": day, **NO_DAY})
            continue
        rows.append(
            {
                "night_of": day,
                "sleep_hours": seconds_to_hours(get(n, "sleepTimeSeconds")),
                "deep_minutes": seconds_to_minutes(get(n, "deepSleepSeconds")),
                "light_minutes": seconds_to_minutes(get(n, "lightSleepSeconds")),
                "rem_minutes": seconds_to_minutes(get(n, "remSleepSeconds")),
                "awake_minutes": seconds_to_minutes(get(n, "awakeSleepSeconds")),
                "sleep_score_0_100": num(get(n, "sleepScores", "overall", "value"), digits=0),
                "sleep_score_quality": text(get(n, "sleepScores", "overall", "qualifierKey")),
                "garmin_feedback": text(get(n, "sleepScoreFeedback")),
                "avg_hr_bpm": num(get(n, "avgHeartRate"), digits=0),
                "avg_respiration_brpm": num(get(n, "averageRespirationValue")),
                "avg_sleep_stress_0_100": num(get(n, "avgSleepStress")),
            }
        )
    return envelope("get_sleep", {"nights": rows}, start=first.isoformat(), end=last.isoformat())


# -- T3 ------------------------------------------------------------------------------------


def get_hrv(src: GarminSource, start: str, end: str) -> dict[str, Any]:
    first, last = parse_range(start, end)
    nights = by_date(src.hrv_summaries(first, last))
    rows = []
    for day in _days(first, last):
        h = nights.get(day)
        if h is None or get(h, "lastNightAvg") is None:
            rows.append({"night_of": day, **NO_DAY})
            continue
        rows.append(
            {
                "night_of": day,
                "last_night_avg_ms": num(get(h, "lastNightAvg"), digits=0),
                "weekly_avg_ms": num(get(h, "weeklyAvg"), digits=0),
                "last_night_5min_high_ms": num(get(h, "lastNight5MinHigh"), digits=0),
                "status": text(get(h, "status")),
                "baseline_balanced_low_ms": num(get(h, "baseline", "balancedLow"), digits=0),
                "baseline_balanced_upper_ms": num(get(h, "baseline", "balancedUpper"), digits=0),
                "garmin_feedback": text(get(h, "feedbackPhrase")),
            }
        )
    return envelope("get_hrv", {"nights": rows}, start=first.isoformat(), end=last.isoformat())


# -- T4 ------------------------------------------------------------------------------------


def _body_battery_range(report: Any) -> tuple[Any, Any]:
    """High and low of the day from Garmin's [timestamp, level] series."""
    index = 1
    for d in get(report, "bodyBatteryValueDescriptorList") or []:
        if get(d, "bodyBatteryValueDescriptorKey") == "bodyBatteryLevel":
            index = get(d, "bodyBatteryValueDescriptorIndex") or 1
    levels = [
        row[index]
        for row in get(report, "bodyBatteryValuesArray") or []
        if isinstance(row, list)
        and len(row) > index
        and isinstance(row[index], int | float)
        and row[index] >= 0
    ]
    if not levels:
        return NOT_RECORDED, NOT_RECORDED
    return int(max(levels)), int(min(levels))


def get_stress_and_body_battery(src: GarminSource, start: str, end: str) -> dict[str, Any]:
    first, last = parse_range(start, end)
    stress = by_date(src.stress(first, last))
    battery = by_date(src.body_battery(first, last), key="date")
    rows = []
    for day in _days(first, last):
        s, b = stress.get(day), battery.get(day)
        if s is None and b is None:
            rows.append({"date": day, **NO_DAY})
            continue
        high, low = _body_battery_range(b)
        rows.append(
            {
                "date": day,
                "stress_avg_0_100": num(get(s, "values", "overallStressLevel"), digits=0),
                "rest_minutes": seconds_to_minutes(get(s, "values", "restStressDuration")),
                "low_stress_minutes": seconds_to_minutes(get(s, "values", "lowStressDuration")),
                "medium_stress_minutes": seconds_to_minutes(
                    get(s, "values", "mediumStressDuration")
                ),
                "high_stress_minutes": seconds_to_minutes(get(s, "values", "highStressDuration")),
                "body_battery_high_0_100": high,
                "body_battery_low_0_100": low,
                "body_battery_charged": num(get(b, "charged"), digits=0),
                "body_battery_drained": num(get(b, "drained"), digits=0),
            }
        )
    return envelope(
        "get_stress_and_body_battery", {"days": rows}, start=first.isoformat(), end=last.isoformat()
    )


# -- T5 ------------------------------------------------------------------------------------


def get_heart_rate(src: GarminSource, day: str) -> dict[str, Any]:
    d = parse_day(day)
    hr = src.heart_rate(d)
    zones_raw = _optional(src.heart_rate_zones)
    if hr is None or (get(hr, "restingHeartRate") is None and get(hr, "maxHeartRate") is None):
        day_data: dict[str, Any] = dict(NO_DAY)
    else:
        day_data = {
            "resting_hr_bpm": num(get(hr, "restingHeartRate"), digits=0),
            "min_hr_bpm": num(get(hr, "minHeartRate"), digits=0),
            "max_hr_bpm": num(get(hr, "maxHeartRate"), digits=0),
            "resting_hr_7day_avg_bpm": num(get(hr, "lastSevenDaysAvgRestingHeartRate"), digits=0),
        }
    if _is_status(zones_raw):
        zones: Any = zones_raw
    else:
        zones = [
            {
                "sport": text(get(z, "sport")),
                "method": text(get(z, "trainingMethod")),
                **{
                    f"zone_{i}_floor_bpm": num(get(z, f"zone{i}Floor"), digits=0)
                    for i in range(1, 6)
                },
                "max_hr_used_bpm": num(get(z, "maxHeartRateUsed"), digits=0),
            }
            for z in (zones_raw if isinstance(zones_raw, list) else [])
        ] or {"status": "no heart rate zones set"}
    return envelope(
        "get_heart_rate", {"day": day_data, "heart_rate_zones": zones}, date=d.isoformat()
    )


# -- T6 ------------------------------------------------------------------------------------


def _activity_row(a: Any) -> dict[str, Any]:
    return {
        "activity_id": get(a, "activityId"),
        "name": text(get(a, "activityName")),
        "type": text(get(a, "activityType", "typeKey")),
        "start_local": text(get(a, "startTimeLocal")),
        "duration_minutes": seconds_to_minutes(get(a, "duration")),
        "distance_km": meters_to_km(get(a, "distance")),
        "avg_hr_bpm": num(get(a, "averageHR"), digits=0),
        "max_hr_bpm": num(get(a, "maxHR"), digits=0),
        "calories_kcal": num(get(a, "calories"), digits=0),
        "aerobic_training_effect_0_5": num(get(a, "aerobicTrainingEffect")),
        "anaerobic_training_effect_0_5": num(get(a, "anaerobicTrainingEffect")),
    }


def list_activities(
    src: GarminSource,
    start: str,
    end: str,
    activity_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    first, last = parse_range(start, end)
    if not 1 <= limit <= MAX_ACTIVITIES:
        raise InvalidInputError(f"`limit` must be between 1 and {MAX_ACTIVITIES}.")
    kind = activity_type.strip() if activity_type and activity_type.strip() else None
    rows = [_activity_row(a) for a in src.activities(first, last, kind, limit)]
    data: dict[str, Any] = {"count": len(rows), "activities": rows}
    if not rows:
        data["status"] = "no activities recorded in this range"
    return envelope(
        "list_activities",
        data,
        start=first.isoformat(),
        end=last.isoformat(),
        activity_type=kind or "all",
    )


# -- T7 ------------------------------------------------------------------------------------


def get_activity(src: GarminSource, activity_id: int) -> dict[str, Any]:
    if not isinstance(activity_id, int) or isinstance(activity_id, bool) or activity_id <= 0:
        raise InvalidInputError("`activity_id` must be a positive whole number.")
    a = src.activity(activity_id)
    workouts_raw = _optional(lambda: src.activity_workouts(activity_id))
    s = get(a, "summaryDTO") or get(a, "summary") or {}
    detail = {
        "activity_id": activity_id,
        "name": text(get(a, "activityName")),
        "type": text(get(a, "activityTypeDTO", "typeKey") or get(a, "activityType", "typeKey")),
        "start_local": text(get(s, "startTimeLocal")),
        "duration_minutes": seconds_to_minutes(get(s, "duration")),
        "moving_minutes": seconds_to_minutes(get(s, "movingDuration")),
        "distance_km": meters_to_km(get(s, "distance")),
        "elevation_gain_m": num(get(s, "elevationGain"), digits=0),
        "avg_pace_min_per_km": pace_min_per_km(get(s, "averageSpeed")),
        "avg_speed_kmh": num(get(s, "averageSpeed"), scale=3.6),
        "avg_hr_bpm": num(get(s, "averageHR"), digits=0),
        "max_hr_bpm": num(get(s, "maxHR"), digits=0),
        "avg_power_w": num(get(s, "averagePower"), digits=0),
        "normalized_power_w": num(get(s, "normalizedPower"), digits=0),
        "avg_run_cadence_spm": num(get(s, "averageRunCadence"), digits=0),
        "avg_bike_cadence_rpm": num(get(s, "averageBikeCadence"), digits=0),
        "calories_kcal": num(get(s, "calories"), digits=0),
        "aerobic_training_effect_0_5": num(get(s, "trainingEffect")),
        "anaerobic_training_effect_0_5": num(get(s, "anaerobicTrainingEffect")),
        "training_effect_label": text(get(s, "trainingEffectLabel")),
        "training_load": num(get(s, "activityTrainingLoad"), digits=0),
        "recovery_hr_bpm": num(get(s, "recoveryHeartRate"), digits=0),
    }
    splits = [
        {
            "type": text(get(sp, "splitType")),
            "distance_km": meters_to_km(get(sp, "distance")),
            "duration_minutes": seconds_to_minutes(get(sp, "duration")),
            "avg_hr_bpm": num(get(sp, "averageHR"), digits=0),
            "avg_pace_min_per_km": pace_min_per_km(get(sp, "averageSpeed")),
        }
        for sp in get(a, "splitSummaries") or []
    ]
    if _is_status(workouts_raw):
        workouts: Any = workouts_raw
    else:
        workouts = [
            {
                "name": text(get(w, "workoutName")),
                "sport": text(get(w, "sport")),
                "steps": len(get(w, "steps") or []),
            }
            for w in (workouts_raw if isinstance(workouts_raw, list) else [])
        ] or {"status": "no structured workout"}
    return envelope(
        "get_activity",
        {
            "activity": detail,
            "splits": splits or {"status": "no splits recorded"},
            "workouts": workouts,
        },
    )


# -- T8 ------------------------------------------------------------------------------------


def get_body_metrics(src: GarminSource, start: str, end: str) -> dict[str, Any]:
    first, last = parse_range(start, end)
    weights = []
    for daily in src.weight_days(first, last):
        for w in get(daily, "allWeightMetrics") or []:
            if get(w, "weight") is None:
                continue
            weights.append(
                {
                    "date": text(get(w, "calendarDate") or get(daily, "summaryDate")),
                    "weight_kg": weight_kg(get(w, "weight")),
                    "bmi": num(get(w, "bmi")),
                    "body_fat_percent": num(get(w, "bodyFat")),
                    "body_water_percent": num(get(w, "bodyWater")),
                }
            )
    hydration = by_date(src.hydration(first, last))
    water = [
        {
            "date": day,
            "intake_ml": num(get(h, "valueInMl"), digits=0),
            "goal_ml": num(get(h, "goalInMl"), digits=0),
        }
        for day, h in sorted(hydration.items())
        if isinstance(get(h, "valueInMl"), int | float) and get(h, "valueInMl") > 0
    ]
    spo2 = _optional(lambda: src.spo2(last))
    fitness = _optional(lambda: src.fitness_age(last))
    data: dict[str, Any] = {
        "weight_entries": weights or {"status": "no weigh-ins recorded in this range"},
        "hydration": water or {"status": "no hydration logged in this range"},
        "as_of": last.isoformat(),
        "spo2": spo2
        if _is_status(spo2)
        else {
            "avg_spo2_percent": num(get(spo2, "averageSpO2") or get(spo2, "averageSpo2"), digits=0),
            "lowest_spo2_percent": num(
                get(spo2, "lowestSpO2") or get(spo2, "lowestSpo2"), digits=0
            ),
            "avg_sleep_spo2_percent": num(
                get(spo2, "avgSleepSpO2") or get(spo2, "avgSleepSpo2"), digits=0
            ),
        },
        "fitness_age": fitness
        if _is_status(fitness)
        else {
            "fitness_age_years": num(get(fitness, "fitnessAge")),
            "chronological_age_years": num(get(fitness, "chronologicalAge"), digits=0),
            "achievable_fitness_age_years": num(get(fitness, "achievableFitnessAge")),
        },
    }
    return envelope("get_body_metrics", data, start=first.isoformat(), end=last.isoformat())


# -- T9 ------------------------------------------------------------------------------------

KEY_WARNING_HOURS = 23.0


def get_account_status(src: GarminSource, today: date | None = None) -> dict[str, Any]:
    """Never raises for account problems: it explains them. Never exposes key or token."""
    today = today or date.today()
    try:
        token = src.token_status()
    except OwnMetricsError as exc:
        return envelope("get_account_status", {"connected": False, "problem": str(exc)})

    lifetime = token.get("token_issued_lifetime_hours")
    expiring = isinstance(lifetime, int | float) and lifetime < KEY_WARNING_HOURS
    probes = {
        "daily_summaries": lambda: src.daily_summaries(today, today),
        "sleep": lambda: src.sleep_summaries(today - timedelta(days=1), today),
        "hrv": lambda: src.hrv_summaries(today - timedelta(days=1), today),
        "activities": lambda: src.activities(today - timedelta(days=30), today, None, 1),
    }
    areas: dict[str, str] = {}
    for name, probe in probes.items():
        try:
            probe()
            areas[name] = "ok"
        except OwnMetricsError as exc:
            areas[name] = str(exc)
    data: dict[str, Any] = {
        "connected": True,
        "scopes": token.get("scopes", []),
        "key_expiry": (
            "Your Garmin Personal API key expires within the next day. Create a new key in "
            "Garmin Connect and run `ownmetrics-mcp auth`."
            if expiring
            else "Not exposed by Garmin. Garmin emails a reminder about a week before "
            "your key expires."
        ),
        "data_areas": areas,
        "not_provided_by_garmin": [
            "training readiness",
            "training status and load",
            "VO2 max",
            "gear",
            "devices",
        ],
    }
    return envelope("get_account_status", data)


__all__ = [
    "NOT_PROVIDED",
    "NOT_RECORDED",
    "get_account_status",
    "get_activity",
    "get_body_metrics",
    "get_daily_overview",
    "get_heart_rate",
    "get_hrv",
    "get_sleep",
    "get_stress_and_body_battery",
    "list_activities",
]
