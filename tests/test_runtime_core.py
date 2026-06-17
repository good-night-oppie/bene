"""Tests for bene.runtime.core frozen DTOs.

Run: uv run python -m pytest tests/test_runtime_core.py -v
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from bene.runtime.core import (
    BusinessIdempotencyKey,
    ChatMessage,
    CostEstimate,
    LLMCommand,
    ReconciliationStrategy,
    SideEffectKind,
    SideEffectLabel,
    TokenUsage,
    ToolCall,
)


# ---------------------------------------------------------------------------
# 1. test_llm_command_frozen
# ---------------------------------------------------------------------------


def test_llm_command_frozen() -> None:
    """LLMCommand must be immutable after construction."""
    cmd = LLMCommand(
        run_id="run-1",
        agent_id="agent-1",
        step=0,
        model="claude-sonnet",
        messages=[ChatMessage(role="user", content="hello")],
    )
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        cmd.step = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. test_llm_command_json_roundtrip
# ---------------------------------------------------------------------------


def test_llm_command_json_roundtrip() -> None:
    """LLMCommand fields must survive JSON serialization/deserialization."""
    tool = ToolCall(id="t1", name="search", input={"q": "ray"})
    msg = ChatMessage(role="user", content="query", tool_calls=[tool])
    cmd = LLMCommand(
        run_id="run-2",
        agent_id="agent-2",
        step=3,
        model="claude-sonnet",
        messages=[msg],
        idempotency_key=("run-2", "step:3", "llm"),
    )

    serialized = json.dumps(dataclasses.asdict(cmd))
    data = json.loads(serialized)

    assert data["run_id"] == "run-2"
    assert data["step"] == 3
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["tool_calls"][0]["name"] == "search"
    assert data["idempotency_key"] == ["run-2", "step:3", "llm"]


# ---------------------------------------------------------------------------
# 3. test_business_idempotency_key_deterministic
# ---------------------------------------------------------------------------


def test_business_idempotency_key_deterministic() -> None:
    """Same tuple must always produce the same hash."""
    key_a = BusinessIdempotencyKey(parts=("post_advisory", "bucket-1", "OFS-999"))
    key_b = BusinessIdempotencyKey(parts=("post_advisory", "bucket-1", "OFS-999"))
    assert key_a.serialize() == key_b.serialize()
    assert len(key_a.serialize()) == 32

    # Different tuple → different hash
    key_c = BusinessIdempotencyKey(parts=("post_advisory", "bucket-2", "OFS-999"))
    assert key_a.serialize() != key_c.serialize()


# ---------------------------------------------------------------------------
# 4. test_business_idempotency_key_order_matters
# ---------------------------------------------------------------------------


def test_business_idempotency_key_order_matters() -> None:
    """Tuple order must affect the resulting hash."""
    key_ab = BusinessIdempotencyKey(parts=("a", "b"))
    key_ba = BusinessIdempotencyKey(parts=("b", "a"))
    assert key_ab.serialize() != key_ba.serialize()


# ---------------------------------------------------------------------------
# 5. test_side_effect_label_defaults
# ---------------------------------------------------------------------------


def test_side_effect_label_defaults() -> None:
    """cost_estimate must default to zero; reconciliation_strategy to None."""
    label = SideEffectLabel(
        kind=SideEffectKind.EXTERNAL_WRITE,
        semantic_class="burst_advisory",
        rate_limit_class="jira:project:default",
    )
    assert label.cost_estimate.latency_ms == 0
    assert label.cost_estimate.dollars == 0.0
    assert label.reconciliation_strategy is None
    assert label.sentinel_template is None


def test_side_effect_label_with_strategy() -> None:
    """reconciliation_strategy and sentinel_template can be set."""
    label = SideEffectLabel(
        kind=SideEffectKind.EXTERNAL_WRITE,
        semantic_class="burst_advisory",
        rate_limit_class="jira:project:default",
        cost_estimate=CostEstimate(latency_ms=200, dollars=0.01),
        reconciliation_strategy=ReconciliationStrategy.READBACK_SENTINEL,
        sentinel_template="<!-- triage-advisory:{testrun_id} -->",
    )
    assert label.reconciliation_strategy == ReconciliationStrategy.READBACK_SENTINEL
    assert label.sentinel_template is not None


# ---------------------------------------------------------------------------
# 6. test_token_usage_total
# ---------------------------------------------------------------------------


def test_token_usage_total() -> None:
    """TokenUsage must accept an explicit total_tokens or allow separate in/out."""
    usage = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.total_tokens == 150
    assert usage.turns == 1

    usage2 = TokenUsage(input_tokens=200, output_tokens=80, total_tokens=200, turns=3)
    assert usage2.turns == 3
