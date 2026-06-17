"""VEA-style evidence re-highlighting — the cheap rung of the recovery ladder.

"Seeing but Not Believing" (SYNTHESIS: agent-theory, VEA — Visual Evidence
Augmentation): a model often *attends to the correct evidence already in
context* yet still answers wrong, because irrelevant context dominates. The
training-free fix is to re-weight — foreground the evidence, dim the
background, then re-ask. No new retrieval, no checkpoint restore.

Mapped onto BENE's context OS (CLAIMS-AUDIT row 43; BENE2-DESIGN §pollution):
*evidence present ≠ evidence used*. Before we pay for re-retrieval or a
consolidate→restore, restructure what is ALREADY in context — push the items
that match the consolidated requirements to the front, truncate the rest — and
let the agent re-ask. This is the first rung of the recovery ladder:

    re-highlight (cheap, in-context)
      → consolidate + restore (mid)
        → respawn (expensive)

We only climb when the cheap rung can't help — and the signal for that is
``evidence_present``: if NOTHING in context matches the requirements, no amount
of re-weighting recovers the answer, so we escalate. The intervention is
verified the VEA way — by whether re-asking with it changes the outcome.

Deterministic and auditable: every re-highlight returns a manifest of what was
foregrounded, what was dimmed, and the terms it keyed on (pillar 5; D9).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bene.kernel.memory.contextos import default_estimator

#: minimal stopword set — requirement terms are trace titles, not prose, so a
#: short list keeps the keying terms meaningful without a dependency.
_STOPWORDS = frozenset(
    "the a an and or but to of in on for with at by from into is are was were be "
    "this that these those it its as not no do did done run ran via".split()
)

_WORD_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


@dataclass
class RehighlightedContext:
    """The restructured context plus the audit trail of the intervention."""

    terms: list[str]
    foregrounded: list[dict] = field(default_factory=list)  # evidence, score-sorted
    dimmed: list[dict] = field(default_factory=list)  # background, truncated

    @property
    def evidence_present(self) -> bool:
        """Did ANY item match the requirements? The recovery-ladder gate — when
        False, re-highlighting cannot help and the caller must escalate."""
        return bool(self.foregrounded)

    @property
    def items(self) -> list[dict]:
        """The re-weighted context in pack order: evidence first, then dimmed."""
        return [*self.foregrounded, *self.dimmed]

    def render(self) -> str:
        """A single string for re-asking (foreground block, then dimmed block)."""
        return "\n".join(i["text"] for i in self.items)

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "terms": self.terms,
            "evidence_present": self.evidence_present,
            "foregrounded": [
                {"id": i.get("id", i["text"][:40]), "score": i.get("evidence_score")}
                for i in self.foregrounded
            ],
            "dimmed": [i.get("id", i["text"][:40]) for i in self.dimmed],
        }


class EvidenceRehighlighter:
    """Re-weight in-context items toward the requirements (VEA, text-domain).

    ``score`` is the fraction of distinct requirement terms that appear as words
    in an item — a deterministic stand-in for VEA's patch-level evidence map.
    Items scoring above ``threshold`` are foregrounded (marked + full text,
    highest score first); the rest are dimmed (truncated to ``dim_chars``).
    """

    def __init__(
        self,
        *,
        dim_chars: int = 160,
        marker: str = "«evidence»",
        min_term_len: int = 3,
        estimator: Callable[[str], int] = default_estimator,
    ) -> None:
        self.dim_chars = dim_chars
        self.marker = marker
        self.min_term_len = min_term_len
        self.estimator = estimator

    def terms_from(self, requirements: str) -> list[str]:
        """Distinct keying terms from a requirements blob (order-preserving)."""
        seen: dict[str, None] = {}
        for tok in _tokenize(requirements):
            if len(tok) >= self.min_term_len and tok not in _STOPWORDS:
                seen.setdefault(tok, None)
        return list(seen)

    def score(self, item: dict, terms: list[str]) -> float:
        """Fraction of requirement terms present as words in the item (0..1)."""
        if not terms:
            return 0.0
        words = set(_tokenize(item.get("text", "")))
        matched = sum(1 for t in terms if t in words)
        return matched / len(terms)

    def _dim(self, text: str) -> str:
        if len(text) <= self.dim_chars:
            return text
        return text[: self.dim_chars].rstrip() + "…"

    def rehighlight(
        self,
        items: list[dict],
        requirements: str,
        *,
        threshold: float = 0.0,
    ) -> RehighlightedContext:
        """Foreground items matching the requirements; dim the rest.

        Each item: ``{"id": str, "text": str, ...}``. Original dicts are never
        mutated — foregrounded/dimmed copies carry a ``rehighlight`` tag and (for
        evidence) an ``evidence_score``.
        """
        terms = self.terms_from(requirements)
        scored = [(self.score(it, terms), idx, it) for idx, it in enumerate(items)]
        # evidence: score strictly above threshold, sorted by score desc then by
        # original position (stable, deterministic — no Math.random in the kernel).
        evidence = sorted(
            (s for s in scored if s[0] > threshold),
            key=lambda s: (-s[0], s[1]),
        )
        ev_ids = {id(it) for _, _, it in evidence}
        foregrounded = [
            {
                **it,
                "text": f"{self.marker} {it['text']}",
                "rehighlight": "foreground",
                "evidence_score": round(s, 4),
            }
            for s, _, it in evidence
        ]
        dimmed = [
            {**it, "text": self._dim(it.get("text", "")), "rehighlight": "dimmed"}
            for _, _, it in scored
            if id(it) not in ev_ids
        ]
        return RehighlightedContext(terms=terms, foregrounded=foregrounded, dimmed=dimmed)
