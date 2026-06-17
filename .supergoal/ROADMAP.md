# Roadmap: BENE 2.0 Mastermind Redesign + Apple EM Interview Kit

**Task:** Redesign BENE through Hassabis/Sutskever/Karpathy lenses, grounded in the eddie-agi-kb gold corpus, to subsume KAOS + the 0.1.0 predecessor — interview materials for the Apple EM screen (Fri 2026-06-12 11:30 PT) land first.
**Type:** brownfield, refactor, docs-heavy
**Created:** 2026-06-11
**Total phases:** 10

## Context summary

- **Stack:** Python 3.11+ (hatchling), SQLite/WAL core, Temporal optional, Starlette UI
- **Package manager:** uv
- **Build / test / lint commands:** `uv run python -m pytest tests/ -q` · `uv run ruff check .` · `uv run ruff format --check .`
- **Risky areas:** interview clock (~26h to phase-3 deadline); new-kernel work must never break legacy suite; apple kit lives outside repo at /home/admin/gh/agentdex-cli/tasks/apple-em-ai-tooling-enablement/

## Assumptions

- BENE 2.0 version is **0.2.0**, shipped at Phase 9; Dune naming (engrams, Other Memory, Breeding Program, Missionaria Protectiva) is retained and extended.
- Kernel v2 = `bene/kernel/` package + **additive** v2 SQLite tables in the same .db; legacy modules keep working untouched until Phase 9 adapters.
- Perspective inputs = the three SKILL.md files read directly from ~/.claude/skills/; no live web research required (WebSearch optional enrichment only).
- Gold-corpus deep-read cap ≈ 25 entries (relevance rubric in phase 1); remaining entries skimmed via titles/slides.json.
- All new tests run keyless/offline (mock providers); Temporal/e2e live tests excluded from mandatory gates if they require services (pre-flight decides the exact pytest invocation).
- Apple kit follows the existing package layout (artifacts/ subdir + BILINGUAL doc + INDEX.md table); files prefixed `bene2-` under `artifacts/bene2/`.
- No git in repo (corrupt .git): Baseline ref = `no-git`; deliverable checks use file existence; cleanliness checks use grep over new/changed paths.

## Risk top 3

1. **Interview deadline slips past phase 3** — likelihood: medium, mitigation: phases 1–3 are self-contained (no implementation dependency); phase-3 demo script uses only commands that already run on 0.1.0.
2. **New core destabilizes the repo** — likelihood: medium, mitigation: kernel is additive (`bene/kernel/`, v2 tables); every phase's mandatory commands include the legacy suite; ports are adapters in phase 9, not rewrites.
3. **Research/design scope explosion** — likelihood: high, mitigation: deep-read cap, per-phase acceptance counts, design doc page targets, hard "claims must be implemented-or-marked-planned" rule audited in phase 10.

## Phase map

| # | Phase | Depends on | Deliverable |
|---|-------|------------|-------------|
| 1 | Mine corpus, audit rivals | — | docs/research/SYNTHESIS.md + GAP-AUDIT.md |
| 2 | Mastermind BENE 2.0 design | 1 | docs/design/BENE2-DESIGN.md + MASTERMIND-RATIONALE.md + KERNEL-SPEC.md |
| 3 | Apple interview narrative kit | 2 | bene2 kit in apple task package + BILINGUAL/INDEX updates |
| 4 | Kernel v2 engram substrate | 2 | bene/kernel/ (engrams, bus, capabilities, schema v2) + tests |
| 5 | Trust & falsifiable-eval layer | 4 | bene/kernel/eval/ + trust ledger + experiments + CLI |
| 6 | Evolution engine | 4, 5 | bene/kernel/evolve/ (GEPA-style, distill, genes) + offline loop |
| 7 | Memory & context OS | 4 | bene/kernel/memory/ (granules, retrieval, contextos, pollution) |
| 8 | Harness-engineering layer | 4 | bene/kernel/harness/ (autonomy, senses, sweeper, guards) |
| 9 | Port, DevEx & demo 2.0 | 4–8 | adapters, `bene demo` 2.0, UI panels, README 2.0, v0.2.0 |
| 10 | Polish & Harden | 1–9 | full gates, claims-vs-implementation audit, kit refresh |

