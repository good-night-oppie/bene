"""Scheduled memory lifecycle helpers.

This module is deliberately small: it automates the consolidation mechanism
that already exists in :class:`GranuleStore` without introducing a daemon,
cron dependency, or another persistence model.  The plan is deterministic and
serializable so a consolidation run can be audited or replayed against the
same source granules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import ulid

from bene.kernel.engrams import EngramStore
from bene.kernel.memory.granules import GRANULE_TIERS, GranuleStore

RUN_SUMMARY_PREFIX = "scheduled memory consolidation"


def _parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_text(raw: bytes) -> str:
    return " ".join(raw.decode(errors="replace").split())


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ConsolidationPolicy:
    """Controls one scheduled consolidation pass.

    ``interval_hours`` is a scheduler guard, not a background scheduler.  Call
    :meth:`ScheduledConsolidator.run` from cron, CI, or an agent loop; the
    helper decides whether a run is due and records only materialized runs.
    """

    to_level: str = "episode"
    min_turns: int = 4
    batch_size: int = 8
    max_batches: int = 1
    interval_hours: float = 24.0
    agent_id: str | None = None
    provenance: dict[str, Any] = field(
        default_factory=lambda: {"system": "bene.kernel.memory.lifecycle"}
    )

    def validate(self) -> None:
        if self.to_level not in GRANULE_TIERS or self.to_level == "turn":
            raise ValueError("to_level must be one of episode/semantic/procedural")
        if self.min_turns <= 0:
            raise ValueError("min_turns must be > 0")
        if self.batch_size < self.min_turns:
            raise ValueError("batch_size must be >= min_turns")
        if self.max_batches <= 0:
            raise ValueError("max_batches must be > 0")
        if self.interval_hours < 0:
            raise ValueError("interval_hours must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "to_level": self.to_level,
            "min_turns": self.min_turns,
            "batch_size": self.batch_size,
            "max_batches": self.max_batches,
            "interval_hours": self.interval_hours,
            "agent_id": self.agent_id,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConsolidationPolicy":
        """Round-trip a :meth:`to_dict` mapping (e.g. a replay manifest's
        ``policy`` block) back into a policy. Unknown keys are ignored."""
        fields = {
            "to_level",
            "min_turns",
            "batch_size",
            "max_batches",
            "interval_hours",
            "agent_id",
            "provenance",
        }
        return cls(**{k: data[k] for k in fields if k in data})


@dataclass(frozen=True)
class ConsolidationSource:
    engram_id: str
    title: str
    content_sha256: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "engram_id": self.engram_id,
            "title": self.title,
            "content_sha256": self.content_sha256,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ConsolidationBatch:
    sources: tuple[ConsolidationSource, ...]
    summary: str
    source_digest: str

    @property
    def source_ids(self) -> list[str]:
        return [s.engram_id for s in self.sources]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ids": self.source_ids,
            "source_digest": self.source_digest,
            "summary": self.summary,
            "sources": [s.to_dict() for s in self.sources],
        }


@dataclass(frozen=True)
class ConsolidationPlan:
    due: bool
    reason: str
    policy: ConsolidationPolicy
    batches: tuple[ConsolidationBatch, ...] = ()
    last_run_at: str | None = None

    def replay_manifest(self) -> dict[str, Any]:
        return {
            "version": 1,
            "kind": "scheduled_consolidation",
            "due": self.due,
            "reason": self.reason,
            "last_run_at": self.last_run_at,
            "policy": self.policy.to_dict(),
            "batches": [b.to_dict() for b in self.batches],
        }


@dataclass(frozen=True)
class ConsolidationRun:
    plan: ConsolidationPlan
    created_engram_ids: tuple[str, ...] = ()
    run_id: str | None = None
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dry_run": self.dry_run,
            "created_engram_ids": list(self.created_engram_ids),
            "plan": self.plan.replay_manifest(),
        }


class ScheduledConsolidator:
    """Plan and run due memory-granule consolidation passes."""

    def __init__(self, store: EngramStore, granules: GranuleStore | None = None) -> None:
        self.store = store
        self.granules = granules or GranuleStore(store)

    def plan(
        self,
        policy: ConsolidationPolicy | None = None,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> ConsolidationPlan:
        policy = policy or ConsolidationPolicy()
        policy.validate()
        last_run_at = self._last_scheduled_run_at()
        if not force and not self._is_due(policy, last_run_at, now or _utc_now()):
            return ConsolidationPlan(
                due=False,
                reason="interval-not-elapsed",
                policy=policy,
                last_run_at=last_run_at,
            )

        candidates = self._eligible_turns(policy.agent_id)
        if len(candidates) < policy.min_turns:
            return ConsolidationPlan(
                due=False,
                reason="insufficient-turns",
                policy=policy,
                last_run_at=last_run_at,
            )

        batches = self._batches(candidates, policy)
        return ConsolidationPlan(
            due=bool(batches),
            reason="due" if batches else "insufficient-turns",
            policy=policy,
            batches=tuple(batches),
            last_run_at=last_run_at,
        )

    def run(
        self,
        policy: ConsolidationPolicy | None = None,
        *,
        now: datetime | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> ConsolidationRun:
        plan = self.plan(policy, now=now, force=force)
        if dry_run or not plan.due:
            return ConsolidationRun(plan=plan, dry_run=dry_run)

        created: list[str] = []
        for batch in plan.batches:
            created.append(
                self.granules.consolidate(
                    batch.source_ids,
                    summary=batch.summary,
                    provenance=plan.policy.provenance,
                    to_level=plan.policy.to_level,
                )
            )
        run_id = self._record_run(plan, created)
        self.store.conn.commit()
        return ConsolidationRun(
            plan=plan,
            created_engram_ids=tuple(created),
            run_id=run_id,
            dry_run=False,
        )

    def _last_scheduled_run_at(self) -> str | None:
        row = self.store.conn.execute(
            "SELECT created_at FROM experiment_runs"
            " WHERE kind='consolidation' AND summary LIKE ?"
            " ORDER BY created_at DESC LIMIT 1",
            (f"{RUN_SUMMARY_PREFIX}%",),
        ).fetchone()
        return row[0] if row else None

    def _is_due(
        self,
        policy: ConsolidationPolicy,
        last_run_at: str | None,
        now: datetime,
    ) -> bool:
        if policy.interval_hours == 0 or last_run_at is None:
            return True
        last = _parse_created_at(last_run_at)
        if last is None:
            return True
        return now - last >= timedelta(hours=policy.interval_hours)

    def _eligible_turns(self, agent_id: str | None) -> list[dict[str, Any]]:
        if self.store.pending:
            self.store.flush()
        rows = self.store.conn.execute(
            "SELECT e.engram_id, e.title, e.metadata, e.created_at"
            " FROM engrams e"
            " WHERE e.kind='trace' AND e.tier=0 AND e.superseded_by IS NULL"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM engram_links l"
            "   WHERE l.dst_id=e.engram_id AND l.link_type='consolidates'"
            " )"
            " ORDER BY e.created_at ASC, e.rowid ASC"
        ).fetchall()
        candidates: list[dict[str, Any]] = []
        for row in rows:
            metadata = json.loads(row[2] or "{}")
            if metadata.get("granule") != "turn":
                continue
            source = self.store.get(row[0])
            if agent_id is not None and source.agent_id != agent_id:
                continue
            raw = self.store.payload(row[0])
            candidates.append(
                {
                    "engram_id": row[0],
                    "title": row[1],
                    "created_at": row[3],
                    "text": _payload_text(raw),
                    "content_sha256": _sha256(raw),
                }
            )
        return candidates

    def _batches(
        self,
        candidates: list[dict[str, Any]],
        policy: ConsolidationPolicy,
    ) -> list[ConsolidationBatch]:
        batches: list[ConsolidationBatch] = []
        for start in range(0, len(candidates), policy.batch_size):
            if len(batches) >= policy.max_batches:
                break
            chunk = candidates[start : start + policy.batch_size]
            if len(chunk) < policy.min_turns:
                break
            sources = tuple(
                ConsolidationSource(
                    engram_id=c["engram_id"],
                    title=c["title"],
                    content_sha256=c["content_sha256"],
                    created_at=c["created_at"],
                )
                for c in chunk
            )
            summary = self._summary(chunk, policy.to_level)
            batches.append(
                ConsolidationBatch(
                    sources=sources,
                    summary=summary,
                    source_digest=self._source_digest(sources),
                )
            )
        return batches

    @staticmethod
    def _summary(chunk: list[dict[str, Any]], to_level: str) -> str:
        lines = []
        for item in chunk:
            text = item["text"] or item["title"]
            lines.append(f"- {text[:180]}")
        return f"{to_level}: scheduled consolidation\n" + "\n".join(lines)

    @staticmethod
    def _source_digest(sources: tuple[ConsolidationSource, ...]) -> str:
        h = hashlib.sha256()
        for source in sources:
            h.update(source.engram_id.encode())
            h.update(b"\0")
            h.update(source.content_sha256.encode())
            h.update(b"\0")
        return h.hexdigest()

    def _record_run(self, plan: ConsolidationPlan, created: list[str]) -> str:
        run_id = str(ulid.new())
        metrics = plan.replay_manifest()
        metrics["created_engram_ids"] = created
        self.store.conn.execute(
            "INSERT INTO experiment_runs (run_id, kind, summary, metrics) VALUES (?,?,?,?)",
            (
                run_id,
                "consolidation",
                f"{RUN_SUMMARY_PREFIX}: created {len(created)} {plan.policy.to_level} granule(s)",
                json.dumps(metrics, sort_keys=True),
            ),
        )
        return run_id
