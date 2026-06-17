"""Signed deterministic replay — export/verify round-trip + tamper detection.

These tests are the repo-native form of the two falsifiable probes in
docs/design/v0.3-roadmap-spec.md §1:
  Probe A (replay.roundtrip.consolidation): export then verify == ok.
  Probe B (replay.tamper.detect): a 1-field mutation makes verify reject.
"""

from __future__ import annotations

import json

import pytest

from bene import Bene
from bene.kernel import ensure_v2
from bene.kernel.engrams import EngramStore
from bene.kernel.memory import ConsolidationPolicy, GranuleStore, ScheduledConsolidator
from bene.kernel.replay import (
    ReplayEnvelope,
    ReplayExporter,
    ReplayVerifier,
    UnknownRun,
    keys,
)


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "replay-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


@pytest.fixture()
def consolidation_run(db, store):
    """A real recorded consolidation run; returns its run_id."""
    granules = GranuleStore(store)
    agent = db.spawn("replay-agent")
    for i in range(4):
        granules.write_turn(agent, f"turn {i}: retry flag checked on step {i}")
    policy = ConsolidationPolicy(min_turns=4, batch_size=4, interval_hours=0, agent_id=agent)
    run = ScheduledConsolidator(store, granules).run(policy)
    assert run.run_id is not None
    return run.run_id


# ---------------- Probe A: round-trip ----------------


def test_export_unsigned_roundtrip_verifies(store, consolidation_run):
    env = ReplayExporter(store).export(consolidation_run)
    result = ReplayVerifier().verify(env)
    assert result.ok is True
    assert result.reasons == ()
    assert result.signature_state == "absent"
    # The re-derived batches are byte-equal to the envelope's.
    assert result.replayed_manifest["batches"] == env.manifest["batches"]
    assert result.replayed_manifest["policy"] == env.manifest["policy"]


def test_export_signed_roundtrip_verifies(store, consolidation_run):
    key = keys.generate_private_key()
    env = ReplayExporter(store).export(consolidation_run, sign_key=key)
    assert env.signature and env.public_key
    result = ReplayVerifier().verify(env)
    assert result.ok is True
    assert result.signature_state == "valid"


def test_replayed_manifest_matches_recorded(store, consolidation_run):
    """The verifier re-derives exactly what was recorded (cross-check vs the
    experiment_runs metrics blob the ScheduledConsolidator wrote)."""
    env = ReplayExporter(store).export(consolidation_run)
    recorded = json.loads(
        store.conn.execute(
            "SELECT metrics FROM experiment_runs WHERE run_id = ?", (consolidation_run,)
        ).fetchone()[0]
    )
    result = ReplayVerifier().verify(env)
    assert result.replayed_manifest["batches"] == recorded["batches"]


# ---------------- Probe B: tamper detection ----------------


def test_tamper_signed_manifest_fails_signature(store, consolidation_run):
    key = keys.generate_private_key()
    env = ReplayExporter(store).export(consolidation_run, sign_key=key)
    raw = json.loads(env.to_json())
    raw["manifest"]["batches"][0]["summary"] += " "  # 1-byte mutation
    tampered = ReplayEnvelope.from_dict(raw)
    result = ReplayVerifier().verify(tampered)
    assert result.ok is False
    assert "signature-invalid" in result.reasons


def test_tamper_unsigned_manifest_fails_replan(store, consolidation_run):
    env = ReplayExporter(store).export(consolidation_run)  # unsigned
    raw = json.loads(env.to_json())
    raw["manifest"]["batches"][0]["summary"] += " worktree drift"
    tampered = ReplayEnvelope.from_dict(raw)
    result = ReplayVerifier().verify(tampered)
    assert result.ok is False
    assert "manifest-mismatch" in result.reasons


def test_tamper_source_payload_fails_hash(store, consolidation_run):
    env = ReplayExporter(store).export(consolidation_run)
    raw = json.loads(env.to_json())
    raw["sources"][0]["payload"] += " injected"  # payload changed, hash not
    tampered = ReplayEnvelope.from_dict(raw)
    result = ReplayVerifier().verify(tampered)
    assert result.ok is False
    assert "source-hash-mismatch" in result.reasons


# ---------------- envelope plumbing ----------------


def test_envelope_json_roundtrip_is_identity(store, consolidation_run):
    key = keys.generate_private_key()
    env = ReplayExporter(store).export(consolidation_run, sign_key=key)
    again = ReplayEnvelope.from_json(env.to_json())
    assert again.to_dict() == env.to_dict()
    assert again.digest() == env.digest()


def test_cite_as_carries_content_digest(store, consolidation_run):
    env = ReplayExporter(store).export(consolidation_run)
    bib = env.cite_as()
    assert f"bene:{consolidation_run}" in bib
    assert f"sha256:{env.digest()}" in bib
    js = json.loads(env.cite_as(style="json"))
    assert js["digest"] == f"sha256:{env.digest()}"


