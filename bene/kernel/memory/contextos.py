"""Context OS — token budgets, pluggable packing strategies, signal routing.

Schmid's frame (SYNTHESIS: harness-engineering #10): context window = RAM, so
an OS pages deliberately. AgentSwing (agent-context-memory #01) shows context
strategy should be a ROUTING decision driven by task signals, not a fixed
compression rule. Every assembly returns a MANIFEST of what was included and
dropped — context becomes transparent and auditable (pillar 5; D9).

Token estimation: chars/4 heuristic, pluggable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: a packing strategy takes (items, budget_tokens, estimator) and returns the
#: chosen subset in pack order
PackStrategy = Callable[[list[dict], int, Callable[[str], int]], list[dict]]


def default_estimator(text: str) -> int:
    return max(1, len(text) // 4)


def recency_window(items: list[dict], budget: int, est) -> list[dict]:
    """Newest-first until the budget is full."""
    chosen: list[dict] = []
    used = 0
    for item in reversed(items):
        t = est(item["text"])
        if used + t > budget:
            break
        chosen.append(item)
        used += t
    return list(reversed(chosen))


def relevance_topk(items: list[dict], budget: int, est) -> list[dict]:
    """Highest-relevance first (requires 'relevance' on items)."""
    chosen: list[dict] = []
    used = 0
    for item in sorted(items, key=lambda i: i.get("relevance", 0.0), reverse=True):
        t = est(item["text"])
        if used + t <= budget:
            chosen.append(item)
            used += t
    return chosen


def compress_then_pack(items: list[dict], budget: int, est) -> list[dict]:
    """Truncate each item to its budget share, then pack newest-first."""
    if not items:
        return []
    share_chars = max(64, (budget * 4) // len(items))
    compressed = [{**i, "text": i["text"][:share_chars]} for i in items]
    return recency_window(compressed, budget, est)


@dataclass
class PackedContext:
    strategy: str
    budget_tokens: int
    estimated_tokens: int
    included: list[dict] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # ids/labels of dropped items

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "budget_tokens": self.budget_tokens,
            "estimated_tokens": self.estimated_tokens,
            "included": [i.get("id", i["text"][:40]) for i in self.included],
            "dropped": self.dropped,
        }


class ContextOS:
    def __init__(self, *, estimator: Callable[[str], int] = default_estimator) -> None:
        self.estimator = estimator
        self._strategies: dict[str, PackStrategy] = {
            "recency-window": recency_window,
            "relevance-topk": relevance_topk,
            "compress-then-pack": compress_then_pack,
        }

    def register_strategy(self, name: str, fn: PackStrategy) -> None:
        self._strategies[name] = fn

    def strategies(self) -> list[str]:
        return sorted(self._strategies)

    def select_strategy(self, signals: dict[str, Any]) -> str:
        """Signal-driven routing (AgentSwing-style, deterministic rules):

        - high error rate → compress-then-pack (derailed runs need broad,
          cheap coverage of what happened, not depth);
        - long-horizon w/ relevance scores → relevance-topk;
        - default → recency-window.
        Rules are intentionally simple and documented; the routing policy is
        itself an evolvable component (a genome's context_strategy).
        """
        if signals.get("error_rate", 0.0) > 0.3:
            return "compress-then-pack"
        if signals.get("long_horizon") and signals.get("has_relevance"):
            return "relevance-topk"
        return "recency-window"

    def assemble(
        self,
        items: list[dict],
        budget_tokens: int,
        *,
        signals: dict[str, Any] | None = None,
        strategy: str | None = None,
    ) -> PackedContext:
        """Pack items under the budget. NEVER exceeds budget_tokens.

        Each item: {"id": str, "text": str, "relevance": float?}. Returns the
        packed context plus a manifest of included and dropped items.
        """
        name = strategy or self.select_strategy(signals or {})
        if name not in self._strategies:
            raise KeyError(f"unknown strategy: {name}")
        # Stamp a stable identity BEFORE packing. id()-based diffing was wrong
        # for any strategy that returns transformed copies — compress-then-pack
        # rebuilds dicts via {**i}, so every chosen copy had a fresh id() and
        # the manifest reported all originals as dropped AND their copies as
        # included. _uid survives both {**i} copies and subset passes.
        tagged = [{**it, "_uid": i} for i, it in enumerate(items)]
        chosen = self._strategies[name](tagged, budget_tokens, self.estimator)
        used = sum(self.estimator(i["text"]) for i in chosen)
        if used > budget_tokens:  # defensive: a strategy must not overrun
            while chosen and used > budget_tokens:
                dropped_item = chosen.pop()
                used -= self.estimator(dropped_item["text"])
        chosen_uids = {i.get("_uid") for i in chosen}
        dropped = [
            it.get("id", it["text"][:40]) for i, it in enumerate(items) if i not in chosen_uids
        ]
        # Strip the internal tag so it never leaks into included / the payload.
        clean = [{k: v for k, v in i.items() if k != "_uid"} for i in chosen]
        return PackedContext(name, budget_tokens, used, clean, dropped)
