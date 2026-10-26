"""Build the Claude Desktop bundle, ownmetrics-mcp-<version>.mcpb (SPEC B1, B4).

Stages only what the bundle needs (manifest, icon, pyproject, README, LICENSE, src/), then
validates and packs it with the official mcpb tool (pinned). With --smoke, it also starts the
staged server the way Claude Desktop does (`uv run --directory <bundle> ownmetrics-mcp`) and
checks its version.

Usage: python scripts/build_bundle.py [--smoke]   (needs Node.js for npx, and uv)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "build" / "bundle"
DIST = ROOT / "dist"
MCPB = "@anthropic-ai/mcpb@2.1.2"
INCLUDE = ["manifest.json", "assets/icon.png", "pyproject.toml", "README.md", "LICENSE"]


def run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, **kw)  # type: ignore[call-overload]  # noqa: S603


def smoke_session(uv: str) -> tuple[list[str], dict[str, object]]:
    """Start the staged server over stdio as Claude Desktop would, with the key setting left
    blank and no saved key: it must list every tool and explain how to add a key (B1, B2)."""
    import tempfile

    import anyio
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def check(home: str) -> tuple[list[str], dict[str, object]]:
        params = StdioServerParameters(
            command=uv,
            args=["run", "--directory", str(STAGE), "ownmetrics-mcp"],
            env={
                "HOME": home,
                "USERPROFILE": home,
                "PATH": str(Path(uv).parent),
                "GARMIN_PERSONAL_API_KEY": "",
            },
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            result = await session.call_tool("get_account_status", {})
            text = "".join(getattr(c, "text", "") for c in result.content)
            return tools, json.loads(text)

    with tempfile.TemporaryDirectory() as home:
        return anyio.run(check, home)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="run the staged server once")
    args = ap.parse_args(argv)

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != version:
        print(f"manifest.json version {manifest['version']} != pyproject {version}")
        return 1

    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    for rel in INCLUDE:
        (STAGE / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, STAGE / rel)
    shutil.copytree(
        ROOT / "src", STAGE / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )

    npx = shutil.which("npx")
    if npx is None:
        print("npx (Node.js) is needed to validate and pack the bundle.")
        return 1
    run([npx, "-y", MCPB, "validate", str(STAGE / "manifest.json")])
    DIST.mkdir(exist_ok=True)
    out = DIST / f"ownmetrics-mcp-{version}.mcpb"
    run([npx, "-y", MCPB, "pack", str(STAGE), str(out)])
    run([npx, "-y", MCPB, "info", str(out)])

    if args.smoke:
        uv = shutil.which("uv")
        if uv is None:
            print("uv is needed for --smoke.")
            return 1
        result = run(
            [uv, "run", "--directory", str(STAGE), "ownmetrics-mcp", "--version"],
            capture_output=True,
        )
        if f"ownmetrics-mcp {version}" not in result.stdout:
            print("Smoke test failed:", result.stdout, result.stderr)
            return 1
        tools, status = smoke_session(uv)
        if len(tools) != len(manifest["tools"]) or status.get("connected") is not False:
            print("Smoke session failed:", tools, status)
            return 1
        if "ownmetrics-mcp auth" not in status.get("problem", ""):
            print("With no key anywhere, the server must explain how to add one:", status)
            return 1
        print(
            f"Smoke test passed: {result.stdout.strip()}, {len(tools)} tools, "
            "starts cleanly with a blank key setting"
        )
    print(f"Built {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
