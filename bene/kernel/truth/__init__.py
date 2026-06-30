"""BENE truth-maintenance layer — a deterministic Belief/Fact contract.

BENE engrams remember *what happened*. BENE **facts** structure *what was
observed or claimed*. BENE **beliefs** are the *current accepted state*. BENE
**decisions** explain *why* the accepted state changed. BENE **admissibility**
flags decide whether a belief may be used for **context**, **promotion**, or
**action**.

This is NOT RAG, NOT vector memory, and NOT a full expert system. It is a small,
boring, auditable, single-node truth-maintenance layer for agent runs: facts are
persisted, a deterministic reducer reconciles them into beliefs, and every
lifecycle transition is explainable from a stored decision row. No LLM call, no
network, no graph/vector DB, no CLIPS, no background daemon.

North star: BENE must never let future agents evolve from unsafe memories.
"""

from __future__ import annotations

from bene.kernel.truth.contract import (
    BELIEF_LIFECYCLES,
    CONFLICT_DIFFERENT_VALUE,
    CONFLICT_STALE_VALUE,
    CONFLICT_UNRELIABLE,
    FACT_KINDS,
    NON_PROMOTABLE_LIFECYCLES,
    UNRELIABLE_SOURCE_TYPES,
    Belief,
    Conflict,
    Decision,
    Fact,
    InvalidFact,
    decode_value,
    encode_value,
    validate_fact,
    value_hash,
)
from bene.kernel.truth.schema import (
    TRUTH_SCHEMA_VERSION,
    ensure_truth,
)
from bene.kernel.truth.reducer import quarantine_belief, reconcile_beliefs
from bene.kernel.truth.store import TruthStore


def emit_fact(conn, **kwargs) -> str:
    """Persist one fact. Convenience wrapper over :meth:`TruthStore.emit_fact`."""
    return TruthStore(conn).emit_fact(**kwargs)


def get_fact(conn, fact_id: str) -> dict | None:
    return TruthStore(conn).get_fact(fact_id)


def list_facts(conn, **kwargs) -> list[dict]:
    return TruthStore(conn).list_facts(**kwargs)


def list_beliefs(conn, **kwargs) -> list[dict]:
    return TruthStore(conn).list_beliefs(**kwargs)


def list_active_beliefs(conn, **kwargs) -> list[dict]:
    return TruthStore(conn).list_active_beliefs(**kwargs)


def explain_belief(conn, belief_id: str) -> dict | None:
    return TruthStore(conn).explain_belief(belief_id)


__all__ = [
    "BELIEF_LIFECYCLES",
    "CONFLICT_DIFFERENT_VALUE",
    "CONFLICT_STALE_VALUE",
    "CONFLICT_UNRELIABLE",
    "FACT_KINDS",
    "NON_PROMOTABLE_LIFECYCLES",
    "TRUTH_SCHEMA_VERSION",
    "UNRELIABLE_SOURCE_TYPES",
    "Belief",
    "Conflict",
    "Decision",
    "Fact",
    "InvalidFact",
    "TruthStore",
    "decode_value",
    "emit_fact",
    "encode_value",
    "ensure_truth",
    "explain_belief",
    "get_fact",
    "list_active_beliefs",
    "list_beliefs",
    "list_facts",
    "quarantine_belief",
    "reconcile_beliefs",
    "validate_fact",
    "value_hash",
]
