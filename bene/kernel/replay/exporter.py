"""Build :class:`ReplayEnvelope` artifacts from recorded ``experiment_runs``."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519

from bene.kernel.engrams import EngramStore
from bene.kernel.replay.keys import public_key_b64, sign
from bene.kernel.replay.manifest import (
    ENVELOPE_VERSION,
    TEXT_NORM_VERSION,
    ReplayEnvelope,
    ReplaySource,
)
from bene.kernel.schema_v2 import KERNEL_SCHEMA_VERSION


class UnknownRun(KeyError):
    """Raised when a run_id is absent from experiment_runs."""


def _manifest_source_ids(manifest: dict[str, Any]) -> list[str]:
    """Ordered, de-duplicated source engram ids across every batch."""
    seen: list[str] = []
    for batch in manifest.get("batches", []):
        for sid in batch.get("source_ids", []):
            if sid not in seen:
                seen.append(sid)
    return seen


class ReplayExporter:
    """Read-only projection of experiment_runs into a portable envelope."""

    def __init__(self, store: EngramStore) -> None:
        self.store = store

    def list_runs(self, *, kind: str = "consolidation", limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            "SELECT run_id, kind, summary, created_at FROM experiment_runs"
            " WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
            (kind, limit),
        ).fetchall()
        return [{"run_id": r[0], "kind": r[1], "summary": r[2], "created_at": r[3]} for r in rows]

    def export(
        self,
        run_id: str,
        *,
        sign_key: ed25519.Ed25519PrivateKey | None = None,
    ) -> ReplayEnvelope:
        row = self.store.conn.execute(
            "SELECT run_id, kind, metrics, created_at, probe_id, verdict_engram"
            " FROM experiment_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise UnknownRun(run_id)
        kind = row[1]
        if kind == "consolidation":
            env = self._export_consolidation(run_id, row)
        elif kind == "probe":
            env = self._export_probe(run_id, row)
        else:
            raise ValueError(f"replay exports kind in {{'consolidation','probe'}}, got {kind!r}")
        if sign_key is not None:
            env = replace(
                env,
                signature=sign(sign_key, env.signed_bytes()),
                public_key=public_key_b64(sign_key),
            )
        return env

    def _envelope(
        self,
        run_id: str,
        kind: str,
        manifest: dict[str, Any],
        sources: tuple[ReplaySource, ...],
        created_at: str,
    ) -> ReplayEnvelope:
        return ReplayEnvelope(
            version=ENVELOPE_VERSION,
            run_id=run_id,
            kind=kind,
            manifest=manifest,
            sources=sources,
            source_payload_hashes={s.engram_id: s.content_sha256() for s in sources},
            bene_version=_bene_version(),
            schema_version=KERNEL_SCHEMA_VERSION,
            text_norm_version=TEXT_NORM_VERSION,
            created_at=created_at,
        )

    def _export_consolidation(self, run_id: str, row: Any) -> ReplayEnvelope:
        manifest = json.loads(row[2])
        # Recorded metrics == replay_manifest() + non-deterministic
        # created_engram_ids (ULIDs); strip the latter so the envelope manifest
        # is purely the source-derived deterministic plan the verifier re-derives.
        manifest.pop("created_engram_ids", None)
        source_ids = _manifest_source_ids(manifest)
        sources = tuple(self._source(eid) for eid in source_ids)
        return self._envelope(run_id, "consolidation", manifest, sources, row[3])

    def _export_probe(self, run_id: str, row: Any) -> ReplayEnvelope:
        """A probe run's envelope: the verdict engram is the source; the locked
        gate spec + lock_sha256 (from probe_registry) ride in the manifest. The
        verifier re-hashes the spec and re-derives the verdict from the recorded
        gate values — the probe analog of re-running the consolidation planner."""
        probe_id, verdict_engram = row[4], row[5]
        if not verdict_engram:
            raise UnknownRun(f"{run_id}: probe run has no verdict_engram")
        preg = self.store.conn.execute(
            "SELECT name, gate_spec, lock_sha256, status FROM probe_registry WHERE probe_id = ?",
            (probe_id,),
        ).fetchone()
        if preg is None:
            raise UnknownRun(f"{run_id}: probe_id {probe_id!r} not in probe_registry")
        name, gate_spec, lock_sha256, registry_status = preg
        verdict_src = self._source(verdict_engram)
        recorded = json.loads(verdict_src.payload)
        manifest = {
            "kind": "probe",
            "probe_id": probe_id,
            "probe_name": name,
            "gate_spec": gate_spec,
            "lock_sha256": lock_sha256,
            "registry_status": registry_status,
            "verdict_engram": verdict_engram,
            "status": recorded.get("status"),
        }
        return self._envelope(run_id, "probe", manifest, (verdict_src,), row[3])

    def _source(self, engram_id: str) -> ReplaySource:
        e = self.store.get(engram_id)
        payload = self.store.payload(engram_id).decode(errors="replace")
        return ReplaySource(
            engram_id=e.engram_id,
            kind=e.kind,
            tier=e.tier,
            title=e.title,
            agent_id=e.agent_id,
            created_at=e.created_at,
            metadata=e.metadata,
            provenance=e.provenance,
            payload=payload,
        )


def _bene_version() -> str:
    import bene

    return bene.__version__
