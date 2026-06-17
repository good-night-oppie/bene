# OppieBugTriageBenchmark

Calibrated synthetic + production L3 triage-decision benchmark. Wires the
Synthetic Reality Architect calibration pipeline (152-row JSONL fitted to
53 real L3 eval rows around the OFS-124960 sibling-confusion cluster) into
a bene [`Benchmark`](../../metaharness/benchmarks/base.py), and ships an
adversarial generator + production drift harvest + four-strategy
overnight lab.

## Why

Production observation: L3 wrong-routes **19 of 53** cluster cases to
OFS-124960 with mean confidence **0.929** (the modal-collapse magnet). No
public benchmark covers Oppie-specific build-lineage / fix-incomplete /
modal-collapse axes — SWE-Bench, DBRD, TriagerX, CASEY all miss it. This
benchmark exposes that failure mode as a primary metric so harnesses must
explicitly resist it.

## Objectives (8-axis Pareto)

| Objective | Definition |
|---|---|
| `+accuracy` | mean of {action_match, duplicate_target_match, fix_incomplete_match, lineage_relation_match} |
| `+pre_fix_duplicate` | accuracy on pre-fix-build subset |
| `+post_fix_no_duplicate` | never duplicate to fixed ticket on post-fix builds |
| `+fix_incomplete_precision` | P(true fix_incomplete \| predicted fix_incomplete) |
| `+new_bug_precision` | P(true new_bug \| predicted new_bug) |
| **`+modal_collapse_resistance`** | **1.0 - rate(wrong-route to OFS-124960 magnet)** — elevated, NOT folded into accuracy |
| `+evidence_quality` | required_evidence substrings present in output |
| `-context_cost` | token usage proxy |

## Seed harnesses (8)

| # | Seed | Strategy |
|---|---|---|
| 1 | `status_blind` | top-by-score baseline (no lifecycle) |
| 2 | `lifecycle_only` | filter closed-fixed |
| 3 | `recency_attribution` | recent-fix → advisory-only |
| 4 | `build_order` | failure_build vs fix_build |
| 5 | `changeset_ancestry` | tested-revision contains fix changeset |
| 6 | `code_path_backtrack` | + failure path overlaps fix-touched path |
| 7 | `hybrid_code_lineage` | ancestry-first → code-path → build fallback |
| 8 | **`modal_collapse_defender`** | **Wilson-bounded magnet deweight + hybrid routing** (MCD = Modal Collapse Defender) |

The first seven port verbatim from
`ai/scratch/2026-05-13/engsvc_3664_lineage_lab.py`. MCD is new: applies a
Wilson lower bound on the observed 19/53 wrong-route rate as a multiplicative
penalty against any OFS-124960 candidate that lacks strong lineage evidence
(changeset ancestry OR code-path overlap), then runs the standard
hybrid routing on the rebalanced top candidate.

## Runners

| Script | Purpose | Cost |
|---|---|---|
| `run_bench.py` | Seeds-only smoke against search / test / adversarial split | $0 |
| `run_lab.py` | 4-strategy programmatic comparison (T_lineage / M_modal_defender / E_ensemble / C_calibration_aware), 95% CI bootstrap | $0 |
| `run_overnight.py` | LLM-driven MetaHarnessSearch evolutionary loop per strategy via tier router | $$ (caller-controlled) |
| `game_master.py` | Generate `data/adversarial.jsonl` (90 rows, 5 axes) | $0 |
| `harvest.py` | Drift-detect against `/mnt/gravytrain/triage/comparator/` | $0 |
| `temporal_split.py` | SWE-Bench-Pro temporal cutoff API — contamination report | $0 |

### Quick start

```bash
# Smoke seeds against search set:
uv run python -m bene.benchmarks.bug_triage.run_bench

# Programmatic 4-strategy lab (test + adversarial, 95% CI bootstrap):
uv run python -m bene.benchmarks.bug_triage.run_lab

# Regenerate the 90-row adversarial set (seeded, deterministic):
uv run python -m bene.benchmarks.bug_triage.game_master --seed 0

# Production drift check (read-only NFS harvest, last 30 days):
uv run python -m bene.benchmarks.bug_triage.harvest --days 30

# Temporal-split contamination report:
uv run python -m bene.benchmarks.bug_triage.temporal_split

# LLM-driven evolutionary loop (do NOT fire from inside a claude_code
# session; the default bene.yaml provider will recurse):
uv run python -m bene.benchmarks.bug_triage.run_overnight \
    --strategies M_modal_defender \
    --max-iterations 3
```

## Data layout

```text
data/
├── world_physics.json         calibrated distributions (53-row baseline)
├── world_physics.lock.json    locked sha256 + ks_stat at snapshot
├── search_set.jsonl           121 train rows
├── test_set.jsonl             31 held-out test rows
└── adversarial.jsonl          90 game-master rows (regenerated on demand)
```

