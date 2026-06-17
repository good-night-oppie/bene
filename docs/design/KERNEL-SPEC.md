# BENE 2.0 — Kernel Spec (buildable)

Implementation contract for `bene/kernel/`. Phases 4–8 build to this spec; deviations require updating this file in the same commit. Conventions inherited from `bene/schema.py`: TEXT ULID primary keys, ISO-8601 `created_at` defaults via `strftime('%Y-%m-%dT%H:%M:%f','now')`, CHECK-constrained enums, `IF NOT EXISTS` everywhere, partial indexes where useful. All writes go through the storage layer / same sqlite3 connection discipline as `bene/core.py` (WAL mode).

---

## 1. Schema v2 (additive — `bene/kernel/schema_v2.py`)

```sql
-- ============ ENGRAM SUBSTRATE ============
CREATE TABLE IF NOT EXISTS engrams (
    engram_id     TEXT PRIMARY KEY,                 -- ULID
    kind          TEXT NOT NULL CHECK (kind IN
                  ('trace','episodic','semantic','procedural','strategic',
                   'eval','experiment','trust','pollution','intervention',
                   'proposal','spec','report')),
    tier          INTEGER NOT NULL DEFAULT 0 CHECK (tier BETWEEN 0 AND 4),
    title         TEXT NOT NULL,
    content_hash  TEXT,                              -- payload in blob store (nullable for small inline)
    inline_body   TEXT,                              -- small payloads (< ~4KB) stored inline
    metadata      TEXT NOT NULL DEFAULT '{}',        -- JSON
    provenance    TEXT NOT NULL,                     -- JSON: {"agent_id": ...} or {"system": "<origin>"} — REQUIRED, enforced in EngramStore.append
    agent_id      TEXT REFERENCES agents(agent_id),  -- scoping agent when applicable
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    superseded_by TEXT REFERENCES engrams(engram_id) -- set when a newer version exists (append-only versioning)
);
CREATE INDEX IF NOT EXISTS idx_engrams_kind   ON engrams(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_engrams_agent  ON engrams(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_engrams_tier   ON engrams(tier);
CREATE INDEX IF NOT EXISTS idx_engrams_active ON engrams(kind) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS engram_links (
    link_id     TEXT PRIMARY KEY,                    -- ULID
    src_id      TEXT NOT NULL REFERENCES engrams(engram_id),  -- child / derived
    dst_id      TEXT NOT NULL REFERENCES engrams(engram_id),  -- parent / source
    link_type   TEXT NOT NULL CHECK (link_type IN
                ('derived_from','consolidates','verifies','refutes','associates',
                 'supersedes','about_agent','gated_by')),
    weight      REAL NOT NULL DEFAULT 1.0,           -- association strength (plasticity-adjustable)
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    UNIQUE(src_id, dst_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_links_src ON engram_links(src_id);
CREATE INDEX IF NOT EXISTS idx_links_dst ON engram_links(dst_id);

CREATE VIRTUAL TABLE IF NOT EXISTS engram_fts USING fts5(
    engram_id UNINDEXED, title, body, tokenize='porter'
);  -- maintained by EngramStore on append (title + searchable text of payload).
    -- engram_id stored UNINDEXED (not contentless) so search can JOIN back to engrams.

-- ============ CAPABILITIES & AUTONOMY ============
CREATE TABLE IF NOT EXISTS capabilities (
    name            TEXT PRIMARY KEY,                -- e.g. 'memory.writeback', 'evolve.promote'
    description     TEXT NOT NULL,
    autonomy_level  INTEGER NOT NULL CHECK (autonomy_level BETWEEN 0 AND 4),
    handler_ref     TEXT,                            -- dotted path or registry token (informational)
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE TABLE IF NOT EXISTS autonomy_grants (
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    domain      TEXT NOT NULL DEFAULT '*',           -- capability domain ('*' = general grant)
    level       INTEGER NOT NULL CHECK (level BETWEEN 0 AND 4),
    granted_by  TEXT NOT NULL,                       -- 'human:<name>' | 'policy:<rule>'
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    revoked_at  TEXT,
    PRIMARY KEY (agent_id, domain)
);

-- ============ EVAL REGISTRY (thin; verdicts live as engrams) ============
CREATE TABLE IF NOT EXISTS probe_registry (
    probe_id      TEXT PRIMARY KEY,                  -- ULID
    name          TEXT NOT NULL UNIQUE,
    gate_spec     TEXT NOT NULL,                     -- canonical JSON (sorted keys) of gates
    lock_sha256   TEXT NOT NULL,                     -- sha256 over gate_spec; tamper => refuse
    status        TEXT NOT NULL DEFAULT 'registered'
                  CHECK (status IN ('registered','admissible','inadmissible','retired')),
    subject_ref   TEXT,                              -- mechanism under test (engram id / module name)
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id        TEXT PRIMARY KEY,                  -- ULID
    kind          TEXT NOT NULL CHECK (kind IN ('probe','evolution','consolidation','sweep')),
    probe_id      TEXT REFERENCES probe_registry(probe_id),
    verdict_engram TEXT REFERENCES engrams(engram_id),
    summary       TEXT NOT NULL DEFAULT '',
    metrics       TEXT NOT NULL DEFAULT '{}',        -- JSON
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS idx_experiments_kind ON experiment_runs(kind, created_at);

-- ============ KERNEL SCHEMA REVISION ============
-- Separate from legacy schema_version (which is never touched)
CREATE TABLE IF NOT EXISTS kernel_schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
```

