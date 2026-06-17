"""Spec-as-artifact SDD gating — proposal → ACCEPT-gated → spec."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from bene import Bene
from bene.cli import main as cli_main
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.spec import SpecGateBlocked, SpecWorkflow


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "spec.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


@pytest.fixture()
def wf(db, store):
    return SpecWorkflow(store, db.conn)


def test_propose_creates_proposed(wf):
    pid = wf.propose("add retry policy", "spec body here")
    assert wf.status(pid) == "proposed"
    assert wf.spec_for(pid) is None


def test_accept_requires_a_verdict(wf):
    pid = wf.propose("p", "body")
    with pytest.raises(SpecGateBlocked):
        wf.accept(pid)  # no verdict, no human → blocked
    with pytest.raises(SpecGateBlocked):
        wf.accept(pid, decided_by="alice")  # not human:<name>


def test_accept_via_human_creates_gated_spec(db, store, wf):
    pid = wf.propose("p", "the spec body")
    spec_id = wf.accept(pid, decided_by="human:eddie", rationale="reviewed")
    assert wf.status(pid) == "accepted"
    assert wf.spec_for(pid) == spec_id
    spec = store.get(spec_id)
    assert spec.kind == "spec"
    assert spec.metadata["proposal_id"] == pid
    # spec is derived_from proposal and gated_by the verdict
    assert (
        db.conn.execute(
            "SELECT COUNT(*) FROM engram_links WHERE src_id=? AND dst_id=? AND link_type='derived_from'",
            (spec_id, pid),
        ).fetchone()[0]
        == 1
    )
    assert (
        db.conn.execute(
            "SELECT COUNT(*) FROM engram_links WHERE src_id=? AND link_type='gated_by'", (spec_id,)
        ).fetchone()[0]
        == 1
    )


def test_accept_via_probe_verdict(db, store, wf):
    pid = wf.propose("p", "body")
    verdict = store.append(
        "eval",
        "verdict ACCEPT",
        "ACCEPT",
        provenance={"system": "t"},
        metadata={"status": "ACCEPT"},
    )
    spec_id = wf.accept(pid, verdict_engram_id=verdict)
    assert wf.spec_for(pid) == spec_id
    assert store.get(spec_id).metadata["verdict_engram"] == verdict


def test_non_accept_verdict_is_blocked(store, wf):
    pid = wf.propose("p", "body")
    reject = store.append(
        "eval",
        "verdict REJECT",
        "REJECT",
        provenance={"system": "t"},
        metadata={"status": "REJECT"},
    )
    with pytest.raises(SpecGateBlocked):
        wf.accept(pid, verdict_engram_id=reject)


def test_reject_marks_rejected(wf):
    pid = wf.propose("p", "body")
    wf.reject(pid, decided_by="human:eddie", rationale="out of scope")
    assert wf.status(pid) == "rejected"


def test_ls_reports_statuses(wf):
    a = wf.propose("accepted one", "x")
    wf.accept(a, decided_by="human:e")
    r = wf.propose("rejected one", "x")
    wf.reject(r)
    p = wf.propose("pending one", "x")
    statuses = {v.proposal_id: v.status for v in wf.ls()}
    assert statuses[a] == "accepted"
    assert statuses[r] == "rejected"
    assert statuses[p] == "proposed"


def test_cli_propose_accept_ls(tmp_path):
    db = str(tmp_path / "cli.db")
    runner = CliRunner()
    prop = runner.invoke(
        cli_main.cli, ["--json", "spec", "propose", "retry policy", "--body", "body", "--db", db]
    )
    assert prop.exit_code == 0, prop.output
    pid = json.loads(prop.output)["proposal_id"]

    acc = runner.invoke(
        cli_main.cli, ["--json", "spec", "accept", pid, "--human", "eddie", "--db", db]
    )
    assert acc.exit_code == 0, acc.output
    assert json.loads(acc.output)["status"] == "accepted"

    ls = runner.invoke(cli_main.cli, ["--json", "spec", "ls", "--db", db])
    rows = json.loads(ls.output)
    assert any(r["proposal_id"] == pid and r["status"] == "accepted" for r in rows)


def test_cli_accept_without_gate_exits_1(tmp_path):
    db = str(tmp_path / "cli2.db")
    runner = CliRunner()
    prop = runner.invoke(
        cli_main.cli, ["--json", "spec", "propose", "p", "--body", "b", "--db", db]
    )
    pid = json.loads(prop.output)["proposal_id"]
    acc = runner.invoke(cli_main.cli, ["--json", "spec", "accept", pid, "--db", db])
    assert acc.exit_code == 1
    assert "error" in json.loads(acc.output)
