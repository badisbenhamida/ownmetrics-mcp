import importlib.util
import sys
from pathlib import Path

import pytest

req = pytest.mark.req
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "traceability.py"


def _load():
    spec = importlib.util.spec_from_file_location("traceability", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["traceability"] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


@req("AC2")
def test_every_in_scope_requirement_has_a_test(tmp_path):
    out = tmp_path / "TRACEABILITY.md"  # never rewrite the committed matrix from a test
    assert _load().main(["--milestone", "M6", "--check", "--out", str(out)]) == 0
    assert "**MISSING**" not in out.read_text()


@req("AC2")
def test_spec_defines_the_tool_catalog():
    reqs = _load().parse_spec()
    assert {f"T{i}" for i in range(1, 10)} <= set(reqs)
    assert reqs["T1"].milestone == "M2" and reqs["T1"].verify == "auto"
    assert reqs["AC1"].verify == "manual"


@req("AC9")
def test_every_known_limitation_has_a_test():
    module = _load()
    reqs, tests = module.parse_spec(), module.collect_tests()
    limitations = {rid for rid in reqs if rid.startswith("L")}
    assert limitations and limitations <= set(tests), limitations - set(tests)


def test_release_metadata_agrees():
    """The release workflow refuses a tag that disagrees; this catches it before tagging."""
    import json
    import tomllib

    from ownmetrics_mcp import __version__

    root = SCRIPT.parent.parent
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))
    assert project["version"] == __version__ == server["version"]
    assert server["packages"][0]["version"] == __version__
    assert server["packages"][0]["identifier"] == project["name"]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert f"mcp-name: {server['name']}" in readme
    assert len(server["description"]) <= 100