8 CREATE TABLE (7 regular + 1 virtual). **No ALTER on legacy tables, ever.** Migration guard: `ensure_v2(conn)` is idempotent; a dedicated `kernel_schema_version` table (separate from the legacy `schema_version`, which has no component column and is never touched) tracks v2 revisions.

## 2. Python API (signatures = the contract)

### 2.1 `bene/kernel/engrams.py`
```python
class EngramStore:
    def __init__(self, conn: sqlite3.Connection, blobs: BlobStore) -> None: ...
    def append(self, kind: str, title: str, payload: str | bytes, *,
               provenance: dict, parents: list[str] | None = None,
               link_type: str = "derived_from", tier: int = 0,
               agent_id: str | None = None, metadata: dict | None = None) -> str:
        """Append-only. Raises ProvenanceRequired if provenance lacks agent_id/system.
        Payload > ~4KB -> blob store; else inline. Indexes title+text in FTS."""
    def get(self, engram_id: str) -> Engram: ...
    def payload(self, engram_id: str) -> bytes: ...
    def search(self, query: str, *, kind: str | None = None, tier: int | None = None,
               agent_id: str | None = None, limit: int = 20) -> list[Engram]: ...
    def lineage(self, engram_id: str, *, direction: str = "ancestors",
                max_depth: int = 10) -> list[Engram]:
        """BFS over engram_links; direction in {'ancestors','descendants'}."""
    def promote(self, engram_id: str, *, new_tier: int, title: str,
                payload: str | bytes, provenance: dict) -> str:
        """Consolidation: NEW engram at new_tier linked 'consolidates' -> source.
        Never mutates the source. Raises TierViolation if new_tier <= source tier."""
    def supersede(self, old_id: str, new_id: str) -> None: ...
    def link(self, src_id: str, dst_id: str, link_type: str, weight: float = 1.0) -> str: ...
```

### 2.2 `bene/kernel/bus.py`
```python
class EventBus:
    def __init__(self, journal: EventJournal | None = None) -> None: ...
    def subscribe(self, event_type: str, handler: Callable[[dict], None]) -> str: ...
    def unsubscribe(self, sub_id: str) -> None: ...
    def publish(self, event_type: str, payload: dict, *, agent_id: str | None = None) -> None:
        """Sync at-least-once dispatch; handler exceptions isolated (logged, others still run);
        mirrors to legacy journal when attached."""
```

