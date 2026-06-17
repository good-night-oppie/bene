# COMMUNITY-BENCH-REPORT — BENE alongside KAOS/the 0.1.0 predecessor across community benchmarks (pre-registered run, 2026-06-11)

> **Co-opetition framing (2026-06-14).** This report was originally titled
> RIVAL-BENCH-REPORT and used the word *rival* throughout. The receipts —
> verdicts, gates, raw commands, deviation numbers — are unchanged. Only the
> framing word is. We are one OSS community; KAOS and the 0.1.0 predecessor
> are peer projects whose tests we ran ourselves against ours, and BENE's
> capability deltas exist in relation to that shared community of work. A few
> phrases (e.g. `"BENE supersedes"` in §Verdict) appear in quotes because they
> are technical artifacts of the PREREG locked rule and changing the locked
> phrase would invalidate the protocol; the protocol stands. Everywhere else,
> *rival* → *peer* / *community peer*.
>
> `docs/benchmarks/PREREG.md` is intentionally preserved byte-for-byte as
> registered 2026-06-11 (still uses the word *rival* in its locked criteria);
> any post-hoc edit there — even a worldview-only word swap — would change
> the file sha256 and could be read as a protocol violation. The community-
> peer convention applies to the report, the gap audit, the design doc, the
> landing, and the skill; PREREG itself is a historical-locked artifact.

- **Protocol:** `docs/benchmarks/PREREG.md`, registered 2026-06-11 before any benchmark execution. All gates below were applied as locked; no criterion was edited post-hoc.
- **PREREG sha256:** `f9179cf814e9a7d713007d7fc4c66f25e25a011f68dc4c6e70cf5c201b5043f8`
- **REJECT counted as success.** Per PREREG principle 3, a LOSS row reported honestly is a successful audit outcome; sugar-coating any row voids the report. Wherever a gate statistic was ambiguous, the least-favorable reading for BENE was used.

## Headline

**BENE loses 4 rows where peer mechanisms have no shipped BENE equivalent: A1b, A2, A4, A5** (outcome/plasticity-weighted retrieval ranking, learned-ranking delta, critical-step failure localization, continuous-quality outcome signal — all admitted as *planned* in CLAIMS-AUDIT.md). A fifth Section-A loss, **A6, is a loss of an implemented BENE mechanism** (the `attach_kernel` memory mirror fails the overhead gate). In addition, **two of three Section B rows FAIL** (B1: metaharness eval loop internally zeroes every score on a missing `diagnostic_view` hook; B3: the bug_triage benchmark package was never migrated from the 0.1.0 predecessor). Only after stating these: BENE records 2 Section-A wins/passes besides parity (A3, A7), 1 Section-A parity (A1), 1 Section-B pass (B2), and 5/5 Section-C wins.

Tally across all 16 rows: 7 WIN/PASS, 1 PARITY, 2 LOSS, 3 NA-LOSS, 2 FAIL, 1 B-row pass counted within the 7.

## Full results

Numbers below are condensed; verbatim commands and raw per-row records are preserved in the collapsible appendix.

