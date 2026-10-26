import asyncio

import pytest
from fakes import FakeAuthenticator, make_source
from mcp.server.mcpserver.exceptions import ToolError

from ownmetrics_mcp.server import build_server

req = pytest.mark.req

EXPECTED = {
    "get_daily_overview": "T1",
    "get_sleep": "T2",
    "get_hrv": "T3",
    "get_stress_and_body_battery": "T4",
    "get_heart_rate": "T5",
    "list_activities": "T6",
    "get_activity": "T7",
    "get_body_metrics": "T8",
    "get_account_status": "T9",
    "training_summary": "I1",
    "compare_periods": "I2",
    "recovery_correlations": "I3",
    "trend": "I4",
}


@req("R6", "C1", "C7")
def test_all_tools_registered_read_only_with_medical_note():
    tools = {t.name: t for t in asyncio.run(build_server(lambda: make_source()[0]).list_tools())}
    assert set(tools) == set(EXPECTED)
    for name, tool in tools.items():
        assert tool.annotations is not None and tool.annotations.read_only_hint is True, name
        assert tool.annotations.destructive_hint is False, name
        assert "not medical advice" in (tool.description or ""), name
        assert (tool.description or "").startswith(EXPECTED[name] + "."), name


@req("AC6")
def test_rejected_key_surfaces_as_clear_tool_error():
    src, _, _ = make_source(auth=FakeAuthenticator(fail_with=401))
    server = build_server(lambda: src)
    with pytest.raises(ToolError, match="ownmetrics-mcp auth"):
        asyncio.run(server.call_tool("get_daily_overview", {"date": "2026-10-20"}))


@req("R1")
def test_bad_date_is_a_helpful_tool_error():
    server = build_server(lambda: make_source()[0])
    with pytest.raises(ToolError, match="2026-10-25"):
        asyncio.run(server.call_tool("get_sleep", {"start": "last week", "end": "2026-10-20"}))


def test_unexpected_errors_are_generic():
    class Exploding:
        def daily_summaries(self, *a):
            raise RuntimeError("internal detail /home/user/secret")

    server = build_server(lambda: Exploding())  # type: ignore[arg-type,return-value]
    with pytest.raises(ToolError) as err:
        asyncio.run(server.call_tool("get_daily_overview", {"date": "2026-10-20"}))
    assert "internal detail" not in str(err.value)
