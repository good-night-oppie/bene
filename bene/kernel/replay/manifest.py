"""Signed deterministic replay envelopes.

A :class:`ReplayEnvelope` is a self-contained, optionally ed25519-signed
artifact that lets a third party re-derive the engrams a recorded run produced
from the exact source granules — and tamper-detect the manifest — *without*
access to the original ``bene.db``. Covers ``kind="consolidation"`` (re-plan the
deterministic batcher) and ``kind="probe"`` (re-hash the locked gate spec +
re-derive the verdict from the recorded gate values). Evolution envelopes are a
follow-up on the same path.

This module is a read-only projection of ``experiment_runs`` + the engrams
they cite; it never mutates source rows (the provenance contract holds).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

ENVELOPE_VERSION = 1
# Bumped only if lifecycle._payload_text whitespace normalization changes;
# verify version-gates on it so old envelopes fail loudly rather than silently.
TEXT_NORM_VERSION = 1


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON encoding — the byte surface that is signed/hashed."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class ReplaySource:
    """One source engram, carrying everything needed to rehydrate it into a
    sandbox db and re-derive the consolidation deterministically."""

    engram_id: str
    kind: str
    tier: int
    title: str
    agent_id: str | None
    created_at: str
    metadata: dict[str, Any]
    provenance: dict[str, Any]
    payload: str  # decoded text payload of the source engram

    def content_sha256(self) -> str:
        return sha256_text(self.payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engram_id": self.engram_id,
            "kind": self.kind,
            "tier": self.tier,
            "title": self.title,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "provenance": self.provenance,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReplaySource":
        return cls(
            engram_id=d["engram_id"],
            kind=d["kind"],
            tier=int(d["tier"]),
            title=d["title"],
            agent_id=d.get("agent_id"),
            created_at=d["created_at"],
            metadata=d.get("metadata") or {},
            provenance=d.get("provenance") or {"system": "bene.kernel.replay"},
            payload=d["payload"],
        )


@dataclass(frozen=True)
class ReplayEnvelope:
    """Self-contained, optionally ed25519-signed replay artifact."""

    version: int
    run_id: str
    kind: str
    manifest: dict[str, Any]  # deterministic replay_manifest (policy + batches)
    sources: tuple[ReplaySource, ...]
    source_payload_hashes: dict[str, str]  # engram_id -> sha256(payload)
    bene_version: str
    schema_version: int
    text_norm_version: int
    created_at: str
    signature: str | None = None  # base64(ed25519) over signed_bytes()
    public_key: str | None = None  # base64 raw public key

    def signed_payload(self) -> dict[str, Any]:
        """The exact dict that is canonical-encoded and signed/verified —
        every field except ``signature`` and ``public_key``."""
        return {
            "version": self.version,
            "run_id": self.run_id,
            "kind": self.kind,
            "manifest": self.manifest,
            "sources": [s.to_dict() for s in self.sources],
            "source_payload_hashes": self.source_payload_hashes,
            "bene_version": self.bene_version,
            "schema_version": self.schema_version,
            "text_norm_version": self.text_norm_version,
            "created_at": self.created_at,
        }

    def signed_bytes(self) -> bytes:
        return canonical_json(self.signed_payload()).encode()

    def digest(self) -> str:
        """sha256 of the canonical signed surface — the citable content id."""
        return hashlib.sha256(self.signed_bytes()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = self.signed_payload()
        d["signature"] = self.signature
        d["public_key"] = self.public_key
        return d

    def to_json(self) -> str:
        # Pretty on disk for human inspection; verify recomputes the canonical
        # form from the parsed fields, so on-disk whitespace is irrelevant.
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReplayEnvelope":
        return cls(
            version=int(d["version"]),
            run_id=d["run_id"],
            kind=d["kind"],
            manifest=d["manifest"],
            sources=tuple(ReplaySource.from_dict(s) for s in d.get("sources", [])),
            source_payload_hashes=d.get("source_payload_hashes") or {},
            bene_version=d["bene_version"],
            schema_version=int(d["schema_version"]),
            text_norm_version=int(d.get("text_norm_version", TEXT_NORM_VERSION)),
            created_at=d["created_at"],
            signature=d.get("signature"),
            public_key=d.get("public_key"),
        )

    @classmethod
    def from_json(cls, text: str) -> "ReplayEnvelope":
        return cls.from_dict(json.loads(text))

    def cite_as(self, *, style: str = "bibtex") -> str:
        """Render a citation referencing this replay artifact by content
        digest. ``style`` is ``bibtex`` (default) or ``json``."""
        short = self.run_id[:8]
        year = (self.created_at or "")[:4] or "2026"
        if style == "json":
            return canonical_json(
                {
                    "id": f"bene:{self.run_id}",
                    "kind": self.kind,
                    "digest": f"sha256:{self.digest()}",
                    "year": year,
                }
            )
        return (
            f"@misc{{bene:{self.run_id},\n"
            f"  title = {{BENE replay {self.kind} {short}}},\n"
            f"  note  = {{sha256:{self.digest()}}},\n"
            f"  year  = {{{year}}}\n"
            f"}}"
        )


@dataclass(frozen=True)
class ReplayResult:
    """Outcome of :meth:`ReplayVerifier.verify`."""

    ok: bool
    reasons: tuple[str, ...]  # empty iff ok
    replayed_manifest: dict[str, Any]
    cite_as: str
    signature_state: str  # "valid" | "invalid" | "absent" | "untrusted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reasons": list(self.reasons),
            "replayed_manifest": self.replayed_manifest,
            "cite_as": self.cite_as,
            "signature": self.signature_state,
        }
