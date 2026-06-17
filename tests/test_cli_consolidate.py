"""`bene consolidate` CLI — cron contract + roadmap §3 eval probes P1/P2.

P1 (consolidate_cron_idempotent_24h): run + immediate rerun → exactly one
experiment_runs row, second call due=false interval-not-elapsed.
P2 (consolidate_replay_manifest_sha256_stable): plan --force twice → identical
per-batch source_digest.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from bene import Bene
from bene.cli import main as cli_main
from bene.kernel import ensure_v2
from bene.kernel.engrams import EngramStore
from bene.kernel.memory import GranuleStore


def _seed_turns(path: str, n: int = 8) -> str:
    b = Bene(path)
    ensure_v2(b.conn)
    g = GranuleStore(EngramStore(b.conn, b.blobs))
    agent = b.spawn("consolidate-agent")
    for i in range(n):
        g.write_turn(agent, f"turn {i}: step {i} done")
    b.close()
    return agent


def _no_config(tmp_path) -> str:
    return str(tmp_path / "absent.yaml")


# ---------------- Probe P1: cron idempotency ----------------


def test_run_then_rerun_interval_gate_idempotent(tmp_path):
    db = str(tmp_path / "p1.db")
    _seed_turns(db, 8)
    runner = CliRunner()
    args = [
        "--json",
        "consolidate",
        "run",
        "--policy",
        "nightly",
        "--db",
        db,
        "--config",
        _no_config(tmp_path),
    ]

    r1 = runner.invoke(cli_main.cli, args)
    assert r1.exit_code == 0, r1.output
    assert json.loads(r1.output)["plan"]["due"] is True

    r2 = runner.invoke(cli_main.cli, args)
    assert r2.exit_code == 0, r2.output
    d2 = json.loads(r2.output)
    assert d2["plan"]["due"] is False
    assert d2["plan"]["reason"] == "interval-not-elapsed"

    b = Bene(db)
    ensure_v2(b.conn)
    count = b.conn.execute(
        "SELECT COUNT(*) FROM experiment_runs WHERE kind='consolidation'"
    ).fetchone()[0]
    b.close()
    assert count == 1  # the skip was not recorded


# ---------------- Probe P2: manifest determinism ----------------


def test_plan_force_source_digest_is_stable(tmp_path):
    db = str(tmp_path / "p2.db")
    _seed_turns(db, 8)
    cfg = _no_config(tmp_path)
    runner = CliRunner()
    args = [
        "--json",
        "consolidate",
        "plan",
        "--policy",
        "nightly",
        "--force",
        "--db",
        db,
        "--config",
        cfg,
    ]

    a = runner.invoke(cli_main.cli, args)
    b = runner.invoke(cli_main.cli, args)
    assert a.exit_code == 0 and b.exit_code == 0
    diga = [x["source_digest"] for x in json.loads(a.output)["batches"]]
    digb = [x["source_digest"] for x in json.loads(b.output)["batches"]]
    assert diga == digb
    assert len(diga[0]) == 64


# ---------------- exit-code contract ----------------


def test_unknown_policy_exits_1(tmp_path):
    db = str(tmp_path / "u.db")
    _seed_turns(db, 4)
    res = CliRunner().invoke(
        cli_main.cli,
        [
            "--json",
            "consolidate",
            "run",
            "--policy",
            "nope",
            "--db",
            db,
            "--config",
            _no_config(tmp_path),
        ],
    )
    assert res.exit_code == 1
    assert "unknown policy" in json.loads(res.output)["error"]


def test_insufficient_turns_exits_2(tmp_path):
    db = str(tmp_path / "i.db")
    _seed_turns(db, 2)  # below built-in nightly min_turns=4
    res = CliRunner().invoke(
        cli_main.cli,
        [
            "--json",
            "consolidate",
            "run",
            "--policy",
            "nightly",
            "--force",
            "--db",
            db,
            "--config",
            _no_config(tmp_path),
        ],
    )
    assert res.exit_code == 2
    assert json.loads(res.output)["plan"]["reason"] == "insufficient-turns"


# ---------------- ls / show + config override ----------------


def test_ls_and_show_after_run(tmp_path):
    db = str(tmp_path / "l.db")
    _seed_turns(db, 8)
    cfg = _no_config(tmp_path)
    runner = CliRunner()
    run = runner.invoke(
        cli_main.cli,
        ["--json", "consolidate", "run", "--policy", "nightly", "--db", db, "--config", cfg],
    )
    rid = json.loads(run.output)["run_id"]
    ls = runner.invoke(cli_main.cli, ["--json", "consolidate", "ls", "--db", db])
    assert any(r["run_id"] == rid for r in json.loads(ls.output))
    show = runner.invoke(cli_main.cli, ["--json", "consolidate", "show", rid, "--db", db])
    assert json.loads(show.output)["metrics"]["kind"] == "scheduled_consolidation"


def test_config_policy_overrides_builtin(tmp_path):
    db = str(tmp_path / "c.db")
    _seed_turns(db, 6)
    cfg = tmp_path / "bene.yaml"
    cfg.write_text(
        "kernel:\n"
        "  enabled: true\n"
        "  consolidation:\n"
        "    enabled: true\n"
        "    policies:\n"
        "      nightly:\n"
        "        to_level: episode\n"
        "        min_turns: 3\n"
        "        batch_size: 3\n"
        "        max_batches: 1\n"
        "        interval_hours: 0\n"
    )
    res = CliRunner().invoke(
        cli_main.cli,
        ["--json", "consolidate", "plan", "--policy", "nightly", "--db", db, "--config", str(cfg)],
    )
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["policy"]["batch_size"] == 3  # override, not built-in 8