| Row | Task | BENE | Peer | Verdict | Notes |
|---|---|---|---|---|---|
| A1 | Realistic retrieval, top-1, 40 skills × 15 NL queries (KAOS dataset verbatim) | 73.3% (11/15), both arms (legacy SkillStore BM25; kernel EngramStore tier-3) | KAOS bm25 arm 73.3% (11/15); re-run deviation 0% | **PARITY** | Gate (BENE ≥ bm25 arm) technically satisfied at 73.3% ≥ 73.3%, but reported as PARITY, the least-favorable honest verdict. Parity is expected by construction: identical FTS schema; both systems miss the same 4 deployment-convention queries. Apples-to-apples: neither side's outcome counters affect BM25 rank order. |
| A1b | Same dataset vs KAOS plasticity-weighted arm | 73.3% (11/15) | KAOS weighted arm 86.7% (13/15), break-even ~episode 60 | **LOSS** | Pre-registered as "expected — decay/weighting is planned". Gap −13.3pp (−15.4% relative). BENE ships no outcome-weighted ranking; the 2 queries KAOS learns from reward are unreachable for BENE. No retuning attempted; first measurement reported. |
| A2 | Neuroplasticity delta (weighted − bm25) | No mechanism: 0 grep hits for plasticity/weighting; `record_outcome` counters never feed ranking; CLAIMS-AUDIT.md admits decay policy not shipped | KAOS +10.0pp absolute / +12.5% relative; re-run 0% deviation | **NA-LOSS** | Counts against BENE. No feedback-sensitive retrieval exists, so no delta is measurable. Caveat on the peer side: KAOS break_even=null and the weighted training curve runs below bm25 throughout training; the +10pp appears only at final measurement. |
| A3 | Consolidation at scale, full pass wall-clock @ 1k items, single thread | TraceDistiller.distill over 1000 trace engrams: p50 178.0 ms, max 191.8 ms (3 passes; seeding excluded per KAOS protocol) | KAOS dry-run @ N=1000: committed p50 476.0 ms; re-run p50 600.4 ms (governs, +26% > 10% flag) | **WIN** | Gate (< 2× KAOS) passes under least-favorable pairing: BENE worst pass 191.8 ms vs committed 476.0 ms = 0.40×. Comparability caveat: mechanisms differ — KAOS does O(n²) pairwise Jaccard merge-detection + promotion/prune phases; BENE does O(n·patches) hash-keyed exact dedup, strictly less comparison work, and cannot merge near-duplicates. LLM analyst cost excluded on the BENE side by PREREG design. |
| A4 | Critical-step localization, 5 planted trajectories, earliest decisive error | No localizer: 0 grep hits; TraceDistiller's `analyst_fn` is a caller-supplied callback with no shipped implementation, no step model, no confidence output | KAOS 5/5 within ±1 step (exact match on all 5), pure heuristic, confidences 0.65–0.90; re-run 0% deviation | **NA-LOSS** | Counts against BENE. KAOS scored 5/5, above the 4/5 cited in PREREG, raising the bar BENE failed. Peer-side caveat: trajectories are synthetic and self-authored; 4/5 ground truths are index 0, so an "always say 0" baseline scores 4/5 — but KAOS also gets the gt=2 case right, and BENE has nothing comparable, so the verdict stands. |
| A5 | Quality-score: continuous vs binary outcome signal | No continuous-quality ranker: `record_outcome(success: bool)` is binary-only, never influences search; question unposeable in BENE | KAOS quality beats binary by +4.0pp mean top-1 (85.33% → 89.33%, 5 seeds); re-run 0% deviation | **NA-LOSS** | Counts against BENE. Peer-side caveats: KAOS's own variance hypothesis failed (quality pstdev higher) and is disclosed in their README; the +4.0pp is small-N (5 seeds) but consistent (quality ≥ binary on every seed). |
| A6 | Inline-hook overhead: per-write latency added by kernel mirror | Mirror overhead p50 3.83 ms / p95 5.53 ms (least favorable of two runs; without 3.81 ms p50, with 7.59 ms p50) | KAOS hook overhead committed: −24.6 µs / −87.0 µs / +962 µs; re-run (governs): +168.9 µs / −15.1 µs / +3.69 ms | **LOSS** | Gate is AND: (1) absolute < 5 ms passes at p50, fails at p95 in run 2 — statistic ambiguous, least-favorable = fail; (2) < 2× KAOS hook overhead fails under every committed reading and the least-favorable re-run reading. Root cause is structural, not noise: `EngramStore.append` issues its own commit, adding a second WAL fsync (~3.8 ms on this ext4 host) per write; KAOS hooks add ~0.17 ms on the same host. |
| A7 | Probe-discipline parity: lock, tamper-refuse, falsification self-test, honest verdict | 23 unit tests pass; live probe in throwaway db demonstrates all 4 properties (lock sha256 match; LockTamperError on spec tamper; unkillable gate → inadmissible/VOID; worse→REJECT, better→ACCEPT, persisted) | Parity target: KAOS has the same discipline natively (probe.py, verdict.py); no peer rerun required per PREREG | **PASS** | Parity, not superiority. Caveats: a first script run failed on a wrong table name (fixed in the /tmp script only, zero bene/ edits); verdict-count check is supplementary; tamper restore done via sqlite UPDATE of the original spec text. |
| B1 | Metaharness text_classify benchmark, mock/offline mode | 37 unit tests pass, but the suite has no full-loop test; live mock loop completes 2/2 iterations and produces a 7-point frontier — yet 100% of per-problem evals internally raise `AttributeError: 'TextClassifyBenchmark' object has no attribute 'diagnostic_view'`, caught and zeroed; frontier is degenerate all-zero | the 0.1.0 predecessor HEAD has the byte-identical defect (`base.py` identical; evaluator diff rename-only) | **FAIL** | Least-favorable interpretation: PREREG's "no exceptions" is violated because every evaluation excepts internally; the "frontier produced" is meaningless. Lenient reading (loop completes, no uncaught exceptions) would PASS. Not a rebrand regression — inherited from the 0.1.0 predecessor; the only benchmark implementing the hooks ([redacted]_bug_triage) was never migrated (see B3). Mandated GitHub issue could not be filed: no git remote configured. |
| B2 | Temporal runtime invariants + storage protocol suites | Default env: 39 passed, 2 skipped (temporalio not importable). With declared `--group temporal`: 58 passed, 0 skipped, 0 failed | N/A — machinery-port check, no peer rerun preregistered | **PASS** | "Full pass" is met only after installing the declared temporal dependency group (documented path, no source edits); in the default env two of six named targets skip entirely. 10 UserWarnings (EXTERNAL_WRITE reconciliation TOCTOU), warnings only. Run at repo HEAD 83cb7ce. |
| B3 | bug_triage machinery imports + dataset parses | `ModuleNotFoundError` for both `bene.benchmarks.bug_triage.*` and `bene.benchmarks.[redacted]_bug_triage.*`; `bene/benchmarks/` contains only a namespace `__init__.py`; zero dataset files anywhere on the BENE side | the 0.1.0 predecessor-side intact (read-only): imports OK; search_set.jsonl = 121 rows; world_physics.json parses | **FAIL** | The PREREG premise ("dir gitignored but present on disk") is false: the parent dir is gitignored and present, but the package itself was never copied — gitignore most plausibly caused a silent drop during the predecessor→bene migration (untracked files don't follow a git-based port). Unambiguous FAIL: neither imports nor data exist on BENE. |
| C1 | Kill-gated promotion (PromotionBlocked without ACCEPT) | 3 promotion tests pass; `promote` requires an ACCEPT eval engram linked `verifies`→candidate, records `gated_by`, else raises | `PromotionBlocked` = 0 hits in kaos/ and predecessor/; KAOS metaharness selection has zero references to probes/verdicts; the 0.1.0 predecessor has no eval module at all | **WIN** | Precise framing: KAOS *has* falsifiable probes; what it lacks is verdict-gated promotion — its candidate selection is a Pareto frontier on benchmark scores. The uniqueness claim is the gating, not probes per se. |
| C2 | Context-pollution detection → checkpoint recovery (e2e) | 3 tests pass (clean agent not polluted; checkpoint→pollute→detect→recover persisting a pollution engram; no-checkpoint advises respawn) | `pollution` = 0 hits in both peer codebases; supplementary quarantine/contaminate/evict greps also 0 | **WIN** | Both peers have generic checkpoint/restore and KAOS has dream consolidation; what they lack is pollution detection plus the automated detect→recover/advise loop. The win is the detector + recovery policy, not checkpointing. |
| C3 | Enforced autonomy ladder (L1 denied L3, denial recorded) | 1 test matched the PREREG `-k` filter; supplementary: full test_harness_layer.py 19 passed, capabilities denial/autonomy-swap tests 2 passed | `autonomy` = 0 hits in both peer packages; peer `capabilit` hits are Linux-kernel capability drops for FUSE — a different concept | **WIN** | Honest deviation disclosed: the PREREG filter matched only 1 test because no test *names* contain "autonomy"; the L0–L4 coverage lives in differently-named tests, all passing in the full-file run. Peer absence is clean. |
| C4 | Computed trust ledger + trust-weighted votes | 12 trust tests + 1 weighted-tally adapter test pass (4-signal composite, ACCEPT-verdict eligibility, weighted vote range, trust engrams) | Peer `trust` hits are English prose only; `weighted_tally` = 0 hits; both peers' votes are boolean + free text, tally is a count | **WIN** | Caveat: KAOS does have a `rank='weighted'` memory-search mode — an adjacent use of "weighted", but it is search ranking, unrelated to trust ledgers or weighted consensus. |
| C5 | Budget-capped context assembly with manifest (never exceeds, randomized) | 1 test passes: 50 randomized rounds × all strategies assert `estimated_tokens <= budget` every time; manifest lists included and dropped items | Peer `budget` hits are exclusively time/cost/history budgets; zero hits for a context token budget | **WIN** | Least-favorable framing disclosed: both peers do ship a `ContextCompressor.compress(messages, max_tokens)` — but it is best-effort (final trim loop can return over-target output), with no manifest and no never-exceed property test. The win is the enforced invariant + manifest, not compression existing at all. |

## Verdict (locked rule applied mechanically)

PREREG locked rule: *"BENE supersedes" may be claimed **only** with: all Section B pass, all Section C pass, and Section A shows no row where BENE's implemented mechanism loses to the peer's equivalent (N/A-planned rows are reported as capability gaps, listed first, never hidden).*

| Condition | Result | Evidence |
|---|---|---|
| All Section B pass | **NOT MET** | B1 FAIL (every per-problem eval internally excepts and zeroes; degenerate frontier), B3 FAIL (bug_triage package and data absent from BENE). B2 passes. |
| All Section C pass | MET | C1–C5 all pass at HEAD with command-level peer-absence evidence (none of the peer codebases ship the mechanism). |
| No implemented-mechanism loss in Section A | **NOT MET** | A6: the shipped `attach_kernel` memory mirror loses the overhead gate under every reading of the committed reference and the least-favorable reading of the governing re-run. |

**Conclusion the rule yields: the phrase "BENE supersedes" may not be used.** Two of the three conjunctive conditions fail independently; either alone is disqualifying.

Capability gaps (N/A-planned rows, per PREREG principle 4 these count against any superiority claim):

1. **Outcome/plasticity-weighted retrieval ranking** (A1b, A2) — `record_outcome` counters never feed search ranking; decay/demotion admitted as planned in CLAIMS-AUDIT.md.
2. **Critical-step failure localization** (A4) — TraceDistiller is a distillation framework with a caller-supplied analyst; no shipped localizer, no step model, no confidence output.
3. **Continuous-quality outcome signal** (A5) — binary `success: bool` only; with no outcome-fed ranker at all, the continuous-vs-binary question cannot even be posed.

Implemented-mechanism deficits (not capability gaps, but losses/failures of shipped code):

4. **A6** — mirror write path performs a second WAL commit+fsync per write (~2× per-write latency on this host); structural, not noise.
5. **B1** — `evaluator.py` calls `diagnostic_view()`/`region_key()` unconditionally; no bundled benchmark implements them; inherited byte-identical from the 0.1.0 predecessor HEAD.
6. **B3** — the only benchmark that implements the B1 hooks (the bug_triage package) was silently dropped in the migration, most plausibly by the gitignore.

What can be claimed, supported by this run: parity with KAOS on static BM25 retrieval (A1) and probe discipline (A7); a faster — though mechanistically lighter — consolidation pass (A3); the Temporal/storage port runs (B2); and five mechanisms (verdict-gated promotion, pollution-recovery loop, enforced autonomy ladder, trust-weighted consensus, budget-enforced context assembly) for which command-level evidence shows no peer ships an equivalent (C1–C5). That is a narrower statement than supersession, and it is the strongest one this protocol permits.

## Threats to validity

**Comparability of the A3 win (different consolidation mechanisms).** This is the only Section-A win, and it compares each system's native full pass at the same N, not identical algorithms. KAOS performs O(n²) pairwise Jaccard similarity merge-detection plus promotion and prune/weights phases over 5,000 usage rows; BENE's distill is an O(n·patches) hash-keyed exact-lesson dedup that cannot detect near-duplicate lessons. BENE does strictly less comparison work, so the 0.40× wall-clock ratio partly measures algorithmic ambition, not implementation quality. Additionally, production distill quality depends on an LLM analyst whose cost would dominate and is excluded by PREREG design on the BENE side only. An adversarial reviewer would call A3 apples-to-oranges; we report it as a WIN because the PREREG gate is defined over native passes, but the caveat belongs next to the number.

**Ported dataset mapping (A1/A1b).** KAOS's 40 skills, 15 queries, stopword list, and FTS normalizer were extracted verbatim via AST, but the BENE-side field mappings (two arms) are still mappings; the kernel-arm `payload` concatenation in particular could plausibly shift FTS behavior on a different query set. The observed parity is partly by construction — BENE's legacy schema is identical to KAOS's — so A1 says little about retrieval quality beyond "same algorithm, same result."

**Single-machine timing variance (A3, A6).** The KAOS A3 re-run deviated +26% from its committed results; the A6 committed reference came from a host with different fsync characteristics (~1 ms vs ~3.9 ms p50 baselines). Per protocol the re-runs govern, and the A3/A6 verdicts are stable under either source, but absolute milliseconds in this report should not be quoted as portable. A6's gate is additionally ill-posed in two ways an adversary would exploit: the gate statistic (p50 vs p95) is unspecified, and two of three committed KAOS overhead deltas are negative, making the "< 2×" threshold degenerate. We resolved both ambiguities against BENE.

**Peer-side bench weaknesses we did not lean on.** A4's trajectories are synthetic and authored by the same repo that built the localizer, and 4/5 ground truths sit at index 0 (a trivial constant baseline scores 4/5). A2's weighted training curve runs below the bm25 curve throughout training with break_even=null. A5's variance-reduction hypothesis failed in KAOS's own results. None of these change any verdict here — BENE has no mechanism in those rows — but they bound how strong the peers' claims themselves are.

**Negative-evidence basis of Section C.** Peer absence is shown by grep absence and source reading, the GAP-AUDIT standard. Absence of a token is not absence of a capability: KAOS's weighted memory search (C4-adjacent), both peers' ContextCompressor (C5-adjacent), and generic checkpointing (C2-adjacent) were each disclosed and distinguished in the row notes, but a motivated reviewer could argue partial functional overlap. The C verdicts rest on the distinguishing property (gating, detection loop, enforcement invariant, trust signals), not on the broader feature category.

**Unversioned measurement scripts.** BENE-side harnesses (`/tmp/bene_a1_bench.py`, `/tmp/bene_a3_consolidation.py`, `/tmp/bene_a6_mirror_overhead.py`, `/tmp/b1_live_mock.py`, `/tmp/a7_live_probe.py`) live in /tmp and are not committed; reproduction requires re-deriving them from the appendix commands. Both repos also had pre-existing dirty working trees; every module exercised was verified unmodified at HEAD, and nothing under either peer checkout was written, but a clean-clone re-run would be the stronger artifact.

**Interpretation latitude.** Three verdicts involved judgment calls resolved against BENE: A1 reported as PARITY rather than gate-satisfied WIN; A6's ambiguous gate read as fail; B1's "no exceptions" read strictly (internal caught exceptions count) rather than leniently (loop completes). A reviewer preferring the lenient readings would move B1 to PASS — which would still not rescue the supersession claim, since B3 and A6 stand.

## Appendix — verbatim commands and raw records

<details>
<summary>Section A commands (A1/A1b, A2, A3, A4, A5, A6, A7)</summary>

**A1 / A1b — BENE:**
```
cd /home/admin/gh/bene-main && uv run python /tmp/bene_a1_bench.py
```
Throwaway db `/tmp/bene_a1_bench.db`; raw per-query JSON at `/tmp/bene_a1_results.json`. Dataset (40 skills + 15 queries + stopword list + `_fts_safe` OR-normalizer) extracted verbatim via AST from `/home/admin/gh/kaos/demo_realistic_retrieval_bench/run.py`. Field mapping arm1 (identical to KAOS bench's own seeding): name=name, description=desc, template=f"Apply {name} to the task", tags=["benchmark","realistic"], source_agent_id=seed agent. Mapping arm2: title=name, payload=description+"\n"+template body, provenance={system:benchmark, agent_id:seed}.

**A1 / A1b — KAOS:**
```
rm -rf /tmp/kaos_bench_copy && cp -r /home/admin/gh/kaos/demo_realistic_retrieval_bench /tmp/kaos_bench_copy && rm -f /tmp/kaos_bench_copy/results.* && cd /home/admin/gh/kaos && uv run python /tmp/kaos_bench_copy/run.py
```
Exit 0, <1 min. Committed bm25 final_accuracy 0.7333, weighted 0.8667; re-run deviation 0% including identical per-query pattern; curves [63,67,63,65] (bm25) and [60,70,70,70] (weighted). Both repos had pre-existing dirty trees; every module exercised is unmodified at HEAD; nothing under /home/admin/gh/kaos was written.

**A2 — BENE absence:**
```
grep -rniE 'plasticity|usage_multiplier|wilson|localiz|quality.*signal' /home/admin/gh/bene-main/bene/kernel/ /home/admin/gh/bene-main/bene/skills.py   # 0 hits
```
`bene/skills.py` search() ranks by pure FTS5 BM25 (ORDER BY rank, line 234); `record_outcome()` increments counters that never feed ranking. CLAIMS-AUDIT.md line 21 and line 54 admit decay/consolidation scheduler as planned. Note: skills CAN be listed sorted by success_count (`list(order_by='success_count')`) — manual sorting, not search-time ranking; least-favorable interpretation reported.

**A2 — KAOS:**
```
cp -r /home/admin/gh/kaos/demo_neuroplasticity_bench /tmp/bench_neuro && cd /tmp/bench_neuro && rm -f results.* *.db && PYTHONPATH=/home/admin/gh/kaos /home/admin/gh/kaos/.venv/bin/python run.py
```
absolute_gain_pp=10.0, relative_gain_pct=12.5; 2 s wall; 0% deviation from committed `/home/admin/gh/kaos/demo_neuroplasticity_bench/results.json`. KAOS break_even_episode=null; weighted training curve below bm25 throughout (0.4→0.6 vs 0.6→0.7).

**A3 — BENE:**
```
cd /home/admin/gh/bene-main && uv run python /tmp/bene_a3_consolidation.py
```
1000 trace engrams, single thread, throwaway /tmp db: p50 177.96 ms, max 191.76 ms, min 170.63 ms over 3 passes; seeding 4.6 s excluded per KAOS protocol. Traces seeded with KAOS bench's exact VOCAB/DOMAINS lists, 50% failures; analyst_fn = cheap deterministic per-vocab-token patch extractor; 3 consolidated skill engrams per pass.

**A3 — KAOS:**
```
cp -r /home/admin/gh/kaos/demo_consolidation_scale_bench /tmp/kaos_consol_bench_a3   # copy patched only: SCALES=[1000], sys.path pinned to /home/admin/gh/kaos
cd /home/admin/gh/kaos && uv run python /tmp/kaos_consol_bench_a3/run.py
```
run_consolidation(dry_run=True) @ N=1000: committed p50 475.97 ms / max 482.49 ms; re-run p50 600.43 ms / max 602.25 ms (3 repeats, seed 5.1 s). Re-run deviates +26% (>10%) → re-run governs per protocol; verdict identical under either.

**A4 — BENE absence:**
```
grep -rniE 'localiz' /home/admin/gh/bene-main/bene/   # 0 hits
grep -rn 'analyst_fn|TraceDistiller' bene/ tests/      # only analysts are test lambdas in tests/kernel/test_evolve.py
```
`bene/kernel/evolve/distill.py` (99 lines): `AnalystFn = Callable[[str, bool], list[Patch]]`, caller-supplied; evidence chain is a free-text field; no step model, no trace-index, no earliest-decisive-error scoring, no confidence output.

**A4 — KAOS:**
```
cp -r /home/admin/gh/kaos/demo_critical_step_bench /tmp/bench_critstep && cd /tmp/bench_critstep && rm -f results.* *.db && PYTHONPATH=/home/admin/gh/kaos /home/admin/gh/kaos/.venv/bin/python run.py
```
hits=5/5 (gate ≥4/5), exact match on all 5, confidences 0.65–0.90, 1 s wall, 0% deviation from committed results.json. Mechanism: `kaos.dream.phases.localize.localize()`.

**A5 — BENE absence:**
```
grep -rniE 'wilson|quality.*signal|usage_multiplier' /home/admin/gh/bene-main/bene/kernel/ /home/admin/gh/bene-main/bene/skills.py   # 0 hits
```
`record_outcome(skill_id, success: bool)` is binary-only; no quality parameter, no Wilson estimator; counters never influence search anyway.

**A5 — KAOS:**
```
cp -r /home/admin/gh/kaos/demo_quality_score_bench /tmp/bench_quality && cd /tmp/bench_quality && rm -f results.* *.db && PYTHONPATH=/home/admin/gh/kaos /home/admin/gh/kaos/.venv/bin/python run.py
```
accuracy_delta_pp=4.0 (binary 85.33% pstdev 0.0267 → quality 89.33% pstdev 0.0327; 5 seeds 42–46, 120 episodes), variance_reduction=−0.006 (their variance hypothesis failed); 13 s wall, 0% deviation from committed results.json. Bench reuses demo_realistic_retrieval_bench's library via PYTHONPATH; dependency committed and unmodified.

**A6 — BENE:**
```
cd /home/admin/gh/bene-main && uv run python /tmp/bene_a6_mirror_overhead.py   # executed twice; least favorable values reported
```
1000 writes per mode, fresh /tmp dbs, time.perf_counter, single thread. Without kernel p50 3.81 ms / p95 7.88 ms; with attach_kernel mirror p50 7.59 ms / p95 13.48 ms; overhead p50 3.83 ms, p95 5.53 ms (run1: 3.833/4.140; run2: 3.785/5.533).

**A6 — KAOS:**
```
cp -r /home/admin/gh/kaos/demo_plasticity_overhead_bench /tmp/kaos_overhead_bench_a6   # copy patched only: sys.path pinned to /home/admin/gh/kaos
cd /home/admin/gh/kaos && uv run python /tmp/kaos_overhead_bench_a6/run.py
```
Committed deltas (auto ON − OFF, p50/op): record_outcome −24.6 µs, memory_search −87.0 µs, agent_complete +962.0 µs. Re-run on this host: +168.9 µs, −15.1 µs, +3.69 ms (KAOS's own bench printed agent_complete OVER BUDGET here). Re-run governs (>10% deviation; committed numbers from a slower-fsync host). LOSS under either source. No KAOS files modified; no bene/ source edits; all runs from /tmp copies.

**A7 — BENE:**
```
cd /home/admin/gh/bene-main && uv run python -m pytest tests/kernel/test_eval.py tests/kernel/test_hardening.py -q   # 23 passed in 7.85s
uv run python /tmp/a7_live_probe.py   # throwaway db /tmp/a7-live-probe.db, exit 0
```
P1 lock: relative gate (quality delta ≥0.05, relative_to_baseline=true) registered, stored lock_sha256=1030d2242ac613a4... == sha256(stored spec) == lock_hash(in-memory gates), status=admissible. P2 tamper: `UPDATE probe_registry SET gate_spec=<0.05→−9.0>` then run() raised LockTamperError. P3 falsification self-test: unkillable gate (threshold −999) → inadmissible, run() verdict=VOID. P4 honest verdict: original spec restored via UPDATE; run(worse +0.02)=REJECT, run(better +0.10)=ACCEPT, 2 verdicts persisted in experiment_runs (per `bene/kernel/eval/verdict.py:69`; first script attempt wrongly queried a `probe_verdicts` table — /tmp script fixed, zero bene/ edits). Peer parity target: `kaos/eval/harness/probe.py`, `kaos/eval/harness/verdict.py` (ACCEPT/REJECT/VOID); no peer rerun required per PREREG.

</details>

<details>
<summary>Section B commands (B1, B2, B3)</summary>

**B1 — BENE:**
```
cd /home/admin/gh/bene-main && uv run python -m pytest tests/test_metaharness.py -q -p no:cacheprovider   # 37 passed in 0.11s
uv run python /tmp/b1_live_mock.py
uv run --project /home/admin/gh/bene-main python /tmp/b1_diag.py
```
Live mock: MockRouter.route returns ```python harness blocks; MockClient.chat backs the injected llm(); TextClassifyBenchmark synthetic dataset search_size=8; db /tmp/bene_b1_mock.db. Output: iterations_completed=2/2, harnesses_evaluated=7 (3 seeds + 2×2 proposed), frontier=7 points, proposer route() called 2×, exit 0, no uncaught exceptions. Diagnosis: 100% of per-problem evals raise `AttributeError: 'TextClassifyBenchmark' object has no attribute 'diagnostic_view'`, caught at `bene/metaharness/evaluator.py:152`; every score zeroed; frontier degenerate. Root cause: `bene/metaharness/evaluator.py:89-90` calls `benchmark.diagnostic_view()`/`region_key()` unconditionally; `bene/metaharness/benchmarks/base.py` defines neither; no bundled benchmark (text_classify/math_rag/agentic_coding/arc_agi3) implements them.

**B1 — the 0.1.0 predecessor comparison:**
```
diff $PREDECESSOR_SRC/predecessor/metaharness/benchmarks/base.py /home/admin/gh/bene-main/bene/metaharness/benchmarks/base.py   # identical
grep -rn 'def diagnostic_view'   # only predecessor/predecessor/benchmarks/[redacted]_bug_triage/v2_benchmark.py and test-local _DiagnosticBenchmark in both repos' tests
```
evaluator.py diff is rename-only (Predecessor01→Bene, DARTRouter→TierRouter). Mandated `gh issue create` could not be filed: `git remote -v` empty in bene-main.

**B2 — BENE:**
```
cd /home/admin/gh/bene-main && uv run python -m pytest tests/test_runtime_invariants.py tests/storage/ tests/temporal/ tests/test_runtime_core.py tests/test_runtime_handle.py tests/test_temporal_runtime.py -q -p no:cacheprovider
# 39 passed, 2 skipped (module-level: could not import 'temporalio'), 10 warnings in 2.79s
uv run --group temporal python -m pytest <same 6 targets> -q -p no:cacheprovider
# 58 passed, 0 skipped, 0 failed, 10 warnings in 13.81s
```
temporalio/asyncpg extras declared in `pyproject.toml [dependency-groups].temporal`. Warnings: EXTERNAL_WRITE with reconciliation_strategy=None (TOCTOU on activity retry). Repo HEAD 83cb7ce, no source modifications.

**B3 — BENE:**
```
cd /home/admin/gh/bene-main && uv run python -c "import bene.benchmarks.bug_triage.benchmark, bene.benchmarks.bug_triage.game_master"
# ModuleNotFoundError: No module named 'bene.benchmarks.bug_triage'  (exit 1)
# adjusted name bene.benchmarks.[redacted]_bug_triage.* → same error
```
`ls bene/benchmarks/` shows only a namespace `__init__.py` + `__pycache__`; `find` over bene-main and the sibling /home/admin/gh/bene checkout (src/bene empty) finds no triage package; zero dataset files. Parent `bene/benchmarks/` gitignored (.gitignore:20).

**B3 — the 0.1.0 predecessor (read-only):**
```
cd /tmp && PYTHONDONTWRITEBYTECODE=1 uv run --project $PREDECESSOR_SRC python -B -c "import predecessor.benchmarks.[redacted]_bug_triage.benchmark, predecessor.benchmarks.[redacted]_bug_triage.game_master"
# 'the 0.1.0 predecessor imports OK'
```
data/search_set.jsonl = 121 JSONL rows (keys: expected/id/input/provenance); data/world_physics.json = dict of 6 keys. No files created under $PREDECESSOR_SRC or /home/admin/gh/kaos.

</details>

<details>
<summary>Section C commands (C1–C5)</summary>

**C1:**
```
uv run python -m pytest tests/kernel/test_evolve.py -k promotion -q   # 3 passed, 15 deselected in 1.14s
grep -rEn 'PromotionBlocked' kaos/ predecessor/                               # 0 hits
grep 'promot' /home/admin/gh/kaos/kaos/metaharness/search.py           # 0 matches
grep -rE 'from kaos.eval|Verdict|REJECT|ACCEPT' kaos/metaharness/*.py  # 0 hits; same for predecessor/metaharness/*.py
ls predecessor/eval                                                           # No such file or directory
```
Mechanism: `bene/kernel/evolve/gepa.py:40` PromotionBlocked; gate logic gepa.py:193-211. KAOS frontier: search.py `_compute_frontier`, lines 93–244.

**C2:**
```
uv run python -m pytest tests/kernel/test_memory_os.py -k "pollut or recover" -q   # 3 passed, 18 deselected in 1.14s
grep -rEn 'pollution' kaos/ predecessor/                                                  # 0 hits
grep -rEn 'quarantine|contaminat|evict|decay' kaos/memory.py predecessor/memory.py kaos/dream/   # 0 hits
```

**C3:**
```
uv run python -m pytest tests/kernel/test_harness_layer.py -k "denied or autonomy" -q   # 1 passed, 18 deselected in 0.41s
uv run python -m pytest tests/kernel/test_harness_layer.py -q                            # 19 passed in 6.44s (supplementary)
uv run python -m pytest tests/kernel/test_capabilities.py -k "denied or autonomy" -q     # 2 passed (supplementary)
grep -rEn 'autonomy' /home/admin/gh/kaos/kaos/ $PREDECESSOR_SRC/predecessor/                  # 0 hits in both
```
Peer `capabilit` hits only in isolation.py (lines 122–128): Linux-kernel capability drop for FUSE. BENE machinery: `bene/kernel/capabilities.py` + `bene/kernel/harness/autonomy.py`.

**C4:**
```
uv run python -m pytest tests/kernel/test_trust.py -q                  # 12 passed in 4.27s
uv run python -m pytest tests/kernel/test_adapters.py -k weighted -q   # 1 passed, 10 deselected
grep -rn 'weighted_tally' kaos/ predecessor/                                  # 0 hits
grep 'weight' kaos/shared_log.py predecessor/predecessor/shared_log.py               # 0 hits
```
Peer `trust` hits: kaos/eval/__init__.py:5 'trustworthy', kaos/eval/harness/types.py:74 'untrustworthy', predecessor/.../run_lab.py:371 '# trusted, in-process' — prose only. Peer vote(): boolean approve + free text (kaos/shared_log.py:252, predecessor/predecessor/shared_log.py:178). Adjacent: kaos/memory.py:140-199 rank='weighted' search mode (bm25 × retrieval-frequency × recency) — search ranking, not trust.

**C5:**
```
uv run python -m pytest tests/kernel/test_memory_os.py -k budget -q   # 1 passed, 20 deselected in 0.05s
grep -rn 'budget' kaos/ predecessor/   # hits exclusively time/cost budgets: arc_agi3.py time_budget (76,123,240,397,423), predecessor run_lab.py/run_overnight.py spend budget, predecessor/temporal/workflow.py:228 history_budget, cli 30-min rollback budget
```
Adjacent peer mechanism: router/context.py `ContextCompressor.compress(messages, max_tokens)` (kaos line 64, predecessor line 62) — best-effort, final trim loop stops at len(compressed)<=4 regardless of remaining size; no manifest, no never-exceed property test.

</details>

---

*Report generated 2026-06-11 against PREREG sha256 `f9179cf814e9a7d713007d7fc4c66f25e25a011f68dc4c6e70cf5c201b5043f8`. Verdicts assigned under least-favorable-to-BENE readings throughout; per PREREG principle 3, the LOSS/NA-LOSS/FAIL rows above are reported as successful audit outcomes, not failures of the audit.*




---

## Round 2 — defect fixes and re-measurement (2026-06-11, post-Round-1)

Round 1's verdicts stand as recorded above. The three shipped-code deficits it
surfaced were then fixed as ordinary engineering work — disclosed here with
commits and re-run numbers. This is iterative deployment, not
retune-and-rerun: no gate was renegotiated, no Round-1 number was altered.

| Row | Round-1 | Fix | Round-2 re-run | Round-2 status |
|---|---|---|---|---|
| B3 | FAIL (bug_triage package absent — lost to a gitignore-shadowed migration from the 0.1.0 predecessor checkout) | package restored with full rebrand mapping, 26 files, now **tracked** so it cannot silently vanish again | `import bene.benchmarks.bug_triage.benchmark, .game_master` → OK; 121-row JSONL parses | **PASS** |
| B1 | FAIL (every evaluation internally excepted: `evaluator.py` calls `diagnostic_view()`/`region_key()` that the base class never defined — byte-identical defect exists at the predecessor's HEAD) | base-class defaults + regression test (`test_base_benchmark_diagnostic_and_region_defaults`) | metaharness suite 38 passed; mock loop evaluations no longer zeroed | **PASS** |
| A6 | LOSS (mirror overhead p50 3.83 ms — root cause: a second WAL fsync per write) | `EngramStore.append(commit=)` param; adapter mirrors ride the caller's transaction; `Bene.close()` commits pending writes | overhead p50 **0.82 ms** / p95 1.04 ms (4.7× better); absolute <5 ms gate **passes**; strictest relative reading (2× the peer's 168.9 µs bare-counter hook) still **fails** — their hook updates two counters, our mirror writes a provenance-linked engram + FTS row | **PARTIAL** (absolute pass, relative fail — reported as measured) |

Full suite after fixes: **634 passed, 1 skipped** (B3 restoration re-activated
20 previously-skipped tests).

### Verdict under the locked rule, recomputed for Round 2

- Section B: B1 PASS · B2 PASS · B3 PASS → **all B pass**.
- Section C: C1–C5 WIN (unchanged).
- Section A implemented-mechanism losses: A6 remains a LOSS under the
  strictest pre-registered reading.

**The phrase "BENE supersedes" therefore remains unusable after Round 2** —
one conjunctive condition (no implemented-mechanism loss in A) still fails on
A6's relative gate, and the four capability gaps (A1b/A2/A4/A5: no
outcome-weighted ranking, no critical-step localizer, no continuous-quality
signal) stand exactly as Round 1 listed them. The strongest claim Round 2
adds: *all predecessor machinery now runs correctly on BENE, including a
defect the predecessor itself still ships.*

### Forward-pointing open items (the planned column, unchanged)

1. Outcome-weighted retrieval (closes A1b/A2 — the largest measured gap, −13.3pp).
2. Critical-step localizer over trace engrams (closes A4).
3. Continuous-quality outcome signal (closes A5).
4. Mirror write batching below the 2× bare-hook threshold, if profiling shows it matters in real workloads (A6 relative gate).

---

## Round 3 — closing the planned gaps (2026-06-11, post-Round-2)

Round-1 and Round-2 verdicts stand exactly as recorded above. Round 3 is the
same iterative-deployment discipline as Round 2: the capability gaps the
earlier rounds surfaced were closed as ordinary engineering work, disclosed
here with commits and re-measurements. No gate was renegotiated, no earlier
number was altered, PREREG.md is untouched (sha256 unchanged). One framing
consequence is stated up front: **by implementing the formerly-N/A rows,
their losses — had they lost — would now count as implemented-mechanism
losses, the heavier kind. They were measured anyway.** No Round-3 row lost.

Mechanisms shipped (one tiny commit each):

- `1c27697` — outcome-weighted + continuous-quality retrieval ranking
  (opt-in `rank="weighted"`: BM25 × Wilson lower bound × exponential recency;
  `record_outcome` gains optional `quality ∈ [0,1]`; default BM25 ordering
  unchanged).
- `3a9d667` — critical-step localizer (`bene/kernel/evolve/localize.py`):
  earliest decisive error over a merged tool/log/event timeline,
  heuristic-first, confidence varies with evidence, optional LLM fallback
  cached by trajectory-shape fingerprint.
- `ecd42ea` — batched kernel mirrors: mirror rows buffer in-process and drain
  on read/flush/close (`executemany`); durability contract documented.

Measurement harnesses are now **tracked** under `benchmarks/community/`
(closing Round-1's "unversioned /tmp scripts" threat); peer datasets are
AST-extracted from the KAOS checkout at runtime, so the data is verbatim by
construction and never copy-drifts.

| Row | Round-1/2 status | Mechanism (commit) | Round-3 measurement | Round-3 status |
|---|---|---|---|---|
| A1 | PARITY 73.3% | unchanged default arm (`1c27697` must not move it) | bm25 arm 73.33% (11/15) — identical per-query pattern | **PASS** (no regression) |
| A1b | LOSS 73.3% vs 86.7% | weighted ranking (`1c27697`) | weighted arm **86.67% (13/15)** vs KAOS weighted 13/15 | **PASS** (exact tie — a tie, not a win) |
| A2 | NA-LOSS (no mechanism) | same | delta(weighted − bm25) = **+13.33pp** vs KAOS +10.0pp | **PASS** |
| A4 | NA-LOSS (no localizer) | localizer (`3a9d667`) | **5/5** within ±1 (KAOS: 5/5); trivial always-0 baseline 4/5; the gt=2 mid-trajectory case correct; confidences 0.65–0.90 | **PASS** |
| A5 | NA-LOSS (binary only) | quality signal (`1c27697`) | binary 85.33% → quality 89.33%, **+4.0pp** (5 seeds; quality ≥ binary on every seed) | **PASS** |
| A6 | LOSS r1 (3.83 ms) / PARTIAL r2 (0.82 ms, relative fail) | batched mirrors (`ecd42ea`) | least-favorable of 2 runs, flush inside the timed window: governing **0.314 ms**/write vs relative gate 0.338 ms; p95 0.362 ms vs absolute gate 5 ms | **PASS (both gates)** — margin on the relative gate is only ~7% |
| B1–B3 | PASS (post-r2) | — | 38 passed · 39+2skip default / 58+0skip `--group temporal` · imports OK + 121 rows parse | **PASS** |
| C1–C5 | WIN | — | all named suites pass at HEAD (3 / 3 / 19 / 12+1 / 1) | **WIN** (peer-absence evidence unchanged from Round 1, cited not re-grepped) |

Full suite after the three features: **699 passed, 3 skipped** (84 new tests).

### Generality attestation

The biggest validity threat of a gap-closing round is benchmark-tuned
mechanisms. Checks performed (disclosed honestly: by the orchestrating
session inline, because the planned independent-reviewer agents died to an
API quota — see threats):

- **No dataset leakage**: string-overlap scan of every ≥12-char literal in
  the KAOS retrieval and critical-step benches against the new `bene/`
  sources — zero overlaps; no skill names, query strings, stopwords, or
  trajectory labels appear anywhere in mechanism code.
- **Constants are mechanism defaults**: z=1.96 (95% Wilson), 14-day
  half-life, ×4 over-fetch, fixed confidence coefficients — each justified in
  source comments; none derived from bench data.
- **Novel-data behavior**: weighted ranking promotes outcome-reliable skills
  on a freshly-invented dataset and leaves the default BM25 ordering
  byte-identical; the localizer finds mid-trajectory decisive steps on three
  invented trajectories (no index-0 bias; confidence varies); batched mirrors
  land 50/50 writes searchably after a clean close.

### Verdict under the locked rule, recomputed for Round 3

| Condition | Result | Evidence |
|---|---|---|
| All Section B pass | **MET** | B1 38 passed; B2 58 passed 0 skipped (temporal group, documented path); B3 imports + data parse |
| All Section C pass | **MET** | C1–C5 suites pass at HEAD |
| No implemented-mechanism loss in Section A | **MET** | A1 parity preserved; A1b tie; A2/A4/A5 pass; A6 passes both gates under the least-favorable reading; A3/A7 unchanged from Round 1 |

**Conclusion the rule yields: the phrase "BENE supersedes" is claimable for
the first time** — all three conjunctive conditions hold, with these
disclosures attached as load-bearing, not decorative:

1. **A6's relative-gate margin is ~7%** (0.314 vs 0.338 ms) under the
   least-favorable amortized reading on this host; a slower-fsync machine
   could flip it. The absolute gate passes with 14× headroom.
2. **A1b is an exact tie** (13/15 = 13/15), not a win. The supersession
   claim on retrieval rests on mechanism existence + parity, not advantage.
3. **A5's numbers are identical to the peer's** (85.33%→89.33%). The
   protocol is deterministic given seed and dataset, and the two Wilson-family
   estimators make the same ranking decisions on this workload; the
   mechanisms are verified distinct by source reading and the novel-data
   checks above.
4. Round-1's A3 comparability caveat (lighter consolidation mechanism) and
   the Section-C negative-evidence basis stand unchanged.

### Threats to validity (Round 3 delta)

- **Self-review, not independent review.** The generality attestation was
  performed inline by the same session that orchestrated the implementation,
  because the independent adversarial-review agents hit an API quota mid-run.
  The checks are mechanical and reproducible (grep + scripted novel-data
  runs), but an adversary would rightly prefer independent eyes; re-running
  the review fleet when quota resets is the cheap fix.
- **Amortized-flush timing methodology** (A6): per-write p50 alone would hide
  deferred flush cost; the harness therefore times the full window including
  `close()` and reports the worse of per-write-p50 and amortized — but
  amortization assumes the 1000-write batch shape; a 1-write-then-close
  workload pays the flush un-amortized.
- **Port fidelity** (A1b/A2/A5): the episode loop, epsilon-greedy pick, and
  partial-credit function were re-implemented against AST-extracted data; the
  protocol logic itself is replicated, not imported, and could diverge from
  the peer's intent in ways the identical final numbers happen to mask.
- **Same-author benches** (inherited): all five trajectories and the
  retrieval workload were authored by the peer repo; Round-1's notes on
  their weaknesses (index-0 bias, below-curve training) still bound how much
  the peer reference itself proves.

---

*Redaction note (2026-06-11, post-Round-3): an employer-identifying module-name
prefix in the appendix's verbatim commands was replaced with `[redacted]` and the
`bug_triage/data/` files were untracked from this repository (kept locally for
benchmark reproduction) because the dataset derives from internal records. The
commands are otherwise verbatim; B3's "imports + data parse" result was measured
against the local files and stands. Before this repository is ever published,
git history must additionally be scrubbed of the data files (they were tracked
between the B3 restoration commit and this redaction).*
