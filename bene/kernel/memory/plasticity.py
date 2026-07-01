"""Skill plasticity — probe-gated demotion / retirement of failing skills.

Closes the demotion/retirement half of the skill-plasticity claim (GAP-AUDIT
BENE-4): the outcome-weighted *ranking* already shipped (``bene/skills.py``),
but a skill that USED to work and now fails is never taken off the menu. This
scanner inspects ``skill_uses`` telemetry, demotes a skill whose recent quality
has *degraded* below threshold, retires long-idle demoted skills, and records
every decision as an append-only audit trail — never mutating ``agent_skills``.

Gate semantics follow the kernel convention (ACCEPT-allows / REJECT-blocks):
a degradation verdict is computed per candidate — **ACCEPT** = degradation
verified (recent window is both below the failure floor AND worse than the
pre-failure baseline) → demote; **REJECT** = still healthy / never a regression
→ hold; **VOID** = insufficient evidence (e.g. too few distinct agents, a
reward-hack guard) → hold with a warning. The verdict + decision are written as
``eval`` and ``intervention`` engrams linked ``gated_by``, mirroring
``evolve.promote``.

Lives next to ``lifecycle.py`` (granule consolidation) — both are idempotent
scheduled maintenance over the substrate, cron/CI-spawnable, no daemon.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from bene.kernel.engrams import EngramStore

ACTIVE, DEMOTED, RETIRED, RESTORED = "active", "demoted", "retired", "restored"

LIFECYCLE_DDL = """
CREATE TABLE IF NOT EXISTS skill_lifecycle (
    lifecycle_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id       INTEGER NOT NULL REFERENCES agent_skills(skill_id),
    status         TEXT NOT NULL CHECK (status IN ('active','demoted','retired','restored')),
    reason         TEXT NOT NULL,
    decided_by     TEXT NOT NULL,
    verdict_engram TEXT,
    superseded_by  INTEGER REFERENCES agent_skills(skill_id),
    decided_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_skill_lifecycle_skill  ON skill_lifecycle(skill_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_skill_lifecycle_status ON skill_lifecycle(status, decided_at DESC);
"""


class PromotionBlocked(RuntimeError):
    """Raised when supersede() is called without an ACCEPT verdict engram."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


@dataclass(frozen=True)
class PlasticityPolicy:
    min_uses: int = 8  # cold-start protection: never demote below this
    recent_window: int = 10  # tail rows scanned for current quality
    baseline_window: int = 30  # pre-failure rows used as the degradation baseline
    failure_threshold: float = 0.25  # recent mean(quality) <= this is a candidate
    epsilon: float = 0.05  # recent must be this much below baseline to count as degraded
    retire_after_days: float = 90.0  # demoted + idle this long → retired
    min_distinct_agents: int = 1  # reward-hack guard (raise to 2+ to require corroboration)

    def validate(self) -> None:
        if self.min_uses <= 0:
            raise ValueError("min_uses must be > 0")
        if self.recent_window <= 0:
            raise ValueError("recent_window must be > 0")
        if not (0.0 <= self.failure_threshold <= 1.0):
            raise ValueError("failure_threshold must be in [0,1]")
        if self.min_distinct_agents <= 0:
            raise ValueError("min_distinct_agents must be > 0")

    def hash(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]


@dataclass(frozen=True)
class SkillDecision:
    skill_id: int
    action: str  # "demote" | "retire" | "hold"
    verdict: str  # "ACCEPT" | "REJECT" | "VOID" | "n/a"
    reason: str
    recent_mean: float | None
    baseline_mean: float | None
    distinct_agents: int
    uses: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "action": self.action,
            "verdict": self.verdict,
            "reason": self.reason,
            "recent_mean": self.recent_mean,
            "baseline_mean": self.baseline_mean,
            "distinct_agents": self.distinct_agents,
            "uses": self.uses,
        }


@dataclass(frozen=True)
class PlasticityRun:
    decisions: tuple[SkillDecision, ...] = ()
    demoted: tuple[int, ...] = ()
    retired: tuple[int, ...] = ()
    dry_run: bool = False
    policy_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "policy_hash": self.policy_hash,
            "demoted": list(self.demoted),
            "retired": list(self.retired),
            "decisions": [d.to_dict() for d in self.decisions],
        }


