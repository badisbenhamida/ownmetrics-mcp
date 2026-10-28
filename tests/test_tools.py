from datetime import date

import pytest
from fakes import FakeAuthenticator, FakeClient, make_source

from ownmetrics_mcp.errors import InvalidInputError
from ownmetrics_mcp.tools import data, insights
from ownmetrics_mcp.tools.shape import NOT_PROVIDED, NOT_RECORDED, pace_min_per_km, weight_kg

req = pytest.mark.req


@req("T1")
def test_daily_overview():
    src, _, _ = make_source()
    out = data.get_daily_overview(src, "2026-10-20")
    o = out["overview"]
    assert out["date"] == "2026-10-20"
    assert o["steps"] == 8020 and o["step_goal"] == 10000
    assert o["distance_km"] == 6.4
    assert o["resting_hr_bpm"] == 52
    assert o["body_battery_high_0_100"] == 92 and o["body_battery_end_of_day_0_100"] == 22
    assert o["calories_total_kcal"] == 2650
    assert o["sleep_hours"] == 7.25 and o["sleep_score_0_100"] == 81
    assert "not medical advice" in out["note"]


@req("T2")
def test_sleep_per_night():
    src, _, _ = make_source()
    out = data.get_sleep(src, "2026-10-18", "2026-10-20")
    assert [n["woke_up_on"] for n in out["nights"]] == ["2026-10-18", "2026-10-19", "2026-10-20"]
    n = out["nights"][0]
    assert n["sleep_hours"] == 7.5 and n["deep_minutes"] == 90.0 and n["rem_minutes"] == 105.0
    assert n["sleep_score_0_100"] == 84 and n["sleep_score_quality"] == "GOOD"
    assert n["avg_respiration_brpm"] == 14.2


@req("T3")
def test_hrv_per_night():
    src, _, _ = make_source()
    n = data.get_hrv(src, "2026-10-19", "2026-10-20")["nights"][1]
    assert n == {
        "woke_up_on": "2026-10-20",
        "last_night_avg_ms": 48,
        "weekly_avg_ms": 50,
        "last_night_5min_high_ms": 71,
        "status": "BALANCED",
        "baseline_balanced_low_ms": 44,
        "baseline_balanced_upper_ms": 58,
        "garmin_feedback": "HRV_BALANCED_1",
    }


@req("T4")
def test_stress_and_body_battery():
    src, _, _ = make_source()
    d = data.get_stress_and_body_battery(src, "2026-10-20", "2026-10-20")["days"][0]
    assert d["stress_avg_0_100"] == 29
    assert d["rest_minutes"] == 480.0 and d["high_stress_minutes"] == 20.0
    # high/low come from the series, ignoring None and Garmin's negative 'no data' markers
    assert d["body_battery_high_0_100"] == 92 and d["body_battery_low_0_100"] == 18
    assert d["body_battery_charged"] == 70


@req("T5")
def test_heart_rate_and_zones():
    src, _, _ = make_source()
    out = data.get_heart_rate(src, "2026-10-20")
    assert out["day"] == {
        "resting_hr_bpm": 52,
        "min_hr_bpm": 47,
        "max_hr_bpm": 163,
        "resting_hr_7day_avg_bpm": 53,
    }
    z = out["heart_rate_zones"][0]
    assert z["zone_1_floor_bpm"] == 110 and z["zone_5_floor_bpm"] == 168
    assert z["max_hr_used_bpm"] == 182


@req("T6")
def test_list_activities_with_type_and_limit():
    src, client, _ = make_source()
    out = data.list_activities(src, "2026-10-01", "2026-10-25", "cycling", 5)
    assert out["count"] == 5 and out["activity_type"] == "cycling"
    a = out["activities"][0]
    assert a["type"] == "cycling" and a["duration_minutes"] == 50.0 and a["distance_km"] == 10.0
    assert a["aerobic_training_effect_0_5"] == 3.4
    assert client.calls[-1][1][4] == "cycling"


@req("T6")
@pytest.mark.parametrize("limit", [0, 101])
def test_list_activities_limit_bounds(limit):
    src, _, _ = make_source()
    with pytest.raises(InvalidInputError):
        data.list_activities(src, "2026-10-01", "2026-10-25", None, limit)


@req("T7")
def test_activity_detail():
    src, _, _ = make_source()
    out = data.get_activity(src, 1234)
    a = out["activity"]
    assert a["type"] == "running" and a["distance_km"] == 10.0
    assert a["avg_pace_min_per_km"] == "5:00"
    assert "avg_speed_kmh" not in a  # R11: running shows pace, not speed
    assert a["normalized_power_w"] == 262 and a["training_load"] == 118
    assert out["splits"][0]["avg_pace_min_per_km"] == "5:00"
    assert out["workouts"] == [{"name": "Tempo 2x5k", "sport": "RUNNING", "workout_step_count": 3}]


@req("T7")
@pytest.mark.parametrize("bad", [0, -5, True])
def test_activity_id_must_be_positive(bad):
    src, _, _ = make_source()
    with pytest.raises(InvalidInputError):
        data.get_activity(src, bad)


