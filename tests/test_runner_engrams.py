"""Engrams-by-default — every run_agent turn lands as a typed trace engram (issue #2).

Before this, a plain run_agent persisted only event-journal rows; engrams were
opt-in (attach_kernel / loop-guard / demo). The default loop now writes one tier-0
'trace' turn engram per iteration, so "every run leaves typed engrams" is literal.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bene.ccr.runner import ClaudeCodeRunner, ModelResponse
from bene.core import Bene
from bene.router.tier import TierRouter


@pytest.fixture
def afs(tmp_path):
    fs = Bene(db_path=str(tmp_path / "engram.db"))
    yield fs
    fs.close()


@pytest.fixture
def mock_router():
    router = MagicMock(spec=TierRouter)
    router.route = AsyncMock(
        return_value=ModelResponse(
            content="classified: positive",
            tool_calls=[],
            stop_reason="end_turn",
            usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        )
    )
    return router


def _trace_turns(afs, agent_id: str) -> int:
    try:
        return afs.conn.execute(
            "SELECT COUNT(*) FROM engrams WHERE kind='trace' AND agent_id=?", (agent_id,)
        ).fetchone()[0]
    except Exception:
        return 0  # engrams table never created (capture disabled)


@pytest.mark.asyncio
async def test_run_agent_emits_a_trace_engram_per_turn_by_default(afs, mock_router):
    ccr = ClaudeCodeRunner(afs, mock_router)  # emit_engrams defaults True
    aid = afs.spawn("engram-agent")
    await ccr.run_agent(aid, "classify this")
    assert _trace_turns(afs, aid) >= 1  # every run leaves at least one typed engram
    row = afs.conn.execute(
        "SELECT tier, metadata FROM engrams WHERE kind='trace' AND agent_id=? LIMIT 1", (aid,)
    ).fetchone()
    import json as _json

    assert row[0] == 0 and _json.loads(row[1])["granule"] == "turn"  # tier-0 turn granule


@pytest.mark.asyncio
async def test_run_agent_engram_capture_can_be_disabled(afs, mock_router):
    ccr = ClaudeCodeRunner(afs, mock_router, emit_engrams=False)
    aid = afs.spawn("quiet-agent")
    await ccr.run_agent(aid, "classify this")
    assert _trace_turns(afs, aid) == 0  # opt-out leaves no engrams
