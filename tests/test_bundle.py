"""One-click Claude Desktop bundle (SPEC 4.3, B1-B4). The build itself, with the official
mcpb validator and a stdio smoke run of the staged bundle, runs in CI via
scripts/build_bundle.py --smoke; these tests pin the manifest and the key handling."""

import asyncio
import json
import tomllib
from pathlib import Path

import pytest
from fakes import FakeAuthenticator, FakeClient

from ownmetrics_mcp import __version__
from ownmetrics_mcp.errors import AuthError, NoKeyError
from ownmetrics_mcp.garmin import KEY_ENV, GarminSource, load_key
from ownmetrics_mcp.server import build_server

req = pytest.mark.req
ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


@req("B1")
def test_bundle_runs_the_packaged_server_with_uv():
    server = MANIFEST["server"]
    assert MANIFEST["manifest_version"] == "0.4" and server["type"] == "uv"
    script = server["mcp_config"]["args"][-1]
    assert script in PROJECT["scripts"]  # the same entry point as `uvx ownmetrics-mcp`
    assert server["mcp_config"]["command"] == "uv"
    assert (ROOT / server["entry_point"]).is_file()


@req("B3", "B1")
def test_manifest_lists_exactly_the_registered_tools():
    registered = {t.name for t in asyncio.run(build_server(lambda: None).list_tools())}  # type: ignore[arg-type,return-value]
    listed = {t["name"] for t in MANIFEST["tools"]}
    assert listed == registered
    assert MANIFEST["tools_generated"] is False


@req("B3", "C6")
def test_manifest_is_descriptive_only_and_links_privacy():
    assert "garmin" not in MANIFEST["name"].lower()
    assert "garmin" not in MANIFEST["display_name"].lower()
    assert "not affiliated with Garmin" in MANIFEST["description"]
    assert "trademarks of Garmin" in MANIFEST["long_description"]
    assert any(u.endswith("PRIVACY.md") for u in MANIFEST["privacy_policies"])
    assert (ROOT / MANIFEST["icon"]).is_file()


@req("B4")
def test_bundle_version_matches_the_package():
    assert MANIFEST["version"] == PROJECT["version"] == __version__


@req("B4")
def test_release_workflow_builds_validates_and_attaches_the_bundle():
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "scripts/build_bundle.py --smoke" in release
    assert "gh release upload" in release and ".mcpb" in release
    build = (ROOT / "scripts" / "build_bundle.py").read_text(encoding="utf-8")
    assert '"validate"' in build and '"pack"' in build


# -- B2: the key setting -------------------------------------------------------------------


@req("B2")
def test_key_setting_is_sensitive_optional_and_passed_as_env():
    setting = MANIFEST["user_config"]["garmin_api_key"]
    assert setting["sensitive"] is True and setting["required"] is False
    env = MANIFEST["server"]["mcp_config"]["env"]
    assert env == {KEY_ENV: "${user_config.garmin_api_key}"}


@pytest.fixture
def saved_key(tmp_path, monkeypatch):
    """A key saved by `ownmetrics-mcp auth`, in Garmin's default location under HOME."""
    import garmin_personal_api.api_keys as api_keys

    key_file = tmp_path / "connect-personal-api-key"
    key_file.write_text("TEST-KEY-saved-file-0007", encoding="utf-8")
    key_file.chmod(0o600)
    monkeypatch.setattr(api_keys, "DEFAULT_API_KEY_FILE", str(key_file))
    return key_file


@req("B2")
@pytest.mark.parametrize("blank", ["", "   ", "${user_config.garmin_api_key}"])
def test_blank_or_unfilled_setting_falls_back_to_the_saved_key(blank, saved_key):
    assert load_key({KEY_ENV: blank}) == "TEST-KEY-saved-file-0007"


@req("B2")
def test_a_filled_setting_wins_over_the_saved_key(saved_key):
    assert load_key({KEY_ENV: "TEST-KEY-from-bundle-0008"}) == "TEST-KEY-from-bundle-0008"


@req("B2", "AC6")
def test_blank_setting_and_no_saved_key_explains_setup(tmp_path, monkeypatch):
    import garmin_personal_api.api_keys as api_keys

    monkeypatch.setattr(api_keys, "DEFAULT_API_KEY_FILE", str(tmp_path / "missing"))
    src = GarminSource(
        key_loader=lambda: load_key({KEY_ENV: ""}),
        authenticator_factory=FakeAuthenticator,
        client_factory=FakeClient,
        min_interval_s=0,
        sleep=lambda s: None,
    )
    with pytest.raises(NoKeyError, match="ownmetrics-mcp auth"):
        src.profile_settings()


@req("B2", "C5", "AC5")
def test_key_from_the_bundle_setting_never_leaks(capfd):
    canary = "CANARY-KEY-bundle-env-0009"
    src = GarminSource(
        key_loader=lambda: load_key({KEY_ENV: canary}),
        authenticator_factory=lambda: FakeAuthenticator(fail_with=401),
        client_factory=FakeClient,
        min_interval_s=0,
        sleep=lambda s: None,
    )
    with pytest.raises(AuthError) as err:
        src.profile_settings()
    out, errs = capfd.readouterr()
    assert canary not in str(err.value) and canary not in out and canary not in errs
