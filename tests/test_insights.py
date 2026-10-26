"""Insight tools I1-I4 (SPEC 4.2) and the M3 rules R11-R12, on small synthetic fixtures whose
answers were worked out by hand (AC4). All data is invented."""

from datetime import date, timedelta

import pytest
from fakes import FakeClient, make_source

from ownmetrics_mcp.errors import InvalidInputError
from ownmetrics_mcp.tools import data, insights
from ownmetrics_mcp.tools.shape import NOT_APPLICABLE, NOT_RECORDED

req = pytest.mark.req


def act(day: str, time: str, kind: str, minutes: float, meters: float = 0.0, te: float = 2.0):
    return {
        "activityId": abs(hash((day, time, kind))) % 10**9,
        "activityName": f"Synthetic {kind}",
        "activityType": {"typeKey": kind},
        "startTimeLocal": f"{day} {time}:00",
        "duration": minutes * 60,
        "distance": meters,
        "aerobicTrainingEffect": te,
    }


class Scripted(FakeClient):
    """Returns exactly the records given, filtered to the requested dates."""

    def __init__(self, activities=(), sleep=None, hrv=None, daily=None):
        super().__init__()
        self.acts = sorted(activities, key=lambda a: a["startTimeLocal"], reverse=True)
        self.sleep = sleep or {}  # woke_up_on -> (sleep seconds, score)
        self.hrv = hrv or {}  # woke_up_on -> ms
        self.daily = daily or {}  # date -> resting HR

    @staticmethod
    def _within(day: str, a: str, b: str) -> bool:
        return a <= day <= b

    def search_activities(self, *, start=0, limit=20, start_date=None, end_date=None, **_):
        self._rec("search_activities", start, limit, start_date, end_date)
        hits = [
            x for x in self.acts if self._within(x["startTimeLocal"][:10], start_date, end_date)
        ]
        return hits[start : start + limit]

    def get_daily_sleep_summaries(self, a, b):
        self._rec("get_daily_sleep_summaries", a, b)
        return [
            {
                "calendarDate": d,
                "sleepTimeSeconds": secs,
                "deepSleepSeconds": 3600,
                "sleepScores": {"overall": {"value": score}},
            }
            for d, (secs, score) in self.sleep.items()
            if self._within(d, a, b)
        ]

    def get_daily_hrv_summaries(self, a, b):
        self._rec("get_daily_hrv_summaries", a, b)
        rows = [
            {"calendarDate": d, "lastNightAvg": v}
            for d, v in self.hrv.items()
            if self._within(d, a, b)
        ]
        return {"hrvSummaries": rows} if rows else None

    def get_daily_summaries(self, a, b):
        self._rec("get_daily_summaries", a, b)
        return {
            "data": [
                {"calendarDate": d, "heartRate": {"restingValue": v}}
                for d, v in self.daily.items()
                if self._within(d, a, b)
            ]
        }


def days(first: str, n: int) -> list[str]:
    d0 = date.fromisoformat(first)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


# Two weeks, Monday 2 March to Sunday 15 March 2026.
TWO_WEEKS = [
    act("2026-03-02", "19:00", "tennis_v2", 90, 4000, te=3.0),
    act("2026-03-04", "08:00", "strength_training", 30, 0, te=1.0),
    act("2026-03-09", "18:30", "tennis_v2", 60, 3000, te=2.0),
    act("2026-03-10", "10:00", "road_biking", 60, 20000, te=2.0),
]


# -- I1 ------------------------------------------------------------------------------------


@req("I1", "AC4")
def test_training_summary_by_week_matches_hand_totals():
    src, _, _ = make_source(Scripted(TWO_WEEKS))
    out = insights.training_summary(src, "2026-03-02", "2026-03-15", "week")
    w1, w2 = out["periods"]
    assert w1["period"] == "week of 2026-03-02" and "partial" not in w1
    assert (w1["sessions"], w1["total_hours"], w1["hours_per_week"]) == (2, 2.0, 2.0)
    assert w1["evening_sessions"] == 1
    assert w1["avg_aerobic_training_effect_0_5"] == 2.0  # (3 + 1) / 2
    assert w1["by_sport"]["tennis_v2"] == {"sessions": 1, "total_hours": 1.5, "distance_km": 4.0}
    assert w1["by_sport"]["strength_training"]["distance_km"] == NOT_APPLICABLE
    assert w2["by_sport"]["road_biking"]["distance_km"] == 20.0
    assert w2["evening_sessions"] == 1  # 18:30 counts as evening
    t = out["totals"]
    assert (t["sessions"], t["total_hours"], t["hours_per_week"], t["evening_sessions"]) == (
        4,
        4.0,
        2.0,
        2,
    )


