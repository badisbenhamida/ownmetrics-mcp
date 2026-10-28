"""weekly_review (I5) on synthetic weeks whose answers were worked out by hand (AC4).
All data is invented."""

from datetime import date

import pytest
from fakes import FakeClient, make_source
from test_insights import Scripted, act, days

from ownmetrics_mcp.errors import InvalidInputError
from ownmetrics_mcp.tools import insights
from ownmetrics_mcp.tools.shape import NOT_APPLICABLE, NOT_RECORDED

req = pytest.mark.req

# "Today" is Wednesday 25 March 2026: the week so far is Mon 23 to Wed 25 (3 days),
# compared with Mon 16 to Wed 18, and with the 28 days Feb 23 to Mar 22.
TODAY = date(2026, 3, 25)
BASELINE = days("2026-02-23", 28)


def _partial_week():
    sleep = {d: (27000, 80) for d in BASELINE}  # 7.5 h, score 80, every night
    sleep |= {"2026-03-23": (25200, 74), "2026-03-24": (25200, 76)}  # Mar 25: no data
    hrv = {d: 50 for d in BASELINE} | {d: 44 for d in days("2026-03-23", 3)}
    daily = {d: 50 for d in BASELINE} | {d: 54 for d in days("2026-03-23", 3)}
    acts = [
        act("2026-03-17", "08:00", "road_biking", 60, 20000),  # last week, same days: 1.0 h
        act("2026-03-20", "08:00", "road_biking", 60, 20000),  # Friday: outside the same days
        act("2026-03-23", "19:00", "tennis_v2", 90, 4000, te=3.0),  # this week: 1.5 h
    ]
    return Scripted(acts, sleep=sleep, hrv=hrv, daily=daily)


@req("I5", "AC4")
def test_partial_week_is_compared_with_the_same_days_last_week():
    src, _, _ = make_source(_partial_week())
    out = insights.weekly_review(src, today=TODAY)
    assert out["week"] == {"first_day": "2026-03-23", "last_day": "2026-03-25", "complete": False}
    assert out["compared_with"]["previous_week_same_days"] == {
        "first_day": "2026-03-16",
        "last_day": "2026-03-18",
    }
    assert out["compared_with"]["previous_28_days"] == {
        "first_day": "2026-02-23",
        "last_day": "2026-03-22",
    }
    t = out["training"]
    assert (t["this_week"]["sessions"], t["this_week"]["total_hours"]) == (1, 1.5)
    assert (t["previous_week"]["sessions"], t["previous_week"]["total_hours"]) == (1, 1.0)
    assert t["this_week"]["evening_sessions"] == 1
    assert t["change"] == {"sessions": 0, "total_hours": 0.5, "total_hours_percent": 50.0}


@req("I5", "AC4", "C4")
def test_recovery_against_last_week_and_the_28_day_average():
    src, _, _ = make_source(_partial_week())
    rec = insights.weekly_review(src, today=TODAY)["recovery"]
    score = rec["sleep_score"]
    assert score["this_week"] == {"average_0_100": 75.0, "days_with_data": 2}  # (74 + 76) / 2
    assert score["previous_week"] == {"average_0_100": 80.0, "days_with_data": 3}
    assert score["previous_28_days"] == {"average_0_100": 80.0, "days_with_data": 28}
    assert score["change_vs_previous_week_0_100"] == -5.0
    assert score["difference_from_28_days_0_100"] == -5.0
    assert rec["sleep_hours"]["this_week"]["average_hours"] == 7.0
    assert rec["hrv_ms"]["difference_from_28_days_ms"] == -6.0
    assert rec["resting_hr_bpm"]["difference_from_28_days_bpm"] == 4.0
    stress = rec["stress_avg"]  # the fixture records no stress at all
    assert stress["this_week"] == {"average_0_100": NOT_RECORDED, "days_with_data": 0}
    assert stress["change_vs_previous_week_0_100"] == NOT_RECORDED


