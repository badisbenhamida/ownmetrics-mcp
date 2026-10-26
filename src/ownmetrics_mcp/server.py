"""MCP server: registers the tools with read-only annotations (R6) and safe errors (C5)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from ownmetrics_mcp import __version__
from ownmetrics_mcp.errors import OwnMetricsError
from ownmetrics_mcp.garmin import GarminSource
from ownmetrics_mcp.redact import redact
from ownmetrics_mcp.tools import data, insights

log = logging.getLogger("ownmetrics_mcp.server")

NOTE = (
    " Results are informational, not medical advice. Fields Garmin did not record say "
    "'not recorded'; never treat them as zero."
)

INSTRUCTIONS = (
    "Tools for the user's own Garmin data, read through Garmin's official Personal API. "
    "All tools are read-only. Dates are YYYY-MM-DD; ranges are inclusive, at most 90 days for "
    "data tools (T1-T9) and 366 days for insight tools (I1-I4). Prefer an insight tool for "
    "questions about totals, comparisons, trends or links between training and sleep: it does "
    "the math in one call. Sleep and HRV are dated by the morning the night ended. "
    "Every field name carries its unit. 'not recorded' means Garmin has no value: never "
    "replace it with zero or an estimate. 'not provided by Garmin's Personal API' means Garmin "
    "does not offer that data to personal keys (for example training readiness, training "
    "status, VO2 max). Results are informational, not medical advice. If a tool reports an "
    "account problem, tell the user exactly what it says. This is an unofficial project, not "
    "affiliated with Garmin."
)

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)

Day = Annotated[str, Field(description="Date as YYYY-MM-DD, e.g. 2026-10-25.")]
Start = Annotated[str, Field(description="First date, YYYY-MM-DD (inclusive).")]
End = Annotated[
    str, Field(description="Last date, YYYY-MM-DD (inclusive); at most 90 days after start.")
]
LongEnd = Annotated[
    str, Field(description="Last date, YYYY-MM-DD (inclusive); at most 366 days after start.")
]
MetricName = Literal[
    "sleep_score",
    "sleep_hours",
    "deep_sleep_minutes",
    "hrv_ms",
    "resting_hr_bpm",
    "stress_avg",
    "body_battery_high",
    "steps",
    "training_hours",
    "training_sessions",
]


def build_server(source_factory: Callable[[], GarminSource] = GarminSource) -> MCPServer:
    server = MCPServer(
        name="ownmetrics",
        title="OwnMetrics (Garmin Personal API)",
        version=__version__,
        instructions=INSTRUCTIONS,
    )
    holder: dict[str, GarminSource] = {}

    def src() -> GarminSource:
        if "s" not in holder:
            holder["s"] = source_factory()
        return holder["s"]

    def run(fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return fn(src(), *args, **kwargs)
        except OwnMetricsError as exc:
            raise ToolError(redact(str(exc))) from None
        except Exception as exc:  # noqa: BLE001 - last line of defense: never leak internals
            log.error("Unexpected error in %s: %s", fn.__name__, redact(repr(exc)))
            raise ToolError(
                "Something unexpected went wrong reading your Garmin data. Try again; "
                "if it keeps happening, please open an issue on the project's GitHub page."
            ) from None

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T1. One day's overview: steps, distance, floors, resting/min/max heart rate, stress, "
            "Body Battery, calories, intensity minutes, sleep hours and sleep score." + NOTE
        ),
    )
    def get_daily_overview(date: Day) -> dict[str, Any]:
        return run(data.get_daily_overview, date)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T2. Sleep per night over a date range: hours, deep/light/REM/awake minutes, sleep "
            "score, Garmin's feedback, average heart rate, respiration and sleep stress. Each "
            "night is labelled woke_up_on, the morning it ended." + NOTE
        ),
    )
    def get_sleep(start: Start, end: End) -> dict[str, Any]:
        return run(data.get_sleep, start, end)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T3. Heart rate variability (HRV) per night over a date range: last-night average, "
            "weekly average, 5-minute high, status and personal baseline, in milliseconds. Each "
            "night is labelled woke_up_on, the morning it ended." + NOTE
        ),
    )
    def get_hrv(start: Start, end: End) -> dict[str, Any]:
        return run(data.get_hrv, start, end)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T4. Per day over a date range: average stress (0-100), minutes in each stress band, "
            "and Body Battery high, low, charged and drained." + NOTE
        ),
    )
    def get_stress_and_body_battery(start: Start, end: End) -> dict[str, Any]:
        return run(data.get_stress_and_body_battery, start, end)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T5. One day's heart rate (resting, min, max, 7-day resting average) and the user's "
            "heart rate zones." + NOTE
        ),
    )
    def get_heart_rate(date: Day) -> dict[str, Any]:
        return run(data.get_heart_rate, date)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T6. List activities in a date range, newest first, optionally filtered by Garmin "
            "activity type key (e.g. running, cycling, indoor_cycling, lap_swimming, "
            "strength_training). Returns ids for get_activity." + NOTE
        ),
    )
    def list_activities(
        start: Start,
        end: End,
        activity_type: Annotated[
            str | None, Field(description="Optional Garmin activity type key, e.g. 'running'.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Maximum activities, 1-100.")] = 20,
    ) -> dict[str, Any]:
        return run(data.list_activities, start, end, activity_type, limit)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T7. Details of one activity by id: duration, distance, pace, speed, heart rate, "
            "power, cadence, training effect and load, splits and structured workout steps." + NOTE
        ),
    )
    def get_activity(
        activity_id: Annotated[int, Field(gt=0, description="Activity id from list_activities.")],
    ) -> dict[str, Any]:
        return run(data.get_activity, activity_id)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T8. Body metrics over a date range: weigh-ins (kg), BMI, body fat, hydration; plus "
            "Pulse Ox (SpO2) and fitness age as of the end date." + NOTE
        ),
    )
    def get_body_metrics(start: Start, end: End) -> dict[str, Any]:
        return run(data.get_body_metrics, start, end)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T9. Check the Garmin connection: whether the key works, granted scopes, a warning if "
            "the key expires within a day, which data areas respond, and what Garmin does not "
            "provide. Use this first when something fails." + NOTE
        ),
    )
    def get_account_status() -> dict[str, Any]:
        return run(data.get_account_status)

    # -- insight tools (SPEC 4.2) --------------------------------------------------------

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "I1. Training totals over up to 366 days, by week or month: sessions, hours, hours "
            "per week, evening sessions, average aerobic training effect, and a per-sport "
            "breakdown. Use for 'how much did I train' questions." + NOTE
        ),
    )
    def training_summary(
        start: Start,
        end: LongEnd,
        group_by: Annotated[
            Literal["week", "month"], Field(description="Group by 'week' or 'month'.")
        ] = "week",
    ) -> dict[str, Any]:
        return run(insights.training_summary, start, end, group_by)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "I2. Compare two periods (each up to 366 days), e.g. this October vs last October: "
            "average sleep, HRV, resting heart rate, stress, Body Battery, steps and training "
            "per week, with change and % change and how many days of data each side has." + NOTE
        ),
    )
    def compare_periods(
        a_start: Annotated[str, Field(description="Period A first date, YYYY-MM-DD.")],
        a_end: Annotated[str, Field(description="Period A last date, YYYY-MM-DD.")],
        b_start: Annotated[str, Field(description="Period B first date, YYYY-MM-DD.")],
        b_end: Annotated[str, Field(description="Period B last date, YYYY-MM-DD.")],
        metrics: Annotated[
            list[MetricName] | None,
            Field(description="Metrics to compare; leave empty for all."),
        ] = None,
    ) -> dict[str, Any]:
        return run(insights.compare_periods, a_start, a_end, b_start, b_end, metrics)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "I3. Does training go with better or worse sleep and HRV? Over up to 366 days, pairs "
            "each day's training with the night after it: correlations with sample size and "
            "strength, plus averages for training vs rest days and evening vs earlier sessions. "
            "Can focus on one sport. "
            "Correlation is not cause; say so when answering." + NOTE
        ),
    )
    def recovery_correlations(
        start: Start,
        end: LongEnd,
        activity_type: Annotated[
            str | None,
            Field(
                description="Optional sport to look at on its own, matched by name "
                "(e.g. 'tennis', 'running', 'cycling'). Days with only other sports are left out."
            ),
        ] = None,
    ) -> dict[str, Any]:
        return run(insights.recovery_correlations, start, end, activity_type)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "I4. Trend of one metric over up to 366 days, by day, week or month: the series, "
            "change per 30 days and whether it is going up, down or flat. Daily grouping adds "
            "a 7-day rolling average." + NOTE
        ),
    )
    def trend(
        metric: Annotated[MetricName, Field(description="The metric to follow.")],
        start: Start,
        end: LongEnd,
        group_by: Annotated[
            Literal["day", "week", "month"], Field(description="Group by day, week or month.")
        ] = "week",
    ) -> dict[str, Any]:
        return run(insights.trend, metric, start, end, group_by)

    return server
