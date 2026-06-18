# KAOS & the 0.1.0 predecessor/BENE-0.1.0 Gap Audit

> **Historical snapshot** — audited at commit `6c55fa3` (v0.1.0 baseline, 2026-06). BENE 0.2.0 (shipped 2026-06-11) closes most BENE-side gaps below; for current state see `docs/design/BENE2-DESIGN.md` §4.

Purpose: evidence base for the "subsume and surpass" claims of BENE 2.0. This audit inventories two community-peer lineages — KAOS v0.9.1 (the sibling orchestration framework at `/home/admin/gh/kaos`) and BENE 0.1.0 itself (the rebranded the 0.1.0 predecessor, this repo) — enumerates each peer's verified capability surface, and documents each peer's shortcomings with verbatim, command-level evidence. The subsumption table at the end lists every capability from both peers as a row; the "BENE 2.0 mechanism" column was a skeleton; phase 2 filled all 55 rows in `docs/design/BENE2-DESIGN.md` §4. Every claim below was verified against source (grep/find/read), not docs alone — both peers' CLAUDE.md files are stale on their own MCP tool counts.

> **Co-opetition note (2026-06-14).** Prior versions of this doc framed
> KAOS and the 0.1.0 predecessor as "rivals". We are one OSS community;
> they are peer projects whose ground we share. "Subsume and surpass"
> language is preserved where it appears in cited section headings of
> `docs/design/BENE2-DESIGN.md`, because the design-doc shape there is
> evidence-of-capability-coverage, not competitive ranking. Throughout
> this audit, *rival* → *peer*.

Community-peer framing:
- **Peer 1 — KAOS v0.9.1** ("Kernel for Agent Orchestration & Sandboxing"). Local-first multi-agent orchestration framework; per-agent SQLite-backed VFS, no embeddings/GPU/external services required. Direct sibling of BENE (same lineage: same CLAUDE.md skeleton, same banned-litellm/raw-httpx rules, same AI-feedback policy) but 8 minor versions ahead (v0.9.1 vs BENE v0.1.0) with a much larger mechanism surface: 58 MCP tools vs BENE's 18-claimed/37-actual, plus dream/neuroplasticity/eval-probe/experiment/ideal-state/war-room layers BENE lacks.
- **Peer 2 — BENE 0.1.0 (predecessor lineage)**. Per `.supergoal/phases/phase-1.md`: "Peer 2: the 0.1.0 predecessor ≈ bene 0.1.0 itself (this repo IS the rebranded the 0.1.0 predecessor; original at $PREDECESSOR_SRC)". BENE/the 0.1.0 predecessor's edges over KAOS are the temporal/ durable runtime, the storage/ protocol (sqlite+postgres), and the runtime/ abstraction — while KAOS holds exactly the surfaces BENE lacks (eval probes w/ falsify/verify, dream consolidation, experiment journal, failure diagnose/lookup store, ideal-state artifacts, systemic alerts).

---

## KAOS v0.9.1 inventory

### Module tree (verified via `find kaos/ -maxdepth 2`)