@req("I1")
def test_training_summary_marks_partial_periods():
    src, _, _ = make_source(Scripted(TWO_WEEKS))
    weeks = insights.training_summary(src, "2026-03-04", "2026-03-15", "week")["periods"]
    assert weeks[0]["partial"] is True and weeks[0]["days_in_range"] == 5
    assert weeks[0]["sessions"] == 1  # the 2 March session is outside the range
    month = insights.training_summary(src, "2026-03-02", "2026-03-15", "month")["periods"]
    assert month[0]["period"] == "2026-03" and month[0]["days_in_range"] == 14
    assert month[0]["hours_per_week"] == 2.0  # 4 h over 14 days


@req("I1", "C4")
def test_training_summary_without_activities_is_explicit():
    src, _, _ = make_source(Scripted())
    out = insights.training_summary(src, "2026-03-02", "2026-03-08", "week")
    period = out["periods"][0]
    assert period["sessions"] == 0  # a real count of zero sessions, not missing data
    assert period["avg_aerobic_training_effect_0_5"] == NOT_APPLICABLE
    assert period["by_sport"] == {"status": "no activities recorded"}


# -- I2 ------------------------------------------------------------------------------------


@req("I2", "AC4")
def test_compare_periods_matches_hand_math():
    scores_a = [80, 82, 84, 86, 88, None, 90]  # one night missing in week A
    sleep = {d: (27000, s) for d, s in zip(days("2026-03-02", 7), scores_a, strict=True) if s}
    sleep |= {d: (25200, 75) for d in days("2026-03-09", 7)}
    hrv = {d: 50 for d in days("2026-03-02", 7)}  # no HRV at all in week B
    src, _, _ = make_source(Scripted(TWO_WEEKS, sleep=sleep, hrv=hrv))
    out = insights.compare_periods(
        src,
        "2026-03-02",
        "2026-03-08",
        "2026-03-09",
        "2026-03-15",
        ["sleep_score", "sleep_hours", "hrv_ms", "training_hours"],
    )["metrics"]
    s = out["sleep_score"]
    assert s["period_a"] == {"average_0_100": 85.0, "days_with_data": 6}  # 510 / 6
    assert s["period_b"] == {"average_0_100": 75.0, "days_with_data": 7}
    assert s["change_0_100"] == -10.0 and s["change_percent"] == -11.8  # -10 / 85
    assert out["sleep_hours"]["change_hours"] == -0.5  # 7.5 h -> 7.0 h
    h = out["hrv_ms"]
    assert h["period_b"]["average_ms"] == NOT_RECORDED and h["change_ms"] == NOT_RECORDED
    t = out["training_hours"]
    assert t["period_a"]["average_hours_per_week"] == 2.0
    assert t["change_hours_per_week"] == 0.0 and t["change_percent"] == 0.0


@req("I2")
def test_compare_periods_rejects_unknown_metric():
    src, _, _ = make_source(Scripted())
    with pytest.raises(InvalidInputError, match="Unknown metric"):
        insights.compare_periods(
            src, "2026-03-02", "2026-03-08", "2026-03-09", "2026-03-15", ["vo2"]
        )


@req("I2", "C4", "AC3")
def test_compare_periods_with_no_data_never_reports_zero():
    src, _, _ = make_source(FakeClient(empty=True))
    out = insights.compare_periods(
        src, "2026-03-02", "2026-03-08", "2026-03-09", "2026-03-15", ["sleep_score", "steps"]
    )["metrics"]
    for row in out.values():
        avg = next(v for k, v in row["period_a"].items() if k.startswith("average"))
        assert avg == NOT_RECORDED and row["change_percent"] == NOT_RECORDED


# -- I3 ------------------------------------------------------------------------------------


@req("AC4")
def test_pearson_and_strength_hand_values():
    # mean x 3, mean y 4; sxy 6, sxx 10, syy 6 -> r = 6 / sqrt(60)
    r = insights.pearson([1, 2, 3, 4, 5], [2, 4, 5, 4, 5])
    assert r == pytest.approx(0.7746, abs=1e-4)
    assert insights.pearson([1, 2, 3], [5, 5, 5]) is None  # no variation
    labels = [insights.strength(v) for v in (0.05, -0.2, 0.4, -0.6)]
    assert labels == ["none", "weak", "moderate", "strong"]


def _alternating(first: str, n: int):
    """Train 60 min on even-indexed days (the first three at 19:00), rest otherwise.
    The night after a training day scores 80, after a rest day 70."""
    acts, sleep = [], {}
    for i, d in enumerate(days(first, n)):
        trained = i % 2 == 0
        if trained:
            acts.append(act(d, "19:00" if i < 6 else "08:00", "tennis_v2", 60, 3000))
        nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        sleep[nxt] = (27000, 80 if trained else 70)
    return acts, sleep


