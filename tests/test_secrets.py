"""AC5 / C5: the API key (and bearer token) never appear in output, logs or errors."""

import asyncio
import json
import logging

import pytest
from fakes import FakeAuthenticator, FakeClient, make_jwt, make_source

from ownmetrics_mcp.redact import RedactingFilter, install_log_redaction, redact, register_secret
from ownmetrics_mcp.server import build_server

req = pytest.mark.req

CANARY = "CANARY-KEY-6f1c2e9a-do-not-leak"

TOOL_CALLS = [
    ("get_daily_overview", {"date": "2026-10-20"}),
    ("get_sleep", {"start": "2026-10-19", "end": "2026-10-20"}),
    ("get_hrv", {"start": "2026-10-19", "end": "2026-10-20"}),
    ("get_stress_and_body_battery", {"start": "2026-10-19", "end": "2026-10-20"}),
    ("get_heart_rate", {"date": "2026-10-20"}),
    ("list_activities", {"start": "2026-10-01", "end": "2026-10-20"}),
    ("get_activity", {"activity_id": 7}),
    ("get_body_metrics", {"start": "2026-10-19", "end": "2026-10-20"}),
    ("get_account_status", {}),
]


def call(server, name, args):
    try:
        result = asyncio.run(server.call_tool(name, args))
        return json.dumps(result.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


def _all_failing_client():
    client = FakeClient()
    for method in dir(client):
        if method.startswith(("get_", "search_")):
            client.fail[method] = [500, 401, 401, 429, 429, 429, 404]
    return client


@req("AC5", "C5")
@pytest.mark.parametrize("scenario", ["success", "server_errors", "rejected_key"])
def test_canary_key_never_appears(scenario, caplog, capfd):
    caplog.set_level(logging.DEBUG)
    client = _all_failing_client() if scenario == "server_errors" else FakeClient()
    auth = FakeAuthenticator(fail_with=401) if scenario == "rejected_key" else FakeAuthenticator()
    src, client, _ = make_source(client, auth, key=CANARY)
    server = build_server(lambda: src)
    outputs = [call(server, name, args) for name, args in TOOL_CALLS]
    for _ in range(3):  # also exercise retries after each queued failure
        outputs += [call(server, name, args) for name, args in TOOL_CALLS]
    raw = capfd.readouterr()  # raw stdout (the MCP channel) and stderr, beyond logging
    blob = "\n".join(outputs) + "\n" + caplog.text + raw.out + raw.err
    assert CANARY not in blob
    assert client.token == "" or client.token not in blob


@req("AC5", "C5")
def test_no_tool_accepts_a_key_or_token_argument():
    server = build_server(lambda: make_source()[0])
    tools = asyncio.run(server.list_tools())
    for tool in tools:
        props = set(tool.input_schema.get("properties", {}))
        assert not props & {"key", "api_key", "token", "password", "apikey"}, tool.name


@req("AC5")
def test_redact_scrubs_registered_secrets_headers_and_jwts():
    register_secret(CANARY)
    jwt = make_jwt()  # built at runtime: no token-shaped literal in the repo
    text = f"key={CANARY} Authorization: ApiKey abc123 Bearer {jwt}"
    out = redact(text)
    assert CANARY not in out and "abc123" not in out and jwt not in out


@req("AC5")
def test_log_filter_redacts_messages_and_args():
    register_secret(CANARY)
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "using %s", (CANARY,), None)
    RedactingFilter().filter(record)
    assert CANARY not in record.getMessage()


@req("AC5")
def test_installed_log_redaction_scrubs_real_log_output(caplog):
    register_secret(CANARY)
    install_log_redaction()
    caplog.set_level(logging.INFO, logger="garmin_personal_api")
    logging.getLogger("garmin_personal_api").info("GET /x with key %s", CANARY)
    assert caplog.records and CANARY not in caplog.text


@req("AC5", "R7")
def test_auth_unexpected_error_never_echoes_the_key():
    import io

    from ownmetrics_mcp.cli import run_auth

    class Boom:
        def __enter__(self):
            return self

        def __exit__(self, *e):
            return None

        def obtain_token(self, key, *, force_refresh=False):
            raise RuntimeError(f"connection reset while sending {key}")

    out = io.StringIO()
    code = run_auth(read_key=lambda _p: CANARY, authenticator_factory=Boom, out=out)
    assert code == 1 and CANARY not in out.getvalue()
