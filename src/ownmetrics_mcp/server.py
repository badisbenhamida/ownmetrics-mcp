"""MCP server: registers the tools with read-only annotations (R6) and safe errors (C5)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from ownmetrics_mcp import __version__
from ownmetrics_mcp.errors import OwnMetricsError
from ownmetrics_mcp.garmin import GarminSource
from ownmetrics_mcp.redact import redact
from ownmetrics_mcp.tools import data

log = logging.getLogger("ownmetrics_mcp.server")

NOTE = (
    " Results are informational, not medical advice. Fields Garmin did not record say "
    "'not recorded'; never treat them as zero."
)

INSTRUCTIONS = (
    "Tools for the user's own Garmin data, read through Garmin's official Personal API. "
    "All tools are read-only. Dates are YYYY-MM-DD; ranges are inclusive and at most 90 days. "
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
            "score, Garmin's feedback, average heart rate, respiration and sleep stress." + NOTE
        ),
    )
    def get_sleep(start: Start, end: End) -> dict[str, Any]:
        return run(data.get_sleep, start, end)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "T3. Heart rate variability (HRV) per night over a date range: last-night average, "
            "weekly average, 5-minute high, status and personal baseline, in milliseconds." + NOTE
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

    return server