@req("I3", "AC4")
def test_recovery_correlations_pairs_each_day_with_the_night_after():
    acts, sleep = _alternating("2026-03-01", 20)
    src, _, _ = make_source(Scripted(acts, sleep=sleep))
    out = insights.recovery_correlations(src, "2026-03-01", "2026-03-20")
    rows = {(r["training"], r["outcome"]): r for r in out["correlations"]}
    score = rows[("training_hours", "sleep_score")]
    assert score["paired_days"] == 20 and score["correlation_r"] == 1.0
    assert score["direction"] == "more training goes with higher sleep score"
    assert rows[("training_hours", "sleep_hours")]["status"] == "not enough variation to measure"
    assert rows[("training_hours", "hrv_ms")]["status"].startswith("not enough data")
    g = out["groups"]
    assert g["training_days"]["days"] == 10 and g["training_days"]["next_sleep_score_0_100"] == 80
    assert g["rest_days"]["next_sleep_score_0_100"] == 70
    assert g["evening_session_days"]["days"] == 3
    assert g["earlier_session_days"]["days"] == 7
    assert g["rest_days"]["next_hrv_ms"] == NOT_RECORDED
    assert g["training_days"]["next_sleep_hours"] == 7.5  # one unit suffix, not two
    assert "not that one causes the other" in out["how_to_read"]


@req("I3")
def test_recovery_correlations_needs_fourteen_paired_days():
    acts, sleep = _alternating("2026-03-01", 13)
    src, _, _ = make_source(Scripted(acts, sleep=sleep))
    out = insights.recovery_correlations(src, "2026-03-01", "2026-03-13")
    for row in out["correlations"]:
        assert "correlation_r" not in row
        assert row["status"].startswith("not enough")


# -- I4 ------------------------------------------------------------------------------------


@req("I4", "AC4")
def test_trend_up_with_hand_slope():
    # Score rises 0.5 a day for 30 days: +15 per 30 days.
    sleep = {d: (27000, 70 + 0.5 * i) for i, d in enumerate(days("2026-04-01", 30))}
    src, _, _ = make_source(Scripted(sleep=sleep))
    out = insights.trend(src, "sleep_score", "2026-04-01", "2026-04-30", "day")
    assert out["summary"]["direction"] == "up"
    assert out["summary"]["change_per_30_days_0_100"] == 15.0
    assert out["summary"]["average_0_100"] == pytest.approx(77.25, abs=0.05)
    rows = out["series"]
    assert rows[2]["rolling_7day_avg_0_100"] == NOT_RECORDED  # only 3 values so far
    assert rows[3]["rolling_7day_avg_0_100"] == pytest.approx(70.75, abs=0.05)


@req("I4")
@pytest.mark.parametrize(
    "values,direction",
    [
        ([60 - 0.5 * i for i in range(30)], "down"),
        ([70 + (0.05 if i % 2 else -0.05) for i in range(30)], "flat"),
    ],
)
def test_trend_direction(values, direction):
    sleep = {d: (27000, v) for d, v in zip(days("2026-04-01", 30), values, strict=True)}
    src, _, _ = make_source(Scripted(sleep=sleep))
    out = insights.trend(src, "sleep_score", "2026-04-01", "2026-04-30", "week")
    assert out["summary"]["direction"] == direction
    first_week = out["series"][0]  # 1 April 2026 is a Wednesday
    assert first_week["partial"] is True and first_week["days_in_range"] == 5


@req("I4")
def test_trend_of_training_is_a_weekly_rate():
    acts = [act(d, "08:00", "road_biking", 60, 20000) for d in days("2026-03-02", 28)[::2]]
    src, _, _ = make_source(Scripted(acts))
    out = insights.trend(src, "training_hours", "2026-03-02", "2026-03-29", "week")
    assert [p["average_hours_per_week"] for p in out["series"]] == [4.0, 3.0, 4.0, 3.0]
    assert out["summary"]["average_hours_per_week"] == 3.5


@req("I4", "C4")
def test_trend_with_too_little_data_says_so():
    sleep = {d: (27000, 80) for d in days("2026-04-01", 3)}
    src, _, _ = make_source(Scripted(sleep=sleep))
    out = insights.trend(src, "sleep_score", "2026-04-01", "2026-04-30", "month")
    assert out["summary"]["direction"].startswith("not enough data")
    assert out["summary"]["change_per_30_days_0_100"] == NOT_RECORDED


# -- R11 -----------------------------------------------------------------------------------


class Sports(FakeClient):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind

    def search_activities(self, **kw):
        return [act("2026-10-20", "08:00", self.kind, 30, 0 if "strength" in self.kind else 5000)]

    def get_activity(self, activity_id):
        out = super().get_activity(activity_id)
        out["activityTypeDTO"] = {"typeKey": self.kind}
        return out


