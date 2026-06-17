# BENE 2.0 — Architecture

> **BENE** — **B**reeding-program · **E**volutionary · **N**exus · **E**ngrams — a Bene Gesserit harness for AI coding agents.
>
> 2.0 thesis: *everything is an engram.* One typed, append-only, provenance-linked substrate under five capability pillars, with falsifiable gates on everything that evolves and an autonomy ladder on everything that acts.

Design rationale (every decision argued through science / compression / engineering lenses): `DESIGN-RATIONALE.md` (D1–D10).
Paper grounding: `../research/SYNTHESIS.md` (48 citations). Community-peer evidence: `../research/GAP-AUDIT.md`.
Buildable spec (DDL + APIs + port plan): `KERNEL-SPEC.md`.

---

## 1. Kernel overview

```
            agents (CCR runner · Temporal workflows · parallel workers · MCP/CLI/UI)
                 │ act through
   ┌─────────────▼──────────────────────────────────────────────────────────┐
   │                          BENE 2.0 KERNEL                               │
   │                                                                        │
   │   CAPABILITY REGISTRY ──── AUTONOMY LADDER (L0..L4, enforced) [D4]     │
   │         │ dispatch              │ denials → trust engrams              │
   │   EVENT BUS ─────────────── TRUST LEDGER (computed, per-agent) [D8]    │
   │         │ every event                                                  │
   │   ┌─────▼──────────────────────────────────────────────────────────┐   │
   │   │                    ENGRAM SUBSTRATE  [D1]                      │   │
   │   │   tier 0 raw trace → 1 episodic → 2 semantic → 3 procedural    │   │
   │   │              → 4 strategic        (compression ladder [D2])    │   │
   │   │   provenance links · FTS5 · content-addressed zstd blobs       │   │
   │   └───────▲───────────────▲────────────────▲───────────────▲──────┘   │
   │           │               │                │               │          │
   │     EVAL/TRUST [D6]   EVOLUTION [D3,D7]  MEMORY/CONTEXT  HARNESS      │
   │     probes · gates    GEPA-style ·       OS [D9]         LAYER        │
   │     verdicts ·        distill ·          granules ·      autonomy ·   │
   │     experiments       genes · Pareto     fast/slow ·     senses ·     │
   │                       gated promotion    pollution       sweeper ·    │
   │                                          recovery        loop guards  │
   └────────────────────────────────────────────────────────────────────────┘
        legacy plane (kept, adapted [D10]): VFS · blobs · events · checkpoints
        · isolation tiers · tier router/providers · shared log · obsidian
        · storage protocol (SQLite/Postgres) · Temporal runtime · intake
```

The kernel is the *Nexus* made literal: one SQLite file (storage-protocol-backed) holding every agent's working state **and** every compression of every experience, joined by provenance. The Dune mapping is retained and now structural:

| Lore | 1.0 (metaphor) | 2.0 (mechanism) |
|---|---|---|
| Other Memory | searchable traces | engram substrate: the full compression ladder over execution history, lineage-queryable |
| Missionaria Protectiva | skills/memory propagation | tier-3 procedural engrams seeded across agents ahead of need, with provenance to source traces |
| The Breeding Program | metaharness search | evolution engine with Pareto frontier and **kill-gated promotion** |
| The Litany Against Fear | checkpoint/restore | pollution detection → consolidate → restore/respawn (face it, let it pass, turn the inner eye, only the clean context remains) |
| The gom jabbar | "harness thesis" prose | autonomy ladder: what separates the reactive beast (L0–L1) from the building human (L3–L4) is *verified* self-control |

## 2. The five pillars

### Pillar 1 — Parity core, re-derived (eval discipline · experiments · consolidation · plasticity)

