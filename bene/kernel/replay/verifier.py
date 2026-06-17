"""Re-derive and tamper-check a :class:`ReplayEnvelope` in an isolated sandbox.

The verifier never touches the live db. It hydrates the carried sources into a
throwaway sqlite (``:memory:`` by default), re-runs the *deterministic* planner
with ``force=True``, and asserts the re-derived policy + batches are byte-equal
to the envelope manifest. The only non-deterministic manifest fields
(``due``/``reason``/``last_run_at`` — scheduler state, plus ULID
``created_engram_ids`` which the exporter already strips) are excluded from the
equality check; everything source-derived is compared exactly.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from bene.kernel.engrams import INLINE_LIMIT, EngramStore
from bene.kernel.eval.gates import OPS
from bene.kernel.eval.verdict import ACCEPT, REJECT
from bene.kernel.memory.lifecycle import ConsolidationPolicy, ScheduledConsolidator
from bene.kernel.replay.keys import verify_signature
from bene.kernel.replay.manifest import ReplayEnvelope, ReplayResult, ReplaySource, sha256_text
from bene.kernel.schema_v2 import ensure_v2


class ReplayVerifier:
    def __init__(self, *, trusted_keys: set[str] | None = None) -> None:
        # Cryptographically-valid-but-untrusted keys still verify; they are
        # flagged signature_state="untrusted" so a UI can warn (TOFU policy is
        # out of v1 scope — trusted_keys is a flat hand-edited list).
        self.trusted_keys = trusted_keys or set()

    def verify(
        self,
        env: ReplayEnvelope,
        *,
        into_db: str | Path | None = None,
    ) -> ReplayResult:
        reasons: list[str] = []

        if env.text_norm_version != _expected_text_norm():
            reasons.append("text-norm-version-mismatch")

        sig_state = self._check_signature(env, reasons)

        # Source payload integrity: the carried hash map must match the carried
        # payloads (catches a payload edit that forgot to update the hash).
        for src in env.sources:
            if env.source_payload_hashes.get(src.engram_id) != src.content_sha256():
                reasons.append("source-hash-mismatch")
                break

        if env.kind == "probe":
            replayed = self._verify_probe(env, reasons)
        else:
            replayed = self._replan(env, into_db)
            if not _source_derived_equal(replayed, env.manifest):
                reasons.append("manifest-mismatch")

        reasons = list(dict.fromkeys(reasons))  # dedupe, preserve order
        return ReplayResult(
            ok=not reasons,
            reasons=tuple(reasons),
            replayed_manifest=replayed,
            cite_as=env.cite_as(),
            signature_state=sig_state,
        )

    def _check_signature(self, env: ReplayEnvelope, reasons: list[str]) -> str:
        if not env.signature or not env.public_key:
            return "absent"
        if not verify_signature(env.public_key, env.signature, env.signed_bytes()):
            reasons.append("signature-invalid")
            return "invalid"
        if self.trusted_keys and env.public_key not in self.trusted_keys:
            return "untrusted"
        return "valid"

    def _verify_probe(self, env: ReplayEnvelope, reasons: list[str]) -> dict[str, Any]:
        """Tamper-check + re-derive a probe verdict envelope (self-contained):

        - the locked gate spec must hash to the pinned ``lock_sha256`` (edit the
          spec → mismatch);
        - the carried verdict's status must match the manifest;
        - for ACCEPT/REJECT, re-derive the status by re-applying the locked gates
          to the recorded per-gate values — the probe analog of re-planning.
        """
        m = env.manifest
        gate_spec = m.get("gate_spec") or ""
        if sha256_text(gate_spec) != m.get("lock_sha256"):
            reasons.append("probe-lock-mismatch")

        verdict_src = next((s for s in env.sources if s.engram_id == m.get("verdict_engram")), None)
        recorded: dict[str, Any] = {}
        if verdict_src is not None:
            try:
                recorded = json.loads(verdict_src.payload)
            except (ValueError, TypeError):
                reasons.append("verdict-unparseable")
        if recorded.get("status") != m.get("status"):
            reasons.append("verdict-status-mismatch")

        rederived = None
        if m.get("status") in (ACCEPT, REJECT):
            rederived = _rederive_probe_status(gate_spec, recorded.get("gate_results", []))
            if rederived != m.get("status"):
                reasons.append("gate-result-inconsistent")

        return {
            "kind": "probe",
            "probe_id": m.get("probe_id"),
            "status": m.get("status"),
            "rederived_status": rederived,
            "lock_sha256": m.get("lock_sha256"),
        }

    def _replan(self, env: ReplayEnvelope, into_db: str | Path | None) -> dict[str, Any]:
        conn = sqlite3.connect(str(into_db) if into_db else ":memory:")
        try:
            ensure_v2(conn)
            store = EngramStore(conn)
            for src in env.sources:
                _hydrate_source(conn, store, src)
            conn.commit()
            policy = ConsolidationPolicy.from_dict(env.manifest["policy"])
            plan = ScheduledConsolidator(store).plan(policy, force=True)
            return plan.replay_manifest()
        finally:
            conn.close()


def _hydrate_source(conn: sqlite3.Connection, store: EngramStore, src: ReplaySource) -> None:
    """Insert one source engram with its original identity (engram_id,
    created_at, payload) so the planner re-derives an identical batch."""
    raw = src.payload.encode()
    content_hash: str | None = None
    inline_body: str | None = None
    if len(raw) > INLINE_LIMIT:
        # v1 scope: consolidation turn payloads are short and inline. A blob
        # source would need the legacy blob table in the sandbox — deferred.
        content_hash, _ = store.blobs.store(raw)
    else:
        inline_body = src.payload
    conn.execute(
        "INSERT INTO engrams (engram_id, kind, tier, title, content_hash,"
        " inline_body, metadata, provenance, agent_id, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            src.engram_id,
            src.kind,
            src.tier,
            src.title,
            content_hash,
            inline_body,
            json.dumps(src.metadata),
            json.dumps(src.provenance),
            src.agent_id,
            src.created_at,
        ),
    )


def _source_derived_equal(replayed: dict[str, Any], manifest: dict[str, Any]) -> bool:
    """Compare only the deterministic, source-derived portions of the manifest:
    the policy and the batches (source_ids, source_digest, summary, per-source
    content hashes). Scheduler state (due/reason/last_run_at) is excluded."""
    return replayed.get("policy") == manifest.get("policy") and replayed.get(
        "batches"
    ) == manifest.get("batches")


def _rederive_probe_status(gate_spec_json: str, gate_results: list[dict[str, Any]]) -> str | None:
    """Re-apply the locked gate spec to the recorded per-gate values and return
    the derived ACCEPT/REJECT. None when the recorded results don't line up with
    the spec (a tampered/inconsistent envelope). Mirrors ``evaluate_gate``: a
    missing value kills, any kill → REJECT, none → ACCEPT."""
    try:
        gates = json.loads(gate_spec_json)
    except (ValueError, TypeError):
        return None
    by_name = {r.get("name"): r for r in gate_results}
    for g in gates:
        r = by_name.get(g.get("name"))
        if r is None:
            return None  # a locked gate has no recorded result — can't re-derive
        value, op = r.get("value"), OPS.get(g.get("op"))
        if op is None:
            return None
        passed = False if value is None else op(float(value), float(g.get("threshold")))
        if not passed:
            return REJECT
    return ACCEPT


def _expected_text_norm() -> int:
    from bene.kernel.replay.manifest import TEXT_NORM_VERSION

    return TEXT_NORM_VERSION
