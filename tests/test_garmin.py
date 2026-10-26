import json
from datetime import date

import pytest
import requests
from fakes import FakeAuthenticator, FakeClient, make_source
from garmin_personal_api import GarminPersonalApiError

from ownmetrics_mcp.errors import (
    AuthError,
    GarminUnavailableError,
    NoKeyError,
    NotProvidedError,
    RateLimitedError,
)
from ownmetrics_mcp.garmin import GarminSource

req = pytest.mark.req


@req("R2")
def test_daily_summaries_are_split_into_31_day_windows():
    src, client, _ = make_source()
    rows = src.daily_summaries(date(2026, 1, 1), date(2026, 3, 31))
    calls = [c for c in client.calls if c[0] == "get_daily_summaries"]
    assert len(calls) == 3
    assert len(rows) == 90


@req("R2")
@pytest.mark.parametrize(
    "method,client_name,days,expected_calls",
    [
        ("stress", "get_daily_stress", 90, 4),  # 28-day limit
        ("sleep_summaries", "get_daily_sleep_summaries", 90, 3),
        ("hrv_summaries", "get_daily_hrv_summaries", 90, 1),  # 365-day limit
        ("body_battery", "get_daily_body_battery", 62, 2),
    ],
)
def test_each_endpoint_respects_its_range_limit(method, client_name, days, expected_calls):
    src, client, _ = make_source()
    first = date(2026, 1, 1)
    last = date.fromordinal(first.toordinal() + days - 1)
    getattr(src, method)(first, last)
    assert len([c for c in client.calls if c[0] == client_name]) == expected_calls


@req("R2")
def test_activities_are_paged_below_garmins_page_limit():
    src, client, _ = make_source()
    rows = src.activities(date(2026, 1, 1), date(2026, 3, 1), None, 100)
    pages = [c for c in client.calls if c[0] == "search_activities"]
    assert all(c[1][1] <= 45 for c in pages)
    assert len(rows) == 55  # the fake account holds 55 activities


@req("R3")
def test_requests_are_throttled():
    now = [100.0]
    sleeps: list[float] = []
    client = FakeClient()
    src = GarminSource(
        key_loader=lambda: "TEST-KEY-not-a-real-key-0001",
        authenticator_factory=FakeAuthenticator,
        client_factory=lambda t: client,
        min_interval_s=0.5,
        sleep=sleeps.append,
        monotonic=lambda: now[0],
    )
    src.profile_settings()
    src.profile_settings()
    assert sleeps and sleeps[-1] == pytest.approx(0.5)


@req("R3")
def test_429_backs_off_then_succeeds():
    client = FakeClient()
    client.fail["get_user_profile_settings"] = [429, 429]
    sleeps: list[float] = []
    src, _, _ = make_source(client, sleeps=sleeps)
    assert src.profile_settings() == {"measurementSystem": "metric"}
    assert sleeps == [2.0, 4.0]  # exponential backoff actually happened


@req("R3", "L5")
def test_persistent_429_gives_clear_rate_limit_error():
    client = FakeClient()
    client.fail["get_user_profile_settings"] = [429, 429, 429]
    src, _, _ = make_source(client)
    with pytest.raises(RateLimitedError, match="limiting requests"):
        src.profile_settings()


@req("R4")
def test_401_refreshes_token_once_and_retries():
    client = FakeClient()
    client.fail["get_user_profile_settings"] = [401]
    src, _, auth = make_source(client)
    assert src.profile_settings() == {"measurementSystem": "metric"}
    assert auth.calls == [False, True]  # initial, then forced refresh


@req("R4", "AC6")
def test_repeated_401_gives_fix_it_message():
    client = FakeClient()
    client.fail["get_user_profile_settings"] = [401, 401]
    src, _, _ = make_source(client)
    with pytest.raises(AuthError) as err:
        src.profile_settings()
    assert "ownmetrics-mcp auth" in str(err.value)
    assert "connect.garmin.com" in str(err.value)


@req("AC6")
@pytest.mark.parametrize("code", [400, 401, 403])
def test_rejected_key_at_sign_in_gives_fix_it_message(code):
    src, _, _ = make_source(auth=FakeAuthenticator(fail_with=code))
    with pytest.raises(AuthError, match="expired or been deleted"):
        src.profile_settings()


@req("AC6")
def test_missing_key_explains_setup():
    def no_key() -> str:
        raise GarminPersonalApiError("No personal API key was provided.")

    src = GarminSource(
        key_loader=no_key,
        authenticator_factory=FakeAuthenticator,
        client_factory=FakeClient,
        min_interval_s=0,
        sleep=lambda s: None,
    )
    with pytest.raises(NoKeyError, match="ownmetrics-mcp auth"):
        src.profile_settings()


@req("L2")
def test_404_means_not_provided_by_garmin():
    client = FakeClient()
    client.fail["get_fitness_age"] = [404]
    src, _, _ = make_source(client)
    with pytest.raises(NotProvidedError, match="not provided by Garmin's Personal API"):
        src.fitness_age(date(2026, 10, 1))


@req("L7")
def test_server_errors_do_not_leak_response_bodies():
    client = FakeClient()
    client.fail["get_user_profile_settings"] = [500]
    src, _, _ = make_source(client)
    with pytest.raises(GarminUnavailableError) as err:
        src.profile_settings()
    assert "error body" not in str(err.value)
    assert "HTTP 500" in str(err.value)


def test_network_errors_are_reported_plainly():
    class Broken(FakeClient):
        def get_user_profile_settings(self):
            raise requests.ConnectionError("dns failure for host")

    src, _, _ = make_source(Broken())
    with pytest.raises(GarminUnavailableError, match="network error"):
        src.profile_settings()


@req("T9", "L6")
def test_token_status_reports_issued_lifetime_and_scopes():
    src, client, _ = make_source(auth=FakeAuthenticator(lifetime_h=6))
    status = src.token_status()
    assert status["token_issued_lifetime_hours"] == pytest.approx(6, abs=0.1)
    assert "PERSONAL_API_FITNESS_READ" in status["scopes"]
    blob = json.dumps(status)
    assert client.token and client.token not in blob  # the token's value never appears