Everything KAOS got right, rebuilt on the substrate instead of beside it (GAP-AUDIT KAOS-6: KAOS's own eval layer cannot write back into its memory layer).

- **Falsifiable probes** (`bene/kernel/eval/`): pre-registered gate specs, sha256 lock, tamper → refuse; admissibility self-test (a probe whose baseline cannot trigger a kill is VOID at registration); verdicts ACCEPT/REJECT/VOID persisted as `eval` engrams with provenance to the probed mechanism. *(Papers: KAOS v0.9 discipline; Anthropic Effective Harnesses pt 2 default-fail ledger; Ctx2Skill rubric probes.)*
- **Experiments journal**: every probe run and evolution round is an `experiment` engram + thin registry row — queryable via `bene experiments`. *(Paper: Autogenesis SEPL — every change a logged, evaluated system event.)*
- **Consolidation (the dream analog)**: schedulable promotion passes (scheduler wiring planned) over the ladder — episodic→semantic merge/dedupe, semantic→procedural distillation — drawing preferentially from Pareto-winning, ACCEPT-verdicted traces (H: mimic the pinnacle). *(Papers: SkillClaw nightly validation; MemCoE evolvable update guideline; Trace2Skill hierarchical conflict-free merge.)*
- **Plasticity**: outcome-recency weighting on procedural engrams (use/success with decay), demotion/retirement for skills that start failing (substrate shipped: superseded_by + link weights; decay policy planned) — addressing GAP-AUDIT BENE-4. *(Papers: SKILLGRAPH edge reinforcement/decay; MUSE-Autoskill lifecycle states.)*

### Pillar 2 — Evolution engine (the Breeding Program)

`bene/kernel/evolve/` — text-genome evolution over harness strategies [D7], beyond both peers' search loops:

- **Structured genomes**: not prompt blobs — components (memory policy, retrieval policy, context strategy, tool config, prompt) mutated independently with per-component credit assignment. *(Papers: Meta-Harness — the harness IS the search space; AHE — prompt-only edits score below seed; ADOPT — Shapley budget across components.)*
- **Reflective mutation**: failure traces → textual gradients → targeted mutations (pluggable `reflect_fn`; deterministic in tests, LLM in production). *(Papers: GEPA; LangChain Deep Agents pt 1 trace-analyzer.)*
- **Pareto frontier**: multi-objective (quality, cost, tokens) non-dominated archive — kept from 0.1.0 (`metaharness/pareto.py`, the one piece GAP-AUDIT verified as already real).
- **Trace→skill distillation**: per-trajectory analysts emit patches (success: single-pass; failure: evidence chain with verified root cause), prevalence-weighted hierarchical merge into a 3-level skill hierarchy (planning/functional/atomic), landing as tier-3 engrams with provenance to *every* source trace. *(Papers: Trace2Skill; SkillX; AdaPlanner — the precursor.)*
- **Strategy genes**: ~control-signal-dense encodings (match signal + steps + AVOID warnings), versioned as tier-4 engrams; explanatory prose is deliberately excluded — control-logic density is what transfers. *(Paper: GEP/EvoMap strategy genes.)*
- **Kill-gated promotion** [D3]: `promote(candidate)` requires an ACCEPT verdict; the verifier is process-isolated from the evolver (AEVO: removing that boundary produced reward hacking in 2/3 runs).

### Pillar 3 — Memory & context OS (Other Memory)

`bene/kernel/memory/` — beyond both peers' flat FTS5 (GAP-AUDIT KAOS-7, BENE-5):

- **Granules**: turn/episode/semantic/procedural levels = ladder tiers 0–3, with association links; consolidation is promotion. *(Papers: MemGAS multi-granularity + association graph; GAM — raw pages kept, light memo index, research-on-demand instead of lossy precompute.)*
- **Adaptive retrieval**: familiarity-gated fast path (repeat/near-duplicate queries short-circuit) vs slow associative path (FTS + link expansion), uncertainty decides spend; the served path is recorded on the query engram so the choice is auditable and testable. *(Paper: RF-Mem.)*
- **Context OS**: token-budget manager + pluggable packing strategies + signal-driven routing (long-horizon? high error rate? → different strategy), returning a *manifest* of what was included and dropped — context assembly becomes transparent (trust pillar). *(Papers: AgentSwing fork/lookahead/route; Schmid context=RAM; ReCAP plan re-injection; RLM metadata-only history; PEARL planned sub-reads.)*
- **Pollution defense** — a capability class neither peer has: deterministic contamination signals (repeated failed tool calls on one target, error-rate spike, contradiction markers) → pollution engram → recovery: *consolidate requirements from the trace, then checkpoint-restore or respawn with clean consolidated context* — because recap-in-place measurably fails. Re-highlighting evidence already in context (VEA) is the cheap intervention to try first (planned — see CLAIMS-AUDIT). *(Papers: Lost in Conversation; VEA; AgentSwing.)*

### Pillar 4 — Harness-engineering layer

`bene/kernel/harness/` — the OpenAI/Anthropic/LangChain canon as primitives (no peer has this layer in code: GAP-AUDIT KAOS-3, BENE-7):

- **Autonomy ladder** (§3): enforced at capability dispatch; denials are trust events.
- **Agent senses**: a generated, machine-readable manifest of the engagement (agents, capabilities + levels, skills, memory domains, recent activity, entry-point commands) — the ~100-line map-not-encyclopedia an incoming agent reads first; plus the existing observability surfaces (events, logs, UI). *(Papers: OpenAI HE pt 2 — give agents senses; pt 3 — discoverability, index-not-encyclopedia.)*
- **Debt sweeper**: scheduled scan for slop signatures (debug prints, stale TODOs, duplicated blocks, dead imports) emitting report engrams — continuous GC for agent-generated debt. *(Paper: OpenAI HE pt 7.)*
- **Loop guards**: sliding-window detection of repeated near-identical actions and oscillation; trips inject forced reflection and emit intervention engrams — built as removable middleware ("built to be deleted"). *(Papers: LangChain pt 4 doom loops; GraSP budgeted local repair.)*
- **Tool design discipline**: single-intent tools, schema-enforced I/O, call-frequency/outcome telemetry as the fitness signal for tool fit. *(Paper: Claude Code — Seeing Like an Agent.)*

### Pillar 5 — Trust & experience

The user-added pillar, and the one aimed at DevEx: *engineers adopt agent tooling only when they trust it.*

- **Trust ledger** [D8] (`bene/kernel/trust.py`): four documented, deterministic signals — verification coverage, audit completeness, checkpoint discipline, outcome reliability (recency-weighted) — plus a composite; surfaced via `bene trust <agent>`; consumed by L3/L4 eligibility and trust-weighted shared-log voting (fixing GAP-AUDIT BENE-8: unweighted votes).
- **Provenance everywhere**: engrams *require* provenance; self-modifications are versioned, candidate→evaluate→commit/rollback events (Autogenesis RSPL/SEPL pattern) — auditable self-evolution.
- **Spec-as-artifact**: change intent (proposal/acceptance criteria) storable as first-class engrams linked to traces and checkpoints; "done" gateable on acceptance evidence. *(Paper: Spec-Driven Development.)*
- **Apple-grade experience**: `bene demo` <60s, keyless, fresh-dir clean; first-run guidance instead of tracebacks; `--json` everywhere; context-assembly manifests and trust reports one command away. The experience claim is itself probe-tested (phase 9/10 gates, passing).

## 3. The autonomy ladder (L0–L4)

| Level | Name | May do | Verification gate to grant |
|---|---|---|---|
| L0 | Observe | read engrams/VFS/senses; no writes outside own scratch | none (default for unknown agents) |
| L1 | Suggest | write proposal/suggestion engrams; file follow-up tasks | identity + audit trail enabled |
| L2 | Act-in-sandbox | mutate own VFS; run tools whitelisted as sandbox-safe; create checkpoints | checkpoint discipline ≥ threshold on probation window |
| L3 | Act-on-shared-state | write shared stores (skill/memory writeback), spawn subagents, vote with full weight | trust composite ≥ threshold **and** ≥1 ACCEPT-verdicted probe on its capability domain |
| L4 | Autonomous-promote | promote evolved artifacts, trigger consolidation, merge without human review | sustained L3 trust + human-set autonomy flag (the explicit threshold crossing — OpenAI HE pt 6) |

Each step up is a nine (K); each gate is a falsifiable artifact, not a vibe (H/S). Grants are per-agent and revocable; capability classes may require higher levels than the agent's general grant (jaggedness: per-capability autonomy requirements; per-domain trust scoring planned).

## 4. Subsumption table (complete)

Every verified peer capability → its BENE 2.0 mechanism. **kept** = legacy module retained as-is (adapter optional); **re-derived** = rebuilt on the engram substrate; **surpassed** = strictly more capable mechanism; a trailing **+** = retained with kernel-era additions.

| # | Peer | Capability | BENE 2.0 mechanism | Verdict |
|---|---|---|---|---|
| 1 | KAOS | Per-agent SQLite VFS + audit | `bene/core.py` VFS (same lineage) + events | kept |
| 2 | KAOS | Content-addressable blobs | `bene/blobs.py` (SHA-256 + zstd); engram payloads ride it | kept |
| 3 | KAOS | Append-only event journal | `bene/events.py` + kernel bus mirroring | kept+ |
| 4 | KAOS | Checkpoint/restore/diff | `bene/checkpoints.py` + pollution-recovery wrapper (consolidate-then-restore) | surpassed |
| 5 | KAOS | 3 isolation tiers | `bene/isolation.py` (logical/FUSE/namespace) | kept |
| 6 | KAOS | Dream cycle (replay→weights→narrative) | kernel consolidation passes over the ladder (episodic→semantic→procedural), Pareto-preferring | re-derived |
| 7 | KAOS | Neuroplasticity (Hebbian + structural) | plasticity weighting + decay/demotion on procedural engrams; consolidation = structural phase | re-derived |
| 8 | KAOS | Failure intelligence (fingerprints, taxonomy, fix outcomes) | failure engrams w/ evidence-chain root cause (Trace2Skill error-analyst pattern), lineage-queryable | re-derived |
| 9 | KAOS | Critical-step localizer | evidence-chain attribution in distill.py failure analysts | re-derived |
| 10 | KAOS | Falsifiable eval harness (hash-locked gates, blind judge, A/R/V) | `bene/kernel/eval/` — same discipline + verdicts-as-engrams + admissibility-at-registration | surpassed |
| 11 | KAOS | Experiments journal | experiment engrams + registry; CLI `bene experiments` | re-derived |
| 12 | KAOS | Ideal State Artifacts (ISA/ISC) | probe gate specs (pre-registered criteria) + spec-as-artifact engrams | re-derived |
| 13 | KAOS | GEPA router, 5 providers | `bene/router/` TierRouter + same 5 providers (incl. agent_sdk) | kept |
| 14 | KAOS | LLM+heuristic complexity classifier | `bene/router/classifier.py` | kept |
| 15 | KAOS | Context compression (continuation blocks, AAAK) | ContextOS: budget manager + strategy routing + manifests (strictly more general) | surpassed |
| 16 | KAOS | War-room web UI (SSE) | `bene/ui/` dashboard + engram browser + trust panels (shipped, v0.2.0) | surpassed |
| 17 | KAOS | TUI dashboard + keyless demo | `bene/cli/dashboard.py` + `bene demo` 2.0 (5-pillar story) | surpassed |
| 18 | KAOS | Parallel agent execution | `bene parallel` + parallel_worker + Temporal option | kept+ |
| 19 | KAOS | Agent lifecycle via MCP (18 tools) | MCP agent_* family (kept); kernel surfaces ship as CLI groups (`bene probe/trust/experiments/senses`) | kept+ |
| 20 | KAOS | Cross-agent FTS5 memory + hit telemetry | GranuleStore: multi-granularity + association links + adaptive retrieval (telemetry = path metadata) | surpassed |
| 21 | KAOS | Skill library + weighted ranking | procedural engrams: hierarchy + plasticity + lifecycle + provenance | surpassed |
| 22 | KAOS | SharedLog consensus (intent→vote→decide) | `bene/shared_log.py` + trust-weighted voting | surpassed |
| 23 | KAOS | Obsidian export | `bene/obsidian/` | kept |
| 24 | KAOS | Dynamic intake (clarifying questions) | `bene/intake.py` | kept |
| 25 | KAOS | Meta-harness search (proposer, Pareto, bg worker, stall recovery) | `bene/metaharness/` + evolve backend (structured genomes, reflective mutation, gated promotion) | surpassed |
| 26 | KAOS | Surrogate Verifier (isolated, blind judge) | kept; reused as probe judge; isolation now mandatory (AEVO) | kept+ |
| 27 | KAOS | Co-evolution + hub sync | `mh_spawn_coevolution`/`mh_hub_sync` MCP tools (same lineage) | kept |
| 28 | KAOS | Doctor proposer + systemic alerts | senses manifest + sweeper reports + loop-guard interventions (systematized) | re-derived |
| 29 | KAOS | Permission-aware tool execution | capability registry + autonomy ladder (graduated, trust-fed — vs static per-run policy) | surpassed |
| 30 | KAOS | ARC-AGI-3 + bench suites | `bene/metaharness/benchmarks/` (incl. arc_agi3) | kept |
| 31 | KAOS | 58 MCP tools; --json CLI | 37 tools (set unchanged) + kernel CLI groups (probe/trust/experiments/senses/sweep); count is not the metric — coverage is | kept+ |
| 32 | KAOS | Harness doc scaffold (AGENTS.md, AUTONOMY_THRESHOLD.md, agent_senses scripts) | *enforced in code*: ladder in dispatch path, senses generated from live db (docs can't rot — KAOS-3/KAOS-8) | surpassed |
| 33 | BENE 0.1.0 | VFS isolation, 3 tiers | kept as-is | kept |
| 34 | BENE 0.1.0 | Checkpoints/diff/restore | kept + pollution-recovery wrapper | kept+ |
| 35 | BENE 0.1.0 | Event journal | kept + bus mirror | kept+ |
| 36 | BENE 0.1.0 | Blob store | kept; engram payload backend | kept+ |
| 37 | BENE 0.1.0 | FTS5 memory (5 types) | adapter mirrors writes to granules; superseded by memory OS behind flag | surpassed |
| 38 | BENE 0.1.0 | Skill library + SKILL.md discovery | adapter mirrors to procedural engrams; hierarchy/plasticity/lifecycle added | surpassed |
| 39 | BENE 0.1.0 | Shared log (LogAct full vocabulary) | kept + trust-weighted tally | surpassed |
| 40 | BENE 0.1.0 | Tier router + classifier | kept | kept |
| 41 | BENE 0.1.0 | 5 providers (raw-httpx vLLM, claude_code, agent_sdk…) | kept | kept |
| 42 | BENE 0.1.0 | Context compaction (preserve-recent-8) | one strategy inside ContextOS; routing decides when | surpassed |
| 43 | BENE 0.1.0 | MCP server (37 tools) | kept; kernel families exposed via CLI groups (MCP additions planned) | kept+ |
| 44 | BENE 0.1.0 | CLI (22 cmds + mh group) | kept + probe/trust/experiments/senses/sweep groups | kept+ |
| 45 | BENE 0.1.0 | Web UI (read-only, multi-project) | kept + engram/trust panels | kept+ |
| 46 | BENE 0.1.0 | TUI dashboard | kept | kept |
| 47 | BENE 0.1.0 | Obsidian export | kept | kept |
| 48 | BENE 0.1.0 | Metaharness (Algorithm-1 search, verifier, compactor, CORAL, coevolution) | kept; evolve/ adds structured genomes + distillation + genes + gated promotion | surpassed |
| 49 | BENE 0.1.0 | Bundled benchmarks | kept (the testbeds — H's games criteria) | kept |
| 50 | BENE 0.1.0 | Temporal durable runtime | kept — the durability edge KAOS lacks (KAOS-1) | kept |
| 51 | BENE 0.1.0 | Storage protocol (SQLite+Postgres, idempotency) | kept — kernel writes through it (KAOS-2) | kept |
| 52 | BENE 0.1.0 | Runtime abstraction (DTOs, LocalRuntime≡TemporalRuntime) | kept | kept |
| 53 | BENE 0.1.0 | Intake (clarifying questions) | kept | kept |
| 54 | BENE 0.1.0 | Parallel + detached bg workers | kept | kept |
| 55 | BENE 0.1.0 | Trace search (FTS over VFS + index.md) | engram FTS + lineage queries + adaptive retrieval | surpassed |

No row is blank. Tally: 20 kept / 11 kept+ / 7 re-derived / 17 surpassed.

## 5. Beyond both — capabilities neither peer has

1. **Engram compression ladder with mandatory provenance** — one lineage-queryable substrate from raw trace to strategy gene (D1+D2). Neither peer can answer "which traces does this skill compress, and did they pass eval?"
2. **Context-pollution detection + consolidate-then-recover** — measured failure mode (Lost in Conversation), detected and recovered, wired to checkpoints (KAOS-4, BENE-6: zero hits for pollution in either).
3. **Enforced autonomy ladder with computed-trust gating** (per-capability autonomy levels; per-domain trust breakdown planned) — KAOS has a markdown file; BENE 0.1.0 has binary run/kill (KAOS-3, BENE-7).
4. **Computed trust ledger + trust-weighted consensus** — agent reputation derived from verification artifacts, consumed by the ladder and the shared log (KAOS-5, BENE-8).
5. **Kill-gated promotion for evolution** — probes existed (KAOS) and Pareto existed (BENE), but *neither wires verdicts into promotion*; BENE 2.0 makes `PromotionBlocked` a kernel exception (BENE-9, KAOS-6).
6. **Strategy genes + structured genomes with per-component credit** — control-signal-dense evolution units vs prompt-blob mutation (AHE finding: prompt-only edits underperform seed).
7. **Adaptive fast/slow retrieval with auditable path choice** — uncertainty-gated retrieval spend; both peers are single-path FTS5 (KAOS-14, BENE-5).
8. **Agent senses generated from the live database** — discoverability that cannot rot, vs hand-maintained docs that demonstrably do (KAOS-8, KAOS-13, BENE-12).

## 6. What BENE 2.0 deliberately does *not* do

- **No fine-tuning, no LoRA, no gradients** [D7] — the model is frozen; the harness evolves.
- **No mandatory embeddings/GPU** — lexical + associative retrieval first; vector search is a pluggable strategy, not a dependency (S: simplicity; K: boring tech). The ceiling is acknowledged (KAOS-14 applies to us too) and revisited only with a probe that shows lexical failing on a real workload.
- **No big-bang rewrite** [D10] — legacy suite green at every commit; adapters mirror; supersession is feature-flagged and phase-numbered (KERNEL-SPEC §4).
- **No opaque single "the agent is good" score** — trust is a per-agent composite with four visible component signals; per-domain breakdown is reserved (domain parameter present, filtering planned; autonomy levels are already per-capability — jaggedness).
- **No retune-and-rerun** — a REJECT verdict stands; the candidate changes, not the gate.

## 7. Versioning & migration

- v2 tables are additive (`CREATE TABLE IF NOT EXISTS`, no ALTER on legacy tables); a 0.1.0 db opens unchanged under 2.0 (phase-4 back-compat test checksums legacy schema before/after kernel init).
- Kernel tables are created lazily on first kernel command or `attach_kernel` (sane defaults, no config required); a `bene.yaml` `kernel:` section now wires runner ContextOS and loop-guard middleware, while autonomy defaults and consolidation schedule wiring remain planned — see CLAIMS-AUDIT.
- Version: 0.2.0 — shipped 2026-06-11 (phases 4–10 complete). Port plan with per-module keep/adapt/supersede and phase numbers: KERNEL-SPEC §4.
