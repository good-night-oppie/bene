"""TruthStore — persistence + read surface for the truth-maintenance layer.

Pure SQLite I/O over the four ``belief_*`` tables. ``emit_fact`` persists a fact
with every reconciliation-critical field; the query methods return plain,
JSON-friendly dicts; ``explain_belief`` assembles the full lineage view. The
low-level ``_insert_*`` / ``_set_*`` helpers do NOT commit — the deterministic
reducer (``bene.kernel.truth.reducer``) composes them inside its own per-fact
transaction. All SQL is parameterized.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import ulid

from bene.kernel.truth.contract import (
    decode_value,
    encode_value,
    validate_fact,
    value_hash,
)
from bene.kernel.truth.schema import ensure_truth

_JSON_FACT_COLS = ("derived_from", "metadata")
_JSON_BELIEF_COLS = ("derived_from",)


def _decode_value_field(d: dict) -> dict:
    """Decode the stored ``value`` TEXT back to its original Python type (read side)."""
    if "value" in d:
        d["value"] = decode_value(d["value"])
    return d


def _row_to_dict(cur: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cur.description)}


def _parse_json_cols(d: dict, cols: tuple[str, ...]) -> dict:
    for c in cols:
        if c in d and isinstance(d[c], str):
            try:
                d[c] = json.loads(d[c])
            except (ValueError, TypeError):
                pass
    return d


class TruthStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        ensure_truth(conn)

    # ---------------- time ----------------

    def now(self) -> str:
        return self.conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%f','now')").fetchone()[0]

    # ---------------- emit ----------------

    def emit_fact(
        self,
        *,
        kind: str,
        subject: str,
        relation: str,
        value: Any,
        scope: str = "global",
        source: str | None = None,
        source_type: str | None = None,
        confidence: float = 1.0,
        observed_at: str | None = None,
        expires_at: str | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
        trace_id: str | None = None,
        evidence_uri: str | None = None,
        derived_from: list | None = None,
        metadata: dict | None = None,
        unsafe: bool = False,
    ) -> str:
        """Persist one fact (immutable). Returns its ``fact_id``."""
        validate_fact(
            kind=kind,
            subject=subject,
            relation=relation,
            confidence=confidence,
            derived_from=derived_from,
            metadata=metadata,
        )
        fact_id = str(ulid.new())
        self.conn.execute(
            "INSERT INTO belief_facts (fact_id, kind, subject, relation, value,"
            " value_hash, scope, source, source_type, confidence, observed_at,"
            " expires_at, run_id, agent_id, trace_id, evidence_uri, derived_from,"
            " metadata, unsafe)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                fact_id,
                kind,
                subject,
                relation,
                encode_value(value),
                value_hash(value),
                scope,
                source,
                source_type,
                float(confidence),
                observed_at or self.now(),
                expires_at,
                run_id,
                agent_id,
                trace_id,
                evidence_uri,
                json.dumps(list(derived_from) if derived_from else []),
                json.dumps(metadata or {}),
                1 if unsafe else 0,
            ),
        )
        self.conn.commit()
        return fact_id

    # ---------------- fact queries ----------------

    def get_fact(self, fact_id: str) -> dict | None:
        cur = self.conn.execute("SELECT * FROM belief_facts WHERE fact_id = ?", (fact_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return _decode_value_field(_parse_json_cols(_row_to_dict(cur, row), _JSON_FACT_COLS))

    def list_facts(
        self,
        *,
        subject: str | None = None,
        relation: str | None = None,
        scope: str | None = None,
        kind: str | None = None,
        reconciled: bool | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        clauses, params = [], []
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        if relation is not None:
            clauses.append("relation = ?")
            params.append(relation)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if reconciled is True:
            clauses.append("reconciled_at IS NOT NULL")
        elif reconciled is False:
            clauses.append("reconciled_at IS NULL")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # noqa: S608 — `where` is built only from hardcoded "col = ?" fragments; every
        # value is bound via `params`. No caller input is interpolated into the SQL text.
        sql = f"SELECT * FROM belief_facts{where} ORDER BY observed_at, value_hash, fact_id"  # noqa: S608
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self.conn.execute(sql, params)
        rows = cur.fetchall()
        return [
            _decode_value_field(_parse_json_cols(_row_to_dict(cur, r), _JSON_FACT_COLS))
            for r in rows
        ]

    def unreconciled_facts(self) -> list[dict]:
        """Facts the reducer has not yet consumed, in a CONTENT-deterministic order.

        Ordered by ``(observed_at, value_hash, fact_id)``. ``value_hash`` is the
        cross-replay-stable tie-breaker: when two facts for the same key share an
        ``observed_at``, the same value always sorts the same regardless of ULID
        entropy or emission order, so a from-scratch replay picks the same winner.
        ``value`` is left RAW (encoded) here — the reducer copies it verbatim into
        the belief row; callers read decoded values via the query methods.
        """
        cur = self.conn.execute(
            "SELECT * FROM belief_facts WHERE reconciled_at IS NULL"
            " ORDER BY observed_at, value_hash, fact_id"
        )
        rows = cur.fetchall()
        return [_parse_json_cols(_row_to_dict(cur, r), _JSON_FACT_COLS) for r in rows]

    def mark_fact_reconciled(self, fact_id: str, now: str) -> None:
        self.conn.execute(
            "UPDATE belief_facts SET reconciled_at = ? WHERE fact_id = ?",
            (now, fact_id),
        )

    # ---------------- belief queries ----------------

    def get_belief(self, belief_id: str) -> dict | None:
        cur = self.conn.execute("SELECT * FROM beliefs WHERE belief_id = ?", (belief_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return _decode_value_field(_parse_json_cols(_row_to_dict(cur, row), _JSON_BELIEF_COLS))

    def get_active_belief(self, subject: str, relation: str, scope: str) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM beliefs WHERE subject = ? AND relation = ? AND scope = ?"
            " AND lifecycle = 'active'",
            (subject, relation, scope),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _decode_value_field(_parse_json_cols(_row_to_dict(cur, row), _JSON_BELIEF_COLS))

    def list_beliefs(
        self,
        *,
        subject: str | None = None,
        relation: str | None = None,
        scope: str | None = None,
        lifecycle: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        clauses, params = [], []
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        if relation is not None:
            clauses.append("relation = ?")
            params.append(relation)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if lifecycle is not None:
            clauses.append("lifecycle = ?")
            params.append(lifecycle)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # noqa: S608 — `where` is hardcoded "col = ?" fragments only; values bound via params.
        sql = f"SELECT * FROM beliefs{where} ORDER BY subject, relation, scope, created_at"  # noqa: S608
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self.conn.execute(sql, params)
        rows = cur.fetchall()
        return [
            _decode_value_field(_parse_json_cols(_row_to_dict(cur, r), _JSON_BELIEF_COLS))
            for r in rows
        ]

    def list_active_beliefs(
        self,
        *,
        subject: str | None = None,
        relation: str | None = None,
        scope: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        return self.list_beliefs(
            subject=subject,
            relation=relation,
            scope=scope,
            lifecycle="active",
            limit=limit,
        )

    # ---------------- decisions / conflicts queries ----------------

    def decisions_for(self, belief_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM belief_decisions WHERE belief_id = ? ORDER BY created_at, decision_id",
            (belief_id,),
        )
        rows = cur.fetchall()
        return [_parse_json_cols(_row_to_dict(cur, r), ("metadata",)) for r in rows]

    def conflicts_for_key(self, subject: str, relation: str, scope: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM belief_conflicts WHERE subject = ? AND relation = ?"
            " AND scope = ? ORDER BY created_at, conflict_id",
            (subject, relation, scope),
        )
        rows = cur.fetchall()
        return [_row_to_dict(cur, r) for r in rows]

    # ---------------- explain ----------------

    def explain_belief(self, belief_id: str) -> dict | None:
        """Full lineage view: belief + source facts + decisions + conflicts + flags."""
        belief = self.get_belief(belief_id)
        if belief is None:
            return None
        # source facts: those linked in derived_from PLUS any fact for the key.
        fact_ids = set(belief.get("derived_from") or [])
        facts: dict[str, dict] = {}
        for fid in fact_ids:
            f = self.get_fact(fid)
            if f is not None:
                facts[fid] = f
        for f in self.list_facts(
            subject=belief["subject"],
            relation=belief["relation"],
            scope=belief["scope"],
        ):
            facts.setdefault(f["fact_id"], f)
        decisions = self.decisions_for(belief_id)
        conflicts = self.conflicts_for_key(belief["subject"], belief["relation"], belief["scope"])
        return {
            "belief": belief,
            "facts": sorted(
                facts.values(), key=lambda x: (x.get("observed_at") or "", x["fact_id"])
            ),
            "decisions": decisions,
            "conflicts": conflicts,
            "admissibility": {
                "context": belief["admissible_for_context"],
                "promotion": belief["admissible_for_promotion"],
                "action": belief["admissible_for_action"],
            },
        }

    # ---------------- low-level writers (used by the reducer; no commit) -------

    def insert_belief(
        self,
        *,
        subject: str,
        relation: str,
        value: str,
        value_hash: str,
        scope: str,
        lifecycle: str,
        confidence: float,
        active_from: str | None,
        active_until: str | None,
        derived_from: list,
        admissible: tuple[int, int, int],
        now: str,
        last_decision_id: str | None = None,
    ) -> str:
        belief_id = str(ulid.new())
        self.conn.execute(
            "INSERT INTO beliefs (belief_id, subject, relation, value, value_hash,"
            " scope, lifecycle, confidence, active_from, active_until, derived_from,"
            " last_decision_id, admissible_for_context, admissible_for_promotion,"
            " admissible_for_action, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                belief_id,
                subject,
                relation,
                value,
                value_hash,
                scope,
                lifecycle,
                float(confidence),
                active_from,
                active_until,
                json.dumps(list(derived_from)),
                last_decision_id,
                int(admissible[0]),
                int(admissible[1]),
                int(admissible[2]),
                now,
                now,
            ),
        )
        return belief_id

    def insert_decision(
        self,
        *,
        belief_id: str | None,
        rule: str,
        from_lifecycle: str | None,
        to_lifecycle: str | None,
        reason: str,
        fact_id: str | None,
        admissible: tuple[int, int, int],
        now: str,
        metadata: dict | None = None,
    ) -> str:
        decision_id = str(ulid.new())
        self.conn.execute(
            "INSERT INTO belief_decisions (decision_id, belief_id, rule,"
            " from_lifecycle, to_lifecycle, reason, fact_id, admissible_for_context,"
            " admissible_for_promotion, admissible_for_action, metadata, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                decision_id,
                belief_id,
                rule,
                from_lifecycle,
                to_lifecycle,
                reason,
                fact_id,
                int(admissible[0]),
                int(admissible[1]),
                int(admissible[2]),
                json.dumps(metadata or {}),
                now,
            ),
        )
        return decision_id

    def insert_conflict(
        self,
        *,
        subject: str,
        relation: str,
        scope: str,
        belief_id: str | None,
        fact_id: str | None,
        kind: str,
        resolution: str,
        decision_id: str | None,
        now: str,
    ) -> str:
        conflict_id = str(ulid.new())
        self.conn.execute(
            "INSERT INTO belief_conflicts (conflict_id, subject, relation, scope,"
            " belief_id, fact_id, kind, resolution, decision_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                conflict_id,
                subject,
                relation,
                scope,
                belief_id,
                fact_id,
                kind,
                resolution,
                decision_id,
                now,
            ),
        )
        return conflict_id

    def set_belief_lifecycle(
        self,
        belief_id: str,
        lifecycle: str,
        *,
        active_until: str | None = None,
        admissible: tuple[int, int, int] | None = None,
        last_decision_id: str | None = None,
        now: str,
    ) -> None:
        sets = ["lifecycle = ?", "updated_at = ?"]
        params: list[Any] = [lifecycle, now]
        if active_until is not None:
            sets.append("active_until = ?")
            params.append(active_until)
        if admissible is not None:
            sets += [
                "admissible_for_context = ?",
                "admissible_for_promotion = ?",
                "admissible_for_action = ?",
            ]
            params += [int(admissible[0]), int(admissible[1]), int(admissible[2])]
        if last_decision_id is not None:
            sets.append("last_decision_id = ?")
            params.append(last_decision_id)
        params.append(belief_id)
        # `sets` is hardcoded "col = ?" assignments only; all values bound via params.
        sql = f"UPDATE beliefs SET {', '.join(sets)} WHERE belief_id = ?"  # noqa: S608
        self.conn.execute(sql, params)

    def set_belief_last_decision(self, belief_id: str, decision_id: str) -> None:
        self.conn.execute(
            "UPDATE beliefs SET last_decision_id = ? WHERE belief_id = ?",
            (decision_id, belief_id),
        )

    def link_fact_to_belief(
        self, belief_id: str, fact_id: str, now: str, *, confidence: float | None = None
    ) -> None:
        belief = self.get_belief(belief_id)
        if belief is None:
            return
        df = list(belief.get("derived_from") or [])
        if fact_id not in df:
            df.append(fact_id)
        if confidence is None:
            self.conn.execute(
                "UPDATE beliefs SET derived_from = ?, updated_at = ? WHERE belief_id = ?",
                (json.dumps(df), now, belief_id),
            )
        else:
            self.conn.execute(
                "UPDATE beliefs SET derived_from = ?, confidence = ?, updated_at = ?"
                " WHERE belief_id = ?",
                (json.dumps(df), float(confidence), now, belief_id),
            )
