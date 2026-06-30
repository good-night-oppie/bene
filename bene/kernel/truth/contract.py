"""Belief/Fact contract — the typed vocabulary of BENE's truth-maintenance layer.

BENE distinguishes five things and never conflates them:

- **Engrams** remember *what happened* (raw, permanent — the existing substrate).
- **Facts** structure *what was observed or claimed* (this module's ``belief_facts``).
- **Beliefs** are BENE's *current accepted state* (``beliefs``).
- **Decisions** explain *why* a belief changed lifecycle (``belief_decisions``).
- **Admissibility** flags decide whether a belief is safe for **context**,
  **promotion**, or **action** (columns on ``beliefs`` + the deciding row).

A *Claim* is just a fact whose ``kind == 'claim'`` — an asserted value with no
observation backing it. A claim does NOT become a belief on its own; only the
deterministic reducer (``bene.kernel.truth.reducer``) promotes facts to beliefs
through the reconciliation rules. The stable reconciliation key is
``(subject, relation, scope)``; ``value`` (+ canonical ``value_hash``) is what
can change for a key over time.

This module is pure data + validation. It performs no I/O, makes no LLM call,
opens no socket. Value equality is canonical (``1 == 1.0``, NFC == NFD) via
``bene.kernel.genome_canonical`` so the reducer's "same value" test (Rule 3) is
robust, not a naive string compare.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from bene.kernel.genome_canonical import NonCanonicalizableGenome, genome_hash

# ---- fact kinds ----------------------------------------------------------
FACT_KINDS: frozenset[str] = frozenset(
    {"observation", "claim", "state", "hypothesis", "decision", "policy"}
)

# ---- belief lifecycle states --------------------------------------------
# ``candidate`` is part of the spec'd vocabulary but RESERVED in the MVP: the
# reducer mints ``active`` for clean facts and ``quarantined`` for unsafe ones
# directly. It is kept here (and as non-promotable) for a future staged-promotion
# workflow so the enum/schema need not change later. ``expired``/``rejected`` are
# likewise valid terminal states a caller or future rule may set.
BELIEF_LIFECYCLES: frozenset[str] = frozenset(
    {"candidate", "active", "superseded", "quarantined", "expired", "rejected"}
)

# Lifecycles that may NEVER be admissible for promotion (Rule 6). ``candidate``
# is also non-promotable: only a clean ``active`` belief can be promoted from.
NON_PROMOTABLE_LIFECYCLES: frozenset[str] = frozenset(
    {"candidate", "superseded", "quarantined", "expired", "rejected"}
)

# ---- reliability policy (Rule 4) ----------------------------------------
# A fact from one of these source_types — or a fact with ``unsafe=1`` — must
# create/move into ``quarantined``, never ``active``. Unknown source_types
# default to reliable so future consumers work without editing core.
UNRELIABLE_SOURCE_TYPES: frozenset[str] = frozenset({"failed", "unreliable", "untrusted", "error"})

# ---- decision rule names (audit vocabulary) ------------------------------
RULE_CREATE = "rule_1_create"
RULE_SUPERSEDE = "rule_2_supersede"
RULE_STALE_IGNORED = "rule_2_stale_ignored"
RULE_REFRESH = "rule_3_refresh"
RULE_QUARANTINE = "rule_4_quarantine"
RULE_EXPIRED = "rule_5_expired"
RULE_MANUAL_QUARANTINE = "rule_10_manual_quarantine"

# ---- conflict kinds ------------------------------------------------------
CONFLICT_DIFFERENT_VALUE = "same_key_different_value"
CONFLICT_STALE_VALUE = "stale_value"
CONFLICT_UNRELIABLE = "unreliable_source"


class InvalidFact(ValueError):
    """A fact violates the contract (unknown kind, missing key field, etc.)."""


def value_hash(value: Any) -> str:
    """Canonical content hash of a fact/belief value.

    Logically-equal values hash identically (``1 == 1.0 == 1.00``; NFC == NFD;
    CRLF == LF) while ``1`` (number) and ``"1"`` (string) stay distinct — reused
    from :mod:`bene.kernel.genome_canonical`. A value with no canonical form
    (an exotic type) falls back to a stable hash of its JSON repr so emit never
    crashes; such values simply do not get the int/float folding.
    """
    try:
        return genome_hash({"value": value})
    except NonCanonicalizableGenome:
        blob = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def encode_value(value: Any) -> str:
    """Storage form of a fact/belief value (a TEXT column).

    Always JSON so ANY value type round-trips losslessly via :func:`decode_value`:
    ``42`` ⇄ ``"42"`` (int), ``"42"`` ⇄ ``'"42"'`` (str — stays a str), ``True`` ⇄
    ``"true"``, ``[1, 2]`` ⇄ ``"[1,2]"``. The canonical identity for reconciliation
    still lives in ``value_hash`` — equality is decided there, not on this text.
    """
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def decode_value(text: str | None) -> Any:
    """Inverse of :func:`encode_value` for reads. Falls back to the raw text if it
    is not valid JSON (e.g. a row written directly via SQL rather than ``emit_fact``)."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def validate_fact(
    *,
    kind: str,
    subject: str,
    relation: str,
    confidence: Any = 1.0,
    derived_from: Any = None,
    metadata: Any = None,
) -> None:
    """Raise :class:`InvalidFact` if any reconciliation-critical field is malformed.

    Guards against silent corruption: a string ``derived_from`` would be exploded
    into characters by ``list()``, and a non-dict ``metadata`` / non-numeric
    ``confidence`` would be stored as the wrong shape. Fail loud at the boundary.
    """
    if kind not in FACT_KINDS:
        raise InvalidFact(f"unknown fact kind {kind!r}; expected one of {sorted(FACT_KINDS)}")
    if not isinstance(subject, str) or not subject:
        raise InvalidFact("fact.subject must be a non-empty string")
    if not isinstance(relation, str) or not relation:
        raise InvalidFact("fact.relation must be a non-empty string")
    if derived_from is not None and not isinstance(derived_from, (list, tuple)):
        raise InvalidFact("fact.derived_from must be a list/tuple of ids (or None)")
    if derived_from is not None and not all(isinstance(x, str) for x in derived_from):
        raise InvalidFact("fact.derived_from entries must all be strings")
    if metadata is not None and not isinstance(metadata, dict):
        raise InvalidFact("fact.metadata must be a dict (or None)")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise InvalidFact("fact.confidence must be a number")