The lock file pins `world_physics.json` + both JSONL sets by sha256 so any
unintended mutation is detectable. `harvest.py` writes fresh world_physics
into a run directory — the canonical snapshot in `data/` stays immutable
until a deliberate v2 release.

## Headline results (this lab run, 2026-05-14)

**Test set (31 rows):**

| strategy | accuracy | CI95 | MCR |
|---|---|---|---|
| T_lineage | **0.742** | [0.613, 0.847] | 0.839 |
| M_modal_defender | 0.669 | [0.524, 0.806] | **1.000** |
| E_ensemble | 0.669 | [0.524, 0.806] | 1.000 |
| C_calibration_aware | 0.677 | [0.532, 0.815] | 1.000 |

**Adversarial set (90 rows):**

| strategy | accuracy | CI95 | MCR |
|---|---|---|---|
| T_lineage | 0.569 | [0.497, 0.642] | 0.644 |
| M_modal_defender | 0.536 | [0.464, 0.617] | **0.989** |
| E_ensemble | 0.528 | [0.453, 0.608] | 0.989 |
| C_calibration_aware | 0.511 | [0.439, 0.592] | 0.989 |

**Adversarial per-axis (HYBRID vs MCD):**

| axis | n | hybrid acc / mcr | MCD acc / mcr |
|---|---|---|---|
| modal_magnet_stress | 30 | 0.600 / 0.000 | 0.442 / **1.000** |
| post_fix_same_path_stress | 20 | 0.950 / 0.950 | **1.000** / 1.000 |
| duplicate_chain_of_3 | 10 | 0.500 / 0.900 | 0.500 / 0.900 |
| adversarial_lineage_missing | 15 | 0.367 / 1.000 | 0.417 / 1.000 |
| wrong_cluster_contamination | 15 | 0.250 / 1.000 | 0.250 / 1.000 |

## Honest limits (Karpathy reality check)

1. **Single-cluster bias.** All calibration data is from the OFS-124960
   sibling cluster (parse_version regression). One bug taxonomy. Need ≥3
   clusters before calling this a generalised benchmark. `harvest.py` will
   surface new clusters as production drifts.
2. **Cluster is historical.** P5 harvest (2026-05-14) shows **0 rows** of the
   sibling cluster in the last 30 days of production decisions. Top live
   predictions: OFS-130800 (675), OFS-131478 (630), OFS-106093 (466). The
   benchmark is calibrated to a snapshot that production has already
   left behind. Honest framing: v1 is a **calibrated historical regression
   suite**, not a leaderboard against current ops.
3. **Ensemble + calibration-deflation add no signal over MCD alone.** The
   Wilson-bounded magnet deweight captures most available headroom on this
   corpus. Stop investing in stacked variants until the corpus broadens.
4. **post_fix_fix_incomplete frequency is uncalibrated.** World physics
   honestly admits this. Game Master rows encode the decision *boundary*,
   not observed production frequency — accuracy on those rows reports
   policy correctness, not operational impact.
5. **wrong_cluster_contamination axis unsolved by any current policy**
   (~0.25 across all four strategies). Needs path-overlap validation before
   duplicate routing, not just within the fix-evidence resolution step.
6. **duplicate_chain_of_3 axis unsolved.** Neither T nor MCD walks the
   `top → mid → root` duplicate chain. Open patch.
7. **MCR vs accuracy is a real tradeoff on test set.** MCD spends ~7
   accuracy points (test) for 16 MCR points. Which is preferable depends on
   the downstream cost of a wrong-route to OFS-124960 — workload-specific
   call, not benchmark-decidable.

## File map

```text
bene/benchmarks/bug_triage/
├── __init__.py             package exports
├── benchmark.py            OppieBugTriageBenchmark (Benchmark ABC subclass)
├── seeds/__init__.py       8 seed harness source strings
├── run_bench.py            seeds-only kaos-style runner
├── run_lab.py              4-strategy programmatic lab
├── run_overnight.py        LLM-driven evolutionary loop (staged)
├── game_master.py          90-row adversarial generator
├── harvest.py              NFS comparator harvest + KS drift detection
├── temporal_split.py       SWE-Bench-Pro temporal cutoff API
├── data/                   snapshot (immutable in git)
└── README.md               this file
```

## Provenance

- Calibration source: 53 real production L3 eval rows pulled from `ai/scratch/2026-05-13/ofs124960_synthetic_dataset.py` pipeline.
- Production anchor: testrun `297658167`, build `343351.1.1`, fix changeset `f266e0c38b4a` NOT in build revision `76792b69229c3eaaca60f925d0fdbc06fc9bc069`.
- 7 of 8 seed harnesses ported from `ai/scratch/2026-05-13/engsvc_3664_lineage_lab.py`. MCD is new.
- Adversarial axes follow Synthetic Reality Architect Phase 4 (Chaos Monkey).
- Plan: `ai/scratch/2026-05-13/` + `.claude/learnings/cursor_autonomous_ml_lab_for_oppie_bug.md`.