```
kaos/core.py                 Kaos VFS engine (SQLite, PRAGMA journal_mode=WAL, thread-safe)
kaos/schema.py               SQLite schema v9 (additive experiments table)
kaos/blobs.py                Content-addressable blob store
kaos/events.py               Append-only event journal
kaos/checkpoints.py          create/restore/list/diff
kaos/isolation.py            3 tiers: logical | FUSE | Linux namespace
kaos/experiments.py          ExperimentStore — append-only journal of probe/mh_search runs (git sha + lock sha + verdict)
kaos/ideal_state.py          ISA/ISC artifacts (per-criterion pass/fail → plasticity signal)
kaos/intake.py               Dynamic clarifying questions (0..N) before run (`kaos run --ask`)
kaos/memory.py               Cross-agent FTS5/BM25 MemoryStore + memory_hits telemetry
kaos/skills.py               Cross-agent skill library (parameterized templates) + neuroplasticity-weighted ranking
kaos/shared_log.py           LogAct intent → vote → decide consensus log
kaos/ccr/                    runner.py (loop, ToolPermissionPolicy), tools.py, prompts.py
kaos/router/                 gepa.py (GEPA router), providers.py (openai-compat local vLLM raw-httpx,
                             anthropic, claude_code streaming + idle/wall timeouts, agent_sdk),
                             classifier.py (LLM + heuristic), context.py (ContextCompressor), vllm_client.py
kaos/dream/                  cycle.py (replay → weights → narrative), auto.py (inline Hebbian hooks),
                             diagnosis.py (failure taxonomy), signals.py,
                             phases/: associations, consolidation, failures, localize (critical-step),
                             narrative, policies, replay, synthesis, weights
kaos/eval/harness/           Falsifiable-eval primitive: types, stats (bootstrap_diff_ci),
                             manifest (hash-locked ISA.lock.json, LockTamperError),
                             judge (blind, via SurrogateVerifier), verdict, probe (verify()/falsify())
kaos/metaharness/            search, proposer, evaluator, pareto, harness, compactor (AAAK tiered),
                             verifier (SurrogateVerifier), worker (detached bg mh_search), benchmarks/ (incl. arc_agi3)
kaos/obsidian/               VaultExporter (one-way, idempotent) + renderer/templates/assets
kaos/mcp/server.py           MCP server — 58 tools
kaos/ui/                     War-room web UI (Starlette + uvicorn, SSE, warroom.html)
kaos/cli/                    main.py (run/parallel/doctor/eval/experiment groups + no-API-key `demo`, --json), dashboard.py (TUI), diff.py, setup.py
```

Root harness docs: AGENTS.md (modular lazy-load index), AUTONOMY_THRESHOLD.md, EVAL.md, IDEAL_EXPERIENCE.md, tools/agent_senses/ (peek_metrics.sh, run_tests.sh, tail_logs.sh), 13 demo_*_bench dirs, blog/, video_scripts/.

### Key mechanisms

- **v0.9 falsifiable-eval discipline**: pre-registered hash-locked ISA.lock.json kill gates (sha256 allow-list, harness refuses edited locks), mandatory falsification self-test (FULL := B0 must emit [KILL: G1] or probe is inadmissible), blind anonymised judging, ACCEPT/REJECT/VOID verdicts, "no retune-and-rerun"; 6 candidates evaluated in v0.9, zero shipped — REJECT counted as success.
- **Neuroplasticity**: inline synaptic (Hebbian) updates on every skill use / memory hit (dream/auto.py) + batched structural consolidation at agent completion (dream/phases/consolidation.py); weighted FTS ranking in skills.py.
- **Dream cycle**: replay → weights → narrative, dry_run/apply modes, phase timings persisted, episode_signals upserts; plus failure fingerprints with one-time diagnosis and critical-step localization (arXiv:2509.25370 pattern).
- **Meta-harness**: evolutionary proposer over execution traces, Pareto frontier, coevolution spawn + hub sync, ProposerStalled recovery, AAAK compactor (57% claimed savings).
- Research provenance table in README maps each capability to a paper/OSS source (LogAct, CORAL, EvoSkills, MemPalace, claude-mem, Meta-Harness).

### MCP tool count

**58** — `grep -c "Tool(" kaos/mcp/server.py` = 58; 58 unique `name="..."` attrs; README badge says 58. (CLAUDE.md stale: claims "50 tools — held flat in v0.9".) Families: agent_* (18), mh_* (9), dream_* (5), shared_log_* (5), skill_* (5), failure_* (4), experiment_* (4), eval_probe_* (3), ideal_state_* (3), doctor_proposer, systemic_alerts.

---

## KAOS shortcomings

1. **No durable workflow runtime** — `grep -ril 'temporal' kaos/ --include='*.py'` hits only kaos/ui/server.py:678 — a comment '# Edges: wave -> next wave (temporal flow)'. Zero temporalio/workflow-engine imports anywhere. Background mh_search is just a detached OS process (kaos/metaharness/worker.py) with no retry/replay/resume guarantees.

2. **No storage protocol / Postgres path — SQLite hard-wired** — `grep -rni 'postgres|psycopg' kaos/ --include='*.py'` returns one hit: a demo fixture string at kaos/cli/main.py:1021 ('Backfill missing orders from cache into PostgreSQL'). core.py opens sqlite3 directly (9 refs, PRAGMA journal_mode=WAL at core.py:54); no storage abstraction interface exists.