def test_untrusted_key_verifies_but_flagged(store, consolidation_run):
    key = keys.generate_private_key()
    env = ReplayExporter(store).export(consolidation_run, sign_key=key)
    result = ReplayVerifier(trusted_keys={"some-other-key"}).verify(env)
    assert result.ok is True  # cryptographically valid
    assert result.signature_state == "untrusted"


def test_verify_into_db_file_persists_sandbox(store, consolidation_run, tmp_path):
    env = ReplayExporter(store).export(consolidation_run)
    sandbox = tmp_path / "replay.db"
    result = ReplayVerifier().verify(env, into_db=str(sandbox))
    assert result.ok is True
    assert sandbox.exists()


# ---------------- export guards ----------------


def test_export_unknown_run_raises(store):
    with pytest.raises(UnknownRun):
        ReplayExporter(store).export("01JZZZNONEXISTENT")


def test_export_rejects_unsupported_kind(store):
    store.conn.execute(
        "INSERT INTO experiment_runs (run_id, kind, summary, metrics) VALUES (?,?,?,?)",
        ("01JEVOLVE000000000000000", "evolution", "an evolution run", "{}"),
    )
    store.conn.commit()
    with pytest.raises(ValueError, match="consolidation"):
        ReplayExporter(store).export("01JEVOLVE000000000000000")


def test_list_runs_returns_consolidation_runs(store, consolidation_run):
    runs = ReplayExporter(store).list_runs()
    assert any(r["run_id"] == consolidation_run for r in runs)
    assert all(r["kind"] == "consolidation" for r in runs)


# ---------------- probe envelopes (kind="probe") ----------------


@pytest.fixture()
def probe_run(db, store):
    """A real recorded probe run (ACCEPT verdict); returns its experiment_runs run_id.

    Held-out promotion probes (C2) replay identically — a held-out probe is just a
    Probe, so its ACCEPT verdict exports + verifies through this same path."""
    from bene.kernel.eval import Probe

    gate = {
        "name": "improve",
        "metric": "quality",
        "op": ">=",
        "threshold": 0.05,
        "relative_to_baseline": True,
    }
    probe = Probe("replay-probe", [gate], dict)  # evaluate_fn=dict → subject IS its metrics
    probe.register(store, db.conn, baseline={"quality": 0.6})
    cand = store.append("strategic", "cand", "{}", tier=4, provenance={"system": "replay-test"})
    verdict = probe.run(
        {"quality": 0.7}, {"quality": 0.6}, store=store, conn=db.conn, subject_ref=cand
    )
    assert verdict.status == "ACCEPT"
    return db.conn.execute(
        "SELECT run_id FROM experiment_runs WHERE kind='probe' AND verdict_engram=?",
        (verdict.engram_id,),
    ).fetchone()[0]


def test_probe_export_verify_roundtrip(store, probe_run):
    env = ReplayExporter(store).export(probe_run)
    assert env.kind == "probe" and env.manifest["status"] == "ACCEPT"
    result = ReplayVerifier().verify(env)
    assert result.ok, result.reasons
    assert result.replayed_manifest["rederived_status"] == "ACCEPT"
    assert result.signature_state == "absent"


def test_probe_signed_roundtrip_verifies(store, probe_run):
    key = keys.generate_private_key()
    env = ReplayExporter(store).export(probe_run, sign_key=key)
    result = ReplayVerifier().verify(env)
    assert result.ok and result.signature_state == "valid"


def test_probe_tamper_gate_spec_breaks_lock(store, probe_run):
    env = ReplayExporter(store).export(probe_run)
    d = env.to_dict()
    d["manifest"]["gate_spec"] = d["manifest"]["gate_spec"].replace(
        "0.05", "0.99"
    )  # retune the gate
    tampered = ReplayEnvelope.from_dict(d)
    result = ReplayVerifier().verify(tampered)
    assert not result.ok and "probe-lock-mismatch" in result.reasons


def test_probe_tamper_status_is_caught(store, probe_run):
    env = ReplayExporter(store).export(probe_run)
    d = env.to_dict()
    d["manifest"]["status"] = "REJECT"  # flip the recorded ACCEPT
    tampered = ReplayEnvelope.from_dict(d)
    result = ReplayVerifier().verify(tampered)
    assert not result.ok
    assert "verdict-status-mismatch" in result.reasons
    assert "gate-result-inconsistent" in result.reasons  # re-derivation says ACCEPT, not REJECT


def test_probe_envelope_is_citable(store, probe_run):
    env = ReplayExporter(store).export(probe_run)
    cite = env.cite_as(style="bibtex")
    assert "BENE replay probe" in cite and f"sha256:{env.digest()}" in cite
