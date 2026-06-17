"""Kernel adapters — legacy stores flow into the engram substrate (D10).

Adapters, NOT rewrites: legacy public APIs stay byte-identical. When a kernel
is attached, legacy writes ALSO emit engrams (mirror), and the shared log
gains an optional trust-weighted tally. Detach (or never attach) and legacy
behavior is exactly 0.1.0 — proven by back-compat tests.

Pattern: bound-method wrapping on *instances* (composition); legacy classes
are never modified. Write-for-deletion: when a subsystem goes native, its
adapter is deleted, not deprecated.

Mirror durability contract (batched mirrors, Round 3)
-----------------------------------------------------
Mirror engrams are appended with ``deferred=True``: rows are buffered in
process memory and drained in batches (``executemany``) instead of executing
two INSERTs inside every legacy write. This takes the mirror off the legacy
hot path; what it changes, stated plainly:

1. **Crash window widens.** Previously an unflushed mirror row sat in
   SQLite's open transaction; buffered rows exist only in Python memory. A
   crash after the legacy store's own commit but before a flush loses up to
   ``DEFER_BUFFER_CAP`` mirror engrams while the legacy rows survive —
   bounded legacy/engram divergence (the mirror is already best-effort).
2. **Read-your-writes is preserved only through EngramStore's API.** Every
   ``EngramStore`` read (``get``/``search``/``payload``/``lineage``) flushes
   the buffer first. Direct SQL against the ``engrams`` table does NOT see
   buffered rows until a flush.
3. **Cross-connection visibility is delayed** until flush + caller commit
   (Round 2: caller commit only).
4. **Nothing is lost on clean close.** ``attach_kernel`` wraps
   ``Bene.close()`` to drain the buffer before the close-time commit, and
   ``KernelHandle.flush()`` drains it on demand.

Flush triggers: buffer reaches ``DEFER_BUFFER_CAP``; any EngramStore read;
explicit ``KernelHandle.flush()`` / ``EngramStore.flush()``; ``Bene.close()``.
Non-mirror callers of ``EngramStore.append`` are unaffected: both
``commit=True`` and ``commit=False`` without ``deferred=True`` behave exactly
as before.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from bene.kernel.engrams import EngramStore
from bene.kernel.schema_v2 import ensure_v2
from bene.kernel.trust import TrustLedger

#: legacy memory types → engram tier (semantic facts vs raw observations)
_MEMORY_TIERS = {"observation": 0, "result": 1, "insight": 2, "error": 1, "skill": 3}
_MEMORY_KINDS = {0: "trace", 1: "episodic", 2: "semantic", 3: "procedural"}


@dataclass
class KernelHandle:
    store: EngramStore
    trust: TrustLedger
    mirrored: list[str]

    def flush(self, *, commit: bool = False) -> int:
        """Drain buffered mirror engrams into SQLite (batched executemany).

        Does not commit unless asked — flushed rows become durable at the
        caller's next commit (or at ``Bene.close()``). Returns the number of
        engrams flushed."""
        return self.store.flush(commit=commit)


def attach_kernel(
    bene: Any,
    *,
    memory: Any | None = None,
    skills: Any | None = None,
    shared_log: Any | None = None,
) -> KernelHandle:
    """Ensure v2 tables and mirror the given legacy stores into engrams.

    Pass the store instances you want mirrored; anything not passed keeps
    pure-legacy behavior (the detached state).
    """
    ensure_v2(bene.conn)
    store = EngramStore(bene.conn, bene.blobs)
    trust = TrustLedger(bene.conn, store)
    mirrored: list[str] = []

    if memory is not None:
        _mirror_memory(memory, store)
        mirrored.append("memory")
    if skills is not None:
        _mirror_skills(skills, store)
        mirrored.append("skills")
    if shared_log is not None:
        _mirror_shared_log(shared_log, store)
        _add_weighted_tally(shared_log, trust)
        mirrored.append("shared_log")
    _hook_close(bene, store)
    return KernelHandle(store=store, trust=trust, mirrored=mirrored)


def _hook_close(bene: Any, store: EngramStore) -> None:
    """Wrap ``Bene.close()`` so the deferred mirror buffer is drained before
    the close-time commit — nothing is lost on a clean close.

    Same instance-level wrapping pattern as the mirrors; ``Bene.close()``
    itself already commits pending transaction work, so flushing first puts
    buffered rows into that final commit. Idempotent under repeated close
    (an empty buffer is a no-op)."""
    original = bene.close

    def close() -> None:
        if store.pending:
            try:
                store.flush()
            except sqlite3.ProgrammingError:
                # Connection already closed underneath us (e.g. direct
                # conn.close()): buffered rows are unrecoverable — this is
                # the documented crash window, not a clean close.
                pass
        original()

    bene.close = close


def _mirror_memory(memory_store: Any, store: EngramStore) -> None:
    original = memory_store.write

    def write(agent_id: str, content: str, type: str = "observation", **kwargs: Any) -> int:
        memory_id = original(agent_id, content, type, **kwargs)
        tier = _MEMORY_TIERS.get(type, 0)
        store.append(
            _MEMORY_KINDS[tier],
            f"memory:{type}:{kwargs.get('key') or memory_id}",
            content,
            tier=tier,
            provenance={"agent_id": agent_id},
            agent_id=agent_id,
            metadata={"mirror": "memory", "memory_id": memory_id, "type": type},
            commit=False,
            deferred=True,
        )
        return memory_id

    memory_store.write = write


def _mirror_skills(skill_store: Any, store: EngramStore) -> None:
    original = skill_store.save

    def save(name: str, description: str, template: str, **kwargs: Any) -> int:
        skill_id = original(name, description, template, **kwargs)
        agent = kwargs.get("source_agent_id")
        store.append(
            "procedural",
            f"skill:{name}",
            f"{description}\n\nTEMPLATE:\n{template}",
            tier=3,
            provenance={"agent_id": agent} if agent else {"system": "bene.kernel.adapters"},
            agent_id=agent,
            metadata={"mirror": "skills", "skill_id": skill_id},
            commit=False,
            deferred=True,
        )
        return skill_id

    skill_store.save = save


def _mirror_shared_log(log: Any, store: EngramStore) -> None:
    original = log._append

    def _append(type: str, agent_id: str, payload: Any, ref_id: Any = None) -> Any:
        entry = original(type, agent_id, payload, ref_id)
        if type in ("intent", "decision", "abort"):  # coordination-significant entries
            store.append(
                "proposal",
                f"shared_log:{type}:{entry.log_id}",
                str(payload),
                provenance={"agent_id": agent_id},
                agent_id=agent_id,
                metadata={"mirror": "shared_log", "log_id": entry.log_id, "entry_type": type},
                commit=False,
                deferred=True,
            )
        return entry

    log._append = _append


def _add_weighted_tally(log: Any, trust: TrustLedger) -> None:
    """Optional trust-weighted tally (GAP-AUDIT BENE-8: votes were unweighted).

    Adds ``log.weighted_tally(intent_id)`` -> dict with trust-weighted approve/
    reject mass alongside raw counts. The legacy ``tally`` is untouched."""

    def weighted_tally(intent_id: int) -> dict[str, Any]:
        if trust.store is not None and trust.store.pending:
            trust.store.flush()  # trust signals read engrams via direct SQL
        summary = log.tally(intent_id)
        approve_w = reject_w = 0.0
        for v in summary.votes:
            w = trust.weighted_vote(v.agent_id)
            if v.payload.get("approve"):
                approve_w += w
            else:
                reject_w += w
        return {
            "intent_id": intent_id,
            "approve": summary.approve,
            "reject": summary.reject,
            "approve_weighted": round(approve_w, 4),
            "reject_weighted": round(reject_w, 4),
            "passed_weighted": approve_w > reject_w,
        }

    log.weighted_tally = weighted_tally


# ---------------- metaharness ↔ evolve bridge ----------------


def genome_from_candidate(candidate: dict[str, Any]) -> "Genome":  # noqa: F821
    """Bridge a metaharness harness-candidate dict into an evolve Genome so
    mh_search results can enter the kill-gated breeding program (opt-in)."""
    from bene.kernel.evolve import Genome

    prompt = candidate.get("prompt", candidate.get("strategy", candidate.get("source_code", "")))
    components = {
        "memory_policy": str(candidate.get("memory_policy", "")),
        "retrieval_policy": str(candidate.get("retrieval_policy", "")),
        "context_strategy": str(candidate.get("context_strategy", "")),
        "tool_config": str(candidate.get("tool_config", "")),
        "prompt": str(prompt),
    }
    return Genome(components=components)
