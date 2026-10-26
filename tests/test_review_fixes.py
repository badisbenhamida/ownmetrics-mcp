"""Regression tests for the independent review of Milestone 2 (one test per finding)."""

import io
import os
import stat
import threading
import time
from datetime import date

import pytest
from fakes import FakeAuthenticator, FakeClient, make_source

from ownmetrics_mcp.cli import run_auth
from ownmetrics_mcp.dates import parse_day
from ownmetrics_mcp.errors import AuthError, InvalidInputError, NotPermittedError
from ownmetrics_mcp.garmin import GarminSource
from ownmetrics_mcp.tools import data
from ownmetrics_mcp.tools.shape import NOT_RECORDED

req = pytest.mark.req
TODAY = date(2026, 10, 25)


# -- Major 1: the final-day warning must not be hidden by a cached token ----------------


class CachingAuthenticator(FakeAuthenticator):
    """Like Garmin's client: returns a cached 24 h token unless forced."""

    def __init__(self) -> None:
        super().__init__(lifetime_h=24)
        self.cached = super().obtain_token("k")
        self.calls.clear()

    def obtain_token(self, api_key, *, force_refresh=False):
        self.calls.append(force_refresh)
        if not force_refresh:
            return self.cached
        self.lifetime_h = 5  # the key now ends in 5 h: a fresh token is capped
        return super().obtain_token(api_key, force_refresh=True)


@req("T9", "L6")
def test_status_uses_a_fresh_token_so_final_day_warning_is_not_hidden():
    auth = CachingAuthenticator()
    src, _, _ = make_source(auth=auth)
    src.profile_settings()  # warm the cached token
    out = data.get_account_status(src, today=TODAY)
    assert True in auth.calls
    assert "expires within about a day" in out["key_expiry"]


# -- Major 2: rejected key on data calls means not connected ----------------------------


@req("T9", "AC6")
def test_status_not_connected_when_data_calls_reject_the_key():
    client = FakeClient()
    client.fail["get_daily_summaries"] = [401, 401]
    src, _, _ = make_source(client)
    out = data.get_account_status(src, today=TODAY)
    assert out["connected"] is False
    assert "ownmetrics-mcp auth" in out["problem"]


@req("T9")
def test_status_probes_every_data_area_used_by_t1_to_t8():
    src, _, _ = make_source()
    areas = data.get_account_status(src, today=TODAY)["data_areas"]
    assert set(areas) == {
        "daily_summaries", "sleep", "hrv", "stress", "body_battery", "heart_rate",
        "heart_rate_zones", "activities", "weight", "hydration", "spo2", "fitness_age",
    }  # fmt: skip
    assert set(areas.values()) == {"ok"}


# -- Major 3: 403 on a data call is a permission gap, not an expired key (R8) -----------


@req("R8")
def test_403_on_data_call_is_not_permitted_and_rest_is_returned():
    client = FakeClient()
    client.fail["get_daily_spo2"] = [403]
    src, _, _ = make_source(client)
    out = data.get_body_metrics(src, "2026-10-20", "2026-10-21")
    assert out["spo2"] == {"status": "not allowed by your Personal API key's permissions"}
    assert out["weight_entries"][0]["weight_kg"] == 78.4


@req("R8")
def test_403_on_main_data_is_a_permission_error_not_auth():
    client = FakeClient()
    client.fail["get_daily_sleep_summaries"] = [403]
    src, _, _ = make_source(client)
    with pytest.raises(NotPermittedError, match="not allowed by your Personal API key"):
        src.sleep_summaries(TODAY, TODAY)


@req("R8", "AC6")
def test_403_at_sign_in_is_still_an_auth_error():
    src, _, _ = make_source(auth=FakeAuthenticator(fail_with=403))
    with pytest.raises(AuthError):
        src.profile_settings()


@req("T9", "R8")
def test_status_reports_permission_gap_per_area():
    client = FakeClient()
    client.fail["get_fitness_age"] = [403]
    src, _, _ = make_source(client)
    out = data.get_account_status(src, today=TODAY)
    assert out["connected"] is True
    assert "not allowed" in out["data_areas"]["fitness_age"]


# -- Major 4: unknown activity id ------------------------------------------------------


