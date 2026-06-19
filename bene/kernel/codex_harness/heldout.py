"""Held-out anti-overfit gate (防偷懒) for codex-harness evolution — SECH bene-core.

The kill-gate proves an evolved harness *beats the seed*; the held-out gate proves it
did so on data it **never trained on**. bene owns the manifest hash-lock + the
disjointness proof + the A/R/V verdict (the SPEC + the autogenesis-harness-evo contract
both assign this to bene-core); adx executes the held-out battles, bene scores + gates.

Contract:
1. The held-out manifest is a content-addressed **frozen tuple set**
   ``{(task_id, seed, scenario_id)}``, sha256 set-hash, registered + hash-locked BEFORE
   the run sees it. The candidate is never scored on these during search.
2. The candidate carries a ``training_manifest`` = the set-hash of every tuple it tuned
   on across its CRN windows. Admissibility verifies ``heldout ∩ training = ∅`` over the
   per-tuple hashes **before** the win-rate gate; overlap ⇒ **VOID** (inadmissible eval,
   distinct from REJECT).
3. On ACCEPT the promotion stamps all three hashes (``probe_lock``, ``heldout_manifest``,
   ``training_manifest``) → promotion is post-hoc provable as "scored on data it never
   trained on" — non-gameable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

# A held-out / training tuple: (task_id, seed, scenario_id). Kept as a plain tuple of
# JSON scalars so the manifest round-trips through the bene<->adx JSON wire.
HeldoutTuple = tuple[str, int, str]


def _tuple_hash(t: HeldoutTuple) -> str:
    return hashlib.sha256(json.dumps(list(t), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class HeldoutManifest:
    """A content-addressed, frozen, hash-locked set of evaluation tuples."""

    tuples: tuple[HeldoutTuple, ...]

    @classmethod
    def from_tuples(cls, tuples) -> "HeldoutManifest":
        # Dedupe + sort so the manifest hash is canonical regardless of input order.
        uniq = sorted({(str(a), int(b), str(c)) for (a, b, c) in tuples})
        return cls(tuples=tuple(uniq))

    def tuple_hashes(self) -> frozenset[str]:
        return frozenset(_tuple_hash(t) for t in self.tuples)

    def manifest_hash(self) -> str:
        """sha256 over the canonical sorted per-tuple hashes — the lock subject."""
        joined = ",".join(sorted(self.tuple_hashes()))
        return hashlib.sha256(joined.encode()).hexdigest()

    def __len__(self) -> int:
        return len(self.tuples)

    def to_dict(self) -> dict:
        return {"tuples": [list(t) for t in self.tuples], "manifest_hash": self.manifest_hash()}


def is_disjoint(heldout: HeldoutManifest, training: HeldoutManifest) -> bool:
    """True iff no held-out tuple was trained on (the admissibility predicate)."""
    return heldout.tuple_hashes().isdisjoint(training.tuple_hashes())


def overlap(heldout: HeldoutManifest, training: HeldoutManifest) -> frozenset[str]:
    """The per-tuple hashes present in BOTH sets (empty iff admissible)."""
    return heldout.tuple_hashes() & training.tuple_hashes()
