"""Truth-maintenance layer tests — schema, contract, persistence, reducer.

Organized by phase: schema/contract (P1), emit + queries (P2), the deterministic
reducer + quarantine (P3), and the no-LLM/no-network source scan (P5). Tests
assert on raw SQLite rows as well as the high-level API so the database stays
directly inspectable.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from bene import Bene
from bene.kernel import ensure_v2
from bene.kernel.truth import (
    BELIEF_LIFECYCLES,
    FACT_KINDS,
    InvalidFact,
    TruthStore,
    ensure_truth,
    quarantine_belief,
    reconcile_beliefs,
    value_hash,
)

TRUTH_TABLES = {"belief_facts", "beliefs", "belief_decisions", "belief_conflicts"}


@pytest.fixture()
def conn(tmp_path):
    b = Bene(str(tmp_path / "truth-test.db"))
    ensure_truth(b.conn)
    yield b.conn
    b.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------- schema (P1)


def test_ensure_truth_creates_all_tables(conn):
    names = _table_names(conn)
    assert TRUTH_TABLES <= names
    assert "truth_schema_version" in names


def test_reconciliation_key_and_value_are_real_columns(conn):
    for table in ("belief_facts", "beliefs"):
        cols = _cols(conn, table)
        assert {"subject", "relation", "scope", "value", "value_hash"} <= cols


def test_partial_unique_active_index_exists(conn):
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(beliefs)").fetchall()}
    assert "idx_beliefs_active_key" in indexes
    # And it is genuinely UNIQUE + partial.
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_beliefs_active_key'"
    ).fetchone()[0]
    assert "UNIQUE" in sql.upper()
    assert "lifecycle" in sql and "active" in sql


def test_partial_unique_index_blocks_two_active_per_key(conn):
    # Direct DB proof the invariant is DB-enforced, not just convention.
    conn.execute(
        "INSERT INTO beliefs (belief_id, subject, relation, value, value_hash, scope, lifecycle)"
        " VALUES ('b1','s','r','v1','h1','global','active')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO beliefs (belief_id, subject, relation, value, value_hash, scope, lifecycle)"
            " VALUES ('b2','s','r','v2','h2','global','active')"
        )


def test_ensure_truth_is_idempotent(conn):
    ensure_truth(conn)
    ensure_truth(conn)
    rows = conn.execute("SELECT COUNT(*) FROM truth_schema_version").fetchone()[0]
    assert rows == 1


def test_ensure_v2_also_creates_truth_and_kernel_tables(tmp_path):
    b = Bene(str(tmp_path / "v2.db"))
    try:
        ensure_v2(b.conn)
        names = _table_names(b.conn)
        assert TRUTH_TABLES <= names  # truth tables present via ensure_v2
        assert "engrams" in names  # legacy v2 tables still created
        assert "kernel_schema_version" in names
    finally:
        b.close()


def test_fact_kinds_and_lifecycles_constants():
    assert FACT_KINDS == {
        "observation",
        "claim",
        "state",
        "hypothesis",
        "decision",
        "policy",
    }
    assert BELIEF_LIFECYCLES == {
        "candidate",
        "active",
        "superseded",
        "quarantined",
        "expired",
        "rejected",
    }


def test_value_hash_is_canonical():
    assert value_hash(1) == value_hash(1.0)  # int == float
    assert value_hash("a") != value_hash(1)  # string != number
    assert value_hash("x") == value_hash("x")  # stable
    assert value_hash(True) != value_hash(1)  # bool not folded into int


# ---------------------------------------------------------------- emit + queries (P2)

# all reconciliation-critical fields supplied to emit_fact in Test 1
_FULL_FACT = dict(
    kind="observation",
    subject="baseline",
    relation="status",
    value="green",
    scope="run:42",
    source="ci",
    source_type="tool",
    confidence=0.9,
    observed_at="2026-06-30T00:00:00.000",
    expires_at="2027-01-01T00:00:00.000",
    run_id="run-42",
    agent_id="agent-7",
    trace_id="trace-9",
    evidence_uri="engram://abc",
    derived_from=["fact-x"],
    metadata={"k": "v"},
    unsafe=False,
)


def test_emit_observation_persists_all_fields(conn):  # Test 1
    store = TruthStore(conn)
    fid = store.emit_fact(**_FULL_FACT)
    # read back via RAW SQL (not the API) — the DB must be directly inspectable
    cur = conn.execute("SELECT * FROM belief_facts WHERE fact_id = ?", (fid,))
    cols = [c[0] for c in cur.description]
    row = dict(zip(cols, cur.fetchone()))
    assert row["kind"] == "observation"
    assert row["subject"] == "baseline"
    assert row["relation"] == "status"
    # value is stored as JSON text (always-JSON encoding) and round-trips on read
    assert json.loads(row["value"]) == "green"
    assert store.get_fact(fid)["value"] == "green"
    assert row["scope"] == "run:42"
    assert row["source"] == "ci"
    assert row["source_type"] == "tool"
    assert abs(row["confidence"] - 0.9) < 1e-9
    assert row["observed_at"] == "2026-06-30T00:00:00.000"
    assert row["expires_at"] == "2027-01-01T00:00:00.000"
    assert row["run_id"] == "run-42"
    assert row["agent_id"] == "agent-7"
    assert row["trace_id"] == "trace-9"
    assert row["evidence_uri"] == "engram://abc"
    assert row["derived_from"] == '["fact-x"]'
    assert row["metadata"] == '{"k": "v"}'
    assert row["unsafe"] == 0
    assert row["value_hash"]  # computed + stored
    assert row["reconciled_at"] is None  # not reconciled yet


def test_emit_defaults_scope_and_observed_at(conn):
    store = TruthStore(conn)
    fid = store.emit_fact(kind="claim", subject="s", relation="r", value="v")
    f = store.get_fact(fid)
    assert f["scope"] == "global"
    assert f["observed_at"]  # auto-set
    assert f["reconciled_at"] is None
    assert f["value_hash"] == value_hash("v")


def test_emit_rejects_unknown_kind(conn):
    store = TruthStore(conn)
    with pytest.raises(InvalidFact):
        store.emit_fact(kind="bogus", subject="s", relation="r", value="v")


def test_emit_claim_creates_fact_but_no_belief(conn):  # Test 2 precondition
    store = TruthStore(conn)
    store.emit_fact(kind="claim", subject="s", relation="r", value="v")
    assert conn.execute("SELECT COUNT(*) FROM belief_facts").fetchone()[0] == 1
    # reducer has NOT run → no belief
    assert conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0] == 0
    assert store.list_beliefs() == []


def test_queries_on_empty_db_do_not_crash(conn):
    store = TruthStore(conn)
    assert store.list_beliefs() == []
    assert store.list_active_beliefs() == []
    assert store.get_belief("nope") is None
    assert store.explain_belief("nope") is None


def test_count_reflects_emitted_facts(conn):  # Test 12 — directly inspectable
    store = TruthStore(conn)
    for i in range(5):
        store.emit_fact(kind="observation", subject=f"s{i}", relation="r", value=i)
    assert conn.execute("SELECT COUNT(*) FROM belief_facts").fetchone()[0] == 5


def test_explain_skeleton_returns_belief_and_facts(conn):
    # Manually insert an active belief + matching fact (reducer not yet exercised).
    store = TruthStore(conn)
    fid = store.emit_fact(kind="observation", subject="s", relation="r", value="v")
    bid = store.insert_belief(
        subject="s",
        relation="r",
        value="v",
        value_hash=value_hash("v"),
        scope="global",
        lifecycle="active",
        confidence=1.0,
        active_from="2026-06-30T00:00:00.000",
        active_until=None,
        derived_from=[fid],
        admissible=(1, 1, 1),
        now="2026-06-30T00:00:00.000",
    )
    conn.commit()
    ex = store.explain_belief(bid)
    assert ex is not None
    assert ex["belief"]["belief_id"] == bid
    assert any(f["fact_id"] == fid for f in ex["facts"])
    assert ex["decisions"] == []
    assert ex["admissibility"] == {"context": 1, "promotion": 1, "action": 1}


# ---------------------------------------------------------------- reducer (P3)

T1 = "2026-06-01T00:00:00.000"
T2 = "2026-06-02T00:00:00.000"
T3 = "2026-06-03T00:00:00.000"
NOW = "2026-06-15T00:00:00.000"


def _emit(store, value, *, observed_at, subject="s", relation="r", scope="global", **kw):
    return store.emit_fact(
        kind=kw.pop("kind", "observation"),
        subject=subject,
        relation=relation,
        value=value,
        scope=scope,
        observed_at=observed_at,
        **kw,
    )


def test_rule1_creates_one_active_belief(conn):  # Test 3
    store = TruthStore(conn)
    _emit(store, "green", observed_at=T1)
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["created"] == 1
    actives = store.list_active_beliefs()
    assert len(actives) == 1
    assert actives[0]["value"] == "green"
    # exactly one decision, rule_1_create
    decs = conn.execute("SELECT rule FROM belief_decisions").fetchall()
    assert len(decs) == 1 and decs[0][0] == "rule_1_create"


def test_rule9_reconcile_twice_idempotent(conn):  # Test 4
    store = TruthStore(conn)
    _emit(store, "green", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    b1 = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    d1 = conn.execute("SELECT COUNT(*) FROM belief_decisions").fetchone()[0]
    counts2 = reconcile_beliefs(conn, now=NOW)  # second run
    b2 = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    d2 = conn.execute("SELECT COUNT(*) FROM belief_decisions").fetchone()[0]
    assert (b1, d1) == (b2, d2)
    assert sum(counts2.values()) == 0  # nothing processed second time


def test_rule2_supersede(conn):  # Test 5
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "B", observed_at=T2)
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["superseded"] == 1
    actives = store.list_active_beliefs()
    assert len(actives) == 1 and actives[0]["value"] == "B"
    superseded = store.list_beliefs(lifecycle="superseded")
    assert len(superseded) == 1
    assert superseded[0]["value"] == "A"
    assert superseded[0]["active_until"] is not None
    # both transitions have decisions; a conflict row exists
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM belief_decisions WHERE rule='rule_2_supersede'"
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM belief_conflicts WHERE kind='same_key_different_value'"
        ).fetchone()[0]
        == 1
    )


def test_supersede_ends_old_belief_at_replacement_time(conn):
    # The superseded belief's active_until must be the REPLACING fact's
    # observed_at (T2), not the reducer's wall-clock `now` (NOW, far later), so the
    # old and new beliefs' active intervals abut instead of overlapping.
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "B", observed_at=T2)
    reconcile_beliefs(conn, now=NOW)  # NOW (2026-06-15) is far after T2
    superseded = store.list_beliefs(lifecycle="superseded")
    assert len(superseded) == 1 and superseded[0]["value"] == "A"
    assert superseded[0]["active_until"] == T2  # replacement time, NOT NOW
    new_active = store.list_active_beliefs()[0]
    assert new_active["value"] == "B" and new_active["active_from"] == T2
    # intervals abut on T2 — no overlapping truth for the same key
    assert superseded[0]["active_until"] == new_active["active_from"]


def test_rule3_same_value_no_duplicate(conn):  # Test 6
    store = TruthStore(conn)
    f1 = _emit(store, "A", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    f2 = _emit(store, "A", observed_at=T2)
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["refreshed"] == 1
    actives = store.list_active_beliefs()
    assert len(actives) == 1
    assert conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0] == 1
    # the confirming fact is linked
    assert set(actives[0]["derived_from"]) == {f1, f2}


def test_refresh_updates_last_decision_id(conn):
    # A same-value refresh mutates derived_from/confidence, so it must become the
    # belief's last_decision_id — an audit following last_decision_id should land
    # on the confirmation, not the older create decision.
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    create_decision = store.list_active_beliefs()[0]["last_decision_id"]
    _emit(store, "A", observed_at=T2)  # confirming, same value
    reconcile_beliefs(conn, now=NOW)
    refreshed = store.list_active_beliefs()[0]
    assert refreshed["last_decision_id"] != create_decision
    last_rule = conn.execute(
        "SELECT rule FROM belief_decisions WHERE decision_id = ?",
        (refreshed["last_decision_id"],),
    ).fetchone()
    assert last_rule[0] == "rule_3_refresh"


def test_rule4_unreliable_source_quarantined(conn):  # Test 7
    store = TruthStore(conn)
    _emit(store, "bad", observed_at=T1, source_type="failed")
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["quarantined"] == 1
    assert store.list_active_beliefs() == []
    q = store.list_beliefs(lifecycle="quarantined")
    assert len(q) == 1
    assert q[0]["admissible_for_promotion"] == 0


def test_rule4_unsafe_flag_quarantined(conn):
    store = TruthStore(conn)
    _emit(store, "danger", observed_at=T1, unsafe=True)
    reconcile_beliefs(conn, now=NOW)
    assert store.list_active_beliefs() == []
    assert len(store.list_beliefs(lifecycle="quarantined")) == 1


def test_rule5_expired_fact_no_active(conn):  # Test 8
    store = TruthStore(conn)
    _emit(store, "stale", observed_at=T1, expires_at="2020-01-01T00:00:00.000")
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["rejected"] == 1
    assert store.list_active_beliefs() == []
    # non-activation is explained
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM belief_decisions WHERE rule='rule_5_expired'"
        ).fetchone()[0]
        == 1
    )


def test_future_ttl_propagates_to_belief_active_until(conn):
    # A fact that is NOT expired at reconcile time but carries a future
    # expires_at must propagate that TTL onto the active belief's active_until,
    # not create an indefinitely-active belief.
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1, expires_at="2027-01-01T00:00:00.000")
    counts = reconcile_beliefs(conn, now=NOW)  # NOW (2026-06-15) < TTL → active
    assert counts["created"] == 1
    actives = store.list_active_beliefs()
    assert len(actives) == 1
    assert actives[0]["active_until"] == "2027-01-01T00:00:00.000"  # TTL kept, not None
    assert actives[0]["admissible_for_promotion"] == 1


def test_belief_expires_when_ttl_elapses(conn):
    # Reconcile before the TTL: belief is active. A later reconcile whose `now`
    # is past the TTL must demote it to `expired` and strip admissibility, even
    # though the source fact was already consumed.
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1, expires_at="2026-06-10T00:00:00.000")
    c1 = reconcile_beliefs(conn, now="2026-06-05T00:00:00.000")  # before TTL
    assert c1["created"] == 1
    assert len(store.list_active_beliefs(now="2026-06-05T00:00:00.000")) == 1

    c2 = reconcile_beliefs(conn, now="2026-06-20T00:00:00.000")  # past TTL
    assert c2["expired"] == 1
    assert store.list_active_beliefs(now="2026-06-20T00:00:00.000") == []  # no longer active
    expired = store.list_beliefs(lifecycle="expired")
    assert len(expired) == 1
    assert (
        expired[0]["admissible_for_context"],
        expired[0]["admissible_for_promotion"],
        expired[0]["admissible_for_action"],
    ) == (0, 0, 0)
    # the demotion is explained (Rule 8) and points at the belief, not a fact
    row = conn.execute(
        "SELECT belief_id, fact_id FROM belief_decisions"
        " WHERE rule='rule_5_expired' AND to_lifecycle='expired'"
    ).fetchall()
    assert len(row) == 1 and row[0][0] == expired[0]["belief_id"] and row[0][1] is None

    # idempotent: a third reconcile at the same `now` expires nothing new
    c3 = reconcile_beliefs(conn, now="2026-06-20T00:00:00.000")
    assert c3["expired"] == 0


def test_refresh_extends_ttl_with_newer_evidence(conn):
    # A later same-value observation with a longer TTL must EXTEND the belief's
    # active_until; otherwise the original, shorter TTL expires it early even
    # though fresh confirming evidence keeps it valid.
    jan1, jan9 = "2026-01-01T00:00:00.000", "2026-01-09T00:00:00.000"
    jan10, feb1 = "2026-01-10T00:00:00.000", "2026-02-01T00:00:00.000"
    store = TruthStore(conn)
    _emit(store, "A", observed_at=jan1, expires_at=jan10)  # short TTL
    _emit(store, "A", observed_at=jan9, expires_at=feb1)  # newer, longer TTL
    reconcile_beliefs(conn, now="2026-01-09T12:00:00.000")
    active = store.list_active_beliefs(now="2026-01-09T12:00:00.000")
    assert len(active) == 1
    assert active[0]["active_until"] == feb1  # extended to the newest evidence's TTL

    # past the ORIGINAL (jan10) TTL the belief is still live, and a reconcile there
    # does NOT expire it
    assert len(store.list_active_beliefs(now="2026-01-11T00:00:00.000")) == 1
    c = reconcile_beliefs(conn, now="2026-01-11T00:00:00.000")
    assert c["expired"] == 0
    assert len(store.list_active_beliefs(now="2026-01-11T00:00:00.000")) == 1


def test_read_path_hides_beliefs_past_ttl_without_reconcile(conn):
    # TTL must be enforced on the READ path, not only during a reconcile sweep:
    # if no new facts arrive after the TTL passes, a caller that only reads active
    # beliefs must still not see the expired one.
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1, expires_at="2026-06-10T00:00:00.000")
    reconcile_beliefs(conn, now="2026-06-05T00:00:00.000")  # before TTL → active
    # before expiry: visible
    assert len(store.list_active_beliefs(now="2026-06-08T00:00:00.000")) == 1
    # after expiry, WITHOUT a second reconcile: the read path hides it
    assert store.list_active_beliefs(now="2026-06-20T00:00:00.000") == []
    # the lifecycle row is still 'active' until a sweep runs — the read overlay
    # is what makes TTL authoritative for callers
    assert conn.execute("SELECT lifecycle FROM beliefs").fetchone()[0] == "active"


def test_rule10_manual_quarantine(conn):  # Test 9
    store = TruthStore(conn)
    _emit(store, "green", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    bid = store.list_active_beliefs()[0]["belief_id"]
    res = quarantine_belief(conn, bid, reason="operator distrust", now=NOW)
    assert res["status"] == "quarantined"
    b = store.get_belief(bid)
    assert b["lifecycle"] == "quarantined"
    assert (
        b["admissible_for_context"],
        b["admissible_for_promotion"],
        b["admissible_for_action"],
    ) == (0, 0, 0)
    dec = conn.execute(
        "SELECT reason FROM belief_decisions WHERE rule='rule_10_manual_quarantine'"
    ).fetchone()
    assert dec is not None and dec[0] == "operator distrust"
    # idempotent
    res2 = quarantine_belief(conn, bid, reason="again", now=NOW)
    assert res2["status"] == "already_quarantined"


def test_rule6_non_active_never_promotable(conn):  # Test 10
    store = TruthStore(conn)
    # produce active + superseded
    _emit(store, "A", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "B", observed_at=T2)
    reconcile_beliefs(conn, now=NOW)
    # produce a quarantined (different key)
    _emit(store, "bad", observed_at=T1, subject="x", source_type="error")
    reconcile_beliefs(conn, now=NOW)
    # manual-quarantine the active B (different key, isolate first)
    rows = store.list_beliefs()
    non_active = [b for b in rows if b["lifecycle"] != "active"]
    assert non_active, "expected some non-active beliefs"
    for b in non_active:
        assert b["admissible_for_promotion"] == 0, (b["lifecycle"], b["belief_id"])
    # the DB-level invariant
    bad = conn.execute(
        "SELECT COUNT(*) FROM beliefs WHERE lifecycle != 'active' AND admissible_for_promotion = 1"
    ).fetchone()[0]
    assert bad == 0


def test_rule7_active_admissibility_matches_decision(conn):
    store = TruthStore(conn)
    _emit(store, "green", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    b = store.list_active_beliefs()[0]
    did = b["last_decision_id"]
    drow = conn.execute(
        "SELECT admissible_for_context, admissible_for_promotion, admissible_for_action"
        " FROM belief_decisions WHERE decision_id = ?",
        (did,),
    ).fetchone()
    assert (
        b["admissible_for_context"],
        b["admissible_for_promotion"],
        b["admissible_for_action"],
    ) == tuple(drow)
    assert tuple(drow) == (1, 1, 1)


def test_rule8_every_belief_has_a_decision(conn):
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "B", observed_at=T2)
    reconcile_beliefs(conn, now=NOW)
    for b in store.list_beliefs():
        n = conn.execute(
            "SELECT COUNT(*) FROM belief_decisions WHERE belief_id = ?",
            (b["belief_id"],),
        ).fetchone()[0]
        assert n >= 1, f"belief {b['belief_id']} ({b['lifecycle']}) has no decision"


def test_explain_belief_full_view(conn):  # Test 11
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "B", observed_at=T2)
    reconcile_beliefs(conn, now=NOW)
    superseded = store.list_beliefs(lifecycle="superseded")[0]
    ex = store.explain_belief(superseded["belief_id"])
    assert ex["belief"]["belief_id"] == superseded["belief_id"]
    assert len(ex["facts"]) >= 1
    assert len(ex["decisions"]) >= 1
    assert len(ex["conflicts"]) >= 1
    assert set(ex["admissibility"]) == {"context", "promotion", "action"}


def test_stale_fact_does_not_supersede(conn):
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T2)  # newer
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "B", observed_at=T1)  # OLDER, different value
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["skipped"] == 1
    actives = store.list_active_beliefs()
    assert len(actives) == 1 and actives[0]["value"] == "A"  # unchanged
    assert (
        conn.execute("SELECT COUNT(*) FROM belief_conflicts WHERE kind='stale_value'").fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM belief_decisions WHERE rule='rule_2_stale_ignored'"
        ).fetchone()[0]
        == 1
    )


def test_out_of_order_contradiction_after_refresh_stays_deterministic(conn, tmp_path):
    # Incremental reconciliation must agree with a from-scratch replay: A@T1
    # creates the belief, A@T3 refreshes it (advancing the evidence to T3), then
    # a late B@T2 arrives out of order. B is newer than active_from (T1) but
    # OLDER than the latest evidence (T3), so it must NOT supersede — replaying
    # A@T1, B@T2, A@T3 in timestamp order also ends at A.
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1)
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "A", observed_at=T3)  # confirming refresh advances evidence to T3
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "B", observed_at=T2)  # late, different value, older than latest evidence
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["skipped"] == 1
    assert counts["superseded"] == 0
    actives = store.list_active_beliefs()
    assert len(actives) == 1 and actives[0]["value"] == "A"  # NOT flipped to B

    # ...and it matches the value a fresh replay of the same three facts yields.
    other = Bene(str(tmp_path / "replay.db"))
    try:
        s2 = TruthStore(other.conn)
        _emit(s2, "A", observed_at=T1)
        _emit(s2, "B", observed_at=T2)
        _emit(s2, "A", observed_at=T3)
        reconcile_beliefs(other.conn, now=NOW)
        replay_actives = s2.list_active_beliefs()
        assert len(replay_actives) == 1
        assert replay_actives[0]["value"] == actives[0]["value"] == "A"
    finally:
        other.close()


def test_equal_timestamp_contradiction_honors_value_hash_tiebreak(tmp_path):
    # Two different values observed at the SAME timestamp. The reducer's canonical
    # order (observed_at, value_hash, fact_id) breaks the tie on value_hash, so the
    # value with the greater value_hash must win regardless of INGESTION order —
    # incremental reconciliation must equal a from-scratch replay.
    v1, v2 = "alpha", "omega"
    hi, lo = (v1, v2) if value_hash(v1) > value_hash(v2) else (v2, v1)
    assert value_hash(hi) > value_hash(lo)

    def active_value_for_order(path, first, second):
        b = Bene(str(path))
        try:
            s = TruthStore(b.conn)
            _emit(s, first, observed_at=T2)
            reconcile_beliefs(b.conn, now=NOW)
            _emit(s, second, observed_at=T2)  # same timestamp, different value
            reconcile_beliefs(b.conn, now=NOW)
            actives = s.list_active_beliefs()
            assert len(actives) == 1
            return actives[0]["value"]
        finally:
            b.close()

    # Whichever order the two same-timestamp facts arrive, the higher value_hash wins.
    assert active_value_for_order(tmp_path / "lo_then_hi.db", lo, hi) == hi
    assert active_value_for_order(tmp_path / "hi_then_lo.db", hi, lo) == hi

    # ...and that matches a from-scratch replay of both facts together.
    b = Bene(str(tmp_path / "replay.db"))
    try:
        s = TruthStore(b.conn)
        _emit(s, lo, observed_at=T2)
        _emit(s, hi, observed_at=T2)
        reconcile_beliefs(b.conn, now=NOW)
        actives = s.list_active_beliefs()
        assert len(actives) == 1 and actives[0]["value"] == hi
    finally:
        b.close()


def test_latest_evidence_key_reads_by_key_not_derived_from(conn):
    # The supersession gate must read latest evidence via a fixed-parameter
    # (key, value_hash) query — never one bound parameter per derived_from id,
    # which can exceed SQLite's host-parameter limit on a hot key. Prove the
    # lookup is key/value driven and independent of the belief's derived_from.
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1)
    _emit(store, "A", observed_at=T3)  # same key+value, later observation
    reconcile_beliefs(conn, now=NOW)
    active = store.list_active_beliefs()[0]
    # Even with an empty derived_from passed in, the key/value query still finds
    # the newest same-value evidence (T3) and returns its value_hash.
    ts, vhash = store.latest_evidence_key({**active, "derived_from": []})
    assert ts == T3
    assert vhash == active["value_hash"]


def test_latest_evidence_excludes_quarantined_same_value_fact(conn):
    # A same-value fact that was quarantined (unsafe/unreliable) never became
    # active evidence, so its timestamp must NOT gate a real contradiction. A
    # valid B newer than the real supporting fact (T1) but older than the
    # quarantined observation must supersede — matching a from-scratch replay.
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1)  # real supporting evidence
    reconcile_beliefs(conn, now=NOW)
    # out-of-order: an unsafe same-value observation lands later and is quarantined
    _emit(store, "A", observed_at="2026-06-05T00:00:00.000", unsafe=True)
    reconcile_beliefs(conn, now=NOW)
    # a valid contradiction between the real evidence (T1) and the quarantined obs
    _emit(store, "B", observed_at=T2)  # T2 = 2026-06-02
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["superseded"] == 1  # NOT skipped/stale
    actives = store.list_active_beliefs(now=NOW)
    assert len(actives) == 1 and actives[0]["value"] == "B"


def _key_tuples(store):
    return sorted(
        (b["subject"], b["relation"], b["scope"], b["value"], b["lifecycle"])
        for b in store.list_beliefs()
    )


def test_replay_from_scratch_is_deterministic(tmp_path):
    def build(path):
        b = Bene(str(path))
        s = TruthStore(b.conn)
        _emit(s, "A", observed_at=T1)
        _emit(s, "B", observed_at=T2, subject="s2")
        _emit(s, "C", observed_at=T3)  # supersedes A on key s/r
        reconcile_beliefs(b.conn, now=NOW)
        out = _key_tuples(s)
        b.close()
        return out

    assert build(tmp_path / "a.db") == build(tmp_path / "b.db")


def test_multi_key_isolation(conn):
    store = TruthStore(conn)
    _emit(store, "A", observed_at=T1, subject="s1")
    _emit(store, "B", observed_at=T1, subject="s2")
    _emit(store, "A", observed_at=T1, subject="s1", scope="run:9")
    reconcile_beliefs(conn, now=NOW)
    assert len(store.list_active_beliefs()) == 3  # three distinct keys


def test_concurrent_reconcile_does_not_double_process(tmp_path):
    # Two+ reducers racing over the same DB file must not both process the same
    # fact (which would trip the active-key unique index or write duplicate
    # rows). Each fact is claimed under BEGIN IMMEDIATE, so concurrent runs
    # serialize into exactly one belief per key with no errors — idempotent
    # under concurrency (Rule 9).
    import threading

    db = str(tmp_path / "concurrent.db")
    seed = Bene(db)
    try:
        s = TruthStore(seed.conn)
        n_keys = 40
        for i in range(n_keys):
            _emit(s, f"v{i}", observed_at=T1, subject=f"s{i:03d}")
    finally:
        seed.close()

    results: list = []
    errors: list = []

    def worker():
        try:
            b = Bene(db)
            try:
                results.append(reconcile_beliefs(b.conn, now=NOW))
            finally:
                b.close()
        except Exception as exc:  # noqa: BLE001 — surface any race crash to the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []  # no IntegrityError / double-claim crash under the race

    check = Bene(db)
    try:
        cs = TruthStore(check.conn)
        # exactly one active belief per key — nothing lost, nothing duplicated
        assert len(cs.list_active_beliefs()) == n_keys
        assert check.conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0] == n_keys
        # every fact consumed exactly once
        assert (
            check.conn.execute(
                "SELECT COUNT(*) FROM belief_facts WHERE reconciled_at IS NULL"
            ).fetchone()[0]
            == 0
        )
        # each fact produced exactly one create decision (no fact processed twice)
        assert (
            check.conn.execute(
                "SELECT COUNT(*) FROM belief_decisions WHERE rule='rule_1_create'"
            ).fetchone()[0]
            == n_keys
        )
        # and the workers together created exactly n_keys beliefs (no overlap)
        assert sum(r["created"] for r in results) == n_keys
    finally:
        check.close()


# ---------------------------------------------------------------- no-LLM / imports (P5)

# Banned: LLM SDKs, network, vector DBs, graph DBs, CLIPS, background/daemon mechanisms.
_BANNED_MODULES = {
    "litellm",
    "openai",
    "anthropic",
    "httpx",
    "requests",
    "urllib",
    "socket",
    "http",
    "aiohttp",
    "clips",
    "neo4j",
    "networkx",
    "chromadb",
    "faiss",
    "pinecone",
    "qdrant_client",
    "threading",
    "multiprocessing",
    "subprocess",
    "asyncio",
}


def test_no_banned_dependencies_in_truth_package():  # Test 13
    import ast
    import pathlib

    pkg = pathlib.Path(__file__).resolve().parents[2] / "bene" / "kernel" / "truth"
    pyfiles = sorted(pkg.glob("*.py"))
    assert pyfiles, "expected truth package source files"
    offenders = {}
    for f in pyfiles:
        tree = ast.parse(f.read_text(), filename=str(f))
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        bad = mods & _BANNED_MODULES
        if bad:
            offenders[f.name] = sorted(bad)
    assert offenders == {}, f"banned imports found: {offenders}"


def test_public_api_imports():
    from bene.kernel.truth import (  # noqa: F401
        TruthStore,
        emit_fact,
        ensure_truth,
        explain_belief,
        list_active_beliefs,
        list_beliefs,
        quarantine_belief,
        reconcile_beliefs,
        value_hash,
    )

    # all are callable
    for fn in (
        emit_fact,
        reconcile_beliefs,
        list_beliefs,
        list_active_beliefs,
        explain_belief,
        quarantine_belief,
        ensure_truth,
        value_hash,
    ):
        assert callable(fn)
    assert isinstance(TruthStore, type)


# ---------------------------------------------------------------- harden / edges (P6)


def test_empty_reconcile_is_all_zero(conn):
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts == {
        "created": 0,
        "superseded": 0,
        "refreshed": 0,
        "quarantined": 0,
        "rejected": 0,
        "skipped": 0,
        "expired": 0,
    }


def test_special_char_and_long_values_round_trip(conn):
    store = TruthStore(conn)
    weird = 'líne1\nlíne2 "quoted" \t \\back — 占位符 ' + "x" * 500
    _emit(store, weird, observed_at=T1, subject="unicode.subj")
    reconcile_beliefs(conn, now=NOW)
    b = store.list_active_beliefs(subject="unicode.subj")[0]
    assert b["value"] == weird


def test_bulk_reconcile_deterministic_and_idempotent(conn):
    store = TruthStore(conn)
    # 20 keys, 3 facts each (final value differs → supersessions), 60 facts total
    for k in range(20):
        _emit(store, "a", observed_at=T1, subject=f"svc{k}")
        _emit(store, "a", observed_at=T2, subject=f"svc{k}")  # refresh
        _emit(store, "b", observed_at=T3, subject=f"svc{k}")  # supersede
    counts = reconcile_beliefs(conn, now=NOW)
    assert counts["created"] == 20
    assert counts["refreshed"] == 20
    assert counts["superseded"] == 20
    assert len(store.list_active_beliefs()) == 20
    # idempotent second run
    counts2 = reconcile_beliefs(conn, now=NOW)
    assert sum(counts2.values()) == 0


def test_north_star_no_unsafe_belief_is_ever_promotable(conn):
    """Across a mixed scenario, nothing that is not a clean active belief is promotable."""
    store = TruthStore(conn)
    # active + superseded on one key
    _emit(store, "A", observed_at=T1, subject="k1")
    reconcile_beliefs(conn, now=NOW)
    _emit(store, "B", observed_at=T2, subject="k1")
    reconcile_beliefs(conn, now=NOW)
    # quarantined via unreliable source
    _emit(store, "bad", observed_at=T1, subject="k2", source_type="failed")
    # quarantined via unsafe flag
    _emit(store, "danger", observed_at=T1, subject="k3", unsafe=True)
    # expired
    _emit(store, "old", observed_at=T1, subject="k4", expires_at="2020-01-01T00:00:00.000")
    reconcile_beliefs(conn, now=NOW)
    # manual quarantine of an active belief
    _emit(store, "C", observed_at=T1, subject="k5")
    reconcile_beliefs(conn, now=NOW)
    bid = store.list_active_beliefs(subject="k5")[0]["belief_id"]
    quarantine_belief(conn, bid, reason="distrust", now=NOW)
    # THE invariant: no non-active belief is promotable
    bad = conn.execute(
        "SELECT COUNT(*) FROM beliefs WHERE lifecycle != 'active' AND admissible_for_promotion = 1"
    ).fetchone()[0]
    assert bad == 0
    # and every belief is explainable (has >=1 decision)
    for b in store.list_beliefs():
        n = conn.execute(
            "SELECT COUNT(*) FROM belief_decisions WHERE belief_id = ?",
            (b["belief_id"],),
        ).fetchone()[0]
        assert n >= 1


# ---------------------------------------------------------------- review-fix regressions (P6)


def test_value_type_round_trip(conn):  # C1
    """Non-string values round-trip to their original Python type through a belief."""
    store = TruthStore(conn)
    cases = {"i": 42, "f": 3.5, "b": True, "lst": [1, 2, 3], "d": {"x": 1}, "s": "green"}
    for rel, val in cases.items():
        store.emit_fact(kind="observation", subject="rt", relation=rel, value=val)
    reconcile_beliefs(conn, now=NOW)
    for rel, val in cases.items():
        b = store.list_active_beliefs(subject="rt", relation=rel)[0]
        assert b["value"] == val, (rel, b["value"], val)
    # int 1 and str "1" stay distinct values (canonical hash)
    store.emit_fact(kind="observation", subject="rt2", relation="n", value=1)
    store.emit_fact(kind="observation", subject="rt2", relation="s", value="1")
    reconcile_beliefs(conn, now=NOW)
    assert store.list_active_beliefs(subject="rt2", relation="n")[0]["value"] == 1
    assert store.list_active_beliefs(subject="rt2", relation="s")[0]["value"] == "1"


def test_emit_rejects_string_derived_from(conn):  # TRUTH-SEC-002
    store = TruthStore(conn)
    with pytest.raises(InvalidFact):
        store.emit_fact(
            kind="observation", subject="s", relation="r", value="v", derived_from="fact-123"
        )


def test_emit_rejects_non_dict_metadata(conn):  # TRUTH-SEC-003
    store = TruthStore(conn)
    with pytest.raises(InvalidFact):
        store.emit_fact(
            kind="observation", subject="s", relation="r", value="v", metadata="not-a-dict"
        )


def test_emit_rejects_non_numeric_confidence(conn):  # TRUTH-SEC-004
    store = TruthStore(conn)
    with pytest.raises(InvalidFact):
        store.emit_fact(kind="observation", subject="s", relation="r", value="v", confidence="high")


def test_db_check_blocks_non_active_promotable(conn):  # TRUTH-SEC-001
    # The north-star invariant is enforced at the DB level, not just in code.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO beliefs (belief_id, subject, relation, value, value_hash, scope,"
            " lifecycle, admissible_for_promotion)"
            " VALUES ('bx','s','r','v','h','global','quarantined',1)"
        )
    # an active belief MAY be promotable (the constraint only restricts non-active)
    conn.execute(
        "INSERT INTO beliefs (belief_id, subject, relation, value, value_hash, scope,"
        " lifecycle, admissible_for_promotion)"
        " VALUES ('bok','s','r','v','h','global','active',1)"
    )


def test_same_timestamp_replay_is_deterministic(tmp_path):  # DETERMINISM-001
    """Two conflicting facts at the SAME observed_at must pick the same winner across
    replays, regardless of emission order (content-stable value_hash tie-break)."""

    def build(path, order):
        b = Bene(str(path))
        s = TruthStore(b.conn)
        for v in order:
            s.emit_fact(kind="observation", subject="k", relation="r", value=v, observed_at=T1)
        reconcile_beliefs(b.conn, now=NOW)
        winner = s.list_active_beliefs(subject="k")[0]["value"]
        b.close()
        return winner

    w1 = build(tmp_path / "ab.db", ["A", "B"])
    w2 = build(tmp_path / "ba.db", ["B", "A"])
    assert w1 == w2  # deterministic winner regardless of insertion order


def test_refresh_raises_confidence(conn):  # C2
    store = TruthStore(conn)
    store.emit_fact(
        kind="observation", subject="c", relation="r", value="v", confidence=0.5, observed_at=T1
    )
    reconcile_beliefs(conn, now=NOW)
    store.emit_fact(
        kind="observation", subject="c", relation="r", value="v", confidence=0.9, observed_at=T2
    )
    reconcile_beliefs(conn, now=NOW)
    b = store.list_active_beliefs(subject="c")[0]
    assert abs(b["confidence"] - 0.9) < 1e-9  # confirming fact raised confidence
