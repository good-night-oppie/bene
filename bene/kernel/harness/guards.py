"""Loop guards — doom-loop detection middleware (LangChain Deep Agents pt 4).

Sliding-window detection over the action stream: repeated near-identical
actions (same tool + similar args ≥ threshold) or A/B oscillation trips the
guard, which emits an ``intervention`` engram and invokes a callback (default:
forced-reflection note). Heuristic, not guarantee — and deliberately built as
removable middleware ("built to be deleted" as models improve).
"""

from __future__ import annotations

import json
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bene.kernel.engrams import EngramStore

DEFAULT_WINDOW = 20
REPEAT_THRESHOLD = 5
OSCILLATION_THRESHOLD = 3  # A-B-A-B-A-B

FORCED_REFLECTION = (
    "LOOP GUARD: you have repeated a near-identical action. Stop. State (1) what "
    "you expected, (2) what actually happened, (3) one alternative approach — then "
    "take the alternative or escalate."
)


def _signature(event: dict[str, Any]) -> str:
    tool = event.get("tool", "?")
    args = event.get("args", {})
    blob = json.dumps(args, sort_keys=True, default=str)[:120]
    return f"{tool}:{blob}"


@dataclass
class Intervention:
    reason: str  # "repetition" | "oscillation"
    signature: str
    count: int
    message: str = FORCED_REFLECTION
    engram_id: str | None = None


class LoopGuard:
    def __init__(
        self,
        store: EngramStore | None = None,
        *,
        window: int = DEFAULT_WINDOW,
        repeat_threshold: int = REPEAT_THRESHOLD,
        on_trip: Callable[[Intervention], None] | None = None,
    ) -> None:
        self.store = store
        self.window: deque[str] = deque(maxlen=window)
        self.repeat_threshold = repeat_threshold
        self.on_trip = on_trip
        self._tripped_sigs: set[str] = set()

    def observe(self, event: dict[str, Any]) -> Intervention | None:
        """Feed one action event ({tool, args, agent_id?}); returns an
        Intervention when a loop pattern trips (once per signature)."""
        sig = _signature(event)
        self.window.append(sig)

        counts = Counter(self.window)
        intervention: Intervention | None = None

        if counts[sig] >= self.repeat_threshold and sig not in self._tripped_sigs:
            intervention = Intervention("repetition", sig, counts[sig])
        elif self._oscillating(sig) and sig not in self._tripped_sigs:
            intervention = Intervention("oscillation", sig, OSCILLATION_THRESHOLD)

        if intervention is not None:
            self._tripped_sigs.add(sig)
            if self.store is not None:
                intervention.engram_id = self.store.append(
                    "intervention",
                    f"loop-guard:{intervention.reason}",
                    json.dumps(
                        {
                            "signature": intervention.signature,
                            "count": intervention.count,
                            "message": intervention.message,
                        }
                    ),
                    provenance={"system": "bene.kernel.harness.guards"},
                    agent_id=event.get("agent_id"),
                    metadata={"reason": intervention.reason},
                )
            if self.on_trip is not None:
                self.on_trip(intervention)
        return intervention

    def _oscillating(self, sig: str) -> bool:
        """A-B-A-B-A-B tail pattern over the last 2*threshold entries."""
        tail = list(self.window)[-2 * OSCILLATION_THRESHOLD :]
        if len(tail) < 2 * OSCILLATION_THRESHOLD:
            return False
        a, b = tail[0], tail[1]
        if a == b or sig not in (a, b):
            return False
        return all(tail[i] == (a if i % 2 == 0 else b) for i in range(len(tail)))

    def reset(self) -> None:
        self.window.clear()
        self._tripped_sigs.clear()
