"""DGM archive — open-ended Darwin-Gödel-Machine archive for SECH (bene-core B1).

The kill-gate decides what is *promotable*; the DGM archive *keeps every accepted
harness* so the search stays open-ended (a later generation can branch from an older
accepted ancestor, not just the current best). This is the "keep ALL accepted
harnesses" requirement of the SPEC's Contract G — distinct from greedy hill-climbing.

The archive is append-only and content-addressed: each entry stamps the harness
content hash + parent so the accepted genealogy is auditable and rollback-able.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ArchiveEntry:
    harness_id: str
    content_hash: str
    parent_id: str | None
    generation: int
    fitness: dict[str, float]
    mutation_kind: str | None  # the kind of the mutation that produced this harness
    accepted_at_gen: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DGMArchive:
    """Append-only archive of accepted harnesses (open-ended search)."""

    entries: list[ArchiveEntry] = field(default_factory=list)

    def add(
        self,
        *,
        harness_id: str,
        content_hash: str,
        parent_id: str | None,
        generation: int,
        fitness: dict[str, float],
        mutation_kind: str | None,
        accepted_at_gen: int,
    ) -> ArchiveEntry:
        entry = ArchiveEntry(
            harness_id=harness_id,
            content_hash=content_hash,
            parent_id=parent_id,
            generation=generation,
            fitness=dict(fitness),
            mutation_kind=mutation_kind,
            accepted_at_gen=accepted_at_gen,
        )
        self.entries.append(entry)
        return entry

    def __len__(self) -> int:
        return len(self.entries)

    def best(self, objective: str = "win_rate") -> ArchiveEntry | None:
        if not self.entries:
            return None
        return max(self.entries, key=lambda e: e.fitness.get(objective, float("-inf")))

    def select_parent(
        self,
        rng: random.Random,
        *,
        objective: str = "win_rate",
        epsilon: float = 0.25,
    ) -> ArchiveEntry | None:
        """Sample a parent from the accepted archive for open-ended search.

        Greedy single-incumbent hill-climbing can never re-select an older accepted
        ancestor with a lower immediate win_rate, so the archive becomes passive
        bookkeeping. Epsilon-greedy over the accepted entries restores open-endedness:
        with prob ``(1 - epsilon)`` return the current ``best()`` (exploit), else a random
        accepted entry (explore a non-incumbent branch). Deterministic given *rng* so the
        run stays reproducible. (PR #67 review)
        """
        if not self.entries:
            return None
        if rng.random() < epsilon:
            return rng.choice(self.entries)
        return self.best(objective)

    def lineage_of(self, harness_id: str) -> list[ArchiveEntry]:
        """Walk parent pointers from *harness_id* back to the seed (root-last)."""
        by_id = {e.harness_id: e for e in self.entries}
        chain: list[ArchiveEntry] = []
        cur: str | None = harness_id
        seen: set[str] = set()
        while cur is not None and cur in by_id and cur not in seen:
            seen.add(cur)
            entry = by_id[cur]
            chain.append(entry)
            cur = entry.parent_id
        return chain

    def accepted_mutation_kinds(self) -> list[str]:
        return [e.mutation_kind for e in self.entries if e.mutation_kind is not None]

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}
