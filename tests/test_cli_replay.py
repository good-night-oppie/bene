"""CLI surface for `bene replay` — ls / export / verify / cite / keygen.

CliRunner runs with a non-tty stdout, so ctx.obj["json"] auto-enables; these
tests exercise the JSON path (the operator-facing rich path is a thin print).
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from bene import Bene
from bene.cli import main as cli_main
from bene.kernel import ensure_v2
from bene.kernel.engrams import EngramStore
from bene.kernel.memory import ConsolidationPolicy, GranuleStore, ScheduledConsolidator


def _make_db_with_run(path: str) -> str:
    """Build a db with one recorded consolidation run; return its run_id."""
    b = Bene(path)
    ensure_v2(b.conn)
    store = EngramStore(b.conn, b.blobs)
    granules = GranuleStore(store)
    agent = b.spawn("cli-replay-agent")
    for i in range(4):
        granules.write_turn(agent, f"turn {i}: checked retry flag at step {i}")
    policy = ConsolidationPolicy(min_turns=4, batch_size=4, interval_hours=0, agent_id=agent)
    run = ScheduledConsolidator(store, granules).run(policy)
    b.close()
    return run.run_id


def test_replay_ls_lists_run(tmp_path):
    db = str(tmp_path / "b.db")
    run_id = _make_db_with_run(db)
    res = CliRunner().invoke(cli_main.cli, ["--json", "replay", "ls", "--db", db])
    assert res.exit_code == 0, res.output
    rows = json.loads(res.output)
    assert any(r["run_id"] == run_id for r in rows)


def test_replay_export_then_verify_roundtrip(tmp_path):
    db = str(tmp_path / "b.db")
    run_id = _make_db_with_run(db)
    out = tmp_path / "r.bene-replay"
    runner = CliRunner()

    exp = runner.invoke(
        cli_main.cli,
        ["--json", "replay", "export", run_id, "--out", str(out), "--sign", "--db", db],
        env={"HOME": str(tmp_path)},  # keygen lands under the tmp HOME
    )
    assert exp.exit_code == 0, exp.output
    assert out.exists()

    ver = runner.invoke(cli_main.cli, ["--json", "replay", "verify", str(out)])
    assert ver.exit_code == 0, ver.output
    result = json.loads(ver.output)
    assert result["ok"] is True
    assert result["signature"] == "valid"
    assert result["reasons"] == []


def test_replay_verify_rejects_tampered_envelope(tmp_path):
    db = str(tmp_path / "b.db")
    run_id = _make_db_with_run(db)
    out = tmp_path / "r.bene-replay"
    runner = CliRunner()
    runner.invoke(
        cli_main.cli, ["--json", "replay", "export", run_id, "--out", str(out), "--db", db]
    )

    env = json.loads(out.read_text())
    env["manifest"]["batches"][0]["summary"] += " tampered"
    out.write_text(json.dumps(env))

    ver = runner.invoke(cli_main.cli, ["--json", "replay", "verify", str(out)])
    assert ver.exit_code == 1, ver.output  # non-zero on mismatch
    result = json.loads(ver.output)
    assert result["ok"] is False
    assert "manifest-mismatch" in result["reasons"]


def test_replay_cite_emits_digest(tmp_path):
    db = str(tmp_path / "b.db")
    run_id = _make_db_with_run(db)
    res = CliRunner().invoke(cli_main.cli, ["replay", "cite", run_id, "--db", db])
    assert res.exit_code == 0, res.output
    assert f"bene:{run_id}" in res.output
    assert "sha256:" in res.output


def test_replay_keygen_writes_key(tmp_path):
    key_file = tmp_path / "k.key"
    res = CliRunner().invoke(
        cli_main.cli, ["--json", "replay", "keygen", "--key-file", str(key_file)]
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert Path(data["key_file"]).exists()
    assert data["public_key"]


def test_replay_export_unknown_run_exits_nonzero(tmp_path):
    db = str(tmp_path / "b.db")
    _make_db_with_run(db)
    res = CliRunner().invoke(
        cli_main.cli, ["--json", "replay", "export", "01JNOPE000000000000000000", "--db", db]
    )
    assert res.exit_code == 1
    assert "error" in json.loads(res.output)