@req("R11")
@pytest.mark.parametrize(
    "kind,pace,speed",
    [
        ("running", True, False),
        ("treadmill_running", True, False),
        ("hiking", True, False),
        ("road_biking", False, True),
        ("lap_swimming", False, True),
        ("tennis_v2", False, False),
        ("pickleball", False, False),
    ],
)
def test_pace_only_for_foot_sports_speed_for_others(kind, pace, speed):
    src, _, _ = make_source(Sports(kind))
    out = data.get_activity(src, 1)
    for row in (out["activity"], out["splits"][0]):
        assert ("avg_pace_min_per_km" in row) is pace, kind
        assert ("avg_speed_kmh" in row) is speed, kind
    if speed:
        assert out["activity"]["avg_speed_kmh"] == 12.0


@req("R11", "C4")
@pytest.mark.parametrize("kind", ["strength_training", "pilates", "breathwork"])
def test_sports_without_distance_say_not_applicable(kind):
    src, _, _ = make_source(Sports(kind))
    row = data.list_activities(src, "2026-10-01", "2026-10-25")["activities"][0]
    assert row["distance_km"] == NOT_APPLICABLE
    detail = data.get_activity(src, 1)["activity"]
    assert detail["distance_km"] == NOT_APPLICABLE
    assert "avg_pace_min_per_km" not in detail and "avg_speed_kmh" not in detail


# -- R12 -----------------------------------------------------------------------------------


@req("R12", "R2")
def test_insight_tools_accept_a_full_year_within_garmins_windows():
    src, client, _ = make_source(Scripted())
    insights.compare_periods(
        src, "2025-01-01", "2025-12-31", "2026-01-01", "2026-12-31", ["sleep_score", "hrv_ms"]
    )
    sleep_calls = [c for c in client.calls if c[0] == "get_daily_sleep_summaries"]
    assert len(sleep_calls) == 24  # 12 windows of at most 31 days per year
    with pytest.raises(InvalidInputError, match="367 days"):
        insights.trend(src, "sleep_score", "2025-01-01", "2026-01-02")
    with pytest.raises(InvalidInputError, match="91 days"):
        data.get_sleep(src, "2026-01-01", "2026-04-01")  # data tools stay at 90


@req("T2", "T3")
def test_nights_are_labelled_by_the_morning_they_end():
    src, _, _ = make_source()
    assert "woke_up_on" in data.get_sleep(src, "2026-10-20", "2026-10-20")["nights"][0]
    assert "woke_up_on" in data.get_hrv(src, "2026-10-20", "2026-10-20")["nights"][0]


# -- L1, L3, L4: what the Personal API does not offer stays out of scope -------------------


def _tool_names() -> set[str]:
    import asyncio

    from ownmetrics_mcp.server import build_server

    return {t.name for t in asyncio.run(build_server(lambda: make_source()[0]).list_tools())}


@req("L1")
def test_no_write_tools_and_no_write_calls():
    import inspect

    from ownmetrics_mcp.garmin import GarminSource

    assert all(
        not n.startswith(("create", "update", "delete", "set", "upload")) for n in _tool_names()
    )
    source = inspect.getsource(GarminSource)
    for verb in (".post(", ".put(", ".patch(", ".delete("):
        assert verb not in source


@req("L3", "L4")
def test_out_of_scope_areas_have_no_tools_and_are_explained():
    names = " ".join(_tool_names())
    for word in ("gear", "device", "workout_plan", "golf", "course"):
        assert word not in names
    src, _, _ = make_source()
    explained = data.get_account_status(src)["not_provided_by_garmin"]
    assert {"gear", "devices"} <= set(explained)


@req("I3")
def test_recovery_correlations_can_focus_on_one_sport():
    acts, sleep = _alternating("2026-03-01", 20)  # tennis on even days
    acts.append(act("2026-03-02", "08:00", "road_biking", 60, 20000))  # a cycling-only day
    acts.append(act("2026-03-04", "19:00", "road_biking", 45, 15000))  # also tennis-free
    src, _, _ = make_source(Scripted(acts, sleep=sleep))
    out = insights.recovery_correlations(src, "2026-03-01", "2026-03-20", "Tennis")
    assert out["activity_type"] == "tennis"
    assert out["sport_filter"] == {
        "matches": "tennis",
        "types_counted": ["tennis_v2"],
        "days_left_out_other_training": 2,
    }
    g = out["groups"]
    assert g["training_days"]["days"] == 10 and g["rest_days"]["days"] == 8
    rows = {(r["training"], r["outcome"]): r for r in out["correlations"]}
    assert rows[("training_hours", "sleep_score")]["paired_days"] == 18
    assert (
        "more tennis training goes with higher sleep score"
        in (rows[("training_hours", "sleep_score")]["direction"])
    )
    hrv = insights.recovery_correlations(src, "2026-03-01", "2026-03-20", "rowing")
    assert hrv["sport_filter"]["types_counted"] == "no matching activities"
