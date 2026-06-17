"""`bene failure localize` — the dedicated failure-lookup CLI (CLAIMS-AUDIT row 63).

Surfaces the shipped critical-step localizer over an agent's trace engrams, blaming
the earliest decisive step before an error. The `_agent` unit tests hand-seed
tool-shaped trace engrams; `test_failure_localize_works_on_a_real_run` drives the
REAL runner end-to-end so the advertised "a run leaves engrams → localize finds the
failure" composition is actually exercised — it returned `localized: false` on a
live run until the runner began emitting per-tool trace engrams.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli
from bene.kernel import EngramStore, ensure_v2


def _agent(db_path: str, *, with_error: bool) -> str:
    b = Bene(db_path)
    ensure_v2(b.conn)
    store = EngramStore(b.conn, b.blobs)
    agent = b.spawn("run")
    store.append(
        "trace",
        "write config",
        "x",
        agent_id=agent,
        provenance={"agent_id": agent},
        metadata={"tool_name": "write_file", "status": "success", "granule": "turn"},
    )
    if with_error:
        store.append(
            "trace",
            "write config retry",
            "y",
            agent_id=agent,
            provenance={"agent_id": agent},
            metadata={
                "tool_name": "write_file",
                "status": "error",
                "error_message": "disk full",
                "granule": "turn",
            },
        )
    b.close()
    return agent


def test_cli_failure_localize_finds_the_decisive_step(tmp_path):
    db = str(tmp_path / "fail.db")
    agent = _agent(db, with_error=True)
    res = CliRunner().invoke(cli, ["--json", "failure", "localize", agent, "--db", db])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["localized"] is True
    assert "write_file" in data["label"]
    assert data["method"] in ("heuristic", "llm", "llm-cached")


def test_cli_failure_localize_no_error_returns_none(tmp_path):
    db = str(tmp_path / "ok.db")
    agent = _agent(db, with_error=False)
    res = CliRunner().invoke(cli, ["--json", "failure", "localize", agent, "--db", db])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["localized"] is False


def test_cli_failure_localize_persist_records_episodic_engram(tmp_path):
    db = str(tmp_path / "fail2.db")
    agent = _agent(db, with_error=True)
    res = CliRunner().invoke(cli, ["--json", "failure", "localize", agent, "--persist", "--db", db])
    assert res.exit_code == 0, res.output
    eid = json.loads(res.output)["persisted_engram"]
    assert eid
    b = Bene(db)
    kind = b.conn.execute("SELECT kind FROM engrams WHERE engram_id=?", (eid,)).fetchone()[0]
    b.close()
    assert kind == "episodic"


@pytest.mark.asyncio
async def test_failure_localize_works_on_a_real_run(tmp_path):
    """End-to-end: a REAL run_agent loop whose tool errors must be localizable by
    `bene failure localize`. Before the runner emitted per-tool trace engrams the
    turn granule carried only {granule, iteration}, so steps_from_engrams saw no
    failing step and the CLI returned localized:false on a genuine run."""
    from unittest.mock import AsyncMock, MagicMock

    from bene.ccr.runner import ClaudeCodeRunner, ModelResponse, ToolCall
    from bene.ccr.tools import ToolDefinition
    from bene.router.tier import TierRouter

    db = str(tmp_path / "real.db")
    afs = Bene(db)
    agent = afs.spawn("run")

    def _boom(**kwargs):
        raise RuntimeError("disk full")

    router = MagicMock(spec=TierRouter)
    router.route = AsyncMock(
        side_effect=[
            ModelResponse(
                content="writing the config",
                tool_calls=[
                    ToolCall(id="t1", name="write_file", input={"path": "/c", "content": "x"})
                ],
                stop_reason="tool_use",
                usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            ),
            ModelResponse(
                content="done",
                tool_calls=[],
                stop_reason="end_turn",
                usage={"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            ),
        ]
    )
    ccr = ClaudeCodeRunner(afs, router)
    ccr.register_tool(
        ToolDefinition(name="write_file", description="write a file", parameters={}, handler=_boom)
    )
    await ccr.run_agent(agent, "set up the config")
    afs.close()

    # The runner captured the tool error with the metadata steps_from_engrams needs.
    b = Bene(db)
    rows = b.conn.execute(
        "SELECT json_extract(metadata,'$.tool_name'), json_extract(metadata,'$.status')"
        " FROM engrams WHERE kind='trace' AND json_extract(metadata,'$.status')='error'"
    ).fetchall()
    b.close()
    assert rows and rows[0][0] == "write_file" and rows[0][1] == "error"

    # And the dedicated CLI localizes it on a real run (was localized:false pre-fix).
    res = CliRunner().invoke(cli, ["--json", "failure", "localize", agent, "--db", db])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["localized"] is True, data
    assert "write_file" in data["label"]
