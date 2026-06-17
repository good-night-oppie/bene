"""Tests for bene.runtime.handle (RunHandle, TypedQuery) and LocalRuntime.

Run: uv run python -m pytest tests/test_runtime_handle.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bene.runtime.core import CostEstimate, SideEffectKind, SideEffectLabel
from bene.runtime.handle import RunHandle, TypedQuery
from bene.runtime.local import LocalRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SimpleSpec:
    """Minimal spec with run_id and workflow_id for LocalRuntime tests."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.workflow_id = run_id


def _label() -> SideEffectLabel:
    return SideEffectLabel(
        kind=SideEffectKind.EXTERNAL_WRITE,
        semantic_class="test_effect",
        rate_limit_class="test:default",
        cost_estimate=CostEstimate(latency_ms=10, dollars=0.0),
    )


# ---------------------------------------------------------------------------
# 7. test_local_submit_and_await
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_submit_and_await() -> None:
    """submit() returns a RunHandle; await_result() resolves without error."""
    rt = LocalRuntime()
    spec = _SimpleSpec("run-submit-1")
    handle = await rt.submit(spec)

    assert isinstance(handle, RunHandle)
    assert handle.run_id == "run-submit-1"

    result = await rt.await_result(handle)
    assert result is None  # spec has no run() fn → result is None


# ---------------------------------------------------------------------------
# 8. test_local_start_or_signal_cold_start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_start_or_signal_cold_start() -> None:
    """start_or_signal with unknown workflow_id → creates new handle + signals it."""
    rt = LocalRuntime()
    spec = _SimpleSpec("run-cos-1")

    handle = await rt.start_or_signal(spec, signal_name="event", payload={"x": 1})

    assert isinstance(handle, RunHandle)
    assert handle.workflow_id == "run-cos-1"

    entry = rt._actors["run-cos-1"]
    assert len(entry.signals) == 1
    assert entry.signals[0] == ("event", {"x": 1})


# ---------------------------------------------------------------------------
# 9. test_local_start_or_signal_warm_hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_start_or_signal_warm_hit() -> None:
    """start_or_signal with existing workflow_id → signals existing, same handle."""
    rt = LocalRuntime()
    spec = _SimpleSpec("run-warm-1")

    handle1 = await rt.start_or_signal(spec, signal_name="event", payload={"n": 1})
    handle2 = await rt.start_or_signal(spec, signal_name="event", payload={"n": 2})

    assert handle1.run_id == handle2.run_id

    entry = rt._actors["run-warm-1"]
    assert len(entry.signals) == 2
    assert entry.signals[0][1] == {"n": 1}
    assert entry.signals[1][1] == {"n": 2}


# ---------------------------------------------------------------------------
# 10. test_local_query_typed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_query_typed() -> None:
    """query() returns the registered value for a TypedQuery descriptor."""
    rt = LocalRuntime()
    spec = _SimpleSpec("run-query-1")
    handle = await rt.submit(spec)

    seed_q: TypedQuery[str | None] = TypedQuery("seed_ticket", type(None))
    rt.register_query_result("run-query-1", "seed_ticket", "OFS-123")

    result = await rt.query(handle, seed_q)
    assert result == "OFS-123"


# ---------------------------------------------------------------------------
# 11. test_local_submit_side_effect_first_call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_submit_side_effect_first_call() -> None:
    """First submit_side_effect call invokes execute_fn and marks ledger DONE."""
    rt = LocalRuntime()
    key = ("post_advisory", "bucket-1", "OFS-999")

    execute_fn = AsyncMock(return_value={"comment_id": "777"})
    result = await rt.submit_side_effect(
        label=_label(),
        business_key=key,
        execute_fn=execute_fn,
    )

    assert result == {"comment_id": "777"}
    execute_fn.assert_awaited_once()
    assert rt.ledger_state(key) == "done"


# ---------------------------------------------------------------------------
# 12. test_local_submit_side_effect_idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_submit_side_effect_idempotent() -> None:
    """Second call with same business_key returns cached result; execute_fn not called again."""
    rt = LocalRuntime()
    key = ("post_advisory", "bucket-1", "OFS-999")

    execute_fn = AsyncMock(return_value={"comment_id": "888"})

    result1 = await rt.submit_side_effect(_label(), key, execute_fn)
    result2 = await rt.submit_side_effect(_label(), key, execute_fn)

    assert result1 == result2 == {"comment_id": "888"}
    execute_fn.assert_awaited_once()  # NOT called twice
    assert rt.ledger_state(key) == "done"


# ---------------------------------------------------------------------------
# 13. test_local_submit_side_effect_different_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_submit_side_effect_different_key() -> None:
    """Different business_key → execute_fn called for each distinct key."""
    rt = LocalRuntime()
    key_a = ("post_advisory", "bucket-A", "OFS-111")
    key_b = ("post_advisory", "bucket-B", "OFS-222")

    call_count = 0

    async def fn_a() -> dict[str, str]:
        nonlocal call_count
        call_count += 1
        return {"key": "A"}

    async def fn_b() -> dict[str, str]:
        nonlocal call_count
        call_count += 1
        return {"key": "B"}

    r_a = await rt.submit_side_effect(_label(), key_a, fn_a)
    r_b = await rt.submit_side_effect(_label(), key_b, fn_b)

    assert r_a == {"key": "A"}
    assert r_b == {"key": "B"}
    assert call_count == 2
    assert rt.ledger_state(key_a) == "done"
    assert rt.ledger_state(key_b) == "done"
