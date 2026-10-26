"""Command line: `ownmetrics-mcp` (serve over stdio), `... auth` and `... status`."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from garmin_personal_api import DEFAULT_API_KEY_FILE, HttpError, PersonalApiAuthenticator

from ownmetrics_mcp import __version__
from ownmetrics_mcp.errors import KEY_PAGE
from ownmetrics_mcp.redact import install_log_redaction, redact, register_secret

KEY_PATH = Path(DEFAULT_API_KEY_FILE).expanduser()
ENV_KEY = "GARMIN_PERSONAL_API_KEY"


def _setup_logging() -> None:
    # stdout carries the MCP protocol; logs go to stderr only.
    logging.basicConfig(
        level=logging.WARNING, stream=sys.stderr, format="ownmetrics-mcp: %(levelname)s %(message)s"
    )
    install_log_redaction()


def write_key_file(key: str, path: Path = KEY_PATH) -> None:
    """Write the key with owner-only permissions on POSIX (R7); directory owner-only too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if os.name == "posix":
        os.fchmod(fd, 0o600)  # an existing file keeps its old mode on open; fix it before writing
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key.strip() + "\n")


def run_auth(
    read_key: Callable[[str], str] = getpass.getpass,
    authenticator_factory: Callable[[], Any] = PersonalApiAuthenticator,
    key_path: Path = KEY_PATH,
    out: Any = sys.stdout,
) -> int:
    print("Paste your Garmin Personal API key (input is hidden).", file=out)
    print(f"Create one at {KEY_PAGE}", file=out)
    key = read_key("Key: ").strip()
    if not key:
        print("No key entered. Nothing was saved.", file=out)
        return 1
    register_secret(key)
    try:
        with authenticator_factory() as auth:
            auth.obtain_token(key, force_refresh=True)
    except HttpError as exc:
        reason = (
            "Garmin rejected this key"
            if exc.status_code in (400, 401, 403)
            else f"Garmin returned HTTP {exc.status_code}"
        )
        print(f"{reason}. Nothing was saved. Check that you copied the whole key.", file=out)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(
            f"Could not reach Garmin ({redact(type(exc).__name__)}). Nothing was saved.", file=out
        )
        return 1
    write_key_file(key, key_path)
    where = "readable only by you" if os.name == "posix" else "in your user profile folder"
    print(f"Key verified with Garmin and saved to {key_path} ({where}).", file=out)
    if os.environ.get(ENV_KEY):
        print(
            f"Note: the {ENV_KEY} environment variable is set and takes precedence over the "
            "saved file. Remove it if it holds an old key.",
            file=out,
        )
    print(
        "Next: add ownmetrics-mcp to your AI app (see the README), then restart the app.", file=out
    )
    return 0


def run_status(out: Any = sys.stdout) -> int:
    from ownmetrics_mcp.garmin import GarminSource
    from ownmetrics_mcp.tools.data import get_account_status

    result = get_account_status(GarminSource())
    print(json.dumps(result, indent=2), file=out)
    return 0 if result.get("connected") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ownmetrics-mcp",
        description="MCP server for your own Garmin data (unofficial; not affiliated with Garmin).",
    )
    parser.add_argument("--version", action="version", version=f"ownmetrics-mcp {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="Run the MCP server over stdio (the default).")
    sub.add_parser("auth", help="Verify and save your Garmin Personal API key.")
    sub.add_parser("status", help="Check the Garmin connection and which data areas respond.")
    args = parser.parse_args(argv)

    _setup_logging()
    if args.command == "auth":
        return run_auth()
    if args.command == "status":
        return run_status()

    from ownmetrics_mcp.server import build_server

    build_server().run("stdio")
    return 0
