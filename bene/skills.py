"""Cross-agent skill library backed by SQLite FTS5.

Inspired by the Externalization framework in:
  "Externalization in LLM Agents: A Unified Review of Memory, Skills,
   Protocols and Harness Engineering"
  Zhou et al. 2026, arXiv:2604.08224

Skills are *procedural* artifacts — parameterized templates that encode
reusable solution patterns.  They are distinct from memory entries
(episodic / factual) and complement them:

  memory → "Accuracy was 87% on dataset X using ensemble voting"
  skill  → "To improve classification: try ensemble with {n_models} models,
             use {voting} voting, tune threshold to {threshold}"

Any agent in the project can save a skill.  Any agent can search and
apply skills using SQLite FTS5 with porter stemming.  Usage outcomes
(success / failure) are tracked so agents can rank skills by reliability.

Two ranking modes are available in :meth:`SkillStore.search`:

  ``rank="bm25"``      (default) classic FTS5 BM25 relevance — unchanged
                       legacy behavior.
  ``rank="weighted"``  opt-in outcome-aware re-ranking: BM25 relevance is
                       multiplied by a Wilson-lower-bound reliability factor
                       and an exponential recency decay, so skills that keep
                       succeeding rise above lexically-similar skills that
                       keep failing.

The weighted mode is fed by :meth:`SkillStore.record_outcome`, which —
besides the legacy ``use_count`` / ``success_count`` aggregates — appends a
per-use telemetry row to the ``skill_uses`` table (provisioned lazily and
additively; pre-existing databases keep working and the write is
best-effort).  Outcomes may optionally carry a *continuous* quality score in
``[0, 1]`` so near-misses earn partial credit instead of being collapsed to
binary failure.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from string import Formatter
from typing import Any, cast

from bene.fts import fallback_fts_query
from bene.skills_discovery import discover_skills

# ── Ranking-signal primitives ────────────────────────────────────────────
#
# Pure, deterministic, no I/O.  These are general estimator defaults
# (statistical / decay choices), not values derived from any dataset:
#
#   DEFAULT_HALF_LIFE_DAYS    exponential recency half-life: a skill last
#                             used two weeks ago counts half as much.
#   DEFAULT_WILSON_Z          1.96 ≈ 95% confidence for the Wilson interval.
#   DEFAULT_BM25_FLOOR        keeps the retrieval term positive so the
#                             usage/recency multipliers stay meaningful.
#   DEFAULT_USAGE_MULTIPLIER  swing between "never used" (0.5) and "proven
#                             reliable" (3.5) — a 7× ratio, enough to
#                             overcome moderate BM25 differences between
#                             nearly-equally-relevant skills.
#   COLD_START_FACTOR         neutral offset so never-used skills are
#                             discounted, not zeroed out.

DEFAULT_HALF_LIFE_DAYS = 14.0
DEFAULT_WILSON_Z = 1.96
DEFAULT_BM25_FLOOR = 0.01
DEFAULT_USAGE_MULTIPLIER = 3.0
COLD_START_FACTOR = 0.5

# Over-fetch factor for weighted re-ranking: pull limit×4 BM25 candidates so
# the reliability/recency weights have something to reorder.  BM25 still
# gates relevance; weights only permute the candidate set.
_WEIGHTED_OVERFETCH = 4


def parse_iso(ts: str | None) -> datetime | None:
    """Parse a BENE ISO-8601 timestamp.  Returns None on empty/garbage input.

    BENE stores ``strftime('%Y-%m-%dT%H:%M:%f','now')`` (UTC, no timezone
    suffix); naive timestamps are therefore treated as UTC.
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def recency_weight(
    ts: str | None,
    *,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Return an exponential-decay recency multiplier in (0, 1].

    ``weight = 2^(-age_days / half_life_days)``.  Never returns 0.0 — an
    ancient timestamp still yields a tiny positive weight rather than zeroing
    the skill out.  Missing or unparseable timestamps get a neutral 0.5 so
    unknowns are neither privileged nor punished.
    """
    if half_life_days <= 0:
        raise ValueError(f"half_life_days must be > 0, got {half_life_days!r}")
    parsed = parse_iso(ts)
    if parsed is None:
        return 0.5
    current = now or datetime.now(timezone.utc)
    age_days = max(0.0, (current - parsed).total_seconds()) / 86400.0
    return math.pow(2.0, -age_days / half_life_days)


def wilson_lower_bound(successes: float, uses: int, z: float = DEFAULT_WILSON_Z) -> float:
    """Wilson score interval lower bound — a conservative reliability estimator.

    Penalises small samples more than a raw success rate does, so a skill
    with 10/10 successes outranks one with 1/1.  Returns 0.0 when
    ``uses <= 0``; the result is clamped to [0, 1].

    ``successes`` may be *fractional*: the Wilson interval is defined for a
    proportion ``p̂ = successes / n`` and nothing in the formula requires an
    integer numerator.  Feeding it ``SUM(quality)`` with each quality ∈ [0, 1]
    is the standard continuous/weighted-Bernoulli generalisation — ``p̂``
    stays in [0, 1] (``SUM(quality) ≤ n``), so the variance term
    ``p̂(1−p̂)`` is non-negative and the square root is always real.  See
    Brown, Cai & DasGupta (2001), "Interval Estimation for a Binomial
    Proportion", on the robustness of the Wilson interval.
    """
    if uses <= 0:
        return 0.0
    phat = successes / uses
    n = uses
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    lower = (centre - margin) / denom
    return max(0.0, min(1.0, lower))


def weighted_score(
    *,
    bm25_score: float,
    uses: int,
    successes: float,
    last_used_at: str | None,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    bm25_floor: float = DEFAULT_BM25_FLOOR,
    usage_multiplier: float = DEFAULT_USAGE_MULTIPLIER,
) -> float:
    """Combine BM25 relevance with outcome-history and recency signals.

    ::

        score = max(bm25_score, bm25_floor) × usage_factor × recency

        usage_factor = 0.5                                          (uses == 0)
                     = 0.5 + usage_multiplier × wilson_lower_bound(successes, uses)

    Args:
        bm25_score:  FTS5 relevance, already negated upstream so higher =
                     better (SQLite ``bm25()`` is negative-leaning).
        uses:        lifetime use count.
        successes:   lifetime effective successes — integer for binary
                     histories, fractional when continuous quality scores
                     contribute (see :func:`wilson_lower_bound`).
        last_used_at: ISO timestamp of the most recent use (or a fallback).

    Returns a positive score; higher = better.  The cold-start offset keeps
    never-used skills from scoring zero, while the default multiplier gives a
    7× swing between never-used and proven-reliable skills.
    """
    retrieval = max(bm25_score, bm25_floor)
    if uses == 0:
        usage_factor = COLD_START_FACTOR
    else:
        usage_factor = COLD_START_FACTOR + usage_multiplier * wilson_lower_bound(successes, uses)
    return (
        retrieval
        * usage_factor
        * recency_weight(last_used_at, now=now, half_life_days=half_life_days)
    )


# Per-use telemetry table.  Provisioned lazily by SkillStore.record_outcome
# (CREATE ... IF NOT EXISTS — purely additive, safe on existing databases and
# idempotent against an equivalent future schema migration).  ``quality`` is
# an opaque caller-supplied scalar in [0, 1]; how it is graded is entirely
# the caller's business.
_SKILL_USES_DDL = (
    """
    CREATE TABLE IF NOT EXISTS skill_uses (
        use_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_id  INTEGER NOT NULL REFERENCES agent_skills(skill_id),
        agent_id  TEXT REFERENCES agents(agent_id),
        used_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
        success   INTEGER,
        quality   REAL CHECK (quality IS NULL OR (quality >= 0 AND quality <= 1)),
        task_hash TEXT
    )
    """,
    # ⚡ Bolt Optimization: Compound index includes use_id DESC and exact sort order to avoid Temp B-Tree on window scans
    # Impact: Avoids O(N log N) sort step per agent query, ensuring O(1) fetch times as telemetry grows.
    "CREATE INDEX IF NOT EXISTS idx_skill_uses_skill_v2 ON skill_uses(skill_id, used_at DESC, use_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_skill_uses_agent ON skill_uses(agent_id, used_at)",
    "CREATE INDEX IF NOT EXISTS idx_skill_uses_quality ON skill_uses(skill_id, quality)",
)


@dataclass
class Skill:
    skill_id: int
    name: str
    description: str
    template: str
    tags: list[str]
    source_agent_id: str | None
    use_count: int
    success_count: int
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Skill":
        tags = row["tags"]
        return cls(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row["description"],
            template=row["template"],
            tags=json.loads(tags) if tags else [],
            source_agent_id=row["source_agent_id"],
            use_count=row["use_count"],
            success_count=row["success_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "template": self.template,
            "tags": self.tags,
            "source_agent_id": self.source_agent_id,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "success_rate": round(self.success_count / self.use_count, 3)
            if self.use_count
            else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def params(self) -> list[str]:
        """Return the list of template parameter names (e.g. {model} → ['model'])."""
        return [
            field_name
            for _, field_name, _, _ in Formatter().parse(self.template)
            if field_name is not None
        ]

    def apply(self, **kwargs: str) -> str:
        """Render the skill template with the provided parameters.

        Unrecognised keys are silently ignored.  Missing keys raise KeyError.
        """
        return self.template.format_map(kwargs)


class SkillStore:
    """Persistent, searchable cross-agent skill library for a BENE project.

    All agents in the same .db file share a single skill store.  Agents save
    skills (parameterised prompt templates) and any agent can search across
    them using SQLite FTS5 with porter stemming.

    Usage::

        from bene import Bene
        from bene.skills import SkillStore

        bene_db = Bene("project.db")
        sk = SkillStore(bene_db.conn)

        # Save a skill after discovering a reliable pattern
        sid = sk.save(
            source_agent_id="agent-01",
            name="ensemble_classifier",
            description="Improve classification accuracy with ensemble voting",
            template="Implement a {n_models}-model ensemble using {voting} voting. "
                     "Tune decision threshold to {threshold}.",
            tags=["classification", "ensemble", "accuracy"],
        )

        # Search from another agent before starting a similar task
        hits = sk.search("classification accuracy")
        for s in hits:
            print(s.name, s.apply(n_models="3", voting="majority", threshold="0.5"))

        # Record outcomes to track reliability
        sk.record_outcome(sid, success=True)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._skill_uses_ready = False

    def _ensure_skill_uses(self) -> None:
        """Provision the ``skill_uses`` telemetry table (lazy, best-effort).

        Purely additive ``CREATE ... IF NOT EXISTS`` statements that join the
        caller's open transaction (no commit here).  Failures (e.g. read-only
        databases) are swallowed: telemetry is best-effort and must never
        break the caller.
        """
        if self._skill_uses_ready:
            return
        try:
            for stmt in _SKILL_USES_DDL:
                self._conn.execute(stmt)
            self._skill_uses_ready = True
        except sqlite3.OperationalError:
            pass

    # ── Discovery import ─────────────────────────────────────────────

    def import_from_paths(self, paths) -> int:
        """Import skills discovered from `*/SKILL.md` under each path.

        Idempotent on `name`: skills whose name already exists in the
        store are skipped. Returns the number of newly inserted skills.
        """
        existing = {row["name"] for row in self._conn.execute("SELECT name FROM agent_skills")}
        inserted = 0
        for entry in discover_skills(paths):
            name = str(entry.get("name") or "")
            if not name or name in existing:
                continue
            try:
                tags_value = entry.get("tags")
                if isinstance(tags_value, list):
                    tags = cast(list[str], tags_value)
                else:
                    tags = []
                self.save(
                    name=name,
                    description=str(entry.get("description") or ""),
                    template=str(entry.get("template") or ""),
                    tags=tags,
                    source_agent_id=None,
                )
            except (sqlite3.Error, RuntimeError) as e:
                # One bad row must not drop the rest of the batch.
                source = entry.get("source_path", "<unknown>")
                logging.getLogger(__name__).warning(
                    "skills_import: skipping %r from %s: %s", name, source, e
                )
                continue
            existing.add(name)
            inserted += 1
        return inserted

    # ── Save ─────────────────────────────────────────────────────────

    def save(
        self,
        name: str,
        description: str,
        template: str,
        source_agent_id: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Save a new skill and return its skill_id.

        Args:
            name:             Short identifier (snake_case recommended).
            description:      What the skill does and when to use it.
            template:         Prompt template — use {param} for variable parts.
            source_agent_id:  Agent that discovered this skill.
            tags:             List of topic tags for faceted search.

        Returns:
            Integer skill_id of the new entry.
        """
        tags_json = json.dumps(tags or [])
        cur = self._conn.execute(
            """
            INSERT INTO agent_skills (name, description, template, tags, source_agent_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, description, template, tags_json, source_agent_id),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ── Search ───────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 10,
        tag: str | None = None,
        rank: str = "bm25",
        include_demoted: bool = False,
    ) -> list[Skill]:
        """Full-text search over skill name, description, tags, and template.

        Uses SQLite FTS5 with porter stemming.  Results are ranked by BM25
        relevance by default.

        Args:
            query: FTS5 query string (supports phrases "like this", NOT, OR, *).
            limit: Maximum number of results.
            tag:   Optional exact-match tag filter applied after FTS ranking.
            rank:  ``"bm25"`` (default — classic FTS5 relevance, unchanged
                   legacy behavior) or ``"weighted"`` (BM25 × Wilson-lower-
                   bound reliability × recency decay).  The weighted mode
                   over-fetches BM25 candidates and re-ranks them using the
                   outcome history recorded by :meth:`record_outcome`, so
                   skills that keep succeeding rise above lexically-similar
                   skills that keep failing.

        Returns:
            List of Skill sorted by the chosen ranking (best first).
        """
        if rank not in ("bm25", "weighted"):
            raise ValueError(f"rank must be 'bm25' or 'weighted', got {rank!r}")

        fetch = limit * _WEIGHTED_OVERFETCH if rank == "weighted" else limit
        params: list[Any] = [query, fetch]
        sql = """
        SELECT s.skill_id, s.name, s.description, s.template, s.tags,
               s.source_agent_id, s.use_count, s.success_count,
               s.created_at, s.updated_at,
               bm25(agent_skills_fts) AS bm25_raw
        FROM agent_skills_fts f
        JOIN agent_skills s ON s.skill_id = f.rowid
        WHERE agent_skills_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            fallback = fallback_fts_query(query)
            if not fallback:
                return []
            params[0] = fallback
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        skills = [Skill.from_row(r) for r in rows]

        if rank == "weighted":
            ids = [s.skill_id for s in skills]
            last_used = _last_used_map(self._conn, ids)
            # Per-skill quality-aware (effective_successes, uses).  Absent
            # for skills with no graded rows → binary aggregate fallback.
            qmap = _quality_signal_map(self._conn, ids)
            # SQLite bm25() is negative-leaning (more negative = more
            # relevant); negate so higher = better.
            bm25_by_id = {r["skill_id"]: -float(r["bm25_raw"] or 0.0) for r in rows}

            def score(s: Skill) -> float:
                eff = qmap.get(s.skill_id)
                successes, uses = eff if eff is not None else (s.success_count, s.use_count)
                return weighted_score(
                    bm25_score=bm25_by_id.get(s.skill_id, 1.0),
                    uses=uses,
                    successes=successes,
                    last_used_at=last_used.get(s.skill_id) or s.updated_at,
                )

            # sorted() is stable: ties keep BM25 order.
            skills = sorted(skills, key=score, reverse=True)

        # Plasticity: hide demoted/retired skills by default. No-op (and
        # byte-identical legacy behavior) when no skill has a lifecycle row.
        if not include_demoted:
            demoted = _demoted_skill_ids(self._conn)
            if demoted:
                skills = [s for s in skills if s.skill_id not in demoted]

        if tag:
            skills = [s for s in skills if tag in s.tags]
        return skills[:limit]

    # ── Get / List ───────────────────────────────────────────────────

    def get(self, skill_id: int) -> Skill | None:
        """Fetch a single skill by its primary key."""
        row = self._conn.execute(
            """
            SELECT skill_id, name, description, template, tags,
                   source_agent_id, use_count, success_count, created_at, updated_at
            FROM agent_skills WHERE skill_id = ?
            """,
            (skill_id,),
        ).fetchone()
        return Skill.from_row(row) if row else None

    def list(
        self,
        tag: str | None = None,
        source_agent_id: str | None = None,
        order_by: str = "created_at",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Skill]:
        """List skills (most recent first by default), with optional filters.

        Args:
            tag:              Filter to skills containing this tag.
            source_agent_id:  Filter to skills saved by one agent.
            order_by:         Column to sort by: created_at | success_count | use_count.
            limit:            Page size.
            offset:           Pagination offset.
        """
        allowed = {"created_at", "success_count", "use_count", "name"}
        if order_by not in allowed:
            order_by = "created_at"

        clauses: list[str] = []
        params: list[Any] = []

        if source_agent_id:
            clauses.append("source_agent_id = ?")
            params.append(source_agent_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params += [limit, offset]

        rows = self._conn.execute(
            f"""
            SELECT skill_id, name, description, template, tags,
                   source_agent_id, use_count, success_count, created_at, updated_at
            FROM agent_skills
            {where}
            ORDER BY {order_by} DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        skills = [Skill.from_row(r) for r in rows]
        if tag:
            skills = [s for s in skills if tag in s.tags]
        return skills

    # ── Outcome tracking ─────────────────────────────────────────────

    def record_outcome(
        self,
        skill_id: int,
        success: bool,
        *,
        agent_id: str | None = None,
        quality: float | None = None,
        task_hash: str | None = None,
    ) -> None:
        """Record whether applying a skill succeeded or failed.

        Increments ``use_count`` always; increments ``success_count`` only on
        success.  This lets agents rank skills by reliability
        (``success_count / use_count``).

        Additionally appends a per-use ``skill_uses`` telemetry row (used by
        ``search(rank="weighted")`` for last-used recency and quality-graded
        reliability).  The telemetry write is best-effort — failures on
        databases that cannot take the row are swallowed so the hot path
        never breaks the caller.

        Args:
            skill_id:  The skill that was applied.
            success:   Binary outcome.  Required, and the sole driver of the
                       legacy aggregate counters.
            agent_id:  Optional attributing agent.
            quality:   Optional *continuous* outcome in ``[0.0, 1.0]``.  When
                       provided, weighted ranking uses it instead of the
                       binary ``success`` so near-misses earn partial credit
                       and the Wilson estimator sees less noise (binary grading
                       cannot distinguish "picked a near-miss sibling" from
                       "picked garbage").  When ``None``, the row stays purely
                       binary and behavior is unchanged.  Values outside
                       ``[0, 1]`` (including NaN) raise ``ValueError`` — never
                       silently clamped, because a clamp hides a caller bug.
            task_hash: Optional per-context bucket id.
        """
        if quality is not None and not (0.0 <= quality <= 1.0):
            raise ValueError(f"quality must be in [0.0, 1.0], got {quality!r}")
        if success:
            self._conn.execute(
                """
                UPDATE agent_skills
                SET use_count = use_count + 1,
                    success_count = success_count + 1,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%f','now')
                WHERE skill_id = ?
                """,
                (skill_id,),
            )
        else:
            self._conn.execute(
                """
                UPDATE agent_skills
                SET use_count = use_count + 1,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%f','now')
                WHERE skill_id = ?
                """,
                (skill_id,),
            )
        # Per-use telemetry: best-effort.  If the table exists but predates
        # the quality column, retry without it; if it cannot be written at
        # all, swallow — aggregates above remain the source of truth.
        self._ensure_skill_uses()
        try:
            self._conn.execute(
                "INSERT INTO skill_uses (skill_id, agent_id, success, quality, task_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (skill_id, agent_id, 1 if success else 0, quality, task_hash),
            )
        except sqlite3.OperationalError:
            try:
                self._conn.execute(
                    "INSERT INTO skill_uses (skill_id, agent_id, success, task_hash) "
                    "VALUES (?, ?, ?, ?)",
                    (skill_id, agent_id, 1 if success else 0, task_hash),
                )
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    # ── Delete ───────────────────────────────────────────────────────

    def delete(self, skill_id: int) -> bool:
        """Delete a skill by skill_id. Returns True if a row was removed."""
        cur = self._conn.execute("DELETE FROM agent_skills WHERE skill_id = ?", (skill_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ── Stats ────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return skill counts and top skills by success rate."""
        total = self._conn.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0]
        top = self._conn.execute(
            """
            SELECT name, use_count, success_count,
                   CASE WHEN use_count > 0
                        THEN ROUND(CAST(success_count AS REAL) / use_count, 3)
                        ELSE NULL END AS success_rate
            FROM agent_skills
            WHERE use_count > 0
            ORDER BY success_rate DESC
            LIMIT 5
            """
        ).fetchall()
        return {
            "total": total,
            "top_by_success_rate": [dict(r) for r in top],
        }


def _demoted_skill_ids(conn: sqlite3.Connection) -> set[int]:
    """Skill ids whose *latest* ``skill_lifecycle`` status is demoted/retired.
    Empty set when the table is absent (plasticity never run) — keeps the
    weighted/bm25 search paths byte-identical on databases without demotions."""
    try:
        rows = conn.execute(
            "SELECT skill_id, status FROM skill_lifecycle l WHERE lifecycle_id = ("
            "  SELECT lifecycle_id FROM skill_lifecycle l2 WHERE l2.skill_id = l.skill_id"
            "  ORDER BY decided_at DESC, lifecycle_id DESC LIMIT 1)"
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {r[0] for r in rows if r[1] in ("demoted", "retired")}


# ── Weighted-ranking signal queries ──────────────────────────────────────


def _last_used_map(conn: sqlite3.Connection, skill_ids: list[int]) -> dict[int, str]:
    """Return ``{skill_id: last_used_at}`` for the given ids, from skill_uses.

    Silently returns an empty dict on databases without a usable
    ``skill_uses`` table — the caller falls back to ``updated_at``.
    """
    if not skill_ids:
        return {}
    placeholders = ",".join("?" * len(skill_ids))
    try:
        rows = conn.execute(
            f"SELECT skill_id, MAX(used_at) AS last_used "
            f"FROM skill_uses WHERE skill_id IN ({placeholders}) "
            f"GROUP BY skill_id",
            skill_ids,
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r["skill_id"]: r["last_used"] for r in rows if r["last_used"]}


def _quality_signal_map(
    conn: sqlite3.Connection, skill_ids: list[int]
) -> dict[int, tuple[float, int]]:
    """Return ``{skill_id: (effective_successes, uses)}`` for skills that
    have at least one quality-graded ``skill_uses`` row.

    Effective successes = SUM(quality) over rows where quality IS NOT NULL,
    plus SUM(success) over rows where quality IS NULL — a mixed binary +
    graded history is scored coherently.  ``uses`` is the total row count.

    A skill with no graded rows is intentionally absent from the result so
    the caller falls back to the fast ``agent_skills`` aggregate counters and
    the binary path stays byte-for-byte unchanged.  Silently empty on
    databases without a usable ``skill_uses`` table.
    """
    if not skill_ids:
        return {}
    placeholders = ",".join("?" * len(skill_ids))
    try:
        rows = conn.execute(
            f"""
            SELECT skill_id,
                   COUNT(*) AS uses,
                   SUM(CASE WHEN quality IS NOT NULL THEN quality ELSE success END) AS eff_succ,
                   SUM(CASE WHEN quality IS NOT NULL THEN 1 ELSE 0 END) AS graded
            FROM skill_uses
            WHERE skill_id IN ({placeholders})
            GROUP BY skill_id
            """,
            skill_ids,
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[int, tuple[float, int]] = {}
    for r in rows:
        # Only override the binary aggregates when graded data actually exists.
        if (r["graded"] or 0) > 0:
            out[r["skill_id"]] = (float(r["eff_succ"] or 0.0), int(r["uses"]))
    return out
