"""Memory granules — multi-granularity memory over the engram ladder.

MemGAS (SYNTHESIS: agent-context-memory #02) stores memories at multiple
granularities with association links; BENE maps granularity onto the existing
compression ladder — turn(0) / episode(1) / semantic(2) / procedural(3) — so
consolidation IS promotion (D2) and no second storage system exists (D1).
"""

from __future__ import annotations

from typing import Any

from bene.kernel.engrams import Engram, EngramStore

GRANULE_TIERS = {"turn": 0, "episode": 1, "semantic": 2, "procedural": 3}


class GranuleStore:
    def __init__(self, store: EngramStore) -> None:
        self.store = store

    def write_turn(self, agent_id: str, text: str, **metadata: Any) -> str:
        return self.store.append(
            "trace",
            text[:80] or "turn",
            text,
            provenance={"agent_id": agent_id},
            agent_id=agent_id,
            metadata={"granule": "turn", **metadata},
        )

    def consolidate(
        self,
        granule_ids: list[str],
        *,
        summary: str,
        provenance: dict[str, Any],
        to_level: str = "episode",
    ) -> str:
        """Promote a group of granules into one higher-level granule.

        The sources are linked via ``consolidates`` and never mutated; the new
        granule's tier comes from the target level (consolidation == promotion).
        """
        if to_level not in GRANULE_TIERS or to_level == "turn":
            raise ValueError(f"to_level must be one of episode/semantic/procedural, got {to_level}")
        if not granule_ids:
            raise ValueError("nothing to consolidate")
        new_tier = GRANULE_TIERS[to_level]
        return self.store.promote(
            granule_ids[0],
            new_tier=new_tier,
            title=summary[:80],
            payload=summary,
            provenance=provenance,
            sources=granule_ids[1:],
            metadata={"granule": to_level, "consolidated_from": len(granule_ids)},
        )

    def associate(self, a: str, b: str, weight: float = 1.0) -> str:
        return self.store.link(a, b, "associates", weight)

    def neighbors(self, engram_id: str) -> list[Engram]:
        """Association-linked granules (both directions)."""
        rows = self.store.conn.execute(
            "SELECT CASE WHEN src_id = ? THEN dst_id ELSE src_id END FROM engram_links"
            " WHERE link_type = 'associates' AND (src_id = ? OR dst_id = ?)",
            (engram_id, engram_id, engram_id),
        ).fetchall()
        return [self.store.get(r[0]) for r in rows]
