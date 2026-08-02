The key facts are confirmed against the live code and copy. I have everything needed to compute final verdicts and synthesize. Here is the report.

# BENE Landing-Page Due-Diligence Report

## Verdict

The landing is **substantially honest at the primitive level and overstated at the competitive level.** Every core internal mechanism it advertises — the sha256-locked kill gate, the 5-tier engram ladder, mandatory provenance, the computed 4-signal trust ledger, the human-only L4 tier, the single-file SQLite substrate, the 37-tool MCP server, structural per-agent isolation, and the intent→vote→decide SharedLog — is real, wired into production paths, and survived empirical adversarial testing. The novelty claim ("the 4 production gaps... most agent stacks haven't picked them up yet") is **defensible only at a narrow, specific bar and overstated at the broad bar it actually uses on the page**: G1 (eval-gated ship), G2 (tiered/shared/searchable memory), and G4 (SQLite as agent state) are all table-stakes or near-table-stakes in named mainstream frameworks today; only G3 (autonomy *computed* from the audit trail and gating capability) and the precise *hash-locked, tamper-refusing, admissibility-tested* variant of G1 are genuinely unmatched natively. The honest move is to keep the mechanisms, narrow the "they haven't" framing, and fix a handful of copy-paste-broken recipes.

## Internal: does the code deliver?

Final verdict = `refute.revised_verdict` where the refutation fired, else original. Empirical runs weighted above code-read.

### VERIFIED

| Claim | Final | Evidence | Note |
|---|---|---|---|
| `promote()` raises `PromotionBlocked` until a sha256-locked probe says ACCEPT; CI halts on the exception (GAP1) | VERIFIED | `gepa.py:188-210` live SQL JOIN for a `verifies`-linked ACCEPT eval engram, else raise; `gates.py:48-49` sha256 lock; `probe.py:136-141` dual tamper check → `LockTamperError`. Empirically reproduced end-to-end. | "CI halts" is true in the test-assertion sense; an unhandled `PromotionBlocked` (a real `PermissionError`) does propagate. Accurate. |
| Plain single SQLite file; sqlite3/cp/rsync/diff work; no client lib; 4-line python reads engrams (GAP4) | VERIFIED | `bene demo` produced one regular `story.db` (no -wal/-shm); bare system python read 12 engrams; reading from a dir where `import bene` fails still works; cp byte-identical, rsync round-trips. | Only nuance: `sqlite3` CLI binary not installed on host, but file is vanilla SQLite3. |
| `register_probe` seals spec under sha256 (B2-1) | VERIFIED | `probe.py:74-95` writes `gate_spec`+`lock_sha256`; stored == recomputed; tamper enforced. | API is `Probe(name,gates,fn).register(...)`, not a free `register_probe(target,fn)` — paraphrase, not a defect. |
| Verdict itself lands as a re-readable engram (B2-4) | VERIFIED | `verdict.py:38-88` appends `eval` engram + `verifies`/`refutes` link + `experiment_runs` row; read back across process boundaries via `bene experiments ls/show`. | Both probe-lock AND verdict are engrams in `bene.db`. |
| `mh_search` exists and produces candidates (B5-1) | VERIFIED | Real keyed run: 3 seeds + 2 LLM-proposed candidates, interface-validated, scored. | Real flag is `-b/--benchmark` (3-choice enum), not landing's `--target`. |
| Genome encoding + Pareto front (B5-2) | VERIFIED | `gepa.py:44-91`, `genes.py:15-51`, `pareto.py:65-95`; `bene demo` printed "frontier 5"; 18 tests pass. | Two frontier impls (mh `ParetoFrontier`, evolve `GenomeFrontier`), same `dominates()`. |
| `promote()` is the single kill gate; no alternate entry (B5-3) | VERIFIED | All 4 entry points converge on `gepa.promote()`; no bypass. | See B5-5 below for the one real caveat (forged engram). |
| Self-disclosure: mh→promote bridge is manual today, e2e on roadmap (B5-4) | VERIFIED | `auto_promote` defaults `False` (`harness.py:156`); CLI/worker expose no flag. Disclosure is accurate and slightly *conservative*. | Honest-and-understated. Good. |
| Engram ladder: tiers 0-4, promotion never mutates sources, provenance mandatory, FTS/lineage (B1) | VERIFIED | All 5 sub-claims reproduced against real schema; `promote()` at `engrams.py:341` called from `distill.py:89`, `granules.py:50`; real `bene consolidate` CLI. | Note this is the *narrower* B1 wording; see GAP2 refutation for why the broader "every run" phrasing is OVERSTATED. |
| ContextOS pollution detector runs 3 signals (B3-pollution) | VERIFIED | `pollution.py:53-106` computes all 3 from audit trail; wired into `bene memory rehighlight` + `bene demo`; thresholds 3/0.5/0.5 reproduced. | |
| 4 trust signals computed from trail, fold to [0,1] composite (B4-signals) | VERIFIED | `trust.py:32-133`, no yaml/env reads; hand-recomputed half-life-20 recency formula matched exactly (order-sensitive, not hardcoded). | Landing's "audit=review hit rate / checkpoint=rollback freq" are loose mislabels of `audit_completeness` / `checkpoint_discipline`. |
| L4 human-only; L0-L4 enforced in code (B4-L4-human) | VERIFIED | `autonomy.py:51-55` raise unless `granted_by` starts `human:`; enforced at `CapabilityRegistry.dispatch` (`capabilities.py:105-122`); DB CHECK 0..4; adversarial prefixes all rejected. | Code-enforced, not markdown. Strong. |
| MCP server registers 37 tools (MCP-1) | VERIFIED | `server.py`: 37 `Tool(` = 37 `name=` = 37 dispatch branches, perfect bijection; empirical `list_tools()` → 37. | Exact, not rounded. |
| `bene serve --transport stdio` → 37-tool MCP server (R8) | VERIFIED | `initialize` returned `serverInfo.name=bene`; `tools/list` → 37. | `claude mcp ls` is a stale Claude-CLI subcommand (`list` is correct) — not a BENE defect. |
| Per-agent SQLite VFS, structural isolation, diff/restore (ISO-1) | VERIFIED | `core.py:268/284` every query carries `WHERE agent_id=?`; `LogicalIsolation` bakes agent_id, methods take no agent_id param; isolation/diff/restore reproduced. | `Bene.query()` is a deliberate global read-only escape hatch; does not contradict the per-agent VFS claim. |
| SharedLog intent→vote→decide, replayable (ISO-2) | VERIFIED | `shared_log.py` 379 lines real; reproduced `{'passed':True,'approve':2}`; idempotent `decide()`, append-only positions, exposed over MCP (5/37 tools). | Full LogAct-style loop. |
| L4 human-only ladder (B4 dup) / DSPy promotion-gate framing — *see Competitive* | — | — | — |

