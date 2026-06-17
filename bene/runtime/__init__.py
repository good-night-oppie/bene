"""Runtime-neutral DTOs and protocol for BENE local and Temporal backends.

No imports from ``temporalio`` or ``bene/temporal/`` are permitted here.
"""

from bene.runtime.core import (
    BusinessIdempotencyKey,
    ChatMessage,
    CostEstimate,
    LLMCommand,
    LLMResult,
    ReconciliationStrategy,
    SideEffectKind,
    SideEffectLabel,
    TokenUsage,
    ToolCall,
)
from bene.runtime.exceptions import (
    ActorAlreadyRunningError,
    ActorCompletedError,
    ActorNotFoundError,
    QueryNotReadyError,
    SideEffectFailedError,
    BeneRuntimeError,
)
from bene.runtime.handle import RunHandle, Runtime, TypedQuery

__all__ = [
    "ActorAlreadyRunningError",
    "ActorCompletedError",
    "ActorNotFoundError",
    "BusinessIdempotencyKey",
    "ChatMessage",
    "CostEstimate",
    "LLMCommand",
    "LLMResult",
    "QueryNotReadyError",
    "ReconciliationStrategy",
    "RunHandle",
    "Runtime",
    "SideEffectFailedError",
    "SideEffectKind",
    "SideEffectLabel",
    "TokenUsage",
    "ToolCall",
    "BeneRuntimeError",
    "TypedQuery",
]