---

## Phase 1 — Mine corpus, audit rivals

**Why:** Every 2.0 capability must trace to a paper and every "beyond KAOS/the 0.1.0 predecessor" claim to an evidenced shortcoming.

**Deliverables:**
- docs/research/SYNTHESIS.md
- docs/research/GAP-AUDIT.md

**Acceptance criteria:**
- [ ] SYNTHESIS.md cites ≥20 gold-corpus entries by list+entry name with per-entry: core idea (≤2 lines), BENE-2.0 capability it informs, pillar assignment (1–5)
- [ ] ≥12 distinct papers/techniques mapped into the five pillars; every pillar has ≥2 papers
- [ ] Selection rubric stated (why these ~25 of ~100; what was skimmed vs deep-read)
- [ ] GAP-AUDIT.md inventories KAOS v0.9.1 modules + MCP surface and bene 0.1.0 modules + MCP surface (from source at /home/admin/gh/kaos and ./bene)
- [ ] ≥8 KAOS shortcomings and ≥8 the 0.1.0 predecessor/bene shortcomings, each with file/module evidence
- [ ] A "subsumption table" skeleton: every KAOS + the 0.1.0 predecessor capability listed with planned BENE-2.0 mechanism column (filled in phase 2)
- [ ] Legacy suite green (mandatory command)

## Phase 2 — Mastermind BENE 2.0 design

**Why:** The redesign IS the three-perspective synthesis — this document is also the centerpiece interview artifact.

**Deliverables:**
- docs/design/BENE2-DESIGN.md
- docs/design/MASTERMIND-RATIONALE.md
- docs/design/KERNEL-SPEC.md

**Acceptance criteria:**
- [ ] All three perspective SKILL.md files read; RATIONALE contains ≥10 design decisions each analyzed through all 3 lenses (H/S/K) with the tension + resolution stated
- [ ] DESIGN covers all 5 pillars with subsystem APIs and ties each to ≥1 cited paper from SYNTHESIS.md
- [ ] The engram substrate + compression ladder (raw→episodic→semantic→procedural→strategic) fully specified
- [ ] KERNEL-SPEC has complete SQL DDL (v2 tables, additive) + Python API signatures for kernel, eval, evolve, memory, harness modules
- [ ] Subsumption table completed: every KAOS + bene capability → BENE-2.0 mechanism (no row blank)
- [ ] Autonomy ladder L0–L4 specified with per-level verification gates
- [ ] Port plan maps each legacy module to keep/adapt/supersede with phase number
- [ ] Legacy suite green

## Phase 3 — Apple interview narrative kit

**Why:** HM screen Fri 11:30 PT — this phase is the deadline-critical, self-contained interview payload.

**Deliverables:**
- /home/admin/gh/agentdex-cli/tasks/apple-em-ai-tooling-enablement/artifacts/bene2/bene2-talk-track.md
- .../artifacts/bene2/design-defense-cards.md
- .../artifacts/bene2/demo-script-5min.md
- .../artifacts/bene2/paper-qa-cards.md
- .../apple-prep-BILINGUAL.md updated (≥4 TODO sections filled, EN/中文)
- .../INDEX.md artifacts table updated

**Acceptance criteria:**
- [ ] Talk track: ≥6 EM-framed stories (vision, org/process, technical judgment, cross-functional, developer-trust, metrics) each ≤90s spoken, mined from the redesign + real BENE/KAOS/the 0.1.0 predecessor history
- [ ] Design-defense cards: ≥10 anticipated challenges (why not just KAOS? why local-first? why SQLite? why evolution? how to staff it? how to measure DevEx success?) with crisp answers
- [ ] Demo script: ≤5 min, every command verified to run TODAY on bene 0.1.0 (executor must actually run each and paste output), plus a 60-second 2.0-vision close from the design doc
- [ ] Paper-QA cards: ≥12 papers, each: 1-line idea, what it informs in BENE, "how I'd productionize it" EM angle
- [ ] BILINGUAL doc: §0 At-a-glance, §2 role context, §9 prep plan, §11 one-page glance filled EN+中文 interleaved
- [ ] INDEX.md table row(s) added pointing at the bene2 kit
- [ ] Zero fabricated claims: every metric/fact in materials traceable to repo/corpus/audit (FDE-resume discipline)
- [ ] Legacy suite green