@req("T7")
def test_unknown_activity_id_says_not_found_not_unsupported():
    client = FakeClient()
    client.fail["get_activity"] = [404]
    src, _, _ = make_source(client)
    with pytest.raises(InvalidInputError, match="No activity with id 999"):
        data.get_activity(src, 999)


# -- R9: concurrency -------------------------------------------------------------------


@req("R9")
def test_concurrent_calls_sign_in_once_and_share_one_client():
    created: list[object] = []

    class SlowAuth(FakeAuthenticator):
        def obtain_token(self, api_key, *, force_refresh=False):
            time.sleep(0.02)  # widen the race window
            return super().obtain_token(api_key, force_refresh=force_refresh)

    auth = SlowAuth()

    def factory(token: str) -> FakeClient:
        c = FakeClient(token)
        created.append(c)
        return c

    src = GarminSource(
        key_loader=lambda: "TEST-KEY-concurrency-0003",
        authenticator_factory=lambda: auth,
        client_factory=factory,
        min_interval_s=0.0,
        sleep=lambda s: None,
    )
    threads = [threading.Thread(target=src.profile_settings) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(auth.calls) == 1
    assert len(created) == 1


@req("R9", "R3")
def test_throttle_spaces_concurrent_requests():
    stamps: list[float] = []

    class Stamping(FakeClient):
        def get_user_profile_settings(self):
            stamps.append(time.monotonic())
            return {}

    src = GarminSource(
        key_loader=lambda: "TEST-KEY-throttle-0004",
        authenticator_factory=FakeAuthenticator,
        client_factory=lambda t: Stamping(t),
        min_interval_s=0.03,
    )
    threads = [threading.Thread(target=src.profile_settings) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert min(gaps) >= 0.025


# -- R10: duplicates and ordering ------------------------------------------------------


@req("R10")
def test_duplicate_sleep_records_keep_the_most_complete():
    class Dupes(FakeClient):
        def get_daily_sleep_summaries(self, a, b):
            return [  # the complete record first, so "last one wins" would pick the wrong one
                {"calendarDate": b, "sleepTimeSeconds": 25200, "deepSleepSeconds": 3600},
                {"calendarDate": b, "sleepTimeSeconds": 1200},  # a nap-like fragment
            ]

    src, _, _ = make_source(Dupes())
    night = data.get_sleep(src, "2026-10-20", "2026-10-20")["nights"][0]
    assert night["sleep_hours"] == 7.0


@req("R10", "T6")
def test_activities_deduplicated_and_newest_first():
    class Repeats(FakeClient):
        def search_activities(self, *, start=0, limit=20, **kw):
            # Garmin ignoring `start`: the same page every time, in no particular order
            return [
                {"activityId": 1, "startTimeLocal": "2026-10-01 07:00:00"},
                {"activityId": 3, "startTimeLocal": "2026-10-03 07:00:00"},
                {"activityId": 2, "startTimeLocal": "2026-10-02 07:00:00"},
            ][:limit] * 1

    src, _, _ = make_source(Repeats())
    rows = src.activities(date(2026, 10, 1), date(2026, 10, 25), None, 100)
    assert [r["activityId"] for r in rows] == [3, 2, 1]


# -- Minor findings --------------------------------------------------------------------


@req("R1")
@pytest.mark.parametrize("loose", ["20261025", "2026-W43-7", "2026-10-25T00:00"])
def test_only_exact_yyyy_mm_dd_is_accepted(loose):
    with pytest.raises(InvalidInputError):
        parse_day(loose)


@req("AC3", "T2")
def test_zero_hour_sleep_is_no_data_not_zero():
    class ZeroSleep(FakeClient):
        def get_daily_sleep_summaries(self, a, b):
            return [{"calendarDate": b, "sleepTimeSeconds": 0, "deepSleepSeconds": 0}]

        def get_daily_sleep(self, d):
            return {"dailySleepDTO": {"calendarDate": d, "sleepTimeSeconds": 0}}

    src, _, _ = make_source(ZeroSleep())
    night = data.get_sleep(src, "2026-10-20", "2026-10-20")["nights"][0]
    assert night == {"night_of": "2026-10-20", "status": "no data recorded"}
    assert data.get_daily_overview(src, "2026-10-20")["overview"]["sleep"] == {
        "status": "no data recorded"
    }


@req("T4")
def test_body_battery_level_column_at_index_zero_is_respected():
    class IndexZero(FakeClient):
        def get_daily_body_battery(self, a, b, *, chunks=None):
            return [
                {
                    "date": b,
                    "bodyBatteryValueDescriptorList": [
                        {
                            "bodyBatteryValueDescriptorKey": "bodyBatteryLevel",
                            "bodyBatteryValueDescriptorIndex": 0,
                        },
                        {
                            "bodyBatteryValueDescriptorKey": "timestamp",
                            "bodyBatteryValueDescriptorIndex": 1,
                        },
                    ],
                    "bodyBatteryValuesArray": [[75, 1_700_000_000_000], [20, 1_700_000_900_000]],
                }
            ]

    src, _, _ = make_source(IndexZero())
    day = data.get_stress_and_body_battery(src, "2026-10-20", "2026-10-20")["days"][0]
    assert (day["body_battery_high_0_100"], day["body_battery_low_0_100"]) == (75, 20)


@req("AC3", "T7")
def test_workout_without_steps_says_not_recorded():
    class NoSteps(FakeClient):
        def get_activity_workouts(self, activity_id):
            return [{"workoutName": "Easy", "sport": "RUNNING"}]

    src, _, _ = make_source(NoSteps())
    assert data.get_activity(src, 1)["workouts"][0]["workout_step_count"] == NOT_RECORDED


@req("AC3", "T6")
def test_activities_without_id_are_skipped():
    class NoId(FakeClient):
        def search_activities(self, **kw):
            return [{"activityName": "ghost"}, {"activityId": 5, "activityName": "real"}]

    src, _, _ = make_source(NoId())
    rows = data.list_activities(src, "2026-10-01", "2026-10-25", None, 10)["activities"]
    assert [r["activity_id"] for r in rows] == [5]


@req("T9")
@pytest.mark.parametrize(
    "scope,expected",
    [
        ("PERSONAL_API_FITNESS_READ PERSONAL_API_USER_READ", ["PERSONAL_API_FITNESS_READ",
                                                               "PERSONAL_API_USER_READ"]),
        ([], NOT_RECORDED),
    ],
)  # fmt: skip
def test_scopes_split_and_never_empty(scope, expected, monkeypatch):
    import ownmetrics_mcp.garmin as g

    monkeypatch.setattr(g, "_token_claims", lambda t: {"iat": 0, "exp": 86400, "scope": scope})
    src, _, _ = make_source()
    assert data.get_account_status(src, today=TODAY)["scopes"] == expected


@req("C5", "T9")
def test_status_text_is_redacted(monkeypatch):
    from ownmetrics_mcp.errors import GarminUnavailableError

    canary = "CANARY-KEY-status-0005"
    src, _, _ = make_source(key=canary)
    src.token_status()  # registers the key as a secret

    def leaky(*a):
        raise GarminUnavailableError(f"upstream said {canary}")

    monkeypatch.setattr(src, "sleep_summaries", leaky)
    out = data.get_account_status(src, today=TODAY)
    assert canary not in str(out)


@req("R7")
@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_existing_world_readable_key_file_is_locked_down_before_writing(tmp_path):
    path = tmp_path / "connect-personal-api-key"
    path.write_text("old\n")
    os.chmod(path, 0o644)
    modes: list[int] = []
    real_fdopen = os.fdopen

    def spy(fd, *a, **kw):
        modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_fdopen(fd, *a, **kw)

    os.fdopen = spy  # type: ignore[assignment]
    try:
        run_auth(read_key=lambda _p: "TEST-KEY-perm-0006", authenticator_factory=FakeAuthenticator,
                 key_path=path, out=io.StringIO())  # fmt: skip
    finally:
        os.fdopen = real_fdopen  # type: ignore[assignment]
    assert modes == [0o600]  # already owner-only when the key bytes were written
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@req("R7")
def test_auth_warns_when_env_var_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "TEST-KEY-env-0007")
    out = io.StringIO()
    run_auth(read_key=lambda _p: "TEST-KEY-new-0008", authenticator_factory=FakeAuthenticator,
             key_path=tmp_path / "k", out=out)  # fmt: skip
    assert "GARMIN_PERSONAL_API_KEY" in out.getvalue()
    assert "TEST-KEY-env-0007" not in out.getvalue()
