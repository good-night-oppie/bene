"""Falsifiable-eval layer — probes, hash-locked gates, verdicts (D3/D6)."""

from bene.kernel.eval.gates import Gate, canonical_spec, evaluate_gate, lock_hash, validate_gates
from bene.kernel.eval.heldout import (
    HeldoutGate,
    HeldoutManifest,
    build_heldout_probe,
    disjoint,
)
from bene.kernel.eval.probe import (
    LockTamperError,
    Probe,
    ProbeInadmissible,
    ProbeNotRegistered,
)
from bene.kernel.eval.verdict import ACCEPT, REJECT, VOID, Verdict, persist_verdict

__all__ = [
    "ACCEPT",
    "REJECT",
    "VOID",
    "Gate",
    "HeldoutGate",
    "HeldoutManifest",
    "LockTamperError",
    "Probe",
    "ProbeInadmissible",
    "ProbeNotRegistered",
    "Verdict",
    "build_heldout_probe",
    "canonical_spec",
    "disjoint",
    "evaluate_gate",
    "lock_hash",
    "persist_verdict",
    "validate_gates",
]
