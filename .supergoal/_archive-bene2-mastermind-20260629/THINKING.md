# THINKING — BENE 2.0 "Mastermind Redesign" + Apple EM Interview Kit

## Goals
1. **Redesign BENE** through the fused lenses of Hassabis (search+learning, falsifiable science, games-as-testbeds), Sutskever (compression-is-intelligence, learn-from-data, simple unified objectives), Karpathy (LLM-OS, autonomy sliders, march of nines, verification pragmatism).
2. **Ground every capability in the gold corpus** (~100 entries, 11 lists at /home/admin/gh/eddie-agi-kb/data/gold/lists/) — paper-cited, not vibes.
3. **Subsume and surpass KAOS v0.9.1 and the 0.1.0 predecessor/bene 0.1.0** — explicit capability mapping: everything they do, done better, plus capabilities neither has.
4. **Interview kit lands FIRST** — Apple EM (AI Developer Tools, DevEx) HM screen Fri 2026-06-12 11:30 AM PT. Materials in /home/admin/gh/agentdex-cli/tasks/apple-em-ai-tooling-enablement/.
5. **Fifth pillar (user-added):** Apple-grade developer experience + engineer trust in agents built with bene.

## Constraints
- New core ("kernel v2") chosen by user — but built ALONGSIDE legacy: additive schema, adapters not rewrites, legacy tests green in every phase's mandatory commands.
- No working git in repo (corrupt .git) → Baseline ref = "no-git"; deliverable checks degrade to file-existence.
- Offline-friendly: all new tests must run without API keys (mock providers exist in tests/).
- Evolution/eval loops must run on mock benchmarks end-to-end keyless.
- Interview materials = verified claims only (memory: FDE-resume discipline). Demo script commands must actually run.

## The five pillars (design skeleton)
1. **KAOS-parity core** — falsifiable-eval harness (pre-registered hash-locked kill gates, ACCEPT/REJECT/VOID, self-falsification admissibility), experiments journal, dream/consolidation analog, skill plasticity. Re-derived on the engram substrate, not copy-pasted.
2. **Evolution engine** (Breeding Program) — GEPA-style reflective text evolution with Pareto frontier (agent-multi-prompt-opt list), Trace2Skill/SkillClaw trace→skill distillation, SkillX 3-level skill hierarchy, EvoMap strategy genes (agent-auto-opt list). Promotion gated by eval probes — breeding with kill gates.
3. **Memory & context OS** (Other Memory) — multi-granularity memory + adaptive familiarity-driven retrieval (MemGAS/RF-Mem, agent-context-memory list), AgentSwing dynamic context-strategy selection, context-pollution detection & checkpoint-recovery (ICLR26 best paper, agent-theory list).
4. **Harness-engineering layer** — autonomy ladder w/ thresholds (OpenAI harness canon, 32-entry list), agent senses/discoverability manifests, debt sweeper, verification-bottleneck tooling, loop guards (LangChain harness series).
5. **Trust & Experience** (user pillar) — Apple-grade zero-config UX (`bene demo` <60s keyless), trust ledger (provenance chains, audit queries, per-agent verification status), deterministic replay surfaces. "Engineers trust agents because every claim is checkable."

## Kernel v2 concept (the unifying idea)
**Everything is an engram.** One typed, append-only substrate where traces, memories, skills, eval verdicts, experiments, and strategies are engram kinds with provenance links and a **compression ladder**: raw trace → episodic → semantic → procedural (skill) → strategic (gene). This is Sutskever's compression-is-understanding made architectural, Hassabis's Other-Memory lore made literal, and Karpathy's LLM-OS kernel made concrete (engram store = memory subsystem; capability registry = syscalls; autonomy ladder = ring levels).

## Top 3 risks → mitigations
1. **Interview clock (~26h).** Phases 1–3 are the critical path and self-contained; implementation phases follow. Phase 3's demo script uses only commands that run TODAY (current 0.1.0 demo + design vision), refreshed in Phase 10 with 2.0 reality.
2. **New-core rewrite breaks the tree.** Kernel lives in bene/kernel/ with additive v2 tables; every phase's mandatory commands include the legacy test suite; ports are adapters. If kernel work stalls, 0.1.0 still demos.
3. **Research scope explosion (100 entries).** Cap deep-reads ~25 entries via relevance rubric; the rest skimmed at title/slides.json level; synthesis cites what it reads.

## Non-obvious dependencies
- Phase 6 (evolution) needs Phase 5's probes (promotion gates) — eval before evolution.
- Phase 7's pollution recovery reuses legacy checkpoints — do not port checkpoints first, wrap them.
- Phase 3 (interview) needs Phase 2's design tables but NOT implementation — by design.
- Apple kit lives OUTSIDE the repo (absolute paths) — executor must write there explicitly; INDEX.md table update required so materials are discoverable.

## Tools/skills relied on
- Perspective skills: read SKILL.md files directly (deterministic) during Phase 2.
- Gold corpus: transcript.txt per entry; slides.json for skim tier.
- KAOS source at /home/admin/gh/kaos (read-only reference for parity audit).
- WebSearch optional in Phase 1 for paper arXiv IDs; degrade gracefully.

## Best practices applied
- Falsifiable-eval discipline (KAOS v0.9 pattern, improved: probes as engrams).
- OpenAI harness canon: autonomy thresholds, mergeability, debt repayment.
- Interview-first sequencing = de-risked deadline (ship narrative, then ship code).
