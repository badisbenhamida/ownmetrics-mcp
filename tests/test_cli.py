import io
import os
import stat

import pytest
from fakes import FakeAuthenticator

from ownmetrics_mcp.cli import main, run_auth

req = pytest.mark.req

KEY = "TEST-KEY-auth-flow-0002"


@req("R7")
@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_auth_verifies_then_saves_key_owner_only(tmp_path):
    path = tmp_path / "garmin" / "connect-personal-api-key"
    out = io.StringIO()
    auth = FakeAuthenticator()
    code = run_auth(
        read_key=lambda _p: f"  {KEY}\n", authenticator_factory=lambda: auth, key_path=path, out=out
    )
    assert code == 0
    assert auth.calls == [True]  # verified with Garmin before saving
    assert path.read_text() == KEY + "\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert KEY not in out.getvalue()


@req("R7", "AC6")
def test_auth_rejected_key_saves_nothing(tmp_path):
    path = tmp_path / "key"
    out = io.StringIO()
    code = run_auth(
        read_key=lambda _p: KEY,
        authenticator_factory=lambda: FakeAuthenticator(fail_with=401),
        key_path=path,
        out=out,
    )
    assert code == 1
    assert not path.exists()
    assert "Nothing was saved" in out.getvalue() and KEY not in out.getvalue()


@req("R7")
def test_auth_empty_input_saves_nothing(tmp_path):
    path = tmp_path / "key"
    assert (
        run_auth(
            read_key=lambda _p: "  ",
            authenticator_factory=FakeAuthenticator,
            key_path=path,
            out=io.StringIO(),
        )
        == 1
    )
    assert not path.exists()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "ownmetrics-mcp 0.1.0" in capsys.readouterr().out
