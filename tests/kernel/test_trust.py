"""Trust ledger tests — four computed signals, composite, CLI surfaces."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe
from bene.kernel.trust import WEIGHTS, TrustLedger


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "trust-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


def _agent_with_calls(db, n_success: int, n_error: int, incomplete: int = 0) -> str:
    agent = db.spawn("synthetic")
    for i in range(n_success):
        cid = db.log_tool_call(agent, "tool", {"i": i})
        db.complete_tool_call(cid, output={"ok": True}, status="success")
    for i in range(n_error):
        cid = db.log_tool_call(agent, "tool", {"i": i})
        db.complete_tool_call(cid, output={"ok": False}, status="error")
    for i in range(incomplete):
        db.log_tool_call(agent, "tool", {"i": i})  # left pending
    return agent


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_summary_has_all_four_signals_and_composite(db, store):
    agent = db.spawn("fresh")
    s = TrustLedger(db.conn, store).summary(agent)
    assert set(s["signals"]) == set(WEIGHTS)
    assert 0.0 <= s["composite"] <= 1.0


def test_audit_completeness_counts_recorded_outcomes(db, store):
    agent = _agent_with_calls(db, n_success=3, n_error=1, incomplete=1)
    value, note = TrustLedger(db.conn, store).audit_completeness(agent)
    assert value == pytest.approx(4 / 5)
    assert "4/5" in note


def test_outcome_reliability_recency_weighting(db, store):
    """Recent successes outweigh old errors — and vice versa."""
    agent = _agent_with_calls(db, n_success=0, n_error=10)
    for i in range(10):
        cid = db.log_tool_call(agent, "tool", {"late": i})
        db.complete_tool_call(cid, output={}, status="success")
    value, _ = TrustLedger(db.conn, store).outcome_reliability(agent)
    assert value > 0.5  # recent successes dominate equal-count older errors


def test_verification_coverage_counts_verified_artifacts(db, store):
    agent = db.spawn("author")
    ledger = TrustLedger(db.conn, store)
    a1 = store.append(
        "procedural", "skill A", "x", tier=3, provenance={"agent_id": agent}, agent_id=agent
    )
    store.append(
        "procedural", "skill B", "y", tier=3, provenance={"agent_id": agent}, agent_id=agent
    )
    value, _ = ledger.verification_coverage(agent)
    assert value == 0.0
    # verify skill A through a real probe ACCEPT
    gate = {
        "name": "G1",
        "description": "improves",
        "metric": "q",
        "op": ">=",
        "threshold": 0.01,
        "relative_to_baseline": True,
    }
    p = Probe("cover-probe", [gate], dict)
    p.register(store, db.conn, baseline={"q": 0.5}, subject_ref=a1)
    p.run({"q": 0.9}, {"q": 0.5}, store=store, conn=db.conn)
    value, note = ledger.verification_coverage(agent)
    assert value == pytest.approx(0.5) and "1/2" in note


def test_checkpoint_discipline_small_window_vacuous(db, store):
    agent = db.spawn("tiny")
    value, note = TrustLedger(db.conn, store).checkpoint_discipline(agent)
    assert value == 1.0 and "probation" in note


def test_record_emits_trust_engram(db, store):
    agent = db.spawn("recorded")
    ledger = TrustLedger(db.conn, store)
    eid = ledger.record(agent, "denial", {"capability": "evolve.promote"})
    e = store.get(eid)
    assert e.kind == "trust" and e.agent_id == agent


def test_eligible_low_levels_always(db, store):
    agent = db.spawn("anyone")
    ledger = TrustLedger(db.conn, store)
    assert ledger.eligible(agent, 0) and ledger.eligible(agent, 2)


def test_eligible_l3_requires_accept_verdict(db, store):
    agent = _agent_with_calls(db, n_success=10, n_error=0)
    ledger = TrustLedger(db.conn, store)
    # high composite but zero ACCEPT verdicts -> not eligible
    assert ledger.summary(agent)["composite"] >= 0.6
    assert not ledger.eligible(agent, 3)


def test_weighted_vote_range(db, store):
    agent = db.spawn("voter")
    w = TrustLedger(db.conn, store).weighted_vote(agent)
    assert 0.5 <= w <= 1.0


# ---------------- CLI smoke ----------------


def test_cli_trust_json(db, tmp_path):
    agent = db.spawn("cli-agent")
    db.close()
    runner = CliRunner()
    res = runner.invoke(cli, ["--json", "trust", agent, "--db", str(tmp_path / "trust-test.db")])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["agent_id"] == agent and "composite" in data


def test_cli_probe_ls_and_experiments_ls_json(db, store, tmp_path):
    gate = {
        "name": "G1",
        "description": "improves",
        "metric": "q",
        "op": ">=",
        "threshold": 0.01,
        "relative_to_baseline": True,
    }
    p = Probe("cli-probe", [gate], dict)
    p.register(store, db.conn, baseline={"q": 0.5})
    p.run({"q": 0.9}, {"q": 0.5}, store=store, conn=db.conn)
    db.close()
    runner = CliRunner()
    dbp = str(tmp_path / "trust-test.db")
    res = runner.invoke(cli, ["--json", "probe", "ls", "--db", dbp])
    assert res.exit_code == 0, res.output
    assert any(p_["name"] == "cli-probe" for p_ in json.loads(res.output))
    res2 = runner.invoke(cli, ["--json", "experiments", "ls", "--db", dbp])
    assert res2.exit_code == 0, res2.output
    assert any("cli-probe" in e["summary"] for e in json.loads(res2.output))
    res3 = runner.invoke(cli, ["--json", "probe", "show", "cli-probe", "--db", dbp])
    assert res3.exit_code == 0 and json.loads(res3.output)["status"] == "admissible"
