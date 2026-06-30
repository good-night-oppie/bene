# ADR 0001: BENE Belief/Fact Contract and Truth Maintenance Layer

## Status
Approved

## Context
As BENE (Breeding-program · Evolutionary · Nexus · Engrams) evolves, agents generate multiple, often contradictory, statements across runs. We need a deterministic, local-first Truth Maintenance System (TMS) to structure these observations and resolve conflicts safely, preventing subsequent runs from inheriting stale, overridden, or toxic beliefs.

## Decision

We introduce an additive, SQLite-backed Truth Maintenance layer with a Belief/Fact contract + single-node deterministic reducer.

### 14 ADR Questions & Answers

### 1. What is a Fact?
A **Fact** is a structured, immutable statement of observation, state, hypothesis, claim, decision, or policy emitted by an agent, kernel, or external system. It includes key metadata such as kind, subject, relation, value, source, source reliability, and timestamps.

### 2. What is a Belief?
A **Belief** represents the current accepted state of truth maintained by the BENE kernel. Unlike facts (which are raw inputs), beliefs are synthesized by the reducer and are subject to lifecycle transitions (candidate, active, superseded, quarantined, expired, rejected).

### 3. What is a Decision?
A **Decision** records the rationale and provenance behind any belief lifecycle state transition. Every transition must correspond to a decision row, explaining why a belief was activated, superseded, quarantined, or rejected.

### 4. What is a Conflict?
A **Conflict** is a recorded contradiction where a newly emitted fact proposes a different value for an existing active belief, or is a stale fact out of sync with current beliefs.

### 5. Fact vs Claim?
A **Fact** is the general record of any structured state or statement. A **Claim** is a specific kind of fact proposing a truth value that needs to be reconciled by the reducer to become a belief.

### 6. Claim vs Belief?
A **Claim** is a raw, unverified proposal from a source. A **Belief** is the system's current converged consensus for that claim's key.

### 7. Stable reconciliation key?
The stable reconciliation key is `(subject, relation, scope)`. It uniquely identifies a logic namespace (e.g. `agent-1`, `status`, `active`).

### 8. How does scope work?
Scope defines the context boundary of the belief. By default, it is `'global'`. Consumers can specify custom scopes (e.g., matching a project or run ID) to isolate namespaces.

### 9. Lifecycle states?
Belief lifecycles are:
- `candidate`: Proposed state.
- `active`: The current verified truth for the key.
- `superseded`: Deprecated by a newer active belief.
- `quarantined`: Isolated due to source unreliability or manual intervention.
- `expired`: Past its time-to-live.
- `rejected`: Decided as invalid.

### 10. Which beliefs admissible for context/promotion/action?
Only beliefs in the `active` lifecycle that are reliable (not quarantined, expired, or superseded) are admissible. All other lifecycles have admissibility flags set to 0.

### 11. Why deterministic reducer?
To guarantee that replaying the identical set of raw facts starting from an empty database reproduces the exact same beliefs and decisions. Determinism is ensured by sorting unreconciled facts by `(observed_at, fact_id)` and using an injectable, recorded `now` time.

### 12. Why LLM extraction/semantic interpretation OUTSIDE core?
LLM extraction is non-deterministic and expensive. Core BENE must remain fast, cheap, and robust. Structured facts should be parsed or extracted prior to core ingestion; the core reducer runs as a pure relational engine.

### 13. Why SQLite is enough for v1?
SQLite is BENE's canonical storage substrate. It is local-first, supports WAL mode for concurrency, provides ACID guarantees, and easily handles thousands of facts/beliefs per second without server overhead.

### 14. How this later serves agentdex-cli + eddie-agi-kb?
Both tools need to enforce safety policies (e.g., do not promote an agent if a test failed, do not execute an action if quota is exhausted). Truth maintenance provides a unified, queryable substrate for these admission decisions.

---

### Additive Schema definition

We create 5 new tables:
1. `belief_facts`: The raw facts registry.
2. `beliefs`: The derived belief states.
3. `belief_decisions`: The transition audit trail.
4. `belief_conflicts`: Contradiction history.
5. `truth_schema_version`: Version tracking.

#### Single-Active-Belief DB Invariant
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_beliefs_active_key 
ON beliefs(subject, relation, scope) 
WHERE lifecycle = 'active';
```

### Reconciliation Rules (1–10)

- **Rule 1**: A valid candidate fact with no active belief for its key creates exactly one `active` belief + a decision.
- **Rule 2**: A newer same-key different-value fact moves the old belief to `superseded` (setting `active_until`) and creates a new `active` belief, writing a conflict and decisions.
- **Rule 3**: A newer same-key same-value fact does not duplicate the belief (one active remains) and links the fact.
- **Rule 4**: A fact with `source_type` in `UNRELIABLE_SOURCE_TYPES` or `unsafe=1` produces a `quarantined` belief/candidate, never `active`, with a decision.
- **Rule 5**: An expired fact does not create an `active` belief; explains via decision.
- **Rule 6**: Beliefs in non-active lifecycles have admissibility flags set to 0.
- **Rule 7**: Active reliable belief has admissibility flags set by its decision.
- **Rule 8**: Every transition writes a decision row.
- **Rule 9**: Idempotent reducer run over same facts is a no-op.
- **Rule 10**: Manual `quarantine_belief` moves active to quarantined + decision.
