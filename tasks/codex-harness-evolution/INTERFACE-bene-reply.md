# bene-core → adx-cli + adx-core — reply to the SECH work-order (Contract G frozen + B1 shipped)

**Status:** ACK + Contract G frozen + B1 SHIPPED (mock-first)
**Date:** 2026-06-19
**Re:** `agentdex-cli/tasks/codex-harness-evolution/SPEC.md` (#344, @EdwardTang)
**From:** bene-core (engine/substrate). Durable channel = this doc + A2A bus.

---

## ACK

Read the SECH SPEC. Accepting the 3-lane split and the harness-**AS-CODE** genome
(Autogenesis RSPL): **bene-core = B1+B2 = Contract G** — MetaHarnessSearch with the
Refiner as the mutation operator, the arena as fitness, a hash-locked kill-gate, and
the open-ended **DGM archive**. Built against a mock Refiner/eval first, per the SPEC
sequencing ("bene-core B1 (mocking the Refiner) starts in parallel").

## Contract G — FROZEN signature (bene-core owns)

```python
# bene/kernel/codex_harness/evolve.py  (SHIPPED — 18 tests green, ruff+mypy clean)
def evolve_codex_harness(
    seed: CodexHarness,
    refine_fn: RefineFn,           # Contract R (adx-core): (H, trajectory, failure_sigs) -> [Mutation]
    eval_fn:   EvalFn,             # Contract E (adx-cli):  (H, run_seed, n_battles) -> CodexEvalResult
    n_gen: int = 1,
    run_seed: int = 0,
    *,
    apply_fn: ApplyFn = mock_apply,  # Contract S (adx-core): (H, Mutation) -> H' | None(reject)
    candidates_per_gen: int = 4,
    n_battles: int = 30,
    db_path: str | None = None,
    bus_path: str | None = None,
) -> EvolveOutput:                 # {best, archive: DGMArchive, lineage, killgate_report}
```

**One refinement to the SPEC signature (please confirm):** the SPEC lists
`evolve_codex_harness(H0, refine_fn, eval_fn, n_gen, run_seed)` but the ASSESS step
(Contract S apply+validate) has nowhere to plug in. I added **`apply_fn` as an injected
keyword param** (mock default) so ASSESS is *real*, not assumed: the loop is
`refine_fn → for each Mutation: apply_fn(H, m) → H' or reject(rollback) → eval_fn(H')`.
This keeps your Contract S as a first-class, swappable operator without widening the
positional signature. If you'd rather fold apply into the Refiner (refine returns
already-applied H' refs), say so and I'll adapt — but separating PROPOSE from
APPLY/VALIDATE keeps the safety rail (an unbuildable H' is never evaluated) crisp.

## Wire types bene consumes/produces (so adx can drive the loop)

```python
# bene/kernel/codex_harness/genome.py
@dataclass
class CodexHarness:        # Contract H head (bene wire form)
    harness_id: str; system_prompt: str; move_selection_strategy: str
    params: dict; harness_ref: str | None       # pointer to the on-disk resource dir
    resources: dict[str,str]                     # mock-phase {rel_path: content}; real form = harness_ref dir
    parent_ids: list[str]; generation: int; manifest: dict
    # from_adx_dict(): a prompt-only BattleHarness is a valid CodexHarness (SPEC back-compat)
    # content_hash(): sha256 over (prompt+params+resources+strategy) — DGM/lineage identity

@dataclass
class Mutation:            # Contract M
    kind: str              # prompt|tool|module|protocol|orchestration|architecture
    target_path: str; diff: str; rationale: str; provenance: dict

@dataclass
class CodexEvalResult:     # Contract E output head
    fitness: CodexFitness  # win_rate/elo/move_legibility/no_forfeit_exploit/turn_efficiency + battles_played/gens
    trajectory: dict; failure_signatures: list[str]
```

`CodexHarness.from_adx_dict()` accepts your `adx_showdown.harness.BattleHarness`
`.model_dump()` directly (+ a `harness_ref`/`resources`), so the typed contract head
stays yours and the dir is the wire — no cross-repo type import.

## What bene SHIPPED in B1 (real, not mocked)

- **The kill-gate is real + hash-locked** (`codex_harness/killgate.py`): sha256-locked
  gate spec, tamper-refusal (`LockTamperError`), ACCEPT/REJECT/VOID — same falsifiable
  `bene.kernel.eval.probe` machinery the battle gate uses. Gates: `win_rate_uplift>=0.10`
  (relative), `battles_played>0`, `gens_completed>0` (anti-vacuous).
- **The DGM archive is real** (`codex_harness/archive.py`): append-only, content-addressed,
  keeps **every accepted harness** (open-ended) + `lineage_of()` genealogy walk.
- **B2 proven on the mock**: an end-to-end run (n_gen=3) gives **verdict ACCEPT, uplift
  +14pp**, **winning mutation is NON-PROMPT** (`[module, module, tool]`), **3 rollbacks**
  (the deliberately-unbuildable mutation is rejected before eval), anti-vacuous holds.
- Mocked (yours to replace, same signatures): `mock_refiner` (Contract R),
  `mock_apply` (Contract S), `mock_codex_eval` (Contract E).

## Asks (to unblock the real loop)

- **adx-cli (Contract H + E).** (1) `load_harness(harness_ref) -> runnable codex policy`
  + `harness_to_json/from_json` for the resource dir (a prompt-only harness must stay
  valid). (2) `evaluate(harness_ref, run_seed, n_battles>=30) -> CodexEvalResult` reusing
  A1+A3 + the C2 **fresh held-out re-measure** rules — it MUST return
  `failure_signatures` (illegal/loss/stall/tool-error) so the Refiner has an OBSERVE
  signal. Your L1 `codex_decide.py` is the play hook ✓.
- **adx-core (Contract R + S).** (1) `refine(harness_ref, trajectory, failure_signatures)
  -> [Mutation]` — codex-as-coding-agent over `codex exec` on the harness dir, emitting
  prompt|tool|module|protocol|orchestration|architecture mutations. (2)
  `apply_and_validate(harness_ref, Mutation) -> H'_ref | None` — isolated worktree,
  build/lint/unit-test, **reject broken H' (never evaluate an unbuildable harness)** — the
  self-modifying-code safety rail. Return `None` (or raise) on reject; bene counts it as a
  rollback.

## Held-out / McNemar reconciliation (carried from the autogenesis-harness-evo contract)

The anti-overfit gate is unchanged and reused: the held-out manifest is a content-addressed
frozen tuple set, **sha256 hash-locked at registration**; admissibility verifies
`heldout ∩ training = ∅` → overlap = **VOID** (not REJECT); ACCEPT stamps `probe_lock` +
`heldout` + `training` hashes (post-hoc provable "scored on data it never trained on").
**Frozen-per-run, rotated-between-runs.** McNemar/CRN: freeze the eval/opponent checkpoint
for the whole generation window; advance only between generations. adx executes the
held-out battles (Contract E); bene scores + the kill-gate decides. bene never runs codex.

## Falsifiable DONE (bene-core's slice)

When the real Refiner+eval are wired, an e2e run reproducible from `(seed, run_seed)` must
show: ≥1 **non-prompt** accepted mutation; best beats seed on held-out by ≥+10pp (95% CI
excludes 0, ≥30 battles/matchup, fresh re-measure); promotion kill-gated + anti-vacuous +
rollback proven; the DGM archive records the accepted genealogy. B1 already proves the
*engine* satisfies this on the mock; swapping in your operators makes it real.

---
_bene-core, 2026-06-19. Contract G frozen + B1 shipped (PR incoming to bene-main). Wire
your Contract H/E (adx-cli) + R/S (adx-core) against the signatures above; coordinate on
the A2A bus._
