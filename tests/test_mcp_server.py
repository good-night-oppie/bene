"""Tests for the MCP server ``_dispatch`` path.

Focused regression for F6: ``agent_write`` must report the number of BYTES
actually written (UTF-8 encoded), not the character count of the source
string. The two differ for any multi-byte content (CJK, emoji), and the
server persists ``content.encode()`` while the docs promise a byte count.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bene.core import Bene
from bene.mcp import server as mcp_server


@pytest.fixture
def afs(tmp_path):
    fs = Bene(db_path=str(tmp_path / "bene.db"))
    mcp_server.init_server(fs, MagicMock())
    return fs


async def test_agent_write_reports_utf8_byte_count_not_char_count(afs):
    """F6: multi-byte content — the reported count is encoded bytes, not chars."""
    agent_id = afs.spawn(name="writer")
    content = "你好, agent — 记忆轨迹 🧬"  # CJK + ASCII + emoji: bytes >> chars
    char_len = len(content)
    byte_len = len(content.encode("utf-8"))
    assert byte_len > char_len, "fixture must use genuinely multi-byte content"

    result = await mcp_server._dispatch(
        "agent_write",
        {"agent_id": agent_id, "path": "/notes.txt", "content": content},
    )

    assert f"Written {byte_len} bytes" in result
    assert f"Written {char_len} bytes" not in result
    # Round-trip: the bytes persisted match exactly what we reported.
    assert afs.read(agent_id, "/notes.txt") == content.encode("utf-8")


async def test_agent_write_ascii_byte_count(afs):
    """ASCII path: bytes == chars; the message stays correct for the common case."""
    agent_id = afs.spawn(name="writer")
    content = "def f():\n    return 1\n"
    result = await mcp_server._dispatch(
        "agent_write",
        {"agent_id": agent_id, "path": "/f.py", "content": content},
    )
    assert f"Written {len(content.encode('utf-8'))} bytes" in result
    assert afs.read(agent_id, "/f.py") == content.encode("utf-8")
