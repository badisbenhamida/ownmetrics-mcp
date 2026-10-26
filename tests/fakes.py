"""Synthetic stand-ins for Garmin's client. All data is invented; no real person's data
is ever committed. Shapes follow Garmin's published Personal API schemas."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from garmin_personal_api import HttpError

from ownmetrics_mcp.garmin import GarminSource


def make_jwt(
    lifetime_h: float = 24.0, scopes: list[str] | None = None, issued: float | None = None
) -> str:
    iat = issued if issued is not None else time.time()
    payload = {
        "iat": int(iat),
        "exp": int(iat + lifetime_h * 3600),
        "scope": scopes or ["PERSONAL_API_FITNESS_READ", "PERSONAL_API_WELLNESS_READ"],
    }

    def b64(obj: Any) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64(payload)}.c2lnbmF0dXJlLXBsYWNlaG9sZGVy"


@dataclass
class FakeToken:
    access_token: str
    expires_at: float


class FakeAuthenticator:
    def __init__(self, fail_with: int | None = None, lifetime_h: float = 24.0) -> None:
        self.fail_with = fail_with
        self.lifetime_h = lifetime_h
        self.calls: list[bool] = []

    def __enter__(self) -> FakeAuthenticator:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def obtain_token(self, api_key: str, *, force_refresh: bool = False) -> FakeToken:
        self.calls.append(force_refresh)
        if self.fail_with:
            raise HttpError(
                status_code=self.fail_with,
                method="POST",
                url="https://personal.connectapi.garmin.com/token",
                response_text=f"invalid key {api_key}",
            )
        token = make_jwt(self.lifetime_h) + f"x{len(self.calls)}"
        return FakeToken(token, time.time() + self.lifetime_h * 3600)


def days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def _d(s: str) -> date:
    return date.fromisoformat(s)


class FakeClient:
    """Mimics garmin_personal_api.GarminPersonalApiClient's methods and raw JSON shapes."""

    def __init__(self, token: str = "", *, empty: bool = False) -> None:
        self.token = token
        self.empty = empty
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail: dict[str, list[int]] = {}  # method -> queued HTTP status codes to raise

    def update_bearer_token(self, token: str) -> None:
        self.token = token

    def _maybe_fail(self, name: str) -> None:
        queue = self.fail.get(name)
        if queue:
            code = queue.pop(0)
            raise HttpError(
                status_code=code,
                method="GET",
                url=f"https://personal.connectapi.garmin.com/{name}",
                response_text=f"error body with token {self.token}",
            )

    def _rec(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        self._maybe_fail(name)

    # range endpoints --------------------------------------------------------------------
    def get_daily_summaries(self, a: str, b: str) -> Any:
        self._rec("get_daily_summaries", a, b)
        if self.empty:
            return {"data": []}
        return {
            "data": [
                {
                    "calendarDate": d.isoformat(),
                    "movement": {
                        "steps": {"value": 8000 + d.day, "goal": 10000, "distanceInMeters": 6400.0},
                        "floorsAscended": {"value": 7},
                    },
                    "heartRate": {"restingValue": 52, "minValue": 48, "maxValue": 151},
                    "stress": {"avgLevel": 31, "maxLevel": 88},
                    "bodyBattery": {
                        "maxValue": 92,
                        "minValue": 18,
                        "chargedValue": 70,
                        "drainedValue": 74,
                        "endOfDayValue": 22,
                    },
                    "calories": {"burnedTotal": 2650, "burnedActive": 720},
                    "intensityMinutes": {"moderate": 25, "vigorous": 14},
                }
                for d in days(_d(a), _d(b))
            ]
        }

    def get_daily_sleep_summaries(self, a: str, b: str) -> Any:
        self._rec("get_daily_sleep_summaries", a, b)
        if self.empty:
            return []
        return [
            {
                "calendarDate": d.isoformat(),
                "sleepTimeSeconds": 27000,
                "deepSleepSeconds": 5400,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 6300,
                "awakeSleepSeconds": 900,
                "avgHeartRate": 51.4,
                "averageRespirationValue": 14.2,
                "avgSleepStress": 17.5,
                "sleepScoreFeedback": "POSITIVE_DEEP",
                "sleepScores": {"overall": {"value": 84, "qualifierKey": "GOOD"}},
            }
            for d in days(_d(a), _d(b))
        ]

    def get_daily_hrv_summaries(self, a: str, b: str) -> Any:
        self._rec("get_daily_hrv_summaries", a, b)
        if self.empty:
            return None  # Garmin answers 204 No Content
        return {
            "hrvSummaries": [
                {
                    "calendarDate": d.isoformat(),
                    "lastNightAvg": 48,
                    "weeklyAvg": 50,
                    "lastNight5MinHigh": 71,
                    "status": "BALANCED",
                    "feedbackPhrase": "HRV_BALANCED_1",
                    "baseline": {"balancedLow": 44, "balancedUpper": 58},
                }
                for d in days(_d(a), _d(b))
            ]
        }

    def get_daily_stress(self, a: str, b: str) -> Any:
        self._rec("get_daily_stress", a, b)
        if self.empty:
            return []
        return [
            {
                "calendarDate": d.isoformat(),
                "values": {
                    "overallStressLevel": 29.0,
                    "restStressDuration": 28800.0,
                    "lowStressDuration": 14400.0,
                    "mediumStressDuration": 5400.0,
                    "highStressDuration": 1200.0,
                },
            }
            for d in days(_d(a), _d(b))
        ]

    def get_daily_body_battery(self, a: str, b: str, *, chunks: Any = None) -> Any:
        self._rec("get_daily_body_battery", a, b)
        if self.empty:
            return []
        return [
            {
                "date": d.isoformat(),
                "charged": 70,
                "drained": 74,
                "bodyBatteryValueDescriptorList": [
                    {
                        "bodyBatteryValueDescriptorKey": "timestamp",
                        "bodyBatteryValueDescriptorIndex": 0,
                    },
                    {
                        "bodyBatteryValueDescriptorKey": "bodyBatteryLevel",
                        "bodyBatteryValueDescriptorIndex": 1,
                    },
                ],
                "bodyBatteryValuesArray": [[1, 40], [2, 92], [3, None], [4, 18], [5, -1]],
            }
            for d in days(_d(a), _d(b))
        ]

    def get_daily_hydration(self, a: str, b: str) -> Any:
        self._rec("get_daily_hydration", a, b)
        if self.empty:
            return []
        return [
            {
                "calendarDate": d.isoformat(),
                "valueInMl": 1800.0 if d.day % 2 else 0.0,
                "goalInMl": 2500.0,
            }
            for d in days(_d(a), _d(b))
        ]

    def get_weight_measurements(self, a: str, b: str) -> Any:
        self._rec("get_weight_measurements", a, b)
        if self.empty:
            return {"dailyWeightSummaries": []}
        return {
            "dailyWeightSummaries": [
                {
                    "summaryDate": b,
                    "allWeightMetrics": [
                        {
                            "calendarDate": b,
                            "weight": 78400.0,
                            "bmi": 24.1,
                            "bodyFat": 18.2,
                            "bodyWater": 57.3,
                        }
                    ],
                }
            ]
        }

    # single-day endpoints ---------------------------------------------------------------
    def get_daily_sleep(self, d: str) -> Any:
        self._rec("get_daily_sleep", d)
        if self.empty:
            return {}
        return {
            "dailySleepDTO": {
                "calendarDate": d,
                "sleepTimeSeconds": 26100,
                "sleepScores": {"overall": {"value": 81}},
            }
        }

    def get_daily_heart_rate(self, d: str) -> Any:
        self._rec("get_daily_heart_rate", d)
        if self.empty:
            return {"calendarDate": d}
        return {
            "calendarDate": d,
            "restingHeartRate": 52,
            "minHeartRate": 47,
            "maxHeartRate": 163,
            "lastSevenDaysAvgRestingHeartRate": 53,
        }

    def get_heart_rate_zones(self) -> Any:
        self._rec("get_heart_rate_zones")
        if self.empty:
            return []
        return [
            {
                "sport": "DEFAULT",
                "trainingMethod": "HR_RESERVE",
                "zone1Floor": 110,
                "zone2Floor": 125,
                "zone3Floor": 140,
                "zone4Floor": 155,
                "zone5Floor": 168,
                "maxHeartRateUsed": 182,
            }
        ]

    def get_daily_spo2(self, d: str) -> Any:
        self._rec("get_daily_spo2", d)
        if self.empty:
            return {"calendarDate": d}
        return {"calendarDate": d, "averageSpO2": 96.0, "lowestSpO2": 89, "avgSleepSpO2": 95.0}

    def get_fitness_age(self, d: str) -> Any:
        self._rec("get_fitness_age", d)
        if self.empty:
            return {}
        return {"chronologicalAge": 52, "fitnessAge": 44.3, "achievableFitnessAge": 41.0}

    def get_user_profile_settings(self) -> Any:
        self._rec("get_user_profile_settings")
        return {"measurementSystem": "metric"}

    def search_activities(
        self,
        *,
        start: int = 0,
        limit: int = 20,
        start_date: str | None = None,
        end_date: str | None = None,
        activity_type: str | None = None,
    ) -> Any:
        self._rec("search_activities", start, limit, start_date, end_date, activity_type)
        if self.empty:
            return []
        total = 55
        items = [
            {
                "activityId": 1000 + i,
                "activityName": f"Synthetic run {i}",
                "activityType": {"typeKey": activity_type or "running"},
                "startTimeLocal": "2026-10-20 07:00:00",
                "duration": 3000.0,
                "distance": 10000.0,
                "averageHR": 148.0,
                "maxHR": 171.0,
                "calories": 690.0,
                "aerobicTrainingEffect": 3.4,
                "anaerobicTrainingEffect": 1.2,
            }
            for i in range(start, min(start + limit, total))
        ]
        return items

    def get_activity(self, activity_id: int) -> Any:
        self._rec("get_activity", activity_id)
        if self.empty:
            return {"activityId": activity_id, "summaryDTO": {}}
        return {
            "activityId": activity_id,
            "activityName": "Synthetic tempo run",
            "activityTypeDTO": {"typeKey": "running"},
            "summaryDTO": {
                "startTimeLocal": "2026-10-20T07:00:00",
                "duration": 3000.0,
                "movingDuration": 2950.0,
                "distance": 10000.0,
                "elevationGain": 85.0,
                "averageSpeed": 3.3333,
                "averageHR": 148.0,
                "maxHR": 171.0,
                "averagePower": 255.0,
                "normalizedPower": 262.0,
                "averageRunCadence": 172.0,
                "calories": 690.0,
                "trainingEffect": 3.4,
                "anaerobicTrainingEffect": 1.2,
                "trainingEffectLabel": "TEMPO",
                "activityTrainingLoad": 118.0,
                "recoveryHeartRate": 128,
            },
            "splitSummaries": [
                {
                    "splitType": "INTERVAL_ACTIVE",
                    "distance": 5000.0,
                    "duration": 1500.0,
                    "averageHR": 150.0,
                    "averageSpeed": 3.3333,
                }
            ],
        }

    def get_activity_workouts(self, activity_id: int) -> Any:
        self._rec("get_activity_workouts", activity_id)
        if self.empty:
            return []
        return [{"workoutName": "Tempo 2x5k", "sport": "RUNNING", "steps": [{}, {}, {}]}]


def make_source(
    client: FakeClient | None = None,
    auth: FakeAuthenticator | None = None,
    key: str = "TEST-KEY-not-a-real-key-0001",
    sleeps: list[float] | None = None,
) -> tuple[GarminSource, FakeClient, FakeAuthenticator]:
    client = client or FakeClient()
    auth = auth or FakeAuthenticator()

    def client_factory(token: str) -> FakeClient:
        client.token = token
        return client

    record = sleeps.append if sleeps is not None else (lambda s: None)
    src = GarminSource(
        key_loader=lambda: key,
        authenticator_factory=lambda: auth,
        client_factory=client_factory,
        min_interval_s=0.0,
        sleep=record,
    )
    return src, client, auth