## Phase 4 — Kernel v2 engram substrate

**Why:** The unifying "everything is an engram" core that all four capability layers build on.

**Deliverables:**
- bene/kernel/__init__.py, engrams.py, bus.py, capabilities.py, schema_v2.py
- tests/kernel/test_engrams.py, test_bus.py, test_capabilities.py

**Acceptance criteria:**
- [ ] Typed engram store: kinds (trace, episodic, semantic, procedural, strategic, eval, experiment, trust), provenance links (parent_ids), compression tier field, content-addressed payloads via existing blob store
- [ ] FTS5 search over engrams; lineage query (ancestors/descendants) works
- [ ] Event bus: subscribe/publish with at-least-once dispatch to registered handlers; events also persisted to legacy journal
- [ ] Capability registry: register/lookup/list with autonomy-level metadata per capability
- [ ] Schema v2 is additive: opening a pre-existing 0.1.0 .db works; legacy tables untouched (test proves it)
- [ ] Every engram requires provenance (source agent or system origin) — enforced, tested
- [ ] ≥25 new kernel tests pass; legacy suite green

## Phase 5 — Trust & falsifiable-eval layer

**Why:** KAOS-parity eval discipline plus the trust pillar — engineers trust agents because claims are checkable.

**Deliverables:**
- bene/kernel/eval/{__init__,probe,gates,verdict}.py
- bene/kernel/trust.py
- CLI groups: `bene probe`, `bene trust`, `bene experiments` (in bene/cli/main.py)
- tests/kernel/test_eval.py, test_trust.py

**Acceptance criteria:**
- [ ] Probe primitive: pre-registered gates, lock-hash (sha256) over gate spec, tamper detection (edited lock refuses to run — tested)
- [ ] Self-falsification admissibility: a probe whose baseline cannot trigger a kill gate is INADMISSIBLE (tested)
- [ ] Verdicts ACCEPT/REJECT/VOID persisted as eval engrams with provenance to the probed mechanism
- [ ] Experiments journal: every probe/evolution run queryable (`bene experiments ls/show --json`)
- [ ] Trust ledger: per-agent trust summary computed from verifiable events (checkpoint coverage, probe pass rate, audit-trail completeness); `bene trust <agent_id> --json` works
- [ ] ≥20 new tests pass; legacy suite green; ruff clean on new files

## Phase 6 — Evolution engine

**Why:** The Breeding Program made real — reflective evolution with kill gates, beyond KAOS's metaharness and bene's static skills.

**Deliverables:**
- bene/kernel/evolve/{__init__,gepa,distill,genes}.py
- tests/kernel/test_evolve.py

**Acceptance criteria:**
- [ ] GEPA-style loop: candidate harness/prompt genomes, reflective mutation from trace feedback, multi-objective Pareto frontier (score, cost, tokens) maintained + queryable
- [ ] Trace→skill distillation: mine trace engrams → propose skill patches → consolidate into 3-level hierarchy (planning/functional/atomic, SkillX-style), stored as procedural engrams with provenance to source traces
- [ ] Strategy genes: compact strategy encoding attached to evolved candidates (EvoMap-style)
- [ ] Promotion gate: no evolved artifact becomes active without an ACCEPT verdict from a phase-5 probe (tested)
- [ ] Full evolution loop runs offline on a mock benchmark, no API keys, in CI-able test
- [ ] ≥20 new tests pass; legacy suite green

## Phase 7 — Memory & context OS

**Why:** Other Memory made real — beyond KAOS memory and bene FTS5: granularity, adaptive retrieval, pollution defense.

**Deliverables:**
- bene/kernel/memory/{__init__,granules,retrieval,contextos,pollution}.py
- tests/kernel/test_memory_os.py

