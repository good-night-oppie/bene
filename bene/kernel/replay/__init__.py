"""Signed deterministic replay — re-derive recorded runs from source engrams.

A read-only projection of ``experiment_runs`` (a sibling kernel submodule, not
nested under the engram ladder): export a recorded run into a self-contained,
optionally ed25519-signed ``.bene-replay`` envelope, hand it to a third party,
and they re-run it in a sandbox to prove the engrams were derived — not
fabricated — from the cited sources. v1 covers ``kind="consolidation"``.
"""

from __future__ import annotations

from bene.kernel.replay import keys
from bene.kernel.replay.exporter import ReplayExporter, UnknownRun
from bene.kernel.replay.manifest import (
    ENVELOPE_VERSION,
    TEXT_NORM_VERSION,
    ReplayEnvelope,
    ReplayResult,
    ReplaySource,
    canonical_json,
)
from bene.kernel.replay.verifier import ReplayVerifier

__all__ = [
    "ENVELOPE_VERSION",
    "TEXT_NORM_VERSION",
    "ReplayEnvelope",
    "ReplayExporter",
    "ReplayResult",
    "ReplaySource",
    "ReplayVerifier",
    "UnknownRun",
    "canonical_json",
    "keys",
]
