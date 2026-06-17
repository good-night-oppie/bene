"""BENE 2.0 kernel — everything is an engram.

One typed, append-only, provenance-linked substrate (engrams) with a
compression ladder (raw trace → episodic → semantic → procedural → strategic),
an event bus, and a capability registry gated by the autonomy ladder.

Design: docs/design/BENE2-DESIGN.md · Contract: docs/design/KERNEL-SPEC.md.
"""

from bene.kernel.bus import EventBus
from bene.kernel.capabilities import (
    AutonomyDenied,
    Capability,
    CapabilityRegistry,
    UnknownCapability,
)
from bene.kernel.engrams import (
    ENGRAM_KINDS,
    LINK_TYPES,
    TIER_KINDS,
    Engram,
    EngramStore,
    ProvenanceRequired,
    TierViolation,
    UnknownEngram,
)
from bene.kernel.replay import (
    ReplayEnvelope,
    ReplayExporter,
    ReplayResult,
    ReplayVerifier,
)
from bene.kernel.schema_v2 import KERNEL_SCHEMA_VERSION, ensure_v2

__all__ = [
    "ENGRAM_KINDS",
    "KERNEL_SCHEMA_VERSION",
    "LINK_TYPES",
    "TIER_KINDS",
    "AutonomyDenied",
    "Capability",
    "CapabilityRegistry",
    "Engram",
    "EngramStore",
    "EventBus",
    "ProvenanceRequired",
    "ReplayEnvelope",
    "ReplayExporter",
    "ReplayResult",
    "ReplayVerifier",
    "TierViolation",
    "UnknownCapability",
    "UnknownEngram",
    "ensure_v2",
]