**Acceptance criteria:**
- [ ] Memory granules at 4 levels (turn/episode/semantic/procedural) with promotion (episodic→semantic consolidation) implemented + tested
- [ ] Adaptive retrieval: fast familiarity path (repeat/near-duplicate queries short-circuit) + slow associative path; test proves both paths taken appropriately
- [ ] Context OS: token-budget manager + strategy selection (choose retrieval/compaction strategy from task signals, AgentSwing-style); strategies pluggable
- [ ] Pollution detector: flags context contamination (wrong-path commitment patterns) in a planted test trace; recovery triggers legacy checkpoint restore (wrap, don't port)
- [ ] ≥20 new tests pass; legacy suite green

## Phase 8 — Harness-engineering layer

**Why:** The OpenAI/LangChain/Anthropic harness canon as first-class BENE primitives — neither KAOS nor the 0.1.0 predecessor has this layer.

**Deliverables:**
- bene/kernel/harness/{__init__,autonomy,senses,sweeper,guards}.py
- tests/kernel/test_harness_layer.py

**Acceptance criteria:**
- [ ] Autonomy ladder L0–L4 with per-level allowed-capability sets; enforcement test: an L1 agent denied an L3 capability
- [ ] Agent senses: machine-readable project manifest generated from a live db (agents, skills, memories, capabilities, recent engrams) — the discoverability surface
- [ ] Debt sweeper: scans VFS/file engrams for slop signatures (debug prints, dead TODOs, duplicated blocks), emits report engram; finds planted slop in fixture
- [ ] Loop guards: repeated-action cycle detection over event stream trips on synthetic loop, emits intervention event
- [ ] ≥18 new tests pass; legacy suite green

## Phase 9 — Port, DevEx & demo 2.0

**Why:** Subsumption becomes real: legacy capabilities flow through the kernel, and the fifth pillar ships — Apple-grade experience.

**Deliverables:**
- Adapters: memory/skills/shared_log emit engrams; metaharness can use evolve; runner can use contextos (feature-flagged)
- `bene demo` 2.0 (zero-config, keyless, <60s) telling the 5-pillar story
- UI: engram + trust panels in web dashboard
- README.md 2.0 sections, CLAUDE.md update, version 0.2.0 everywhere

**Acceptance criteria:**
- [ ] Legacy API back-compat: existing public calls still work (shim tests); full legacy suite green unchanged
- [ ] `bene demo` runs clean on a fresh tmp dir with no keys, exercising engrams, a probe, an evolution mock round, memory granules, trust report
- [ ] CLI UX pass: first-run guidance, helpful error messages with next-step hints, consistent --json everywhere new
- [ ] Web UI shows engram browser + per-agent trust panel (server endpoint + static page section)
- [ ] Version 0.2.0 in pyproject.toml, bene/__init__.py, CLI, uv.lock; README documents the 2.0 architecture + pillars; CLAUDE.md architecture map updated
- [ ] Full suite (legacy + all kernel tests) green; ruff clean

## Phase 10 — Polish & Harden

**Why:** "Every aspect perfect" enforced: gates, claims audit, edge cases, kit refresh with implemented reality.

**Deliverables:**
- docs/design/CLAIMS-AUDIT.md (every design claim: implemented | planned, with evidence)
- Apple kit refreshed (demo script updated to what NOW runs; one-page glance updated)
- Edge-case + security hardening commits

**Acceptance criteria:**
- [ ] `uv run python -m pytest tests/ -q` fully green; `uv run ruff check .` and `uv run ruff format --check .` clean
- [ ] Edge cases tested: empty db, missing provenance rejected, concurrent agent engram writes, corrupt lock hash, oversized payload
- [ ] Security pass: all new SQL parameterized (grep audit), no secrets in code/docs, no debug prints in new modules (grep clean)
- [ ] CLAIMS-AUDIT.md: every BENE2-DESIGN claim marked implemented (with test/file ref) or planned (with phase/issue) — zero false "done" claims
- [ ] Apple kit demo script re-verified by running every command; BILINGUAL one-page glance reflects final state
- [ ] Cross-links: README ↔ design docs ↔ research docs all resolve (no dead relative links)
- [ ] Memory writeback: project memory updated with BENE 2.0 state
