# Bene .harness/ scratch notes

## 2026-05-30 — Phase 1 framing conflict surfaced

Operator handed over `/tmp/bene-situation-ab-memo.md` after the bootstrap
of bene's `.harness/spec.md` (which I initially scoped as "extract API
spec from ionq.evolve into docs/spec/"). The memo describes a different
Phase 1 task that may be the actual intent:

### Memo summary (situation-engine A/B experiment)

- **Finding**: `ionq/evolve/proposer.py` defines `_build_situation_brief()`
  at line 831 but **never calls it** inside `propose()`. Source diff vs
  trex shows trex DID call it (line 217). ionq's situation engine is
  invisible dead code: function exists, gets unit-tested, never wired into
  runtime.
- **Why bene-worthy**: ionq's published P0.C scoreboard (+56% accuracy,
  +28% MRR on bug_attribution) was measured situation-OFF. A one-line
  patch (re-add the trex call site) flips it on. A/B reduces to:
  run on-arm N times → delta = situation lift.
- **Hypothesis**: adding `situation_brief` injection lifts bug_attribution
  accuracy / MRR by ≥5% absolute over the situation-OFF baseline.
- **Method**:
  1. Pin ionq tree at simplify-v1 `281a7dd` as immutable baseline (off-arm
     = ionq's recorded P0.C numbers — no re-run needed).
  2. Apply one-line patch in bene worktree after line ~250 of
     `ionq/evolve/proposer.py`:
     ```python
     situation_brief = self._build_situation_brief()
     if situation_brief:
         prompt += "\n\n" + situation_brief
     ```
  3. Run `scripts/eval_mutate_vs_baseline.py --benchmark bug_attribution
     --iterations 10` N times (N≥3) with patch applied → on-arm.
  4. Report delta + per-iteration breakdown.
- **Cost**: ~1h patch + driver, ~2-4h compute depending on N + iterations.
- **Decision rule on outcome**:
  - **Positive lift (≥5%)**: situation engine works → file ionq issue to
    re-wire main repo + add regression test pinning the call site.
  - **Null lift (<5%)**: plausible-useful but unproven → close as
    no-evidence; situation is dead code worth removing on next ionq
    cleanup pass.
  - **Negative lift**: prompt-injection harms proposer reasoning → file
    as design-flaw finding.

### Open questions from memo (operator decisions needed)

1. Patch + experiment lives in bene tree (clean, duplicates proposer.py)
   OR in an ionq worktree gated by env var `IONQ_ENABLE_SITUATION=1`
   (less duplication, more env coupling)?
2. Compute budget: N=3 cheap, N=10 statistically meaningful but ~10× cost.
3. If positive lift, who lands the fix — bene experiment writes the
   issue, or upstream ionq directly?

### Companion artifacts (not core to A/B but worth carrying)

ARC marquee results that prove ionq vs trex byte-identical given pinned
RNG and quantify noise floor (cv ≈ 0.5-2.6 unpinned, 0.0 pinned):

- `/tmp/ionq-arc-marquee-results.json`
- `/tmp/trex-arc-marquee-results.json`
- `/tmp/ionq-arc-noise-results.json` (N=10 unpinned)
- `/tmp/trex-arc-noise-results.json` (N=10 unpinned)
- `/tmp/ionq-arc-pinned-results.json` (RNG=42)
- `/tmp/trex-arc-pinned-results.json` (RNG=42)

Drivers:
- `/tmp/ionq-arc-marquee/scripts/arc_marquee.py`
- `/tmp/arc-marquee-noise.py`
- `/tmp/arc-marquee-pinned.py`
- `/tmp/ionq-arc-marquee/scripts/arc_probe.py`

### Conflict with current bootstrap spec.md

Current `.harness/spec.md` says Phase 1 = "extract API spec from ionq.evolve
into docs/spec/" — a clean-room rebuild prep task.

Memo says bene's purpose is the A/B experiment — measure if situation
injection lifts bug_attribution.

These are different tasks. Both can be valid bene work but only ONE can
be the active Phase 1 per the harness protocol (single active spec).

### Operator-only files blocking pivot

To make the memo-described A/B the active Phase 1, the operator must:
1. Rewrite `.harness/spec.md` to describe the A/B experiment task (instead
   of spec extraction).
2. Update `.harness/files-allowed` to add: `scripts/**` (for the A/B
   driver), `docs/experiments/**` (for results), and possibly a
   read-only path for ionq source consultation.

Both files are agent-deny-listed by my own bootstrap rule. Operator
needs to either:
- Edit those two files manually, OR
- Explicitly authorize me to edit them with a `### scope:` disclosure
  entry covering operator-only file modification.

Until then, agent (me) cannot start the A/B experiment — would violate
files-allowed scope on first commit.

### Pointers (read-only context)

- ionq plan: `/home/admin/gh/ionq/.harness/plan.md`
- ionq disclosure log: `/home/admin/gh/ionq/.harness/disclosure.md`
- trex source (read-only, DO NOT consult during clean-room work):
  `/home/admin/gh/trex/trex/metaharness/proposer.py:217`
- ionq simplify-v1 baseline: `~/gh/ionq @ 281a7dd`
- Source memo: `/tmp/bene-situation-ab-memo.md`
