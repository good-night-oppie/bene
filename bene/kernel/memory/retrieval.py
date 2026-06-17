"""Adaptive retrieval — familiarity-gated fast/slow dual path (RF-Mem).

RF-Mem (SYNTHESIS: agent-context-memory #03): confident (familiar) queries
take a one-shot top-K path; uncertain ones take a bounded associative
recollection loop. The served path is RECORDED on the query engram so the
choice is auditable and testable (trust pillar: retrieval spend is a visible,
explainable decision, not a black box).

Familiarity here is a deterministic, documented heuristic — normalized token
overlap with recent queries (pluggable; an LLM/embedding scorer can replace it
without changing the interface).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from bene.kernel.engrams import Engram, EngramStore
from bene.kernel.memory.granules import GranuleStore

FAST_THRESHOLD = 0.6
RECENT_QUERIES = 20


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in text.split() if len(w) > 2}


@dataclass
class RetrievalResult:
    query: str
    path: str  # "fast" | "slow"
    familiarity: float
    hits: list[Engram] = field(default_factory=list)
    query_engram: str | None = None


class AdaptiveRetriever:
    def __init__(
        self,
        store: EngramStore,
        granules: GranuleStore | None = None,
        *,
        fast_threshold: float = FAST_THRESHOLD,
    ) -> None:
        self.store = store
        self.granules = granules or GranuleStore(store)
        self.fast_threshold = fast_threshold
        self._recent: list[str] = []  # recent query texts (per-process familiarity window)

    def familiarity(self, text: str) -> float:
        """Max normalized token overlap against the recent-query window."""
        q = _tokens(text)
        if not q or not self._recent:
            return 0.0
        best = 0.0
        for prev in self._recent[-RECENT_QUERIES:]:
            p = _tokens(prev)
            if p:
                best = max(best, len(q & p) / len(q | p))
        return best

    def query(self, agent_id: str, text: str, *, k: int = 8) -> RetrievalResult:
        fam = self.familiarity(text)
        path = "fast" if fam >= self.fast_threshold else "slow"
        safe = " ".join(w for w in text.split() if w.isalnum())  # FTS5-safe terms

        hits = self.store.search(safe or text, limit=k) if (safe or text).strip() else []
        if path == "slow":
            # bounded associative expansion: one hop from the top hits
            expanded: dict[str, Engram] = {e.engram_id: e for e in hits}
            for e in hits[:3]:
                for n in self.granules.neighbors(e.engram_id):
                    expanded.setdefault(n.engram_id, n)
            hits = list(expanded.values())[: k * 2]

        self._recent.append(text)
        query_engram = self.store.append(
            "trace",
            f"query:{text[:60]}",
            text,
            provenance=(
                {"agent_id": agent_id} if agent_id else {"system": "bene.kernel.memory.retrieval"}
            ),
            agent_id=agent_id,
            metadata={"retrieval_path": path, "familiarity": round(fam, 4), "hits": len(hits)},
        )
        return RetrievalResult(text, path, fam, hits, query_engram)


# ---------------------------------------------------------------------------
# MemGAS — entropy-routed multi-granularity retrieval
# ---------------------------------------------------------------------------

MEMGAS_TIERS = (0, 2, 3, 4)  # skip tier-1 episodic by default
PER_TIER_K = 8
WEIGHT_CUTOFF = 0.15
TEMPERATURE = 1.0


@dataclass
class TierProbe:
    tier: int
    hits: list[Engram]
    entropy: float  # H(softmax(-bm25)) normalized to [0,1]; flat=1, peaked→0
    weight: float  # softmin over entropies across non-empty tiers; sum==1
    top_score: float  # best bm25 (smaller=better) in the tier, 0.0 if empty


@dataclass
class MemGASResult(RetrievalResult):
    """A RetrievalResult plus the per-tier routing trace (auditable)."""

    tier_probes: list[TierProbe] = field(default_factory=list)
    routed_tiers: list[int] = field(default_factory=list)


class MemGASRouter(AdaptiveRetriever):
    """Multi-granularity entropy router. Probes each configured ladder tier,
    weights tiers by softmin(entropy) (a sharply-peaked tier wins; a flat,
    uncertain one is down-weighted), merges the surviving tiers, then keeps the
    existing familiarity-gated fast/slow stage as the final associative step.

    Backwards-compatible: with one non-empty tier it collapses to single-tier
    behavior. Opt-in — ``AdaptiveRetriever`` stays the default live path.
    """

    def __init__(
        self,
        store: EngramStore,
        granules: GranuleStore | None = None,
        *,
        tiers: tuple[int, ...] = MEMGAS_TIERS,
        per_tier_k: int = PER_TIER_K,
        weight_cutoff: float = WEIGHT_CUTOFF,
        temperature: float = TEMPERATURE,
        fast_threshold: float = FAST_THRESHOLD,
    ) -> None:
        super().__init__(store, granules, fast_threshold=fast_threshold)
        self.tiers = tuple(tiers)
        self.per_tier_k = per_tier_k
        self.weight_cutoff = weight_cutoff
        self.temperature = max(temperature, 1e-6)

    @staticmethod
    def _safe_query(text: str) -> str:
        return " ".join(w for w in text.split() if w.isalnum())

    def _entropy(self, scores: list[float]) -> float:
        """Normalized Shannon entropy of softmax(-bm25/temp). bm25 is
        smaller=better, so -bm25 is larger=better; a single dominant hit gives
        low entropy, a flat distribution gives ~1.0. Empty → 1.0 (max
        uncertainty); single hit → 0.0 (fully certain)."""
        if not scores:
            return 1.0
        if len(scores) == 1:
            return 0.0
        logits = [(-s) / self.temperature for s in scores]
        m = max(logits)
        exps = [math.exp(v - m) for v in logits]
        z = sum(exps)
        ps = [e / z for e in exps]
        h = -sum(p * math.log(p) for p in ps if p > 0)
        return h / math.log(len(ps))

    def probe_tier(self, query: str, tier: int, k: int) -> TierProbe:
        hits = self.store.search(query, tier=tier, limit=k) if query.strip() else []
        scores = [h.score for h in hits if h.score is not None]
        top = min(scores) if scores else 0.0
        return TierProbe(
            tier=tier, hits=hits, entropy=self._entropy(scores), weight=0.0, top_score=top
        )

    def route(self, probes: list[TierProbe]) -> list[TierProbe]:
        """Assign softmin(entropy) weights to non-empty tiers (sum==1)."""
        active = [p for p in probes if p.hits]
        if not active:
            return []
        logits = [(-p.entropy) / self.temperature for p in active]
        m = max(logits)
        exps = [math.exp(v - m) for v in logits]
        z = sum(exps)
        for p, e in zip(active, exps):
            p.weight = e / z
        return active

    def query(self, agent_id: str, text: str, *, k: int = 8) -> MemGASResult:
        safe = self._safe_query(text) or text
        probes = [self.probe_tier(safe, t, self.per_tier_k) for t in self.tiers]
        routed = self.route(probes)
        kept = [p for p in routed if p.weight >= self.weight_cutoff] or routed
        routed_tiers = [p.tier for p in kept]

        # Merge surviving tiers, dedup by engram_id, rank by weight * 1/rank.
        scored: dict[str, tuple[float, Engram]] = {}
        for p in kept:
            for rank, e in enumerate(p.hits, start=1):
                s = p.weight * (1.0 / rank)
                cur = scored.get(e.engram_id)
                if cur is None or s > cur[0]:
                    scored[e.engram_id] = (s, e)
        merged = [e for _, e in sorted(scored.values(), key=lambda x: x[0], reverse=True)][:k]

        # Final fast/slow stage: associative expansion only when unfamiliar.
        fam = self.familiarity(text)
        path = "fast" if fam >= self.fast_threshold else "slow"
        if path == "slow" and merged:
            expanded: dict[str, Engram] = {e.engram_id: e for e in merged}
            for e in merged[:3]:
                for n in self.granules.neighbors(e.engram_id):
                    expanded.setdefault(n.engram_id, n)
            merged = list(expanded.values())[: k * 2]

        self._recent.append(text)
        # Metadata carries per-tier summary only (counts/scores), never hit
        # bodies, so the query engram's FTS body stays bounded.
        tier_meta = [
            {
                "tier": p.tier,
                "entropy": round(p.entropy, 4),
                "weight": round(p.weight, 4),
                "top_score": round(p.top_score, 4),
                "hits": len(p.hits),
            }
            for p in probes
        ]
        query_engram = self.store.append(
            "trace",
            f"memgas:{text[:50]}",
            text,
            provenance=(
                {"agent_id": agent_id} if agent_id else {"system": "bene.kernel.memory.retrieval"}
            ),
            agent_id=agent_id,
            metadata={
                "retrieval_path": path,
                "familiarity": round(fam, 4),
                "router": "memgas",
                "tier_probes": tier_meta,
                "routed_tiers": routed_tiers,
                "hits": len(merged),
            },
        )
        return MemGASResult(
            text, path, fam, merged, query_engram, tier_probes=probes, routed_tiers=routed_tiers
        )