3. **Autonomy ladder is doc-only, unenforced in code** — AUTONOMY_THRESHOLD.md exists at repo root ('Current threshold: SUPERVISED', all 5 gates unchecked) but `grep -rni 'autonomy' kaos/ --include='*.py'` = 0 hits — nothing in the runtime reads or enforces the threshold; flipping to AUTONOMOUS is a manual doc edit.

4. **No context-pollution detection** — `grep -rni 'pollution' kaos/ --include='*.py'` = 0 hits. kaos/router/context.py only does compaction (summarize-old-messages continuation blocks); there is no detection/quarantine of poisoned or degraded context.

5. **No per-agent trust surface** — `grep -rni 'trust' kaos/ --include='*.py'` matches only the words 'trustworthy/untrustworthy' in eval docstrings (kaos/eval/__init__.py:5, kaos/eval/harness/types.py:74). No trust score, reputation ledger, or graduated per-agent capability grants; ToolPermissionPolicy is static per-run.

6. **Eval harness decoupled from the memory/skill substrate** — `grep 'import' kaos/eval/harness/*.py | grep -i 'memory|skills|shared_log'` returns nothing (exit 1). Probe verdicts never write back into MemoryStore/SkillStore; the only durable record is the separate experiments table (kaos/experiments.py) — kaos/eval vs kaos/memory.py share no store.

7. **No multi-granularity memory** — Single flat memory table (kaos/schema.py:121-129) with a 5-value type enum ('observation','result','skill','insight','error'); `grep -n 'granularity|tier' kaos/memory.py` = 0 hits. No working/episodic/semantic hierarchy, no TTL/decay column, one storage granularity for everything.

8. **Eval anchor docs are unfilled scaffolds — ground-truth gate has no ground truth** — EVAL.md: 'Location: tests/golden/ (TODO: populate)' and `ls tests/golden` → 'No such file or directory'. IDEAL_EXPERIENCE.md persona and ideal-session sections are literal 'TODO'. The G13/G14 anchor chain AGENTS.md mandates on cold start is hollow.

9. **War-room UI: no authentication, wildcard CORS** — kaos/ui/server.py:909-910: CORSMiddleware allow_origins=['*']. `grep -ni 'auth|login|password' kaos/ui/server.py` = 0 relevant hits (only LLM token_count SQL fields). Anyone who can reach the port reads all agent traces and project data.

10. **No observability export (OTel/Langfuse)** — `grep -rni 'opentelemetry|otel|langfuse' kaos/ --include='*.py'` = 0 hits. Traces/events live only inside kaos.db; no OTLP exporter, no trace-tier integration despite the engrams/traces being the core asset.

11. **No dollar-cost tracking or budget enforcement** — `grep -ni 'cost' kaos/router/gepa.py kaos/ccr/runner.py` = 0 hits; `grep -rni 'budget'` finds only time budgets (proposer wall budget in router/providers.py:616, time_budget=120 in metaharness/benchmarks/arc_agi3.py:76). No per-agent spend ledger or cost-aware routing despite GEPA claiming 'optimal model' allocation.

12. **No distributed or remote execution — single-host asyncio only** — `grep -rni 'docker|kubernetes|ssh' kaos/ --include='*.py'` = 0 hits. 'Parallel' agents are in-process asyncio.run(ccr.run_parallel(tasks)) (kaos/cli/main.py:561); FUSE/namespace isolation tier explicitly Linux-local only (kaos/isolation.py:84 raises on non-Linux).

13. **Doc drift on its own headline number** — CLAUDE.md states 'kaos/mcp/server.py → MCP server (50 tools — held flat in v0.9)' but `grep -c 'Tool(' kaos/mcp/server.py` = 58 and the README badge says 58 — the canonical agent-facing doc is stale by 8 tools.

14. **Retrieval ceiling: lexical only, no semantic/vector option** — Deliberate but limiting: kaos/dream/phases/synthesis.py:119 'No LLM, no embeddings, deterministic' and consolidation.py:201 'Intentionally cheap — no embeddings. Works on normalised word-bag overlap'; `grep -rni 'embedding|vector'` confirms no optional vector store exists, so cross-agent recall is FTS5/BM25 + word-bag overlap only.

