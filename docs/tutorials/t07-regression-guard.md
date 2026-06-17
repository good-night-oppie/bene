# Swap Models Without Shipping Regressions

*MLOps*

You should be able to upgrade your model the way you upgrade a library: change one line, let the tests decide. This tutorial builds that — a bene regression guard in CI that replays your benchmark suite against every candidate model and refuses to deploy anything that scores worse than your baseline where it counts.

> **One CI job, 12 minutes: five benchmarks replayed against the new model, and any score that falls more than 5% blocks the deploy on its own.**


*One upgrade, end to end: the suite replays, `code_review` falls 8.4%, the gate holds the deploy, a five-iteration search recovers the score, and the swap ships Monday.*

You'll follow one real upgrade — `claude-sonnet-4-5` to `claude-sonnet-4-6` — from green pipeline to blocked deploy to restored baseline, with no person watching any step of it.

## One job in your pipeline

The whole guard is a single CI step. Spawn an agent pinned to the candidate model and anchored to the checkpoint your current model produced, replay the benchmarks, then query the score deltas:

```yaml
# .github/workflows/model-regression.yml
- name: Run regression suite
  run: |
    bene spawn regression-check-v46 \
      --model claude-sonnet-4-6 \
      --baseline-checkpoint baseline-v45

    bene run regression-check-v46 \
      "run_benchmarks text_classify code_review sentiment math_qa tool_calling"

    bene --json query "
      SELECT benchmark, delta_pct
      FROM regression_results
      WHERE run_id = 'regression-check-v46'
        AND delta_pct < -5.0" \
    | jq -e '. | length == 0' \
    || (echo "REGRESSION DETECTED — deploy blocked" && exit 1)
```

Three commands, one contract. `bene spawn` creates the agent with `baseline-v45` as its reference point; `bene run` executes the five benchmarks; the `--json query` pulls every benchmark whose delta fell past -5.0. A non-empty result makes `jq -e` fail, the step exits 1, and nothing deploys.

Everything these runs produce — scores, checkpoints, traces — lives in `bene.db`, one local SQLite file you can cp, diff, and archive. Nothing leaves your machine.

## The whole loop, up front

Six moves, repeated on every upgrade:

1. **Swap** — point the config at the candidate model.
2. **Replay** — run the full suite and diff each score against the baseline checkpoint.
3. **Gate** — let CI kill the build when any delta crosses the threshold.
4. **Repair** — aim a short, seeded meta-harness search at whichever benchmark fell.
5. **Re-baseline** — checkpoint the repaired harness with the new model as tomorrow's reference.
6. **Ship** — deploy once the gate is green.

The rest of this tutorial walks one swap through all six.

## A real swap, scored

12 minutes after the pipeline started, every benchmark had a verdict:

```text
Benchmark      v4-5  v4-6  Delta   Status
-------------  ----  ----  ------  -------------------
text_classify  0.87  0.87   0.0%   NO CHANGE
tool_calling   0.88  0.91  +3.4%   IMPROVED
math_qa        0.74  0.76  +2.7%   IMPROVED
sentiment      0.83  0.81  -2.4%   REGRESSION
code_review    0.83  0.76  -8.4%   CRITICAL REGRESSION  ← blocked
```

Read the right-hand column first. Three benchmarks held or improved — `tool_calling` up 3.4%, `math_qa` up 2.7%, `text_classify` flat. Two fell. `sentiment` lost 2.4%, inside this team's tolerance. `code_review` lost 8.4% — far past the gate, and on the capability their users feel most directly. On aggregate the new model wins; in production it would have lost, because aggregate isn't what users touch.

The gate's verdict came back as one JSON row:

```json
[{"benchmark": "code_review",
  "baseline_score": 0.83,
  "new_score": 0.76,
  "delta_pct": -8.4}]

# 1 critical regression found
# CI gate: FAILED
# Deploy: BLOCKED
```

Non-empty result, non-zero exit, held deploy — plus a notification naming the exact benchmark that failed. The -5.0 cutoff is yours to tune per task: tighter where a mistake is expensive, looser where day-to-day wobble is normal. What matters is that nobody has to remember it; the gate fires whether or not anyone is paying attention.

