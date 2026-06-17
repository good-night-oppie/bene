# Pre-registered Evaluation Protocol — BENE vs KAOS/the 0.1.0 predecessor unique benchmarks

Registered 2026-06-11, BEFORE any benchmark execution. sha256 of this file is
committed in the same commit; post-hoc edits to criteria are protocol
violations (the verdict for an edited-protocol run is VOID).

## Principles (non-negotiable)

1. **No retune-and-rerun.** BENE-side parameters are frozen at current HEAD
   (3acb93d lineage). If a row loses, it loses.
2. **Same data, same task.** BENE equivalents must consume the RIVAL's
   dataset/queries verbatim (ported, not paraphrased, not simplified).
3. **REJECT counted as success.** A LOSS row reported honestly is a successful
   audit outcome. Sugar-coating any row voids the report.
4. **N/A is a loss for capability coverage.** If BENE lacks the mechanism a
   rival bench measures, the row is recorded as "N/A — capability gap
   (planned)" and counts AGAINST the superiority claim in the summary tally.
5. Baselines: rival committed results.json are cited AND re-run where
   wall-clock permits; if re-run deviates >10% from committed, flag and use
   the re-run.

## Rows and kill gates

### Section A — KAOS-unique benches (BENE must face them)

| Row | Task | BENE mechanism under test | Gate (BENE wins iff) |
|---|---|---|---|
| A1 | realistic_retrieval: top-1 acc, 40 skills × 15 NL queries (KAOS dataset verbatim) | legacy SkillStore BM25 + kernel EngramStore FTS | BENE top-1 ≥ KAOS **bm25 baseline** arm. (Plasticity-weighted arm comparison recorded separately as A1b.) |
| A1b | same vs KAOS plasticity-weighted arm | (no plasticity ranking shipped) | BENE ≥ weighted arm, else **LOSS — expected** (decay/weighting is planned) |
| A2 | neuroplasticity delta (weighted − bm25) | none (planned) | N/A unless BENE shows an equivalent learned-ranking delta ≥ KAOS's. Expected: **N/A-LOSS** |
| A3 | consolidation at scale: full pass wall-clock @ 1k synthetic skills | TraceDistiller.distill over 1k trace engrams | BENE pass completes < 2× KAOS dry-run wall-clock @ same N, single thread |
| A4 | critical-step localization: 5 planted trajectories, earliest decisive error | none (planned) | exact-match ≥ KAOS (4/5 per their results) else **N/A-LOSS expected** |
| A5 | quality-score (continuous vs binary signal) | none (planned ranker) | **N/A-LOSS expected** |
| A6 | inline-hook overhead: per-write latency added by mirroring | adapters.attach_kernel memory mirror | mirror overhead per MemoryStore.write < 2× KAOS inline-hook overhead per op (their results.json), and absolute < 5 ms |
| A7 | probe-discipline parity (action_realization/synthesis pattern: lock, tamper-refuse, falsification self-test, honest verdict) | bene.kernel.eval | BENE demonstrates all 4 properties by running its own test suite + 1 live probe; parity = pass |

### Section B — the 0.1.0 predecessor-unique machinery (BENE is the lineage; must still run post-rebrand)

| Row | Task | Gate |
|---|---|---|
| B1 | metaharness text_classify benchmark, mock/offline mode | search loop completes ≥2 iterations, produces frontier, no exceptions |
| B2 | Temporal runtime invariants + storage protocol suites | existing tests pass (tests/test_runtime_invariants.py, tests/storage/) |
| B3 | bug_triage machinery imports + data loads | benchmark module imports; dataset files parse |

### Section C — BENE-unique capabilities (rivals must face BENE's benches)

For each: BENE's own test must pass at HEAD **and** the rival's inability is
shown by command-level evidence (grep absence / no mechanism), same standard
as GAP-AUDIT.

| Row | Capability | Rival status to verify |
|---|---|---|
| C1 | kill-gated promotion (PromotionBlocked without ACCEPT) | KAOS: probes exist but promotion not gated; the 0.1.0 predecessor: no probes at all |
| C2 | context-pollution detection → checkpoint recovery (e2e) | both: `grep -ri pollution` = 0 |
| C3 | enforced autonomy ladder (L1 denied L3, denial recorded) | KAOS: doc-only; the 0.1.0 predecessor: binary run/kill |
| C4 | computed trust ledger + trust-weighted votes | both: no trust mechanism |
| C5 | budget-capped context assembly w/ manifest (never exceeds budget, randomized) | both: compaction only, no budget contract |

## Summary verdict rule (locked)

- "BENE supersedes" may be claimed **only** with: all Section B pass, all
  Section C pass, and Section A shows no row where BENE's *implemented*
  mechanism loses to the rival's equivalent (N/A-planned rows are reported as
  capability gaps, listed first, never hidden).
- The headline of the report MUST state the count of N/A-LOSS rows before any
  win counts.