---

## BENE 0.1.0 (predecessor lineage) inventory

Repo: /home/admin/gh/bene-main, audited at commit `6c55fa3 baseline: BENE 0.1.0 post-rebrand` — the initial single-commit 0.1.0 snapshot; main has since advanced to v0.2.0 (16 commits as of 2026-06-11). Schema: 11 tables + 2 FTS5 virtual tables (bene/schema.py: agents, files, blobs, tool_calls, state, events, checkpoints, schema_version, memory(+fts), shared_log, agent_skills(+fts)).

### Module tree

```
bene/
├── core.py                  Bene VFS engine (main class)
├── schema.py                SQLite schema (11 tables, 2 FTS5)
├── blobs.py                 Content-addressable blobs — SHA-256 dedup + zstd
├── events.py                Append-only event journal (audit trail)
├── checkpoints.py           Checkpoint/restore ("time-travel debugging", ULID ids)
├── isolation.py             Isolation tiers: logical | fuse | namespace (fusepy, Linux)
├── memory.py                Cross-agent MemoryStore — FTS5 + porter + BM25, 5 types
├── skills.py                SkillStore — parameterized templates, FTS5, use/success counters
├── skills_discovery.py      */SKILL.md filesystem import
├── shared_log.py            LogAct shared log — intent/vote/decision/commit/result/abort/policy/mail
├── intake.py                Dynamic clarifying-questions step (`bene run --ask`)
├── ccr/                     runner.py (agent loop), tools.py (registry), parallel_worker.py, prompts.py
├── router/                  tier.py (TierRouter), providers.py (OpenAI/Anthropic/Local/ClaudeCode),
│                            agent_sdk.py (Claude Agent SDK), classifier.py (LLM+heuristic),
│                            vllm_client.py (raw httpx), context.py (compaction, preserve-recent-8)
├── mcp/server.py            MCP server — 37 tools (1995 lines)
├── cli/                     main.py (22 top-level commands + mh group; 35 command/group decorators),
│                            dashboard.py (Textual TUI), diff.py, setup.py
├── ui/                      server.py (Starlette web observability dashboard, ?db= multi-project) + static/
├── obsidian/                exporter.py (one-way idempotent vault export), renderer, templates, assets
├── metaharness/             search.py (Algorithm 1, arXiv:2603.28052), proposer.py (CORAL consolidation
│                            heartbeat), evaluator.py, verifier.py (Surrogate Verifier, info-isolated),
│                            pareto.py (multi-objective frontier + dominates()), compactor.py,
│                            situation.py, worker.py (detached bg process), prompts.py, harness.py,
│                            benchmarks/ (base, text_classify, math_rag, agentic_coding, arc_agi3,
│                            paper_datasets)
├── benchmarks/              EMPTY namespace — __init__.py docstring only ("higher-level domain packages")
├── storage/                 protocol.py (Storage + BlobStore Protocols, idempotency_key on every write),
│                            sqlite.py, postgres.py (asyncpg, partition-per-agent)
├── runtime/                 core.py (frozen JSON-safe DTOs), local.py (LocalRuntime test double),
│                            handle.py (RunHandle/TypedQuery), exceptions.py
├── temporal/                workflow.py (AgentWorkflow, signals pause/resume/kill, continue_as_new
│                            @45K-event history budget), activities.py, worker.py, runtime.py (DI globals),
│                            runtime_impl.py
└── integrations/            empty stub (__init__.py only)
```

### Key mechanisms

- **VFS-per-agent in one SQLite file** (files+blobs+events), trace search = `afs.search()` FTS over file contents + `build_index` /index.md (cli `index`/`search`).
- **Litany loop**: checkpoint → diff → restore (checkpoints.py + cli/diff.py + MCP agent_checkpoint/diff/restore).
- **LogAct coordination**: position-ordered shared log w/ intent→vote→tally→decide quorum (shared_log.py).
- **Tier routing**: classifier (trivial/moderate/complex/critical) → provider per tier; providers = openai, anthropic, local (vLLM raw httpx), claude_code subprocess, agent_sdk.
- **Meta-harness breeding**: proposer→AST-validate→parallel evaluate→archive→Pareto frontier; Surrogate Verifier reads output not source (anti-confirmation-bias); detached worker survives parent exit; coevolution + hub sync MCP tools.
- **Durability split**: Storage/BlobStore Protocols with idempotency keys sized for Temporal Activity retries; LocalRuntime ↔ TemporalRuntime parity contract.