## Ask the diff why

A blocked deploy is half the story. The other half is what changed. `bene diff` compares the two runs and writes the failure analysis:

```text
bene diff baseline-v45 regression-check-v46 /results/code_review_failures.md

## code_review regression analysis: 0.83 → 0.76 (-8.4%)

### Failure pattern
New model struggles to distinguish BLOCKER from IMPORTANT.

v4-5: BLOCKER/IMPORTANT confusion rate: 14%
v4-6: BLOCKER/IMPORTANT confusion rate: 31%

### Example failure (new model)
Input: "SQL query is vulnerable to injection — must fix before merge"
Expected: BLOCKER
Got:      IMPORTANT (new model downgrades severity)

### Root cause
The harness was optimized for v4-5's instruction-following pattern.
v4-5 responds strongly to "must fix" keywords → BLOCKER.
v4-6 applies more nuanced severity reasoning → IMPORTANT.

This is not a model deficiency — it's a harness mismatch.
The two-step_attr_merged strategy from the original search
may transfer better to v4-6's reasoning style.
```

The BLOCKER/IMPORTANT confusion rate more than doubled, 14% to 31% — and nothing is wrong with the model. The old harness leaned on v4-5's habit of treating "must fix" phrasing as an automatic BLOCKER; v4-6 reasons about severity instead of pattern-matching it. Different RLHF, different reflexes. So the remedy isn't rolling the model back — it's re-tuning the harness to the model you actually want to run.

## Win the points back

The diff already nominated a starting strategy, so the search doesn't begin cold. Seed it from the old frontier and give it five iterations on the one benchmark that fell:

```bash
bene mh search \
  -b code_review \
  --model claude-sonnet-4-6 \
  -n 5 \
  --seed-from baseline-v45

# [mh-search] Loading from baseline-v45...
# [mh-search] Seed: two_step_attr_merged  acc=0.76 (on v4-6, was 0.83 on v4-5)
# [mh-search] Starting search from known frontier
```

```text
[iter 1/5]  two_step_attr_merged_v46  acc=0.78  +0.02  IMPROVED
[iter 2/5]  attr_merged_explicit      acc=0.81  +0.03  IMPROVED
[iter 3/5]  attr_merged_explicit_v2   acc=0.81  —      no improvement
[iter 4/5]  blocker_severity_v46      acc=0.83  +0.02  IMPROVED  ← baseline restored
[iter 5/5]  blocker_severity_merged   acc=0.83  —      no further gain

Best: blocker_severity_v46  acc=0.83  (baseline fully restored)
```

Iteration 4 lands `blocker_severity_v46` at 0.83 — the old number, on the new model. The two-step structure survived the swap; what it needed was an explicit severity rubric written for how v4-6 reasons. The edit itself is small: a single added section of system prompt.

## The trap this retires

The dangerous sentence in any model upgrade is "the new one is better, so the product gets better for free." Often true. Not reliably true — a model can improve on average while losing exactly the behavior your harness depended on, because that harness was shaped around the old model's quirks. Without a gate, the loss surfaces as weekend tickets or a 3am page. With one, it surfaces as a red CI run.

Play this swap forward unguarded: it ships Friday afternoon; by Saturday, tickets arrive about reviews that quietly downgrade severity; Sunday belongs to the on-call engineer, debugging what is really a harness mismatch. Guarded, the same swap waited, picked up a re-tuned harness verified against v4-6, and went out clean Monday morning. That is the entire job of a regression guard.

## Related

- [README](../README.md) — project overview and where every doc lives
- [Use Cases](../use-cases.md) — other patterns from production deployments
- [Component guide: Meta-Harness](../meta-harness.md) — how the search itself works
- [Use case: Model Regression Guard](../use-cases.md#model-regression-guard) — the condensed form of this pattern
- [Tutorial: t01 — Meta-Harness from 48% to 83%](t01-bene-meta-harness.md) — where the `baseline-v45` frontier came from

---

*bene is MIT-licensed. Everything in this tutorial ran locally — nothing leaves your machine.*

*GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