### 2.3 `bene/kernel/capabilities.py`
```python
class CapabilityRegistry:
    def register(self, name: str, *, autonomy_level: int, description: str,
                 handler: Callable | None = None, metadata: dict | None = None) -> None: ...
    def lookup(self, name: str) -> Capability: ...
    def list(self, *, max_level: int | None = None) -> list[Capability]: ...
    def dispatch(self, name: str, agent_id: str, /, *args, **kwargs):
        """The enforcement point: AutonomyPolicy.check before handler; denial ->
        AutonomyDenied raised + trust engram emitted via bus."""
```

### 2.4 `bene/kernel/eval/` (probe.py, gates.py, verdict.py)
```python
class Gate(TypedDict, total=False):
    name: str; description: str; metric: str; op: str  # one of >=, >, <=, <
    threshold: float; relative_to_baseline: bool

class Probe:
    name: str
    gates: list[Gate]
    def register(self, store: EngramStore, conn, *,
                 baseline: Any, subject_ref: str | None = None) -> str:
        """Canonical-JSON gate spec -> sha256 lock -> probe_registry row.
        Then admissibility self-test (folded in here — no separate
        baseline_self_test method): evaluate baseline against itself; if NO gate
        can kill the identity candidate -> status 'inadmissible' + VOID engram.
        Else 'admissible'."""
    def run(self, subject: Any, baseline: Any, *, store, conn,
            subject_ref: str | None = None) -> Verdict:
        """Recompute lock; mismatch -> LockTamperError (refuse to run).
        Evaluate gates -> Verdict(ACCEPT|REJECT|VOID) persisted as 'eval' engram
        with 'verifies'/'refutes' link to subject_ref; experiment_runs row logged."""

class Verdict:  # ACCEPT / REJECT / VOID + per-gate results, engram-backed
    status: str; gate_results: list[dict]; engram_id: str
```

### 2.5 `bene/kernel/trust.py`
```python
class TrustLedger:
    """Computed, never declared. Four documented signals (each 0..1):
    verification_coverage = verified claims / claims;
    audit_completeness   = tool calls w/ recorded outcome / tool calls;
    checkpoint_discipline = checkpoints / risky-op windows;
    outcome_reliability  = recency-weighted success rate (half-life decay).
    composite = weighted mean (weights documented in module)."""
    def summary(self, agent_id: str, *, domain: str = "*") -> dict: ...
    def record(self, agent_id: str, signal: str, value: dict) -> str:  # trust engram
    def eligible(self, agent_id: str, level: int, *, domain: str = "*") -> bool: ...
    def weighted_vote(self, agent_id: str) -> float:  # for shared_log tally
```

### 2.6 `bene/kernel/evolve/` (gepa.py, distill.py, genes.py)
```python
class Genome:           # structured: components mutated independently (D7/AHE/ADOPT)
    components: dict[str, str]   # {'memory_policy','retrieval_policy','context_strategy','tool_config','prompt'}
    gene: StrategyGene | None
    scores: dict[str, float]     # {'quality','cost','tokens'}

class ReflectiveEvolver:
    def __init__(self, store: EngramStore, conn, *,
                 reflect_fn: Callable[[Genome, list[str]], dict[str, str]],
                 benchmark: Callable[[Genome], dict[str, float]],
                 frontier: GenomeFrontier | None = None,
                 feedback_fn: Callable[[Genome, dict[str, float]], list[str]] | None = None,
                 surrogate: Callable | None = None) -> None:
        """reflect_fn returns {"component", "new_text", "rationale"} — a structured
        mutation targeting a named component (ADOPT credit assignment)."""
    def run(self, seed: Genome, *, generations: int, population: int = 4) -> GenomeFrontier:
        """Per gen: reflect on worst failure traces -> textual gradient -> targeted
        component mutation -> (surrogate prefilter) -> benchmark -> frontier update.
        Every round logged as experiment_run; candidates persisted as 'strategic' engrams."""

class GenomeFrontier:    # non-dominated set; reuses bene/metaharness/pareto.dominates()
    def update(self, genome: Genome) -> bool: ...   # (NOT metaharness's ParetoFrontier —
    def members(self) -> list[Genome]: ...          #  that is a different class)

def promote(candidate_engram_id: str, *, store, conn) -> str:
    """Requires an ACCEPT 'eval' engram linked ('verifies') to the candidate.
    Otherwise raises PromotionBlocked. Records 'gated_by' link; returns the
    verdict engram id. [D3]"""

class TraceDistiller:
    def distill(self, trace_ids: list[str], *, analyst_fn: Callable) -> list[str]:
        """Per-trace patches (success: single-pass; failure: evidence chain w/ root cause)
        -> prevalence-weighted merge -> 3-level hierarchy (planning/functional/atomic)
        as tier-3 engrams, 'consolidates'-linked to EVERY source trace."""

class StrategyGene:      # control-signal-dense (GEP): match_signal, steps, avoid[]
    def encode(self) -> str: ...
    @classmethod
    def merge(cls, a: "StrategyGene", b: "StrategyGene") -> "StrategyGene": ...
```

