"""CLI tests for `bene belief …` — emit / reconcile / ls / active / explain / quarantine.

Driven through Click's CliRunner against a temp ``--db`` so the commands are
exercised exactly as a user would. JSON output is parsed to prove it is valid.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from bene.cli.main import cli


@pytest.fixture()
def db(tmp_path):
    return str(tmp_path / "cli-belief.db")


@pytest.fixture()
def runner():
    return CliRunner()


def _emit(runner, db, **fact):
    return runner.invoke(cli, ["belief", "emit", "--db", db, "--json", json.dumps(fact)])


def test_emit_returns_fact_id(runner, db):
    # BENE auto-enables --json when stdout is not a TTY (CliRunner), so output is JSON.
    r = _emit(runner, db, kind="observation", subject="s", relation="r", value="v")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["fact_id"]


def test_emit_json_output_is_valid(runner, db):
    r = runner.invoke(
        cli,
        [
            "--json",
            "belief",
            "emit",
            "--db",
            db,
            "--json",
            json.dumps({"kind": "claim", "subject": "s", "relation": "r", "value": "v"}),
        ],
    )
    assert r.exit_code == 0, r.output
    obj = json.loads(r.output)
    assert "fact_id" in obj


def test_emit_from_stdin(runner, db):
    payload = json.dumps({"kind": "observation", "subject": "s", "relation": "r", "value": "v"})
    r = runner.invoke(cli, ["belief", "emit", "--db", db], input=payload)
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["fact_id"]


def test_emit_malformed_json_errors(runner, db):
    r = runner.invoke(cli, ["belief", "emit", "--db", db, "--json", "{not json"])
    assert r.exit_code != 0
    assert "invalid JSON" in r.output


def test_emit_unknown_kind_errors(runner, db):
    r = _emit(runner, db, kind="bogus", subject="s", relation="r", value="v")
    assert r.exit_code != 0
    assert "kind" in r.output.lower()


def test_reconcile_summary_and_json(runner, db):
    _emit(runner, db, kind="observation", subject="s", relation="r", value="green")
    r = runner.invoke(cli, ["belief", "reconcile", "--db", db])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["created"] == 1
    rj = runner.invoke(cli, ["--json", "belief", "reconcile", "--db", db])
    counts = json.loads(rj.output)
    assert set(counts) >= {"created", "superseded", "refreshed", "quarantined"}


def test_active_and_ls(runner, db):
    _emit(runner, db, kind="observation", subject="s", relation="r", value="green")
    runner.invoke(cli, ["belief", "reconcile", "--db", db])
    ra = runner.invoke(cli, ["--json", "belief", "active", "--db", db])
    actives = json.loads(ra.output)
    assert len(actives) == 1 and actives[0]["value"] == "green"
    rl = runner.invoke(cli, ["--json", "belief", "ls", "--db", db])
    assert len(json.loads(rl.output)) == 1


def test_explain_json_structure(runner, db):
    _emit(runner, db, kind="observation", subject="s", relation="r", value="green")
    runner.invoke(cli, ["belief", "reconcile", "--db", db])
    bid = json.loads(runner.invoke(cli, ["--json", "belief", "active", "--db", db]).output)[0][
        "belief_id"
    ]
    r = runner.invoke(cli, ["--json", "belief", "explain", bid, "--db", db])
    assert r.exit_code == 0, r.output
    ex = json.loads(r.output)
    assert set(ex) >= {"belief", "facts", "decisions", "conflicts", "admissibility"}
    assert ex["belief"]["belief_id"] == bid


def test_explain_unknown_id_errors(runner, db):
    runner.invoke(cli, ["belief", "reconcile", "--db", db])  # init db
    r = runner.invoke(cli, ["belief", "explain", "nonexistent", "--db", db])
    assert r.exit_code != 0
    assert "not found" in r.output.lower()


def test_quarantine_unknown_id_errors(runner, db):
    runner.invoke(cli, ["belief", "reconcile", "--db", db])
    r = runner.invoke(cli, ["belief", "quarantine", "nope", "--reason", "x", "--db", db])
    assert r.exit_code != 0
    assert "not found" in r.output.lower()


def test_end_to_end_emit_reconcile_active_quarantine(runner, db):
    # emit → reconcile → active shows it → quarantine → active no longer shows it
    _emit(runner, db, kind="observation", subject="svc", relation="status", value="up")
    assert runner.invoke(cli, ["belief", "reconcile", "--db", db]).exit_code == 0
    actives = json.loads(runner.invoke(cli, ["--json", "belief", "active", "--db", db]).output)
    assert len(actives) == 1
    bid = actives[0]["belief_id"]

    rq = runner.invoke(
        cli, ["belief", "quarantine", bid, "--reason", "operator distrust", "--db", db]
    )
    assert rq.exit_code == 0, rq.output

    actives_after = json.loads(
        runner.invoke(cli, ["--json", "belief", "active", "--db", db]).output
    )
    assert actives_after == []  # no longer active
    # but still inspectable as quarantined
    quarantined = json.loads(
        runner.invoke(
            cli, ["--json", "belief", "ls", "--lifecycle", "quarantined", "--db", db]
        ).output
    )
    assert len(quarantined) == 1 and quarantined[0]["belief_id"] == bid
