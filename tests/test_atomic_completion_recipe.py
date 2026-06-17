"""Tests for the atomic-completion reference recipe (bene/recipes/idempotent_append).

Proves the two properties the recipe promises:
- **exactly-once append**: a replayed write with the same idempotency key is a
  no-op returning the prior id (no duplicate row);
- **ordering inversion leaves no ghost**: durable-record-first completion survives
  a mid-sequence crash with no orphan side effect, whereas the side-effect-first
  anti-pattern leaves a ghost (an external mutation with no committed record).
"""

from __future__ import annotations

import sqlite3

import pytest

from bene.recipes.idempotent_append import (
    append_once,
    complete_in_order,
    complete_side_effect_first,
    ensure_log,
    replay_projection,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    ensure_log(conn)
    return conn


def test_append_once_is_exactly_once_under_retry():
    conn = _conn()
    seq_a, created_a = append_once(conn, "evt-1", {"v": 1})
    conn.commit()
    seq_b, created_b = append_once(conn, "evt-1", {"v": 1})  # replay same key
    assert created_a is True
    assert created_b is False  # the replay is a no-op
    assert seq_a == seq_b  # returns the prior id
    assert conn.execute("SELECT COUNT(*) FROM completions").fetchone()[0] == 1  # no duplicate


def test_unique_key_constraint_rejects_a_racing_duplicate():
    conn = _conn()
    append_once(conn, "evt-1", {"v": 1})
    conn.commit()
    # A racer that bypasses the SELECT and inserts the same key hits the UNIQUE wall.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO completions (idempotency_key, payload) VALUES (?, ?)", ("evt-1", "{}")
        )


def test_side_effect_first_leaves_a_ghost_on_crash():
    """The anti-pattern: the external mutation happens, then a crash before the
    durable commit -> external state changed with NO committed record = ghost."""
    conn = _conn()
    external = {"receipts": 0}

    def side_effect(_payload):
        external["receipts"] += 1
        raise RuntimeError("crash before durable commit")

    with pytest.raises(RuntimeError):
        complete_side_effect_first(conn, "evt-1", {"v": 1}, side_effect)
    conn.rollback()  # restart discards the uncommitted transaction

    # GHOST: the side effect happened, but there is no durable record of it.
    assert external["receipts"] == 1
    assert conn.execute("SELECT COUNT(*) FROM completions").fetchone()[0] == 0


def test_ordered_completion_replays_pending_without_a_ghost():
    """Ordering inversion: the durable record commits FIRST, so the same crash
    before the externally visible mutation leaves a recorded pending completion
    (recoverable), never an orphan side effect."""
    conn = _conn()
    external = {"receipts": 0}

    def crash_before_mutation(_payload):
        raise RuntimeError("crash before side effect, after the durable commit")

    with pytest.raises(RuntimeError):
        complete_in_order(conn, "evt-1", {"v": 1}, crash_before_mutation)

    # The durable record was committed BEFORE the side effect -> it survives the crash,
    # but no external mutation escaped.
    assert conn.execute("SELECT COUNT(*), SUM(side_effect_done) FROM completions").fetchone() == (
        1,
        0,
    )
    assert external["receipts"] == 0

    # Replay with the same key re-drives the pending side effect and marks it done.
    seq, created = complete_in_order(
        conn,
        "evt-1",
        {"v": 1},
        lambda _p: external.__setitem__("receipts", external["receipts"] + 1),
    )
    assert created is False
    assert seq == 1
    assert external["receipts"] == 1
    assert conn.execute("SELECT side_effect_done FROM completions").fetchone()[0] == 1

    # A later replay of a completed key is a no-op.
    _seq, created_again = complete_in_order(
        conn,
        "evt-1",
        {"v": 1},
        lambda _p: external.__setitem__("receipts", external["receipts"] + 1),
    )
    assert created_again is False
    assert external["receipts"] == 1


def test_replay_projection_rebuilds_state_from_the_log():
    """Boot-time projection rebuild: an in-RAM counter reconstructed purely by
    folding the durable log (the restart-amnesia fix)."""
    conn = _conn()
    for i in range(3):
        append_once(conn, f"evt-{i}", {"amount": i})
    conn.commit()

    total = {"sum": 0}
    n = replay_projection(conn, lambda _k, p: total.__setitem__("sum", total["sum"] + p["amount"]))
    assert n == 3
    assert total["sum"] == 0 + 1 + 2
