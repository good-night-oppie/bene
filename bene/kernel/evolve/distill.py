"""Trace→skill distillation — patches, prevalence merge, 3-level hierarchy.

Trace2Skill mechanics (SYNTHESIS: agent-auto-opt #04): per-trajectory analysts
emit skill patches (success: single-pass lesson; failure: evidence chain with
root cause), then a prevalence-weighted, conflict-free merge consolidates them
into a static hierarchy — planning / functional / atomic (SkillX 3-tier,
agent-auto-opt #02). Every produced skill engram carries ``consolidates``
links to EVERY source trace that contributed a patch (D1: lineage answers
"which traces does this skill compress?").
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any, TypedDict

from bene.kernel.engrams import EngramStore

LEVELS = ("planning", "functional", "atomic")


class Patch(TypedDict, total=False):
    level: str  # planning | functional | atomic
    lesson: str  # the transferable rule, imperative form
    evidence: str  # supporting evidence (root-cause chain for failures)


# analyst_fn(trace_payload, is_failure) -> list of patches
AnalystFn = Callable[[str, bool], list[Patch]]


class TraceDistiller:
    def __init__(self, store: EngramStore) -> None:
        self.store = store

    def distill(
        self,
        trace_ids: list[str],
        *,
        analyst_fn: AnalystFn,
        provenance: dict[str, Any] | None = None,
    ) -> list[str]:
        """Mine traces → patches → prevalence-merged per-level skills.

        Returns the engram ids of the produced procedural (tier-3) engrams,
        one per level that received patches. Lessons proposed by more traces
        rank higher (prevalence weighting); duplicate lessons merge their
        evidence instead of repeating.
        """
        if not trace_ids:
            return []
        prov = provenance or {"system": "bene.kernel.evolve.distill"}

        # lesson-key -> {level, lesson, evidence[], sources[]}
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        contributors: dict[str, set[str]] = defaultdict(set)  # level -> trace ids

        for tid in trace_ids:
            engram = self.store.get(tid)
            payload = self.store.payload(tid).decode(errors="replace")
            is_failure = bool(engram.metadata.get("failure"))
            for patch in analyst_fn(payload, is_failure):
                level = patch.get("level", "functional")
                if level not in LEVELS:
                    raise ValueError(f"patch level must be one of {LEVELS}: {patch!r}")
                key = (level, patch["lesson"].strip().lower())
                entry = merged.setdefault(
                    key,
                    {"level": level, "lesson": patch["lesson"], "evidence": [], "sources": []},
                )
                if patch.get("evidence"):
                    entry["evidence"].append(patch["evidence"])
                entry["sources"].append(tid)
                contributors[level].add(tid)

        produced: list[str] = []
        for level in LEVELS:
            entries = [e for (lv, _), e in merged.items() if lv == level]
            if not entries:
                continue
            entries.sort(key=lambda e: len(e["sources"]), reverse=True)  # prevalence
            body_lines = [f"# {level} skills (distilled from {len(contributors[level])} traces)"]
            for e in entries:
                body_lines.append(f"- [{len(e['sources'])}x] {e['lesson']}")
                for ev in e["evidence"][:3]:
                    body_lines.append(f"  evidence: {ev}")
            sources = sorted(contributors[level])
            eid = self.store.promote(
                sources[0],
                new_tier=3,
                title=f"distilled:{level}",
                payload="\n".join(body_lines),
                provenance=prov,
                sources=sources[1:],
                metadata={"level": level, "lessons": len(entries)},
            )
            produced.append(eid)
        return produced
