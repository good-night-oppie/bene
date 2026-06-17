"""Tests for the squirrel_localpath built-in agent tool (closes #9).

Donald's debugging skill already uses `squirrel localpath <url>` in src
to translate a Jira / gravytrain URL to an NFS-mounted path. Exposing
the same capability as a bene tool lets every bene agent use the
fast fs read path without operator boilerplate.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from bene.core import Bene
from bene.ccr.tools import ToolRegistry


@pytest.fixture
def registry(tmp_path):
    afs = Bene(db_path=str(tmp_path / "bene.db"))
    return ToolRegistry(afs=afs)


def test_squirrel_localpath_is_registered(registry):
    tool = registry.get("squirrel_localpath")
    assert tool is not None, "squirrel_localpath tool must be registered as a builtin"
    assert "url" in tool.parameters.get("properties", {}), "Tool must accept a 'url' parameter"


async def test_squirrel_localpath_returns_path_when_found(registry, tmp_path):
    """When `squirrel localpath <url>` prints a local path, the tool returns it."""
    # Pretend /mnt/iss/build/123/foo.log exists.
    fake_path = tmp_path / "mock_local.log"
    fake_path.write_text("ok")

    fake_proc = MagicMock(returncode=0, stdout=str(fake_path) + "\n", stderr="")
    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        result = await registry.execute(
            agent_id="a1",
            tool_name="squirrel_localpath",
            arguments={"url": "https://oppie.com/build/123/foo.log"},
        )
    # Tool returned the local path (string).
    assert str(fake_path) in result
    # Tool actually shelled out to `squirrel`.
    argv = mock_run.call_args.args[0]
    assert "squirrel" in argv[0] or argv[0] == "squirrel"
    assert "localpath" in argv
    assert "https://oppie.com/build/123/foo.log" in argv


async def test_squirrel_localpath_returns_none_when_not_found(registry):
    """When `squirrel localpath` exits non-zero or prints nothing,
    the tool returns a structured 'not found' marker, not a crash."""
    fake_proc = MagicMock(returncode=1, stdout="", stderr="no mapping")
    with patch("subprocess.run", return_value=fake_proc):
        result = await registry.execute(
            agent_id="a1",
            tool_name="squirrel_localpath",
            arguments={"url": "https://example.com/missing"},
        )
    # Should be a clear miss signal, not an exception.
    assert "not found" in result.lower() or result.strip() in ("", "null", "None")


async def test_squirrel_localpath_handles_missing_binary(registry):
    """If `squirrel` is not on PATH, the tool degrades gracefully."""
    with patch("subprocess.run", side_effect=FileNotFoundError("squirrel")):
        result = await registry.execute(
            agent_id="a1",
            tool_name="squirrel_localpath",
            arguments={"url": "https://example.com/x"},
        )
    assert "not available" in result.lower() or "not found" in result.lower()