### MCP tool count

**37** (verified: `grep -c '"name":' bene/mcp/server.py` → 7 is misleading; `grep -c 'name="'` and `grep -c 'Tool('` both → 37; full list: 15 agent_*, 9 mh_*, 3 agent_memory_*, 5 shared_log_*, 5 skill_*). CLAUDE.md's "18 tools" is stale.

Tests: 29 entries in tests/ incl. storage/, temporal/ subdirs; docs/: 16 md files + tutorials + case-studies.

---

## BENE 0.1.0 shortcomings

1. **No falsifiable-eval harness — no probe/verdict/kill-gate discipline anywhere** — `grep -rn -iE 'eval_probe|falsif|verdict|kill.?gate' bene/` returns zero hits; no eval/ module in bene/ tree; the only evaluation machinery is metaharness/evaluator.py which scores benchmark candidates, not agent claims. Peer KAOS exposes eval_probe_run/verify/falsify.

2. **No experiments journal** — `grep -rn -iE 'experiment' bene/ --include='*.py'` matches only a benchmark sample sentence (bene/metaharness/benchmarks/text_classify.py:267 'protein folding prediction matches experimental results'); no experiment table in bene/schema.py (11 tables: agents, files, blobs, tool_calls, state, events, checkpoints, schema_version, memory, shared_log, agent_skills). KAOS has experiment_log/list/show/compare.

3. **No dream/consolidation cycle over memory** — `grep -rn -iE 'dream|consolidat' bene/ --include='*.py'`: only hits are the metaharness CORAL 'consolidation heartbeat' (bene/metaharness/prompts.py:160 build_consolidation_prompt, proposer.py:249-252) — a periodic prompt nudging the proposer to write skills mid-search, not an offline memory merge/dedupe/abstraction cycle. KAOS has dream_run/consolidate/merges/localize.

4. **Skills are static — no plasticity, decay, versioning, or refinement** — Read bene/skills.py (364 lines): record_outcome() only increments use_count/success_count; no decay/forgetting/pruning/deprecation, no skill mutation or version chain (`grep -rn -iE 'decay|forget|prune|plastic' bene/` matches only text_classify.py:272 sample string 'Neural plasticity enables recovery'). A skill that starts failing is never demoted or retired.

5. **Retrieval is FTS5-only — no embeddings, no granularity tiers, no adaptive fast/slow path** — bene/memory.py search() is a single FTS5 MATCH + BM25 rank query (lines 155-167); bene/skills.py search() likewise (lines 226-238); `grep -rn -iE 'embedding|vector|cosine' bene/ --include='*.py'` returns zero hits. No semantic recall, no recency/importance weighting, no two-stage retrieve-then-rerank.

6. **No context-pollution defense** — `grep -rn -iE 'pollution|quarantine|taint|poison' bene/ --include='*.py'` returns zero hits. bene/router/context.py is token-budget compaction only (summarize old, preserve recent 8, truncate tool results >2000 chars) — no provenance tagging, no untrusted-content quarantine, no injection filtering before memory/skill writes propagate cross-agent.

7. **No autonomy ladder** — `grep -rn -iE 'autonomy' bene/ --include='*.py'` returns zero hits. Agent control surface is binary: run vs pause/resume/kill (bene/temporal/workflow.py signals; MCP agent_pause/resume/kill). No graduated permission tiers, no earn-trust-then-widen-scope mechanism.

8. **No trust ledger / per-agent trust score; shared-log votes are unweighted** — `grep -rn -iE 'trust' bene/ --include='*.py'` returns zero hits; bene/shared_log.py tally()/decide() (lines 200-246) counts approve/reject votes with equal weight per agent and persists no reputation; no trust table in schema.py.

