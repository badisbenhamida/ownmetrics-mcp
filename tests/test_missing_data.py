"""AC3 / C4: missing or unsupported data never appears as zero or blank."""

from datetime import date

import pytest
from fakes import FakeClient, make_source

from ownmetrics_mcp.tools import data
from ownmetrics_mcp.tools.shape import NOT_PROVIDED, NOT_RECORDED

req = pytest.mark.req


def run_all(src):
    return {
        "T1": data.get_daily_overview(src, "2026-10-20"),
        "T2": data.get_sleep(src, "2026-10-19", "2026-10-20"),
        "T3": data.get_hrv(src, "2026-10-19", "2026-10-20"),
        "T4": data.get_stress_and_body_battery(src, "2026-10-19", "2026-10-20"),
        "T5": data.get_heart_rate(src, "2026-10-20"),
        "T6": data.list_activities(src, "2026-10-01", "2026-10-20", None, 5),
        "T7": data.get_activity(src, 1),
        "T8": data.get_body_metrics(src, "2026-10-19", "2026-10-20"),
        "T9": data.get_account_status(src, today=date(2026, 10, 25)),
    }


def leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


IDENTIFIERS = {"activity_id", "count"}


@req("AC3", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9")
def test_no_zero_or_blank_when_garmin_has_no_data():
    src, _, _ = make_source(FakeClient(empty=True))
    for tool, out in run_all(src).items():
        for path, value in leaves(out):
            name = path.rsplit(".", 1)[-1]
            if name in IDENTIFIERS:
                continue
            assert value != 0, f"{tool}{path} is a zero for missing data"
            assert value not in ("", None), f"{tool}{path} is blank for missing data"


@req("AC3")
def test_empty_days_are_labelled_not_dropped():
    src, _, _ = make_source(FakeClient(empty=True))
    nights = data.get_sleep(src, "2026-10-19", "2026-10-20")["nights"]
    assert nights == [
        {"night_of": "2026-10-19", "status": "no data recorded"},
        {"night_of": "2026-10-20", "status": "no data recorded"},
    ]


@req("AC3", "L2")
def test_secondary_area_not_provided_is_labelled_and_rest_still_returned():
    client = FakeClient()
    client.fail["get_fitness_age"] = [404]
    client.fail["get_daily_spo2"] = [404]
    src, _, _ = make_source(client)
    out = data.get_body_metrics(src, "2026-10-20", "2026-10-21")
    assert out["fitness_age"] == {"status": NOT_PROVIDED}
    assert out["spo2"] == {"status": NOT_PROVIDED}
    assert out["weight_entries"][0]["weight_kg"] == 78.4


@req("AC3")
def test_partial_fields_say_not_recorded():
    class Partial(FakeClient):
        def get_daily_summaries(self, a, b):
            return {
                "data": [
                    {
                        "calendarDate": a,
                        "movement": {"steps": {"value": 5000}},
                        "stress": {"avgLevel": -1},
                    }
                ]
            }

    src, _, _ = make_source(Partial())
    o = data.get_daily_overview(src, "2026-10-20")["overview"]
    assert o["steps"] == 5000
    assert o["stress_avg_0_100"] == NOT_RECORDED  # Garmin's -1 means "no data"
    assert o["resting_hr_bpm"] == NOT_RECORDED