@req("I5", "AC4")
def test_best_worst_and_missing_nights():
    src, _, _ = make_source(_partial_week())
    nights = insights.weekly_review(src, today=TODAY)["nights"]
    assert nights["best"] == {
        "woke_up_on": "2026-03-24",
        "sleep_score_0_100": 76,
        "sleep_hours": 7.0,
    }
    assert nights["worst"]["woke_up_on"] == "2026-03-23"
    assert nights["nights_without_data"] == ["2026-03-25"]


@req("I5", "AC4")
def test_highlights_follow_the_fixed_rules_and_respect_the_boundaries():
    src, _, _ = make_source(_partial_week())
    flags = insights.weekly_review(src, today=TODAY)["highlights"]
    rules = [h["rule"] for h in flags]
    # HRV 44 vs 50 = 12% below; resting HR +4 bpm; training +50%.
    assert rules == ["hrv_vs_28_days", "resting_hr_vs_28_days", "training_vs_previous_week"]
    # Sleep score is exactly 5 points below (rule: MORE than 5) and only 1 night is
    # missing (rule: 2 or more): neither is flagged.
    assert (
        flags[0]["text"] == "HRV averaged 44 ms this week, 12% below your 28-day average of 50 ms."
    )
    assert "50% more than the same days last week (1.0 h)" in flags[2]["text"]


@req("I5", "AC4")
def test_a_quiet_complete_week_has_no_highlights():
    # The full week Mon 9 to Sun 15 March, reviewed later: compared with Mon 2 to Sun 8.
    base = days("2026-02-09", 35)
    sleep = {d: (27000, 80) for d in base} | {d: (27000, 76) for d in days("2026-03-09", 7)}
    hrv = {d: 50 for d in base} | {d: 46 for d in days("2026-03-09", 7)}  # 8%: under 10%
    daily = {d: 50 for d in base} | {d: 53 for d in days("2026-03-09", 7)}  # 3 bpm: not more
    acts = [act(d, "08:00", "road_biking", 60, 20000) for d in ("2026-03-03", "2026-03-10")]
    src, _, _ = make_source(Scripted(acts, sleep=sleep, hrv=hrv, daily=daily))
    out = insights.weekly_review(src, week_of="2026-03-11", today=date(2026, 3, 27))
    assert out["week"]["complete"] is True
    assert out["compared_with"]["previous_week_same_days"]["last_day"] == "2026-03-08"
    assert out["highlights"] == {"status": "nothing outside the set thresholds"}
    assert out["nights"]["nights_without_data"] == {"status": "none"}


@req("I5")
def test_training_after_a_week_without_any_is_flagged():
    acts = [act("2026-03-23", "08:00", "running", 30, 5000)]
    src, _, _ = make_source(Scripted(acts))
    out = insights.weekly_review(src, today=TODAY)
    assert out["training"]["change"]["total_hours_percent"] == NOT_APPLICABLE
    flag = next(h for h in out["highlights"] if h["rule"] == "training_vs_previous_week")
    assert flag["text"] == "Training time was 0.5 h, after none on the same days last week."
    missing = next(h for h in out["highlights"] if h["rule"] == "missing_nights")
    assert missing["text"] == "3 nights this week have no sleep data."


@req("I5", "C4", "AC3")
def test_no_data_at_all_is_explicit():
    src, _, _ = make_source(FakeClient(empty=True))
    out = insights.weekly_review(src, today=TODAY)
    assert out["nights"]["best"] == NOT_RECORDED
    assert out["recovery"]["hrv_ms"]["this_week"]["average_ms"] == NOT_RECORDED
    assert out["training"]["this_week"]["by_sport"] == {"status": "no activities recorded"}


@req("I5", "R1")
def test_week_of_is_validated():
    src, _, _ = make_source(Scripted())
    with pytest.raises(InvalidInputError, match="future"):
        insights.weekly_review(src, week_of="2026-04-01", today=TODAY)
    with pytest.raises(InvalidInputError, match="2026-10-25"):
        insights.weekly_review(src, week_of="last week", today=TODAY)