### 2.7 `bene/kernel/memory/` (granules.py, retrieval.py, contextos.py, pollution.py)
```python
class GranuleStore:      # tiers 0..3 over EngramStore
    def write_turn(self, agent_id: str, text: str, **meta) -> str: ...
    def consolidate(self, granule_ids: list[str], *, summary: str,
                    provenance: dict) -> str:   # promotion via EngramStore.promote
    def associate(self, a: str, b: str, weight: float = 1.0) -> str: ...

class AdaptiveRetriever:
    def query(self, agent_id: str, text: str, *, k: int = 8) -> RetrievalResult:
        """Familiarity score vs recent query engrams; >= fast_threshold -> fast path
        (cached/top-k); else slow path (FTS + association expansion). Served path
        recorded in result + engram metadata (auditable)."""

class ContextOS:
    def register_strategy(self, name: str, fn: PackStrategy) -> None: ...
    def select_strategy(self, signals: dict) -> str:   # AgentSwing-style routing rules
    def assemble(self, items: list[dict], budget_tokens: int, *,
                 signals: dict | None = None, strategy: str | None = None) -> PackedContext:
        """Never exceeds budget (chars/4 estimator, pluggable). Caller passes items
        directly ({"id","text","relevance"?}); agent-level assembly by agent_id
        awaits runner wiring (PLANNED). Returns manifest: included[], dropped[],
        strategy, estimated_tokens. [transparency/D8]"""

class PollutionDetector:
    SIGNALS = ('repeated_failed_calls', 'error_rate_spike', 'contradiction_markers')
    def scan(self, agent_id: str, *, window: int = 50) -> PollutionReport: ...
    def recover(self, agent_id: str, report: PollutionReport, *, bene: "Bene") -> dict[str, Any]:
        """Consolidate requirements from trace -> emit 'pollution' engram ->
        restore latest pre-contamination checkpoint (legacy API, wrapped not ported)
        or respawn with consolidated context. Emits recovery event. Returns a
        three-key dict: {"pollution_engram", "consolidated", "restored_checkpoint"}. [D9]"""
```

### 2.8 `bene/kernel/harness/` (autonomy.py, senses.py, sweeper.py, guards.py)
```python
class AutonomyPolicy:
    def grant(self, agent_id: str, level: int, *, domain: str = "*", granted_by: str) -> None: ...
    def check(self, agent_id: str, capability: Capability) -> bool:
        """Takes a Capability object (needs .name/.autonomy_level for domain
        derivation + comparison). max(grant level for domain) >=
        capability.autonomy_level; deny -> trust engram."""
    def guard(self, capability: Capability) -> Callable:   # decorator for handler fns

class SensesManifest:
    @staticmethod
    def generate(bene: "Bene", *, fmt: str = "json") -> str:
        """Sections: agents+status, capabilities+levels, skills, memory domains,
        recent engram activity, entry-point commands. Generated from live db. [can't rot]"""

class DebtSweeper:
    SIGNATURES: dict[str, re.Pattern]  # 3 regexes: debug_print, stale_todo, dead_import
    def scan_paths(self, paths: list[str]) -> SweepReport: ...
    def scan_agent_vfs(self, bene, agent_id: str) -> SweepReport:
        """Findings persisted as 'report' engram; CLI `bene sweep`.
        duplicated_block is detected by a separate sliding-window comparison
        (DUP_WINDOW consecutive lines), not a SIGNATURES regex."""

class LoopGuard:
    def __init__(self, *, window: int = 20, repeat_threshold: int = 5) -> None: ...
    def observe(self, event: dict) -> Intervention | None:
        """Near-identical action repetition / oscillation -> 'intervention' engram +
        callback (default: forced-reflection note + needs-attention mark). Removable middleware."""
```

