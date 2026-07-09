"""EngramStore — the BENE 2.0 unified experience substrate.

Everything is an engram: traces, memories, skills, eval verdicts, experiments,
trust events, strategies — one typed, append-only, provenance-linked log with
a compression ladder (tier 0 raw trace → 4 strategic gene). Design: D1/D2 in
docs/design/DESIGN-RATIONALE.md; contract: docs/design/KERNEL-SPEC.md §2.1.

Invariants enforced here:
- Every engram REQUIRES provenance ({"agent_id": ...} or {"system": ...}).
- Promotion never mutates sources; it appends a new engram at a strictly
  higher tier with a ``consolidates`` link.
- Payloads >4KB go to the content-addressed blob store; small ones inline.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import ulid

from bene.blobs import BlobStore
from bene.fts import fallback_fts_query

INLINE_LIMIT = 4096
FTS_BODY_LIMIT = 8192

#: Deferred-append buffer cap. A memory-bound constant (small power of two),
#: not derived from any dataset: it bounds both the RAM held by buffered rows
#: and the worst-case number of mirror engrams lost if the process dies before
#: a flush. Reaching the cap triggers an automatic non-committing flush.
DEFER_BUFFER_CAP = 64

ENGRAM_KINDS = frozenset(
    {
        "trace",
        "episodic",
        "semantic",
        "procedural",
        "strategic",
        "eval",
        "experiment",
        "trust",
        "pollution",
        "intervention",
        "proposal",
        "spec",
        "report",
    }
)

LINK_TYPES = frozenset(
    {
        "derived_from",
        "consolidates",
        "verifies",
        "refutes",
        "associates",
        "supersedes",
        "about_agent",
        "gated_by",
    }
)

#: Tier → kind used by :meth:`EngramStore.promote` (the compression ladder).
TIER_KINDS = {0: "trace", 1: "episodic", 2: "semantic", 3: "procedural", 4: "strategic"}


class ProvenanceRequired(ValueError):
    """Raised when an engram is appended without agent or system provenance."""


class TierViolation(ValueError):
    """Raised when a promotion does not strictly increase the tier."""


class UnknownEngram(KeyError):
    """Raised when an engram_id does not exist."""


@dataclass(frozen=True)
class Engram:
    engram_id: str
    kind: str
    tier: int
    title: str
    content_hash: str | None
    inline_body: str | None
    metadata: dict[str, Any]
    provenance: dict[str, Any]
    agent_id: str | None
    created_at: str
    superseded_by: str | None = None
    score: float | None = field(default=None, compare=False)  # FTS rank when searched


def _validate_provenance(provenance: dict[str, Any]) -> None:
    if not isinstance(provenance, dict) or not (
        provenance.get("agent_id") or provenance.get("system")
    ):
        raise ProvenanceRequired(
            "engram provenance must include 'agent_id' or 'system' — no anonymous experience"
        )


class EngramStore:
    """Append-only typed engram log over one BENE database connection."""

    def __init__(self, conn: sqlite3.Connection, blobs: BlobStore | None = None) -> None:
        self.conn = conn
        self.blobs = blobs or BlobStore(conn)
        # Deferred-append buffers (opt-in via append(..., deferred=True)).
        # Parallel lists drained together by flush() with executemany.
        self._pending_engrams: list[tuple[Any, ...]] = []
        self._pending_fts: list[tuple[str, str, str]] = []
        self._pending_links: list[tuple[str, str, str, str, float]] = []

    # ---------------- append / read ----------------

    def append(
        self,
        kind: str,
        title: str,
        payload: str | bytes = "",
        *,
        provenance: dict[str, Any],
        parents: list[str] | None = None,
        link_type: str = "derived_from",
        tier: int = 0,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
        deferred: bool = False,
    ) -> str:
        """Append one engram. Default path (``deferred=False``) is unchanged:
        rows hit SQLite synchronously and ``commit=True`` makes them durable
        before returning.

        ``deferred=True`` (opt-in, used by the adapter mirrors) buffers the
        row in process memory instead: the hot path is validation + ULID +
        tuple-build, and SQLite work is batched into :meth:`flush` via
        ``executemany``. Buffered rows are flushed automatically when the
        buffer reaches :data:`DEFER_BUFFER_CAP`, before any read on this
        store (read-your-writes), or explicitly via :meth:`flush`; they
        become durable at the caller's next commit. ``deferred=True`` with
        ``commit=True`` flushes and commits immediately (durability on
        return is preserved). Crash caveat: until flushed, buffered rows
        exist only in memory — see ``bene/kernel/adapters.py`` for the full
        mirror durability contract."""
        if kind not in ENGRAM_KINDS:
            raise ValueError(f"unknown engram kind: {kind!r}")
        _validate_provenance(provenance)
        if deferred and parents and link_type not in LINK_TYPES:
            raise ValueError(f"unknown link type: {link_type!r}")

        raw = payload.encode() if isinstance(payload, str) else payload
        content_hash: str | None = None
        inline_body: str | None = None
        if len(raw) > INLINE_LIMIT:
            # Blob rows are content-addressed and carry no FK to engrams, so
            # they are written synchronously even in deferred mode (they ride
            # the same open transaction).
            content_hash, _size = self.blobs.store(raw)
        else:
            inline_body = raw.decode(errors="replace")

        engram_id = str(ulid.new())
        row = (
            engram_id,
            kind,
            tier,
            title,
            content_hash,
            inline_body,
            json.dumps(metadata or {}),
            json.dumps(provenance),
            agent_id,
        )
        body_text = raw.decode(errors="replace")[:FTS_BODY_LIMIT]

        if deferred:
            self._pending_engrams.append(row)
            self._pending_fts.append((engram_id, title, body_text))
            for parent in parents or []:
                self._pending_links.append((str(ulid.new()), engram_id, parent, link_type, 1.0))
            if len(self._pending_engrams) >= DEFER_BUFFER_CAP:
                self.flush()
            if commit:
                self.flush(commit=True)
            return engram_id

        self.conn.execute(
            "INSERT INTO engrams (engram_id, kind, tier, title, content_hash, inline_body,"
            " metadata, provenance, agent_id) VALUES (?,?,?,?,?,?,?,?,?)",
            row,
        )
        self.conn.execute(
            "INSERT INTO engram_fts (engram_id, title, body) VALUES (?,?,?)",
            (engram_id, title, body_text),
        )
        for parent in parents or []:
            self.link(engram_id, parent, link_type)
        if commit:
            # Per-call durability costs an fsync (~3.7 ms measured, bench row
            # A6); high-frequency mirror paths pass commit=False and ride the
            # caller's transaction cadence instead.
            self.conn.commit()
        return engram_id

    def flush(self, *, commit: bool = False) -> int:
        """Drain the deferred-append buffer into SQLite with batched
        ``executemany`` inserts (engrams, then FTS rows, then parent links —
        FK-safe order). Does NOT commit unless asked: flushed rows join the
        connection's open transaction and become durable at the caller's
        next commit, exactly the ``commit=False`` contract. Returns the
        number of engrams flushed."""
        n = len(self._pending_engrams)
        if n:
            self.conn.executemany(
                "INSERT INTO engrams (engram_id, kind, tier, title, content_hash, inline_body,"
                " metadata, provenance, agent_id) VALUES (?,?,?,?,?,?,?,?,?)",
                self._pending_engrams,
            )
            self.conn.executemany(
                "INSERT INTO engram_fts (engram_id, title, body) VALUES (?,?,?)",
                self._pending_fts,
            )
            if self._pending_links:
                self.conn.executemany(
                    "INSERT OR IGNORE INTO engram_links (link_id, src_id, dst_id, link_type,"
                    " weight) VALUES (?,?,?,?,?)",
                    self._pending_links,
                )
            self._pending_engrams.clear()
            self._pending_fts.clear()
            self._pending_links.clear()
        if commit:
            self.conn.commit()
        return n

    @property
    def pending(self) -> int:
        """Number of deferred engrams buffered in memory, not yet in SQLite."""
        return len(self._pending_engrams)

    def get(self, engram_id: str) -> Engram:
        if self._pending_engrams:
            self.flush()  # read-your-writes over the deferred buffer
        row = self.conn.execute(
            "SELECT engram_id, kind, tier, title, content_hash, inline_body, metadata,"
            " provenance, agent_id, created_at, superseded_by FROM engrams WHERE engram_id = ?",
            (engram_id,),
        ).fetchone()
        if row is None:
            raise UnknownEngram(engram_id)
        return self._to_engram(row)

    def payload(self, engram_id: str) -> bytes:
        e = self.get(engram_id)
        if e.content_hash:
            return self.blobs.retrieve(e.content_hash)
        return (e.inline_body or "").encode()

    # ---------------- search / lineage ----------------

    def search(
        self,
        query: str,
        *,
        kind: str | None = None,
        tier: int | None = None,
        agent_id: str | None = None,
        limit: int = 20,
    ) -> list[Engram]:
        if self._pending_engrams:
            self.flush()  # read-your-writes over the deferred buffer
        sql = (
            "SELECT e.engram_id, e.kind, e.tier, e.title, e.content_hash, e.inline_body,"
            " e.metadata, e.provenance, e.agent_id, e.created_at, e.superseded_by,"
            " bm25(engram_fts) AS rank FROM engram_fts"
            " JOIN engrams e ON e.engram_id = engram_fts.engram_id"
            " WHERE engram_fts MATCH ?"
        )
        params: list[Any] = [query]
        if kind is not None:
            sql += " AND e.kind = ?"
            params.append(kind)
        if tier is not None:
            sql += " AND e.tier = ?"
            params.append(tier)
        if agent_id is not None:
            sql += " AND e.agent_id = ?"
            params.append(agent_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # Malformed FTS5 syntax (unbalanced quotes, bare operators, ...):
            # degrade to a sanitized bag-of-words query instead of crashing.
            fallback = fallback_fts_query(query)
            if not fallback:
                return []
            params[0] = fallback
            try:
                rows = self.conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        return [self._to_engram(r[:11], score=r[11]) for r in rows]

    def lineage(
        self, engram_id: str, *, direction: str = "ancestors", max_depth: int = 10
    ) -> list[Engram]:
        """BFS over engram_links. ancestors: follow src→dst; descendants: dst→src."""
        if direction not in ("ancestors", "descendants"):
            raise ValueError("direction must be 'ancestors' or 'descendants'")
        self.get(engram_id)  # existence check
        col_from, col_to = (
            ("src_id", "dst_id") if direction == "ancestors" else ("dst_id", "src_id")
        )
        seen: set[str] = {engram_id}
        frontier = [engram_id]
        ordered: list[str] = []
        for _ in range(max_depth):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            rows = self.conn.execute(
                f"SELECT {col_to} FROM engram_links WHERE {col_from} IN ({placeholders})",
                frontier,
            ).fetchall()
            frontier = [r[0] for r in rows if r[0] not in seen]
            seen.update(frontier)
            ordered.extend(frontier)

        # Batched hydration instead of one get() per node (N+1). Chunked so a
        # deep/wide lineage can never exceed SQLite's per-statement host-parameter
        # limit, and missing ids still raise UnknownEngram exactly like get() —
        # a dangling link is graph corruption, not something to silently drop.
        # Pending engrams were already flushed by the existence-check get() above.
        row_map: dict[str, Any] = {}
        chunk_size = 500
        for i in range(0, len(ordered), chunk_size):
            chunk = ordered[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            for r in self.conn.execute(
                "SELECT engram_id, kind, tier, title, content_hash, inline_body, metadata,"
                " provenance, agent_id, created_at, superseded_by FROM engrams"
                f" WHERE engram_id IN ({placeholders})",  # noqa: S608 — bound "?" markers only
                chunk,
            ).fetchall():
                row_map[r[0]] = r
        result = []
        for eid in ordered:
            row = row_map.get(eid)
            if row is None:
                raise UnknownEngram(eid)
            result.append(self._to_engram(row))
        return result

    # ---------------- promotion / linking ----------------

    def promote(
        self,
        engram_id: str,
        *,
        new_tier: int,
        title: str,
        payload: str | bytes,
        provenance: dict[str, Any],
        sources: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Consolidate: append a NEW engram at a strictly higher tier linked
        ``consolidates`` → source(s). The sources are never mutated."""
        primary = self.get(engram_id)
        if new_tier <= primary.tier:
            raise TierViolation(
                f"promotion must increase tier (source={primary.tier}, new={new_tier})"
            )
        if new_tier not in TIER_KINDS:
            raise TierViolation(f"tier must be 0..4, got {new_tier}")
        all_sources = [engram_id] + [s for s in (sources or []) if s != engram_id]
        return self.append(
            TIER_KINDS[new_tier],
            title,
            payload,
            provenance=provenance,
            parents=all_sources,
            link_type="consolidates",
            tier=new_tier,
            agent_id=primary.agent_id,
            metadata=metadata,
        )

    def supersede(self, old_id: str, new_id: str) -> None:
        self.get(old_id)
        self.get(new_id)
        self.conn.execute(
            "UPDATE engrams SET superseded_by = ? WHERE engram_id = ?", (new_id, old_id)
        )
        self.link(new_id, old_id, "supersedes")
        self.conn.commit()

    def link(self, src_id: str, dst_id: str, link_type: str, weight: float = 1.0) -> str:
        if link_type not in LINK_TYPES:
            raise ValueError(f"unknown link type: {link_type!r}")
        if self._pending_engrams:
            self.flush()  # links carry FKs to engrams; flush so targets exist
        link_id = str(ulid.new())
        self.conn.execute(
            "INSERT OR IGNORE INTO engram_links (link_id, src_id, dst_id, link_type, weight)"
            " VALUES (?,?,?,?,?)",
            (link_id, src_id, dst_id, link_type, weight),
        )
        return link_id

    # ---------------- helpers ----------------

    @staticmethod
    def _to_engram(row: Any, score: float | None = None) -> Engram:
        return Engram(
            engram_id=row[0],
            kind=row[1],
            tier=row[2],
            title=row[3],
            content_hash=row[4],
            inline_body=row[5],
            metadata=json.loads(row[6]),
            provenance=json.loads(row[7]),
            agent_id=row[8],
            created_at=row[9],
            superseded_by=row[10],
            score=score,
        )