### PARTIAL

| Claim | Final | Evidence | Note |
|---|---|---|---|
| 4 signals fold to composite; L4 needs human grant or API raises; **no YAML flag changes it** (GAP3) | PARTIAL | Core mechanisms confirmed empirically. But a `bene.yaml` `kernel.autonomy.grants` entry with `level:4 + granted_by:'human:eddie'` **does** flow through to L4. | True invariant is "L4 always needs a `human:` prefix," not "YAML cannot reach L4." Only `default_level` is hard-capped 0..3. Soften the copy. |
| `promote()` yields ACCEPT/REJECT/VOID; VOID = failed to beat baseline (B2-2) | PARTIAL | `promote()` returns the verdict engram id or raises — it does NOT return the tri-state. VOID = probe **inadmissible/unobservable**, not "failed to beat baseline" (that's REJECT). | Landing parenthetical "VOID = failed to beat baseline" (index.html:577) is **inaccurate**. |
| Tamper the spec → REJECT (B2-3) | PARTIAL | Tamper raises `LockTamperError` (a hard refuse-to-run, both directions) — stronger than REJECT, but the landing's "the probe REJECTs" is the wrong label. | Same protective outcome; imprecise verdict label. |
| ContextOS drops lowest-priority at assemble; NOT silently truncated; manifest records included+dropped (B3-contextos) | PARTIAL | Budget cap + manifest real and wired (`runner.py:302`). But "lowest-priority" holds only for relevance-topk (default is recency=oldest); compress-then-pack **does** truncate per-item; and a `id()`-identity bug makes the dropped-list report all items as both included+dropped for that strategy. | Real bug, slightly worse than the original caveat. |
| R3 gate-the-promote recipe (B-R3) | PARTIAL | `experiments show <run>` works, ACCEPT verdict is real/falsifiable. But grep returns **2 lines** not "one line," and bare command hits empty local db (needs `--db`). | Underspecified placeholders. |
| R4 compound memory recipe (R4) | PARTIAL | `bene memory search` (FTS5) works and persists across runs; but demo seeds **0** memory rows, so "hits from prior sessions" never come from the demo. | Plus a FK gotcha: `memory write <id>` needs an already-spawned agent. |
| R6 escalate-autonomy recipe (R6) | PARTIAL | `bene trust show <agent>` **fails** (`show` is spurious); correct form `bene trust <id>` returns composite in [0,1]. Demo footer itself prints the correct form, contradicting the recipe. | Mechanism real; printed command wrong. Note: returns vacuous all-1.0 for an agent absent from db. |
| R7 breed-a-strategy recipe (R7) | PARTIAL | Both printed commands fail (`--target` not a flag; `frontier` needs `SEARCH_AGENT_ID`). Corrected form works and returns real Pareto JSON. Honestly disclosed as roadmap. | Under-specified, but disclosed. |

### OVERSTATED

| Claim | Final | Evidence | Note |
|---|---|---|---|
| "Every run leaves typed engrams on a 5-tier ladder" (GAP2 lead) | OVERSTATED | Empirical: a default `run_agent` produces **0 engrams** (the `engrams` table isn't even created unless loop_guard requested); what persists is 8 `events` rows. Engram production is **opt-in** (attach_kernel mirroring, loop-guard interventions, demo/CLI), not universal-per-run. | The mechanism is real but conditional. Landing's "writes every turn as that kind of engram by default" (index.html:339, contract #2) overstates an available mechanism as an automatic one. **Fix the copy.** |
| "sha256-locked probe says ACCEPT (no back door)" (B2-5/B5-5) | OVERSTATED | The lock guards verdict **production** (Probe.run), not promotion **consumption**. `promote()` only queries for an `eval` engram linked `verifies` with `metadata.status=='ACCEPT'` — it never consults `probe_registry`/`lock_sha256`. A forged engram via the public `store.append`+`store.link` promotes with no probe run, no lock. | "No back door" does not hold for any in-process caller with a store handle. This is the most material internal overstatement. |
| Trust signals DRIVE L0-L3 auto-promotion (B4-auto-promote / GAP3 feature-card) | OVERSTATED | `trust.eligible()` is self-documented "Advisory" and has **zero** production callers. Every level change is an explicit human/config `grant()`. Nothing reads trust/probes and calls `grant()`. Empirically: composite 0.875 yet `level_for==0` until an explicit human grant. | index.html:625 "these tiers auto-promote when probes pass" is false. The headline GAP3 (the 4 signals list) is fine; this deeper narrative oversells. |

### FALSE

| Claim | Final | Evidence | Note |
|---|---|---|---|
| R5 recipe `ctx = ContextOS(budget=8192)` + verify grep `context_budget` (B3-recipe-R5 / R5) | FALSE | `ContextOS(budget=8192)` raises `TypeError` (budget is an arg to `.assemble`, not `__init__`); `bene senses --md|grep context_budget` always exits 1 (no such key in the manifest). | Copy-paste-broken snippet; `site/SKILL.md:183` correctly uses `ContextOS()`. Underlying budget mechanism is real. |
| R2 recipe `bene log show --topic plan/v1` (R2) | OVERSTATED (was FALSE) | `bene log show` and `--topic` exist nowhere — the recipe tests a fabricated command. The **actual** documented R2 verify (`bene log tail --n 5`) works and seeds real intent/vote/decision rows. | Feature is present and wired; the verdict's FALSE framing was a strawman. The printed command is still wrong. |
| Drop-in adapters for LangGraph/CrewAI/AutoGen/smolagents/DSPy/Letta (INT-1) | FALSE | `bene/integrations/__init__.py` is `__all__ = []`. No adapter classes/functions, no integration tests, no optional deps. The named hooks ("crew.kickoff()→engram batch", "Letta memory-block mirroring", "DSPy.compile registration") have **zero** backing code. | Aspirational methodology copy (React strings, index.html:396-401), not shipped adapters. **Relabel as "patterns you implement," not adapters.** |

### ROADMAP_DISCLOSED (honest-but-not-shipped — this is good)

| Claim | Final | Note |
|---|---|---|
| mh_search→promote end-to-end bridge is manual today, e2e wiring on roadmap (B5-4) | VERIFIED disclosure | Accurate and conservative — the auto-path is actually shipped-but-default-off; landing understates how complete it is. Keep. |
| R7 "bridge is manual today, end-to-end wiring on roadmap" | VERIFIED disclosure | Same. Honest. |

### Demo-UX correction (R0)

`R0-demo-seeds-separate-db` was **refuted → VERIFIED**: the landing's "run the demo, if it exits 0..." refers to the demo's *own* output and exit code (and the demo prints the `--db <tempdb>` to inspect), not bare local-db verify commands. The empty `./bene.db` after demo is real but irrelevant to what the copy states. However R1-R6 recipe friction (commands hit empty `./bene.db` without `--db`, or use spurious subcommands) remains a real UX/copy gap.

## Competitive: have the popular frameworks caught up?

Per the 4 gaps, weighting cited web-research findings above code-read.

### G1 — Eval scoring ≠ promotion gating: **OVERSTATED** (broad), **VERIFIED** (narrow hash-locked variant)

The broad framing ("frameworks haven't picked up a falsifiable eval gate that hard-blocks ship") is **false for several named frameworks**:

- **Letta (MemGPT lineage, named in-scope):** first-class declarative `gate:` primitive (`kind: simple, op: gte, value: 0.95`), exit 0/1, "block pull requests that break agent behavior." Shipped ~a year before BENE's claim. — https://docs.letta.com/guides/evals/concepts/gates , https://www.letta.com/blog/letta-evals
- **Google ADK (named):** native `test_config.json` `criteria` thresholds; `agent_evaluator.py` `EvalStatus.FAILED` → `assert` → pytest fails → CI blocks. — https://adk.dev/evaluate/criteria/ , https://adk.dev/evaluate/
- **DSPy/GEPA (named, the exact algorithm BENE models on):** GEPA **does** hard-refuse to promote a mutated candidate that fails to beat its parent on the minibatch gate (ICLR-2026 paper Algorithm 1 line 16; runtime "score is not better, skipping"). The original finding's "DSPy just returns the best candidate" was **factually wrong** (this is why G1-dspy was refuted VERIFIED→PARTIAL). — https://arxiv.org/html/2507.19457v1 , https://dspy.ai/api/optimizers/GEPA/overview/
- **Pydantic Evals / LlamaIndex (named):** native boolean assertions marketed as "quality gates" (Pydantic); LlamaIndex computes first-party `EvaluationResult.passing` with `assert eval_result.passing` — the original "external harness" characterization was wrong (G1-pydantic refuted PARTIAL→OVERSTATED). — https://pydantic.dev/docs/ai/evals/evaluators/overview/

**Partial-block (CI-recipe, not native default):** LangGraph/LangSmith (DIY pytest assert + branch protection; LangChain admits it's still building a GitHub Action), OpenAI Agents SDK (Promptfoo cookbook, default = human review; OpenAI is *retiring* hosted Evals/graders), CrewAI (`crewai test` scores only; the gate-before-rollout is an unmerged docs-only PR #6140), AutoGen/AG2 ("built for measurement, not assertion"; user wraps `diff.regressions` in a pytest assert). These four genuinely lack a *native* block primitive — for them "score but don't block by default" holds (PARTIAL).

**Genuinely differentiated (G1-hashlock, VERIFIED):** No mainstream framework binds promotion to a *pre-registered, sha256-locked, tamper-refusing* probe spec with a *falsifiability/admissibility (D6) self-test* that registers VOID for a gate that can't kill its own baseline. The only analogs are research artifacts (RewardHackingAgents `evalhashlock`, arXiv:2603.11337) and standalone signed-benchmark/audit-chain tools (verievals, signet) — none are named in-scope frameworks. Promptfoo/Braintrust thresholds are explicitly *tunable/editable*, not locked.

**Net G1:** the bare "gate-and-block" is mainstream; BENE's hash-locked + admissibility-tested + verifier-isolated + provenance-linked + in-process-`PromotionBlocked` *conjunction* is unmatched natively. **Landing's "they haven't picked it up" is overstated; the specific sliver is real.**

### G2 — Cross-agent typed/provenance-mandatory/immutable tiered memory: **PARTIAL** (overstated as a bundle)

Decompose the bundle:

- **Tiered ladder — FALSE as novel.** Letta (core/recall/archival), LangMem (semantic/episodic/procedural with consolidation), CrewAI (short/long/entity), Mem0 (user/session/agent) all ship tiered memory with cross-tier consolidation. 5 tiers vs 3 is a design detail. — https://atlan.com/know/best-ai-agent-memory-frameworks-2026/ , https://www.langchain.com/blog/langmem-sdk-launch
- **Cross-agent shared + greppable — OVERSTATED as novel.** Native in Letta (shared memory blocks), CrewAI ("all agents share the crew's memory," with a `source` provenance param), LangGraph (`BaseStore.put/search`). — https://docs.letta.com/guides/agents/multi-agent-shared-memory/ , https://docs.crewai.com/en/concepts/memory , https://docs.langchain.com/oss/python/langgraph/memory
- **Searchable/typed — FALSE as novel.** Universal table-stakes (LangGraph semantic `BaseStore.search`, Letta `archival_memory_search`, Mem0 hybrid retrieval, Graphiti hybrid).
- **Mandatory provenance + immutable source — PARTIAL.** Genuinely **absent natively from the 7 lighter named frameworks** (OpenAI SDK, ADK, LlamaIndex, smolagents, DSPy, Pydantic AI, AutoGen/AG2 — Atlan 2026: "None of these frameworks provide [lineage]"); Letta has no per-edit provenance, CrewAI's `source` is *optional*, Mem0's `actor_id` is *optional*. **But** the popular plug-in memory layer **Zep/Graphiti** delivers the load-bearing combo — provenance intrinsic ("everything traces back to episodes"), immutability ("old facts invalidated, not deleted"). Graphiti is framework-agnostic and plugs into all of these. — https://github.com/getzep/graphiti , https://atlan.com/know/best-ai-agent-memory-frameworks-2026/

**Net G2:** cross-agent + tiered + searchable = table-stakes. The *mandatory-provenance + immutable-source* conjunction is genuinely rare among the **named agentic frameworks** but **not unique** in the broader mainstream memory ecosystem (Zep/Graphiti, Mem0ᵍ). BENE's *full* 5-property bundle (adds kill-gated promotion + "why it shipped" decision provenance) is more novel than any single competitor, but the page oversells the individual properties.

### G3 — Autonomy *computed* from the audit trail that *gates* capability: **VERIFIED** (on its stated scope)

This is BENE's strongest competitive claim. Across all 5 named frameworks, gating is **human-set/config**, never computed from the agent's own audit trail:

- **LangGraph:** hand-written `interrupt()` + compile-time `interrupt_before/after`; only "computed" branching is a developer-hardcoded `if confidence < 0.8`. (Caveat: the original finding cited a third-party PyPI package `langgraph_agentmesh` that **does not exist** — strike that citation; the conclusion stands on the LangGraph docs alone.) — https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- **CrewAI:** `human_input=True` flag + human-assigned RBAC; native trust-from-history was **closed as not-planned** (issue #5562). — https://docs.crewai.com/en/concepts/tasks
- **AutoGen/AG2:** `human_input_mode` enum (ALWAYS/TERMINATE/NEVER); RFC discussion only, unshipped.
- **OpenAI Agents SDK:** per-call guardrail tripwires + human-approval interruptions; "no mechanism to compute confidence scores [or] graduate to higher autonomy levels." — https://openai.github.io/openai-agents-python/guardrails/
- **Google ADK:** Tool Confirmation + developer-written policy engines; open governance issues (#4764/#4910) confirm no native trust gate. — https://adk.dev/safety/

**Caveat (moat is narrower than the copy implies):** computed-trust-from-behavior gating now ships as a *first-party framework-agnostic add-on* — Microsoft Agent Governance Toolkit (April 2026: dynamic 0-1000 trust score, 5 tiers, trust-tiered capability gating, kill switch) — and as a published spec (CSA Agentic Trust Framework v0.9.1 Public Review). Neither is native to any of the 5 named frameworks, so the scoped claim survives, but "research moved past this / they haven't picked it up" is closer to "the ecosystem is one integration-hook away." — https://github.com/microsoft/agent-governance-toolkit , https://cloudsecurityalliance.org/blog/2026/02/02

**Net G3:** VERIFIED that the *audit-derived composite + earned ladder + hard human-only top tier* is unmatched **natively** in the named frameworks. This is BENE's most defensible differentiator.

### G4 — A single portable SQLite file as source of truth: **OVERSTATED** (broad), **PARTIAL** (narrow union)

- **SQLite-as-agent-state — OVERSTATED.** Native in LangGraph (`SqliteSaver`), OpenAI Agents SDK (`SQLiteSession`), CrewAI (long-term SQLite), Google ADK (`DatabaseSessionService` sqlite). The single-file/`cp`/no-server pitch is a *named 2026 pattern* (Turso AgentFS: "entire agent runtime in a single SQLite file... `cp agent.db snapshot.db`"). — https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver , https://openai.github.io/openai-agents-python/sessions/ , https://github.com/tursodatabase/agentfs
- **"Server-backed / needs a client or portal" — OVERSTATED (refuted).** Most named frameworks ship **no-server, no-client, no-portal** file persistence: OpenAI `SQLiteSession` ("no external infrastructure"), AutoGen `save_state`→`json.dump`, LlamaIndex `Context.to_dict()`, LangGraph `SqliteSaver` ("no separate server process"), ADK local sqlite. Only **Letta** is genuinely server-first (and even it exports a portable `.af` file). BENE's single-file persistence is a **commodity**, not a differentiator.
- **The unified scope — PARTIAL (the part that holds).** No mainstream framework writes **state + cross-agent decisions + traces + eval verdicts + trust** to **one** server-free file: LangGraph pairs checkpoints with cloud LangSmith for traces+evals; CrewAI splits ChromaDB vs SQLite; OpenAI `SQLiteSession` is "conversational exchanges, not eval verdicts/trust/cross-agent decisions." Closest neighbors (Turso AgentFS ~2/5, agent-replay ~3/5) are niche/beta. The **intent→vote→decide cross-agent vote ledger as a first-class auditable table** is the most differentiated G4 sub-claim (CrewAI's "consensus voting" is an unimplemented enum that raises `NotImplementedError`).

**Net G4:** the headline ("most agent stacks haven't picked up a single SQLite file") is the **weakest competitive claim** — 4+ named frameworks ship it. The *unified five-domain single file* is genuinely uncommon, but a crowded design space.

## Overstated or false claims to fix (landing-copy level)

1. **Gap 4 headline / "they haven't picked up a single SQLite file."** Multiple named frameworks ship SQLite-backed file state. **Rewrite to the part that's true:** "one file holds state *and* cross-agent decisions *and* traces *and* eval verdicts *and* trust — no second store, no cloud dashboard for the receipts." Drop the implication that file-based state itself is novel.
2. **Gap 2 / Contract #2: "every run leaves typed engrams... writes every turn by default."** Empirically a default run produces 0 engrams. **Soften to:** "opt into engram capture (attach_kernel / kernel runs) and every turn lands as a typed, provenance-linked engram." Or wire engram emission into the default `run_agent` path so the copy becomes true.
3. **"no back door" on the kill gate (Contract #3 / Gap 1).** A forged `eval`+`verifies` engram via the public store API promotes with no probe run. **Either** make `promote()` re-verify the `lock_sha256`/`probe_registry` linkage, **or** drop "no back door" and say "promotion requires an ACCEPT verdict on record." Don't claim tamper-proofness the consumption path doesn't enforce.
4. **"these tiers auto-promote when probes pass" (index.html:625).** No autonomy auto-promotion exists; `trust.eligible()` has zero callers. **Delete the auto-promotion sentence**; keep "trust is computed and advisory; grants are explicit."
5. **"VOID = failed to beat baseline" (index.html:577).** Wrong — that's REJECT. **Fix to:** "VOID = the probe is inadmissible (a gate that can't kill its own baseline)."
6. **"Tamper the spec, the probe REJECTs" (Contract #3).** It *raises* `LockTamperError` (refuses to run) — stronger and more accurate. **Say "refuses to run."**
7. **"No YAML knob for [L4]" (Contract #4).** YAML *can* grant L4 *with* a `human:` prefix. **Fix the invariant to:** "L4 always requires `granted_by='human:<name>'`; no config flag bypasses that." (Only `default_level` is hard-capped at 3.)
8. **Integration "recipes" (03 Plays well with your toolbox).** No adapters exist in `bene/integrations/` (it's `__all__=[]`). **Relabel from adapters to "patterns you implement with BENE's primitives,"** or build the adapters. Remove the named-hook specifics (`crew.kickoff()→engram batch`, Letta memory-block mirroring, DSPy.compile registration) until backed by code.
9. **Broken recipe snippets:** R5 `ContextOS(budget=8192)` (TypeError — use `ContextOS()`, budget is an `assemble()` arg) and the `grep "context_budget"` verify (never matches); R2 `bene log show --topic` (use `bene log tail --n 5`); R6 `bene trust show` (use `bene trust <id>`); R7 `--target` (use `-b <benchmark>`) and `frontier` needs `SEARCH_AGENT_ID`; R3 "one line" (grep returns two). Add `--db` to bare verify commands or instruct users to seed before verifying.

## What's genuinely differentiated (survived scrutiny)

1. **Hash-locked, tamper-refusing, admissibility-tested kill gate (G1 narrow).** sha256-locked probe spec at registration; `LockTamperError` both directions on tamper; D6 self-test → VOID for a gate that can't kill its own baseline; verdicts persisted as re-readable engrams. **No named mainstream framework ships this conjunction natively** — only research artifacts do.
2. **Autonomy computed from the audit trail that gates capability, with a hard human-only top tier (G3).** A 4-signal [0,1] composite derived from the audit trail (not config), an earned L0-L3 *advisory* ladder, and an L4 that the API refuses without `granted_by='human:<name>'`, enforced at the single capability-dispatch boundary. **Unmatched natively across LangGraph/CrewAI/AutoGen/OpenAI SDK/ADK** (the closest analogs are an external Microsoft add-on and a draft CSA spec, neither native).
3. **Verifier-isolated, provenance-linked, kill-gated promotion of *evolved* strategies (G1 + evolution).** The evolver never scores its own candidates for promotion; promotion requires a separate probe-layer ACCEPT verdict engram linked `verifies→candidate`. DSPy/GEPA self-scores with a soft minibatch gate and no hash-lock/provenance link — BENE's separation of evolution from the gate is real.
4. **The full single-file *union* (G4 narrow).** State + cross-agent SharedLog decisions + engram traces + hash-locked eval verdicts + computed trust in **one** server-free, `cp`/`rsync`/`diff`-able SQLite file. The bare "SQLite file" is commodity; the **five-domain union plus a first-class `intent→vote→decide` vote ledger** is not shipped by any named framework.
5. **Structural per-agent VFS isolation + checkpoint/diff/restore (ISO-1).** Isolation lives in mandatory `WHERE agent_id=?` SQL scoping, not ACL config; diff/restore exercised end-to-end. Solid and honest.
6. **Mandatory (schema-enforced) provenance on every engram + immutable sources (B1).** `ProvenanceRequired` on every append path; `promote()` appends a new higher-tier engram and never mutates the source. Genuinely rare among the *named* agentic frameworks (matched only by separate graph-memory layers like Graphiti, not by the orchestrators themselves).

**Bottom line for diligence:** the engineering is real and mostly as advertised; the deltas are (a) a handful of true-but-conditional or copy-wrong claims (engrams-per-run, "no back door," auto-promotion, broken recipes) and (b) competitive framing that claims category novelty where the honest claim is *conjunction* novelty. Narrow the four "they haven't" lines to the specific hash-locked / computed-trust / unified-file slivers, fix the seven copy items and the broken recipes, and the page becomes defensible.