"""Access to Garmin's Personal API, built on Garmin's official Python client.

Responsibilities: key and token handling (R4, AC6), throttling and 429 backoff (R3),
splitting requests to Garmin's per-endpoint range limits (R2), and turning every failure
into a safe, user-facing error (C5). It stores no Garmin data (C3).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

import requests
from garmin_personal_api import (
    GarminPersonalApiClient,
    GarminPersonalApiError,
    HttpError,
    PersonalApiAuthenticator,
    resolve_api_key,
)

from ownmetrics_mcp.dates import windows
from ownmetrics_mcp.errors import (
    AuthError,
    GarminUnavailableError,
    NoKeyError,
    NotProvidedError,
    RateLimitedError,
)
from ownmetrics_mcp.redact import register_secret

log = logging.getLogger("ownmetrics_mcp.garmin")

# Garmin's per-request range limits, verified against the live API (SPEC section 3).
WINDOW_DAYS = {
    "daily_summaries": 31,
    "sleep": 31,
    "hydration": 31,
    "body_battery": 31,
    "stress": 28,
    "steps": 28,
    "hrv": 365,
    "weight": 365,
}
ACTIVITY_PAGE_SIZE = 40  # Garmin fails above ~45 per page.

Json = Any


class _Token(Protocol):
    access_token: str
    expires_at: float


class GarminSource:
    """Read-only facade over Garmin's client. One instance per server process."""

    def __init__(
        self,
        *,
        key_loader: Callable[[], str] = resolve_api_key,
        authenticator_factory: Callable[[], Any] = PersonalApiAuthenticator,
        client_factory: Callable[[str], Any] = GarminPersonalApiClient,
        min_interval_s: float = 0.25,
        max_rate_limit_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._key_loader = key_loader
        self._authenticator_factory = authenticator_factory
        self._client_factory = client_factory
        self._min_interval_s = min_interval_s
        self._max_retries = max_rate_limit_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._key: str | None = None
        self._authenticator: Any = None
        self._client: Any = None
        self._token: _Token | None = None
        self._last_request = float("-inf")

    # -- auth -------------------------------------------------------------------------------

    def _load_key(self) -> str:
        if self._key is None:
            try:
                key = self._key_loader()
            except GarminPersonalApiError:
                raise NoKeyError() from None
            except OSError:
                raise NoKeyError() from None
            if not key:
                raise NoKeyError()
            register_secret(key)
            self._key = key
        return self._key

    def _ensure_token(self, *, force: bool = False) -> None:
        if self._token is not None and not force:
            return
        key = self._load_key()
        if self._authenticator is None:
            self._authenticator = self._authenticator_factory()
        try:
            token = self._authenticator.obtain_token(key, force_refresh=force)
        except HttpError as exc:
            if exc.status_code in (400, 401, 403):
                raise AuthError() from None
            raise GarminUnavailableError(f"token request returned HTTP {exc.status_code}") from None
        except requests.RequestException:
            raise GarminUnavailableError("network error while signing in") from None
        except GarminPersonalApiError:
            raise AuthError() from None
        register_secret(token.access_token)
        self._token = token
        if self._client is None:
            self._client = self._client_factory(token.access_token)
        else:
            self._client.update_bearer_token(token.access_token)

    def token_status(self) -> dict[str, Any]:
        """Scopes, hours left and issued lifetime of the bearer token. Never the token itself.

        Garmin issues 24-hour tokens, capped at the key's expiry. A token whose issued
        lifetime is well under 24 h therefore means the key itself ends soon (L6).
        """
        self._ensure_token()
        assert self._token is not None
        claims = _token_claims(self._token)
        hours_left = (self._token.expires_at - self._wall_clock()) / 3600
        lifetime = None
        if isinstance(claims.get("iat"), int | float) and isinstance(
            claims.get("exp"), int | float
        ):
            lifetime = round((claims["exp"] - claims["iat"]) / 3600, 1)
        scopes = claims.get("scope", [])
        return {
            "token_hours_left": round(hours_left, 1),
            "token_issued_lifetime_hours": lifetime,
            "scopes": [str(s) for s in scopes] if isinstance(scopes, list) else [str(scopes)],
        }

    # -- request core -----------------------------------------------------------------------

    def _throttle(self) -> None:
        wait = self._min_interval_s - (self._monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._monotonic()

    def call(self, what: str, fn: Callable[[Any], Json]) -> Json:
        """Run one client call with refresh-on-401 (R4), backoff on 429 (R3), safe errors (C5)."""
        self._ensure_token()
        refreshed = False
        attempt = 0
        while True:
            self._throttle()
            try:
                return fn(self._client)
            except HttpError as exc:
                code = exc.status_code
                if code == 401 and not refreshed:
                    refreshed = True
                    self._ensure_token(force=True)
                    continue
                if code in (401, 403):
                    raise AuthError() from None
                if code == 404:
                    raise NotProvidedError(what) from None
                if code == 429 and attempt < self._max_retries:
                    attempt += 1
                    self._sleep(2.0 * 2 ** (attempt - 1))
                    continue
                if code == 429:
                    raise RateLimitedError() from None
                log.info("Garmin returned HTTP %s for %s", code, what)
                raise GarminUnavailableError(f"HTTP {code} for {what}") from None
            except requests.RequestException:
                raise GarminUnavailableError(f"network error for {what}") from None

    def _ranged(
        self,
        what: str,
        window_key: str,
        first: date,
        last: date,
        fn: Callable[[Any, str, str], Json],
        unwrap: str | None = None,
    ) -> list[Json]:
        out: list[Json] = []
        for a, b in windows(first, last, WINDOW_DAYS[window_key]):
            page = self.call(what, lambda c, a=a, b=b: fn(c, a.isoformat(), b.isoformat()))
            out.extend(_as_list(page, unwrap))
        return out

    # -- data (thin; shaping happens in tools/) --------------------------------------------

    def daily_summaries(self, first: date, last: date) -> list[Json]:
        return self._ranged(
            "Daily summaries",
            "daily_summaries",
            first,
            last,
            lambda c, a, b: c.get_daily_summaries(a, b),
            unwrap="data",
        )

    def sleep_summaries(self, first: date, last: date) -> list[Json]:
        return self._ranged(
            "Sleep data", "sleep", first, last, lambda c, a, b: c.get_daily_sleep_summaries(a, b)
        )

    def hrv_summaries(self, first: date, last: date) -> list[Json]:
        return self._ranged(
            "HRV data",
            "hrv",
            first,
            last,
            lambda c, a, b: c.get_daily_hrv_summaries(a, b),
            unwrap="hrvSummaries",
        )

    def stress(self, first: date, last: date) -> list[Json]:
        return self._ranged(
            "Stress data", "stress", first, last, lambda c, a, b: c.get_daily_stress(a, b)
        )

    def body_battery(self, first: date, last: date) -> list[Json]:
        return self._ranged(
            "Body Battery data",
            "body_battery",
            first,
            last,
            lambda c, a, b: c.get_daily_body_battery(a, b),
        )

    def hydration(self, first: date, last: date) -> list[Json]:
        return self._ranged(
            "Hydration data", "hydration", first, last, lambda c, a, b: c.get_daily_hydration(a, b)
        )

    def weight_days(self, first: date, last: date) -> list[Json]:
        return self._ranged(
            "Weight data",
            "weight",
            first,
            last,
            lambda c, a, b: c.get_weight_measurements(a, b),
            unwrap="dailyWeightSummaries",
        )

    def daily_sleep(self, day: date) -> Json:
        return self.call("Sleep data", lambda c: c.get_daily_sleep(day.isoformat()))

    def heart_rate(self, day: date) -> Json:
        return self.call("Heart rate data", lambda c: c.get_daily_heart_rate(day.isoformat()))

    def heart_rate_zones(self) -> Json:
        return self.call("Heart rate zones", lambda c: c.get_heart_rate_zones())

    def spo2(self, day: date) -> Json:
        return self.call("Pulse Ox (SpO2) data", lambda c: c.get_daily_spo2(day.isoformat()))

    def fitness_age(self, day: date) -> Json:
        return self.call("Fitness age", lambda c: c.get_fitness_age(day.isoformat()))

    def profile_settings(self) -> Json:
        return self.call("Profile settings", lambda c: c.get_user_profile_settings())

    def activities(
        self, first: date, last: date, activity_type: str | None, limit: int
    ) -> list[Json]:
        out: list[Json] = []
        start = 0
        while len(out) < limit:
            size = min(ACTIVITY_PAGE_SIZE, limit - len(out))
            page = _as_list(
                self.call(
                    "Activities",
                    lambda c, s=start, n=size: c.search_activities(
                        start=s,
                        limit=n,
                        start_date=first.isoformat(),
                        end_date=last.isoformat(),
                        activity_type=activity_type,
                    ),
                ),
                None,
            )
            out.extend(page)
            if len(page) < size:
                break
            start += size
        return out[:limit]

    def activity(self, activity_id: int) -> Json:
        return self.call("Activity details", lambda c: c.get_activity(activity_id))

    def activity_workouts(self, activity_id: int) -> Json:
        return self.call("Activity workouts", lambda c: c.get_activity_workouts(activity_id))


def _as_list(page: Json, unwrap: str | None) -> list[Json]:
    if page is None:
        return []
    if unwrap and isinstance(page, dict):
        page = page.get(unwrap)
    if page is None:
        return []
    if isinstance(page, list):
        return page
    return [page]


def _token_claims(token: _Token) -> dict[str, Any]:
    """Read the JWT payload without verifying or exposing the token."""
    import base64
    import json

    try:
        payload = token.access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims if isinstance(claims, dict) else {}
    except (IndexError, ValueError, TypeError, AttributeError):
        return {}