### 2.9 CLI additions (`bene/cli/main.py`)
Groups: `bene probe ls|show`, `bene trust <agent_id>`, `bene experiments ls|show`, `bene senses`, `bene sweep` — every command supports `--json`. (No `probe selftest` subcommand: the admissibility self-test runs automatically inside `Probe.register`.)

## 3. Invariants (enforced by tests, phase 4–8)

1. Engram append without provenance raises — no anonymous experience.
2. Promotion never mutates sources; tiers only increase along `consolidates` links.
3. Opening a 0.1.0 db: legacy `sqlite_master` entries byte-identical after `ensure_v2`.
4. A probe with an edited gate spec refuses to run (LockTamperError).
5. A probe whose baseline cannot trigger any kill gate is inadmissible (VOID).
6. `evolve.promote` without ACCEPT verdict raises PromotionBlocked.
7. ContextOS.assemble output ≤ budget for all inputs (property test).
8. An L1 agent invoking an L3 capability raises AutonomyDenied AND leaves a trust engram.
9. Evolver and probe judge never share state (verifier isolation — AEVO). Test: `test_verifier_isolation_evolver_cannot_mint_verdicts` in `tests/kernel/test_hardening.py`.
10. Every kernel CLI command supports `--json`.

## 4. Port plan (every legacy top-level module)

| Legacy module | Plan | Phase | Notes |
|---|---|---|---|
| core.py (VFS) | keep | — | kernel reads same conn; no changes |
| schema.py | keep | — | v2 additive in kernel/schema_v2.py |
| blobs.py | keep | 4 | engram payload backend |
| events.py | keep | 4 | bus mirrors into journal |
| checkpoints.py | keep (wrap) | 7 | pollution recovery calls it; never modified |
| isolation.py | keep | — | |
| memory.py | adapt | 9 | writes mirror to engram ladder via `attach_kernel(memory=...)` opt-in; no config flag |
| skills.py / skills_discovery.py | adapt | 9 | mirror to procedural engrams (shipped); skill decay/demotion lifecycle deferred (PLANNED) |
| shared_log.py | adapt | 9 | trust-weighted tally option |
| intake.py | keep | — | |
| ccr/ (runner, tools, parallel_worker, prompts) | adapt | 9 | runner wiring of ContextOS packing / loop-guard middleware / senses tools deferred to a later release (PLANNED); kernel primitives ship standalone |
| router/ (tier, providers, agent_sdk, classifier, vllm_client, context.py) | keep | 9 | kept as-is; folding router/context.py into a ContextOS strategy deferred (PLANNED) |
| mcp/server.py | adapt | 9 | kernel families shipped via CLI (`bene probe/trust/experiments/senses/sweep`) + UI (/api/engrams, /api/trust); MCP kernel tool families deferred (PLANNED) |
| cli/ | adapt | 5,8,9 | new groups; UX pass |
| ui/ | adapt | 9 | engram browser + trust panel |
| obsidian/ | keep | — | |
| metaharness/ | adapt | 6,9 | evolve/ backend opt-in; pareto.py reused; verifier reused as probe judge |
| benchmarks/ (empty ns) | keep (docstring-only namespace) | 10 | left for the first real domain package, avoiding import-path breakage |
| storage/ | keep | — | kernel writes through it |
| runtime/ | keep | — | |
| temporal/ | keep | — | durability edge retained |
| integrations/ (empty) | keep (docstring-only namespace) | 10 | left for the first real domain package, avoiding import-path breakage |
```
