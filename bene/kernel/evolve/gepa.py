"""Reflective evolution with a Pareto frontier and kill-gated promotion.

GEPA-style (SYNTHESIS: agent-multi-prompt-opt #01) with the AHE/ADOPT
correction: genomes are STRUCTURED — components mutated independently with
per-component credit — because prompt-only mutation scores below seed
(SYNTHESIS: agent-auto-opt #08). Verifier isolation is mandatory: the evolver
never evaluates its own candidates for promotion; that is the probe layer's
job (AEVO: removing the boundary produced reward hacking in 2/3 runs).

Promotion (D3): ``promote()`` requires an ACCEPT verdict engram linked
``verifies`` → candidate; otherwise PromotionBlocked. No retune-and-rerun.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import ulid

from bene.kernel.engrams import EngramStore
from bene.kernel.evolve.genes import StrategyGene
from bene.metaharness.pareto import dominates

GENOME_COMPONENTS = (
    "memory_policy",
    "retrieval_policy",
    "context_strategy",
    "tool_config",
    "prompt",
)

#: quality is maximized; cost and tokens are minimized (multi-objective)
OBJECTIVES = {"quality": "maximize", "cost": "minimize", "tokens": "minimize"}


class PromotionBlocked(PermissionError):
    """No ACCEPT verdict verifies this candidate — promotion refused (D3)."""


@dataclass
class Genome:
    components: dict[str, str]
    gene: StrategyGene | None = None
    scores: dict[str, float] = field(default_factory=dict)
    genome_id: str = field(default_factory=lambda: str(ulid.new()))
    parent_id: str | None = None
    engram_id: str | None = None

    def mutate(self, component: str, new_text: str) -> Genome:
        if component not in self.components:
            raise KeyError(f"unknown genome component: {component}")
        child = dict(self.components)
        child[component] = new_text
        return Genome(components=child, gene=self.gene, parent_id=self.genome_id)

    def encode(self) -> str:
        parts = [f"## {k}\n{v}" for k, v in sorted(self.components.items())]
        if self.gene:
            parts.append("## gene\n" + self.gene.encode())
        return "\n\n".join(parts)


class GenomeFrontier:
    """Non-dominated archive over genomes (reuses metaharness dominates())."""

    def __init__(self, objectives: dict[str, str] | None = None) -> None:
        self.objectives = objectives or dict(OBJECTIVES)
        self._members: list[Genome] = []

    def update(self, genome: Genome) -> bool:
        """Add if non-dominated; evict members it dominates. True if added."""
        if any(dominates(m.scores, genome.scores, self.objectives) for m in self._members):
            return False
        self._members = [
            m for m in self._members if not dominates(genome.scores, m.scores, self.objectives)
        ]
        self._members.append(genome)
        return True

    def members(self) -> list[Genome]:
        return list(self._members)

    def dump(self) -> list[dict[str, Any]]:
        return [
            {"genome_id": m.genome_id, "scores": m.scores, "parent_id": m.parent_id}
            for m in self._members
        ]


# reflect_fn(genome, feedback) -> {"component": str, "new_text": str, "rationale": str}
# NOTE: spec deviation from KERNEL-SPEC's (str, list[str]) -> str signature —
# structured mutation targets a named component (ADOPT credit assignment).
ReflectFn = Callable[[Genome, list[str]], dict[str, str]]
BenchmarkFn = Callable[[Genome], dict[str, float]]
FeedbackFn = Callable[[Genome, dict[str, float]], list[str]]


def _default_feedback(genome: Genome, scores: dict[str, float]) -> list[str]:
    return [f"{k}={v:.4f}" for k, v in sorted(scores.items())]


class ReflectiveEvolver:
    def __init__(
        self,
        store: EngramStore,
        conn: sqlite3.Connection,
        *,
        reflect_fn: ReflectFn,
        benchmark: BenchmarkFn,
        frontier: GenomeFrontier | None = None,
        feedback_fn: FeedbackFn | None = None,
        surrogate: Callable[[Genome], float] | None = None,
    ) -> None:
        self.store = store
        self.conn = conn
        self.reflect_fn = reflect_fn
        self.benchmark = benchmark
        self.frontier = frontier or GenomeFrontier()
        self.feedback_fn = feedback_fn or _default_feedback
        self.surrogate = surrogate

    def _persist(self, genome: Genome, generation: int) -> str:
        eid = self.store.append(
            "strategic",
            f"genome:{genome.genome_id}",
            genome.encode(),
            tier=4,
            provenance={"system": "bene.kernel.evolve"},
            metadata={
                "generation": generation,
                "scores": genome.scores,
                "parent_id": genome.parent_id,
            },
        )
        genome.engram_id = eid
        return eid

    def _log_generation(self, generation: int, evaluated: int, frontier_size: int) -> None:
        self.conn.execute(
            "INSERT INTO experiment_runs (run_id, kind, summary, metrics) VALUES (?,?,?,?)",
            (
                str(ulid.new()),
                "evolution",
                f"generation {generation}: evaluated {evaluated}, frontier {frontier_size}",
                json.dumps({"generation": generation, "evaluated": evaluated}),
            ),
        )
        self.conn.commit()

    def run(self, seed: Genome, *, generations: int, population: int = 4) -> GenomeFrontier:
        """Per generation: reflect on the worst member's feedback → targeted
        component mutation → (optional surrogate prefilter) → benchmark →
        frontier update → persist + journal. Deterministic given deterministic
        reflect/benchmark fns (tests run keyless)."""
        seed.scores = self.benchmark(seed)
        self._persist(seed, 0)
        self.frontier.update(seed)
        self._log_generation(0, 1, len(self.frontier.members()))

        for gen in range(1, generations + 1):
            members = self.frontier.members()
            worst = min(members, key=lambda m: m.scores.get("quality", 0.0))
            feedback = self.feedback_fn(worst, worst.scores)

            candidates: list[Genome] = []
            base = worst
            for _ in range(population):
                mutation = self.reflect_fn(base, feedback)
                child = base.mutate(mutation["component"], mutation["new_text"])
                candidates.append(child)
                base = child  # chain mutations for diversity

            if self.surrogate is not None and len(candidates) > 2:
                candidates = sorted(candidates, key=self.surrogate, reverse=True)[:2]

            for cand in candidates:
                cand.scores = self.benchmark(cand)
                self._persist(cand, gen)
                self.frontier.update(cand)
            self._log_generation(gen, len(candidates), len(self.frontier.members()))
        return self.frontier


def promote(candidate_engram_id: str, *, store: EngramStore, conn: sqlite3.Connection) -> str:
    """Activate an evolved artifact — ONLY behind an ACCEPT verdict (D3).

    Requires an eval engram with metadata status ACCEPT linked ``verifies`` →
    candidate, AND that verdict must be backed by a real probe run: an
    ``experiment_runs`` row tying it to an *admissible*, lock-intact
    ``probe_registry`` entry. A hand-appended eval engram (forged ``ACCEPT``
    via the public ``store.append`` + ``store.link`` path, with no probe run)
    is therefore rejected — closing the consumption-side back door where the
    sha256 lock only guarded verdict *production*, not promotion. Records a
    ``gated_by`` link candidate → verdict and returns the verdict engram id.
    Raises PromotionBlocked otherwise.
    """
    store.get(candidate_engram_id)  # existence check
    rows = conn.execute(
        "SELECT e.engram_id, e.metadata FROM engram_links l"
        " JOIN engrams e ON e.engram_id = l.src_id"
        " WHERE l.link_type = 'verifies' AND e.kind = 'eval' AND l.dst_id = ?",
        (candidate_engram_id,),
    ).fetchall()
    for verdict_id, metadata in rows:
        if json.loads(metadata).get("status") != "ACCEPT":
            continue
        if not _verdict_is_probe_backed(verdict_id, conn):
            continue  # forged / unbacked ACCEPT — no admissible probe produced it
        store.link(candidate_engram_id, verdict_id, "gated_by")
        conn.commit()
        return verdict_id
    raise PromotionBlocked(
        f"candidate {candidate_engram_id}: no probe-backed ACCEPT verdict on "
        "record — run a registered, admissible probe first (no retune-and-rerun, "
        "no hand-forged verdict engram)"
    )


def _verdict_is_probe_backed(verdict_id: str, conn: sqlite3.Connection) -> bool:
    """True iff the verdict engram was produced by a real, admissible,
    lock-intact probe run.

    Integrity (D3/D6): a genuine verdict has an ``experiment_runs`` row whose
    ``probe_id`` resolves to a ``probe_registry`` entry that is (a) marked
    ``admissible`` (an inadmissible probe can never grant a true ACCEPT) and
    (b) whose stored ``gate_spec`` still hashes to its ``lock_sha256`` (no
    post-registration tamper of the registry row). A forged eval engram has no
    such ``experiment_runs`` row and fails here.
    """
    import hashlib

    row = conn.execute(
        "SELECT p.gate_spec, p.lock_sha256, p.status"
        " FROM experiment_runs r JOIN probe_registry p ON p.probe_id = r.probe_id"
        " WHERE r.verdict_engram = ? AND r.kind = 'probe'",
        (verdict_id,),
    ).fetchone()
    if row is None:
        return False
    gate_spec, lock_sha256, status = row
    if status != "admissible":
        return False
    return hashlib.sha256(gate_spec.encode()).hexdigest() == lock_sha256