@req("T8")
def test_body_metrics():
    src, _, _ = make_source()
    out = data.get_body_metrics(src, "2026-10-20", "2026-10-21")
    w = out["weight_entries"][0]
    assert w["weight_kg"] == 78.4 and w["bmi"] == 24.1 and w["body_fat_percent"] == 18.2
    # days with 0 ml logged are not shown as "0 ml drunk"
    assert out["hydration"] == [
        {"date": "2026-10-20", "status": "no hydration logged"},
        {"date": "2026-10-21", "intake_ml": 1800, "goal_ml": 2500},
    ]
    assert out["spo2"]["avg_spo2_percent"] == 96
    assert out["fitness_age"]["fitness_age_years"] == 44.3


@req("T9")
def test_account_status_connected():
    src, _, _ = make_source()
    out = data.get_account_status(src, today=date(2026, 10, 25))
    assert out["connected"] is True
    assert set(out["data_areas"].values()) == {"ok"}
    assert "Not exposed by Garmin" in out["key_expiry"]
    assert "VO2 max" in out["not_provided_by_garmin"]


@req("T9", "L6")
def test_account_status_warns_in_keys_final_day():
    src, _, _ = make_source(auth=FakeAuthenticator(lifetime_h=5))
    out = data.get_account_status(src, today=date(2026, 10, 25))
    assert "expires within about a day" in out["key_expiry"]


@req("T9", "AC6")
def test_account_status_explains_rejected_key_instead_of_crashing():
    src, _, _ = make_source(auth=FakeAuthenticator(fail_with=401))
    out = data.get_account_status(src)
    assert out["connected"] is False
    assert "ownmetrics-mcp auth" in out["problem"]


@req("T9", "L2")
def test_account_status_reports_area_not_provided():
    client = FakeClient()
    client.fail["get_daily_hrv_summaries"] = [404]
    src, _, _ = make_source(client)
    out = data.get_account_status(src, today=date(2026, 10, 25))
    assert out["data_areas"]["hrv"].endswith(NOT_PROVIDED + ".")


def test_pace_and_weight_conversions():
    assert pace_min_per_km(1000 / 299.6) == "5:00"  # rounding up to a whole minute
    assert pace_min_per_km(0) == NOT_RECORDED
    assert weight_kg(78400.0) == 78.4  # live API: grams
    assert weight_kg(78.4) == 78.4  # documented: kilograms


# -- R5: every numeric field name carries a unit or a scale ---------------------------------

UNIT_SUFFIXES = (
    "_bpm",
    "_ms",
    "_km",
    "_kmh",
    "_kcal",
    "_minutes",
    "_hours",
    "_0_100",
    "_0_5",
    "_w",
    "_rpm",
    "_spm",
    "_m",
    "_ml",
    "_percent",
    "_brpm",
    "_years",
    "_kg",
    "_min_per_km",
    "_per_week",
    "_steps",
    "_sessions",
)
UNITLESS = {
    "steps",
    "step_goal",
    "floors_climbed",
    "intensity_minutes_moderate",
    "intensity_minutes_vigorous",
    "count",
    "activity_id",
    "training_load",
    "bmi",
    "body_battery_charged",
    "workout_step_count",
    "body_battery_drained",
    # counts
    "sessions",
    "evening_sessions",
    "days",
    "days_with_data",
    "days_in_range",
    "paired_days",
    "nights_with_sleep_score",
    "nights_with_sleep_hours",
    "nights_with_hrv",
    # a correlation coefficient has no unit
    "correlation_r",
}


def _numeric_keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, int | float) and not isinstance(v, bool):
                out.add(k)
            _numeric_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _numeric_keys(v, out)
    return out


@req("R5")
def test_every_numeric_field_names_its_unit():
    src, _, _ = make_source()
    outputs = [
        data.get_daily_overview(src, "2026-10-20"),
        data.get_sleep(src, "2026-10-19", "2026-10-20"),
        data.get_hrv(src, "2026-10-19", "2026-10-20"),
        data.get_stress_and_body_battery(src, "2026-10-19", "2026-10-20"),
        data.get_heart_rate(src, "2026-10-20"),
        data.list_activities(src, "2026-10-01", "2026-10-20", None, 3),
        data.get_activity(src, 1),
        data.get_body_metrics(src, "2026-10-19", "2026-10-20"),
        insights.training_summary(src, "2026-10-01", "2026-10-20", "week"),
        insights.compare_periods(src, "2026-09-01", "2026-09-30", "2026-10-01", "2026-10-20"),
        insights.recovery_correlations(src, "2026-09-01", "2026-10-20"),
        insights.trend(src, "sleep_score", "2026-10-01", "2026-10-20", "day"),
        insights.trend(src, "training_hours", "2026-08-01", "2026-10-20", "month"),
        insights.weekly_review(src, today=date(2026, 10, 21)),
    ]
    keys = set().union(*(_numeric_keys(o, set()) for o in outputs))
    unlabelled = {k for k in keys if k not in UNITLESS and not k.endswith(UNIT_SUFFIXES)}
    assert unlabelled == set()