class PlasticityScanner:
    """Inspect skill telemetry; demote/retire failing skills through the gate."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        store: EngramStore,
        *,
        policy: PlasticityPolicy | None = None,
    ) -> None:
        self.conn = conn
        self.store = store
        self.policy = policy or PlasticityPolicy()
        self.policy.validate()
        self._ensure_lifecycle()

    def _ensure_lifecycle(self) -> None:
        self.conn.executescript(LIFECYCLE_DDL)

    # ---------------- status ----------------

    def current_status(self, skill_id: int) -> str:
        row = self.conn.execute(
            "SELECT status FROM skill_lifecycle WHERE skill_id=?"
            " ORDER BY decided_at DESC, lifecycle_id DESC LIMIT 1",
            (skill_id,),
        ).fetchone()
        return row[0] if row else ACTIVE

    def lifecycle(self, skill_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT status, reason, decided_by, verdict_engram, superseded_by, decided_at"
            " FROM skill_lifecycle WHERE skill_id=? ORDER BY decided_at ASC, lifecycle_id ASC",
            (skill_id,),
        ).fetchall()
        return [
            {
                "status": r[0],
                "reason": r[1],
                "decided_by": r[2],
                "verdict_engram": r[3],
                "superseded_by": r[4],
                "decided_at": r[5],
            }
            for r in rows
        ]

    # ---------------- scan ----------------

    def _candidates(self) -> list[int]:
        rows = self.conn.execute(
            "SELECT skill_id, COUNT(*) AS n FROM skill_uses GROUP BY skill_id"
            " HAVING n >= ? ORDER BY skill_id",
            (self.policy.min_uses,),
        ).fetchall()
        return [r[0] for r in rows]

    def _window_mean(self, skill_id: int, *, limit: int, offset: int = 0) -> float | None:
        row = self.conn.execute(
            "SELECT AVG(q) FROM (SELECT COALESCE(quality, success) AS q FROM skill_uses"
            " WHERE skill_id=? ORDER BY used_at DESC, use_id DESC LIMIT ? OFFSET ?)",
            (skill_id, limit, offset),
        ).fetchone()
        return None if row[0] is None else float(row[0])

    def _distinct_failing_agents(self, skill_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT agent_id) FROM (SELECT agent_id, COALESCE(quality, success) AS q"
            " FROM skill_uses WHERE skill_id=? ORDER BY used_at DESC, use_id DESC LIMIT ?)"
            " WHERE q <= ?",
            (skill_id, self.policy.recent_window, self.policy.failure_threshold),
        ).fetchone()
        return int(row[0] or 0)

    def _last_used(self, skill_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT used_at FROM skill_uses WHERE skill_id=? ORDER BY used_at DESC, use_id DESC LIMIT 1",
            (skill_id,),
        ).fetchone()
        return row[0] if row else None

    def _uses(self, skill_id: int) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM skill_uses WHERE skill_id=?", (skill_id,)
            ).fetchone()[0]
        )

    def _decide(self, skill_id: int, now: datetime) -> SkillDecision:
        p = self.policy
        uses = self._uses(skill_id)
        status = self.current_status(skill_id)
        recent = self._window_mean(skill_id, limit=p.recent_window)

        if status == DEMOTED:
            last = _parse_dt(self._last_used(skill_id))
            idle_days = (now - last).total_seconds() / 86400.0 if last else 0.0
            if idle_days >= p.retire_after_days:
                return SkillDecision(
                    skill_id,
                    "retire",
                    "n/a",
                    f"demoted and idle {idle_days:.0f}d >= {p.retire_after_days:.0f}d",
                    recent,
                    None,
                    0,
                    uses,
                )
            return SkillDecision(
                skill_id, "hold", "n/a", "demoted, not yet idle enough", recent, None, 0, uses
            )

        if status == RETIRED:
            return SkillDecision(skill_id, "hold", "n/a", "already retired", recent, None, 0, uses)

        # active / restored → degradation gate
        if recent is None or recent > p.failure_threshold:
            return SkillDecision(
                skill_id,
                "hold",
                "REJECT",
                "recent quality above failure floor",
                recent,
                None,
                0,
                uses,
            )

        baseline = self._window_mean(skill_id, limit=p.baseline_window, offset=p.recent_window)
        distinct = self._distinct_failing_agents(skill_id)
        if distinct < p.min_distinct_agents:
            return SkillDecision(
                skill_id,
                "hold",
                "VOID",
                f"insufficient evidence: {distinct} distinct failing agent(s) < {p.min_distinct_agents}",
                recent,
                baseline,
                distinct,
                uses,
            )
        degraded = baseline is not None and recent < baseline - p.epsilon
        if degraded:
            return SkillDecision(
                skill_id,
                "demote",
                "ACCEPT",
                f"mean_quality={recent:.3f} over last {p.recent_window} uses, "
                f"degraded from baseline {baseline:.3f}",
                recent,
                baseline,
                distinct,
                uses,
            )
        return SkillDecision(
            skill_id,
            "hold",
            "REJECT",
            "below floor but not a regression vs baseline (never reliably worked)",
            recent,
            baseline,
            distinct,
            uses,
        )

    def scan(self, *, dry_run: bool = False, now: datetime | None = None) -> PlasticityRun:
        now = now or _utc_now()
        decisions: list[SkillDecision] = []
        demoted: list[int] = []
        retired: list[int] = []
        for skill_id in self._candidates():
            d = self._decide(skill_id, now)
            decisions.append(d)
            if d.action == "hold":
                continue
            if not dry_run:
                self._record(d)
            (demoted if d.action == "demote" else retired).append(d.skill_id)
        if not dry_run and (demoted or retired):
            self.conn.commit()
        return PlasticityRun(
            decisions=tuple(decisions),
            demoted=tuple(demoted),
            retired=tuple(retired),
            dry_run=dry_run,
            policy_hash=self.policy.hash(),
        )

    def _record(self, d: SkillDecision) -> None:
        to_status = DEMOTED if d.action == "demote" else RETIRED
        # Verdict engram (the gate result), then the intervention engram linked
        # gated_by → verdict, mirroring evolve.promote's audit pattern.
        verdict_id = self.store.append(
            "eval",
            f"plasticity-verdict:skill-{d.skill_id}:{d.verdict}",
            json.dumps(d.to_dict(), sort_keys=True),
            provenance={"system": "bene.kernel.memory.plasticity"},
            metadata={"plasticity": True, "skill_id": d.skill_id, "verdict": d.verdict},
            commit=False,
        )
        self.store.append(
            "intervention",
            f"plasticity:skill-{d.skill_id}:{ACTIVE}->{to_status}",
            d.reason,
            provenance={"system": "bene.kernel.memory.plasticity"},
            parents=[verdict_id],
            link_type="gated_by",
            metadata={
                "plasticity": True,
                "skill_id": d.skill_id,
                "from": ACTIVE,
                "to": to_status,
                "policy_hash": self.policy.hash(),
                "recent_mean": d.recent_mean,
                "baseline_mean": d.baseline_mean,
            },
            commit=False,
        )
        self.conn.execute(
            "INSERT INTO skill_lifecycle (skill_id, status, reason, decided_by, verdict_engram)"
            " VALUES (?,?,?,?,?)",
            (d.skill_id, to_status, d.reason, "policy:PlasticityScanner", verdict_id),
        )

    # ---------------- manual transitions ----------------

    def restore(self, skill_id: int, *, decided_by: str = "human") -> None:
        """Append a ``restored`` row so the skill re-enters search results."""
        self.conn.execute(
            "INSERT INTO skill_lifecycle (skill_id, status, reason, decided_by) VALUES (?,?,?,?)",
            (skill_id, RESTORED, "manual restore", decided_by),
        )
        self.conn.commit()

    def supersede(self, old_skill_id: int, new_skill_id: int, *, verdict_engram_id: str) -> str:
        """Record old→new supersession on the lifecycle trail, gated by an
        ACCEPT verdict engram (same kill-gate contract as ``evolve.promote``);
        raises :class:`PromotionBlocked` otherwise. Returns the intervention
        engram id. (Skills aren't engrams, so the supersession lives on
        ``skill_lifecycle.superseded_by`` + an ``intervention`` engram, not in
        ``engram_links`` which is engram-to-engram only.)"""
        verdict = self.store.get(verdict_engram_id)
        payload = self.store.payload(verdict_engram_id).decode(errors="replace")
        if "ACCEPT" not in (verdict.title + payload):
            raise PromotionBlocked(
                f"supersede requires an ACCEPT verdict engram, got {verdict_engram_id}"
            )
        eng = self.store.append(
            "intervention",
            f"plasticity-supersede:skill-{old_skill_id}->{new_skill_id}",
            f"skill {old_skill_id} superseded by skill {new_skill_id}",
            provenance={"system": "bene.kernel.memory.plasticity"},
            parents=[verdict_engram_id],
            link_type="gated_by",
            metadata={
                "plasticity": True,
                "supersede": True,
                "old": old_skill_id,
                "new": new_skill_id,
            },
            commit=False,
        )
        self.conn.execute(
            "INSERT INTO skill_lifecycle (skill_id, status, reason, decided_by, verdict_engram, superseded_by)"
            " VALUES (?,?,?,?,?,?)",
            (
                old_skill_id,
                DEMOTED,
                f"superseded by skill {new_skill_id}",
                "policy:supersede",
                verdict_engram_id,
                new_skill_id,
            ),
        )
        self.conn.commit()
        return eng

    def demoted_skill_ids(self) -> set[int]:
        """Skill ids whose latest lifecycle status is demoted/retired."""
        rows = self.conn.execute(
            "SELECT skill_id, status FROM skill_lifecycle l WHERE lifecycle_id = ("
            "  SELECT MAX(lifecycle_id) FROM skill_lifecycle l2 WHERE l2.skill_id = l.skill_id)"
        ).fetchall()
        return {r[0] for r in rows if r[1] in (DEMOTED, RETIRED)}