# ---- typed views (the contract surface) ----------------------------------
# Stores return plain dicts (JSON-friendly for the CLI); these dataclasses are
# the documented, typed view for callers that want one. ``from_row`` builds one
# from a sqlite row-dict.


@dataclass(frozen=True)
class Fact:
    fact_id: str
    kind: str
    subject: str
    relation: str
    value: str
    value_hash: str
    scope: str = "global"
    source: str | None = None
    source_type: str | None = None
    confidence: float = 1.0
    observed_at: str | None = None
    expires_at: str | None = None
    run_id: str | None = None
    agent_id: str | None = None
    trace_id: str | None = None
    evidence_uri: str | None = None
    derived_from: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    unsafe: int = 0
    reconciled_at: str | None = None
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> Fact:
        return cls(**{k: row[k] for k in row if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Belief:
    belief_id: str
    subject: str
    relation: str
    value: str
    value_hash: str
    scope: str
    lifecycle: str
    confidence: float = 1.0
    active_from: str | None = None
    active_until: str | None = None
    derived_from: list = field(default_factory=list)
    last_decision_id: str | None = None
    admissible_for_context: int = 0
    admissible_for_promotion: int = 0
    admissible_for_action: int = 0
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> Belief:
        return cls(**{k: row[k] for k in row if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Decision:
    decision_id: str
    belief_id: str | None
    rule: str
    from_lifecycle: str | None
    to_lifecycle: str | None
    reason: str = ""
    fact_id: str | None = None
    admissible_for_context: int = 0
    admissible_for_promotion: int = 0
    admissible_for_action: int = 0
    metadata: dict = field(default_factory=dict)
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> Decision:
        return cls(**{k: row[k] for k in row if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Conflict:
    conflict_id: str
    subject: str
    relation: str
    scope: str
    belief_id: str | None
    fact_id: str | None
    kind: str
    resolution: str = "pending"
    decision_id: str | None = None
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> Conflict:
        return cls(**{k: row[k] for k in row if k in cls.__dataclass_fields__})
