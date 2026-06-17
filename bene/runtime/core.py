"""Frozen, JSON-safe DTOs shared by LocalRuntime and TemporalRuntime.

No imports from ``temporalio`` or ``bene/temporal/`` permitted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

JSONScalar = str | int | float | bool | None
JSONValue = "JSONScalar | list[JSONValue] | dict[str, JSONValue]"


# ---------------------------------------------------------------------------
# Core usage / message primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    turns: int = 1


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


# ---------------------------------------------------------------------------
# LLM command / result boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMCommand:
    run_id: str
    agent_id: str
    step: int
    model: str
    messages: list[ChatMessage]
    conversation_id: str | None = None
    tools: list[dict[str, Any]] | None = None
    config: dict[str, Any] | None = None
    # Business-level dedup key. Runtime computes the SHA hash via
    # BusinessIdempotencyKey. Single canonical key — no parallel str variant.
    idempotency_key: tuple[str, ...] | None = None


@dataclass(frozen=True)
class LLMResult:
    content: str | None
    tool_calls: list[ToolCall] | None
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"
    usage: TokenUsage
    raw_metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Side-effect classification
# ---------------------------------------------------------------------------


class SideEffectKind(str, Enum):
    EXTERNAL_WRITE = "external_write"
    EXTERNAL_READ = "external_read"
    LLM_CALL = "llm_call"


class ReconciliationStrategy(str, Enum):
    """How the runtime detects that a side effect already committed on retry.

    IDEMPOTENT_BY_KEY: Operation is naturally idempotent; re-executing is safe.
        Both runtimes: ledger dedup by business_key handles common case.
    READBACK_SENTINEL: Runtime reads sentinel field post-execution to detect
        prior commit on retry. NOTE: LocalRuntime stores this strategy but does
        NOT execute the scan — its lock prevents double-call instead. Tests
        with READBACK_SENTINEL on LocalRuntime give false confidence; verify
        sentinel-scan correctness on TemporalRuntime integration test only.
    READBACK_RESULT_KEY: Phase-2 reserved. No runtime behavior on either
        backend yet.
    MANUAL: Human operator detects and remediates double-execution post-hoc.
        NOT equivalent to None. Use for irreversible operations (payment,
        physical action) where automation is impossible. If you mean "I have
        not decided yet," use None — LocalRuntime will warn at submit time.
    """

    IDEMPOTENT_BY_KEY = "idempotent_by_key"
    READBACK_SENTINEL = "readback_sentinel"
    READBACK_RESULT_KEY = "readback_result_key"  # reserved for Phase 2
    MANUAL = "manual"


@dataclass(frozen=True)
class CostEstimate:
    latency_ms: int = 0
    dollars: float = 0.0
    confirmed_free: bool = False


@dataclass(frozen=True)
class SideEffectLabel:
    kind: SideEffectKind
    semantic_class: str
    rate_limit_class: str
    cost_estimate: CostEstimate = field(default_factory=CostEstimate)
    reconciliation_strategy: ReconciliationStrategy | None = None
    sentinel_template: str | None = None


# ---------------------------------------------------------------------------
# Business idempotency key
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BusinessIdempotencyKey:
    """Caller passes a tuple; runtime owns serialization.

    The hash is deterministic and collision-resistant. The caller must NOT
    join the parts with ``":"`` — that creates encoding-variance bugs when
    parts themselves contain ``":"``.
    """

    parts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("BusinessIdempotencyKey.parts must be non-empty")

    def serialize(self) -> str:
        """Return a 32-hex-char stable key for this tuple."""
        return hashlib.sha256("\x00".join(self.parts).encode()).hexdigest()[:32]