9. **Metaharness has Pareto multi-objective but NO gated promotion** — bene/metaharness/pareto.py implements dominates()/ParetoFrontier (multi-objective EXISTS — the suggested claim 'lacks Pareto' is false); however `grep -n -iE 'promot|gate' bene/metaharness/*.py` returns nothing relevant — every evaluated candidate joins the archive and frontier directly (search.py steps 3c-d), with no held-out validation set, no champion/challenger regression gate, no statistical-significance threshold before promotion.

10. **No persistent failure-pattern store — verifier diagnoses are ephemeral to a search run** — bene/metaharness/verifier.py produces VerifierDiagnosis (root causes, failure_patterns) but only feeds the next proposer iteration; no failure table in bene/schema.py, no project-level failure lookup for ordinary agents. KAOS has failure_diagnose/lookup/list/fix_outcome.

11. **No cost/token budget guardrails on agent or search spend** — `grep -rn -iE 'budget' bene/ --include='*.py'` hits only bene/temporal/workflow.py:73 _HISTORY_BUDGET=45_000 (Temporal event-history size, not money/tokens) and arc_agi3.py time_budget; bene/ccr/runner.py and bene/router/tier.py have no spend caps or per-agent token ceilings.

12. **Doc drift post-rebrand: CLAUDE.md claims 18 MCP tools; server has 37** — CLAUDE.md architecture section: 'bene/mcp/server.py → MCP server (18 tools)'; verified count: `grep -c 'name="' bene/mcp/server.py` → 37 (and `grep -c 'Tool('` → 37). Also stale working-tree artifacts from the old branding: kaos.db / kaos.db-shm / kaos.db-wal at repo root (untracked, but present).

13. **Top-level benchmarks and integrations namespaces are empty shells** — bene/benchmarks/__init__.py is a docstring-only placeholder ('this namespace is for higher-level domain-specific benchmark packages') with no packages; bene/integrations/ contains only __init__.py. The advertised 'benchmarks machinery' lives solely under bene/metaharness/benchmarks/.

---

## Subsumption table (skeleton — now filled: see `../design/BENE2-DESIGN.md` §4 'Subsumption table (complete)')

One row per capability from both peers' verified capability lists. Phase 2 filled the last column (in `docs/design/BENE2-DESIGN.md` §4) with the BENE 2.0 mechanism that subsumes (matches) or surpasses each row.

