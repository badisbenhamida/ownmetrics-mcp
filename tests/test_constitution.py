"""Constitution rules C2-C4 (SPEC section 2) checked against the code itself."""

import os
import re
from pathlib import Path

import pytest
from fakes import FakeClient, make_source

from ownmetrics_mcp.tools import data

req = pytest.mark.req
SRC = Path(__file__).resolve().parent.parent / "src" / "ownmetrics_mcp"
ALLOWED_HOSTS = {"connect.garmin.com", "github.com"}  # links shown to users, never fetched


@req("C2")
def test_no_network_destinations_besides_garmin():
    """The package fetches nothing itself; Garmin's client is the only network path."""
    urls = set()
    for path in SRC.rglob("*.py"):
        urls |= set(re.findall(r"https?://([a-zA-Z0-9.-]+)", path.read_text(encoding="utf-8")))
    assert urls <= ALLOWED_HOSTS, urls
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "requests.get(" not in source and "urllib.request" not in source, path
        assert "socket." not in source and "httpx" not in source, path


@req("C3", "C1")
def test_tools_write_nothing_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    before = set(os.listdir(tmp_path))
    src, _, _ = make_source(FakeClient())
    data.get_daily_overview(src, "2026-10-20")
    data.get_sleep(src, "2026-10-01", "2026-10-20")
    data.list_activities(src, "2026-10-01", "2026-10-20", None, 10)
    data.get_activity(src, 3)
    data.get_body_metrics(src, "2026-10-01", "2026-10-20")
    assert set(os.listdir(tmp_path)) == before


@req("C3")
def test_no_database_or_cache_modules():
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for banned in ("sqlite3", "shelve", "pickle", "diskcache", "lru_cache"):
            assert banned not in source, f"{banned} in {path.name}"


@req("C4", "AC3")
def test_missing_marker_is_explicit_text():
    src, _, _ = make_source(FakeClient(empty=True))
    out = data.get_heart_rate(src, "2026-10-20")
    assert out["day"] == {"status": "no data recorded"}