| # | Peer | Capability | Peer mechanism | BENE 2.0 mechanism (TBD) |
|---|-------|------------|-----------------|--------------------------|
| 1 | KAOS | Per-agent isolated SQLite VFS with audit trail | kaos/core.py, WAL mode | TBD |
| 2 | KAOS | Content-addressable blob store | kaos/blobs.py | TBD |
| 3 | KAOS | Append-only event journal | kaos/events.py | TBD |
| 4 | KAOS | Checkpoint / restore / list / diff | kaos/checkpoints.py | TBD |
| 5 | KAOS | Three isolation tiers: logical, FUSE-mounted VFS, Linux mount-namespace | kaos/isolation.py | TBD |
| 6 | KAOS | Dream cycle consolidation (replay → weights → narrative, dry_run/apply, persisted phase timings) | kaos/dream/cycle.py + 9 phase modules | TBD |
| 7 | KAOS | Neuroplasticity (inline Hebbian hooks on skill use/memory hit + batched structural consolidation) | kaos/dream/auto.py, kaos/dream/phases/consolidation.py, weighted ranking in kaos/skills.py | TBD |
| 8 | KAOS | Failure intelligence — fingerprints, one-time taxonomy diagnosis, fix-outcome tracking | kaos/dream/diagnosis.py; MCP failure_diagnose/lookup/list/fix_outcome | TBD |
| 9 | KAOS | Critical-step localizer (earliest decisive wrong step in failed trajectory) | kaos/dream/phases/localize.py, arXiv:2509.25370 | TBD |
| 10 | KAOS | Falsifiable eval harness with hash-locked pre-registered kill gates, blind judge, ACCEPT/REJECT/VOID | kaos/eval/harness/: manifest.py (ISA.lock.json sha256 allow-list, LockTamperError), probe.py falsify(), judge.py, verdict.py, stats.py | TBD |
| 11 | KAOS | Experiments journal (probe/mh_search runs w/ git sha + lock sha256 + verdict + per-arm stats) | kaos/experiments.py ExperimentStore, schema v9 | TBD |
| 12 | KAOS | Ideal State Artifacts (ISA/ISC) — per-criterion pass/fail feeding plasticity quality scores | kaos/ideal_state.py, schema v8 | TBD |
| 13 | KAOS | GEPA model router across 5 providers (local vLLM raw httpx, openai-compat, anthropic, claude_code, agent_sdk) | kaos/router/gepa.py, providers.py, agent_sdk.py | TBD |
| 14 | KAOS | LLM + heuristic task-complexity classifier for routing | kaos/router/classifier.py | TBD |
| 15 | KAOS | Context compression (continuation-summary blocks + AAAK tiered archive compactor) | kaos/router/context.py ContextCompressor; kaos/metaharness/compactor.py | TBD |
| 16 | KAOS | War-room web UI with SSE, Gantt/wave views | kaos/ui/server.py (Starlette/uvicorn), static/warroom.html | TBD |
| 17 | KAOS | TUI dashboard and no-API-key `kaos demo` mode | kaos/cli/dashboard.py | TBD |
| 18 | KAOS | Parallel agent execution | kaos parallel CLI, asyncio run_parallel, MCP agent_parallel (kaos/cli/main.py:545-561) | TBD |
| 19 | KAOS | Full agent lifecycle control via MCP (spawn, spawn_only, pause, resume, kill, status, query, read/write) | 18 agent_* MCP tools | TBD |
| 20 | KAOS | Cross-agent FTS5 memory with BM25 search and per-hit telemetry | kaos/memory.py, memory + memory_hits tables | TBD |
| 21 | KAOS | Cross-agent skill library (parameterized templates, usage/success tracking, FTS5 porter search) | kaos/skills.py | TBD |
| 22 | KAOS | SharedLog consensus coordination (intent → vote → decide, LogAct protocol) | kaos/shared_log.py | TBD |
| 23 | KAOS | Obsidian vault export (one-way, idempotent) | kaos/obsidian/exporter.py VaultExporter | TBD |
| 24 | KAOS | Dynamic intake — LLM-analyzed clarifying questions (0..N) before run, --intake-only JSON preview | kaos/intake.py | TBD |
| 25 | KAOS | Meta-harness evolutionary search (trace-reading proposer, Pareto frontier, detached bg worker, ProposerStalled recovery) | kaos/metaharness/search.py, pareto.py, worker.py | TBD |
| 26 | KAOS | Surrogate Verifier — isolated structured failure diagnostics, reused as blind eval judge | kaos/metaharness/verifier.py | TBD |
| 27 | KAOS | Co-evolution — coevolution spawn + periodic hub sync skill/discovery sharing | MCP mh_spawn_coevolution + mh_hub_sync (kaos/mcp/server.py:365-381) | TBD |
| 28 | KAOS | Doctor proposer + systemic alerts surfacing cross-agent issues | MCP doctor_proposer, systemic_alerts; kaos/dream/auto.py | TBD |
| 29 | KAOS | Permission-aware tool execution (denied tools inject errors so the LLM adapts) | ToolPermissionPolicy, kaos/ccr/runner.py:6,99-103 | TBD |
| 30 | KAOS | Benchmarks incl. ARC-AGI-3 game harness + 13 demo_*_bench suites | kaos/metaharness/benchmarks/arc_agi3.py | TBD |
| 31 | KAOS | MCP server exposing 58 tools; CLI with --json on all commands | kaos/mcp/server.py; kaos/cli/main.py | TBD |
| 32 | KAOS | Harness-engineering doc scaffold (AGENTS.md modular index, AUTONOMY_THRESHOLD.md, EVAL.md, IDEAL_EXPERIENCE.md, agent_senses scripts) | repo-root docs + tools/agent_senses/ (peek_metrics.sh, run_tests.sh, tail_logs.sh) | TBD |
| 33 | BENE 0.1.0 | VFS isolation per agent in single SQLite db, 3 tiers: logical / FUSE / Linux namespace | bene/isolation.py (fusepy optional extra) | TBD |
| 34 | BENE 0.1.0 | Checkpoints / diff / restore time-travel | bene/checkpoints.py, bene/cli/diff.py, MCP agent_checkpoint/agent_diff/agent_restore/agent_checkpoints | TBD |
| 35 | BENE 0.1.0 | Append-only event journal for full auditability | bene/events.py EventJournal | TBD |
| 36 | BENE 0.1.0 | Content-addressable blob store, SHA-256 dedup + zstd compression | bene/blobs.py | TBD |
| 37 | BENE 0.1.0 | Cross-agent memory with SQLite FTS5 porter/BM25 search, 5 typed entries | bene/memory.py MemoryStore | TBD |
| 38 | BENE 0.1.0 | Skill library: parameterized templates, FTS5 search, success/use counters, SKILL.md discovery import | bene/skills.py, bene/skills_discovery.py | TBD |
| 39 | BENE 0.1.0 | Shared coordination log (LogAct): intent/vote/decision/commit/result/abort/policy/mail with quorum tally | bene/shared_log.py | TBD |
| 40 | BENE 0.1.0 | Tier model router with LLM+heuristic complexity classifier | bene/router/tier.py, classifier.py | TBD |
| 41 | BENE 0.1.0 | Providers: openai, anthropic, local vLLM via raw httpx, claude_code subprocess, agent_sdk | bene/router/providers.py, agent_sdk.py, vllm_client.py | TBD |
| 42 | BENE 0.1.0 | Context compaction: summarize-old / preserve-recent-8 / truncate-tool-results | bene/router/context.py | TBD |
| 43 | BENE 0.1.0 | MCP server with 37 tools (15 agent_*, 9 mh_*, 3 memory, 5 shared_log, 5 skill) | bene/mcp/server.py (1995 lines) | TBD |
| 44 | BENE 0.1.0 | CLI: 22 top-level commands + mh group (35 command/group decorators), all --json | bene/cli/main.py | TBD |
| 45 | BENE 0.1.0 | Web UI: Starlette observability dashboard, read-only multi-project ?db= | bene/ui/server.py + static/index.html | TBD |
| 46 | BENE 0.1.0 | TUI dashboard via Textual | bene/cli/dashboard.py (textual>=0.50) | TBD |
| 47 | BENE 0.1.0 | Obsidian vault export, one-way idempotent | bene/obsidian/exporter.py + renderer/templates/assets | TBD |
| 48 | BENE 0.1.0 | Meta-harness evolutionary search: proposer/evaluator/Pareto frontier/Surrogate Verifier (output-only, info-isolated)/compactor/situation/CORAL consolidation heartbeat/detached worker/coevolution+hub-sync | bene/metaharness/ | TBD |
| 49 | BENE 0.1.0 | Bundled benchmarks: text_classify, math_rag, agentic_coding, arc_agi3, paper_datasets (top-level bene/benchmarks/ is an empty placeholder) | bene/metaharness/benchmarks/ | TBD |
| 50 | BENE 0.1.0 | Temporal durable runtime: AgentWorkflow w/ pause/resume/kill signals, Activities for all side effects, continue_as_new at 45K-event history budget | bene/temporal/ (temporalio>=1.6) | TBD |
| 51 | BENE 0.1.0 | Storage protocol abstraction with idempotency keys: SQLite + Postgres/asyncpg backends, BlobStore protocol | bene/storage/protocol.py, sqlite.py, postgres.py | TBD |
| 52 | BENE 0.1.0 | Runtime abstraction: frozen JSON-safe DTOs + LocalRuntime test double contractually identical to TemporalRuntime | bene/runtime/core.py, local.py, handle.py | TBD |
| 53 | BENE 0.1.0 | Intake step: dynamic clarifying questions before run, 0..N, via `bene run --ask` | bene/intake.py | TBD |
| 54 | BENE 0.1.0 | Parallel agent execution + detached background mh_search | bene/ccr/parallel_worker.py, MCP agent_parallel, bene/metaharness/worker.py | TBD |
| 55 | BENE 0.1.0 | Trace search: FTS over VFS file contents + per-agent /index.md generation | cli `search`/`index`, afs.search | TBD |
