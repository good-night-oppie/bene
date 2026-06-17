# Primitive Review Cycle

**Status:** Methodology document. Describes how to validate a new BENE runtime primitive before locking it into the boundary plan.

**Companion to:** `philosophy.md` (why BENE is structured around evolving harnesses), `codegen.md` (the IR-as-codegen-target vision), and the runtime boundary itself in `bene/runtime/handle.py` (protocol) + `bene/runtime/core.py` (DTOs).

---

## What this is for

When BENE considers adding a new primitive to the runtime boundary (a new method on `RunHandle`, a new field on a command, a new lifecycle hook), the design has at least three blind spots that no single reviewer can see:

1. **The owner blind spot.** Whoever owns the abstraction designs it from the implementation side. They know what's possible to build, but they don't routinely walk through what consumer code looks like under retry, replay, or partial failure. They tend to overstate atomicity guarantees and understate boilerplate burden.
2. **The consumer blind spot.** Whoever uses the abstraction first sees only their own use case. They miss API smells that would matter for the second consumer, miss DTO placement issues that wouldn't surface until LocalRuntime needs to implement the same protocol, and miss reconciliation strategies for external systems they happen not to touch.
3. **The facilitator blind spot.** Whoever frames the design discussion (often a third party reading both sides) lacks the implementation intuition of the owner and the production experience of the consumer. They tend to invent abstractions that sound clean but don't survive contact with either real implementation or real production retry paths.

A single reviewer covering the design will reliably miss two of three blind spots. A two-stakeholder review (e.g., owner + consumer) catches more, but still misses the facilitator perspective on whether the abstraction actually shrinks the consumer surface or just relocates the complexity.

The Primitive Review Cycle uses three reviewers — explicitly playing the three roles above — and rotates the design through three cycles. Each cycle is structured to surface a different class of bug.

---

## The three cycles

### Cycle 1: Consultative review

**Question to consumer:** "Here is a sketch of the proposed primitive. Does it map cleanly onto a real use case you have? What would you change?"

**What this cycle catches:** Conceptual mismatches, missing parameters that are obvious only when the consumer pictures their actual code, opportunities for consumer-side simplification (the consumer often sees a better idiom than the owner anticipated).

**Output:** A revised primitive sketch with consumer-suggested refinements. Not yet code.

**What this cycle does NOT catch:** Implementation-time honesty about what the runtime can and cannot guarantee. Failure paths under partial crash. Cross-consumer DTO placement issues. The consumer is still operating on a sketch, not under stress.

### Cycle 2: Codegen stress test

**Task to consumer:** "Generate complete, production-shaped code that uses the proposed primitive against your real use case. Include tests covering retry, replay, and partial failure scenarios."

**What this cycle catches:** TOCTOU races that emerge from any consumer-side multi-step operation, missing primitives that the consumer is forced to invent on the spot to fill gaps, gaps between abstract concept and runnable contract, surprising API shapes that look fine in pseudocode but feel wrong in real code.

**Output:** Real code committed to a branch. Real test cases. A self-review where the consumer flags every place they had to escape the abstraction.

**What this cycle does NOT catch:** Implementation cost. Owner-side honesty about external-system atomicity. Module placement that affects other runtimes. The consumer is writing against a single runtime backend (often the one closest to their real use case), not auditing the full protocol.

### Cycle 3: Owner ratification

**Task to owner:** "Review the proposed primitive after consumer stress test. Push back specifically on (a) any guarantees the runtime cannot actually deliver, (b) any DTO placement that constrains other runtimes, (c) any abstraction surface that would be expensive to maintain across versions. Apply Design Review Gates retroactively to any pre-existing related todos."

**What this cycle catches:** Atomicity overclaims (runtime promising what only the external system can deliver), module placement that would force LocalRuntime to depend on TemporalRuntime modules, missing reconciliation strategies for external writes, version evolution constraints, doc hygiene that would confuse future readers.

**Output:** Final primitive specification with honest atomicity scope, correct DTO module placement, explicit reconciliation strategies, and Design Review Gates filled in for related todos.

**What this cycle does NOT catch:** Net new use cases the second consumer would surface. That requires a second consumer, which is the test of whether the primitive generalizes — see "When to repeat the cycle" below.

---

## Worked example: the `submit_side_effect` primitive (2026-05-04)

The pattern was discovered while validating four new primitives for the bene runtime boundary plan: `start_or_signal`, `business_idempotency_key`, `side_effect_label`, and (eventually) `submit_side_effect`. The discovery process was itself a Primitive Review Cycle run.

**Cycle 1 outcome.** The consumer (l3 burst aggregator session) reviewed the first three primitives in isolation. Verdict: accept all three, plus a consumer-suggested improvement — encode the time bucket directly into the workflow ID using `int(timestamp / delta_burst)`, which makes TTL semantics tumbling-window by construction and bounds workflow history naturally. This pattern was promoted into the plan as the recommended idiom for time-bounded entity actors.

**Cycle 2 outcome.** The consumer was asked to generate real code (`burst_aggregator.py`, 339 LOC + tests, 419 LOC) using the proposed primitives as if they already existed. The consumer reported back a critical gap: the proposed primitives had no atomic verb for the check-then-write pattern that external writes (Jira POST in this case) require. The consumer was forced to invent `runtime.check_side_effect` and `runtime.record_side_effect` on the spot. Between those two calls, an activity retry after a crashed worker re-executes the external write — duplicate Jira comments in production. The consumer recommended adding `submit_side_effect(label, business_key, execute_fn) -> result` as a single atomic verb where the runtime owns the lock around the entire operation. This gap would not have been visible from the abstract sketch in Cycle 1.

**Cycle 3 outcome.** The owner (bene boundary plan session) ratified the consumer's `submit_side_effect` recommendation but pushed back on the framing. The runtime cannot actually guarantee atomicity across an external system like Jira — only across its own ledger and lease. The honest contract is: runtime guarantees atomic ledger transitions (`pending → executing → done | failed`) and lease exclusivity, but for external writes the `SideEffectLabel` must declare a `reconciliation_strategy` (`IDEMPOTENT_BY_KEY`, `READBACK_SENTINEL`, `READBACK_RESULT_KEY`, or `MANUAL`) that retry uses to detect whether the prior attempt actually committed. The owner also flagged that the new shared DTOs cannot live under `bene/temporal/` because LocalRuntime needs to implement the same protocol — they belong in a runtime-neutral module like `bene/runtime/core/`. Finally, the owner provided retroactive Design Review Gates for three pre-existing related todos.

**Cycle 3 follow-up by consumer.** After receiving the precision-refined `submit_side_effect` semantics plus the recommendation to use `READBACK_SENTINEL` for Jira (with sentinel template `<!-- bene-business-key: {key} -->`), the consumer revised both the generated code and tests. The consumer additionally surfaced a real-world implementation constraint: Jira's ADF format wraps the sentinel as a paragraph node in serialized JSON rather than preserving it as a native HTML comment, so the runtime's reconciliation scan must search the JSON representation, not rendered HTML. The same pattern is already used in `check_existing_advisory.py:76-84` of the consumer's codebase, so the constraint is well-understood domain knowledge — but it implies `READBACK_SENTINEL` as a generic strategy needs a per-external-system "where to scan" sub-parameter. Logged as a follow-up; does not block the immediate change.

**Net result of one cycle pass:** Four new boundary plan todos (one BLOCKING), three retroactive Design Review Gates filled in, one new follow-up identified for future iteration (`READBACK_SENTINEL` scan-location parameter), and a 339+419 LOC reference implementation on a feature branch. None of these outcomes would have been produced by single-reviewer review.

---

## Why this works

The cycle works because the three reviewers have **structurally different blind spots**, and the cycle structure forces each blind spot to be exercised at a different stage.

The owner cannot see TOCTOU races in consumer code because the owner doesn't write consumer code. The cycle exposes this by making Cycle 2 produce real consumer code under the consumer's own design pressure.

The consumer cannot see atomicity overclaims because the consumer's mental model treats the runtime as a black box — if the API says "atomic," the consumer assumes atomic. The cycle exposes this by making Cycle 3 force the owner to defend the contract against the consumer's stress-test artifacts.

The facilitator (often whoever is reading both sides and writing the plan amendments) cannot see implementation-cost tradeoffs because the facilitator isn't the one shipping the code. The cycle exposes this by making the owner ratify (or amend) all facilitator-proposed wording before it locks into the plan.

Each cycle's output becomes the next cycle's input. By the end of three cycles, the primitive has been challenged from three orthogonal directions — and the surviving spec has demonstrably passed all three.

---

## When to use this method (and when not to)

**Use it for:** new primitives on the runtime boundary, new fields on shared command DTOs, new lifecycle hooks, new module placement decisions, anything where the design will lock in for multiple consumers and be hard to change later.

**Skip it for:** bug fixes, internal refactors that don't change the boundary, small additions that have only one consumer and are explicitly scoped as throwaway, anything where the design is already constrained by a fixed external API (e.g., implementing a third-party SDK trait).

The cycle is heavyweight — it costs the time of three sessions plus the coordination overhead of the facilitator. Use it when the cost of a wrong abstraction is much higher than the cycle cost. For boundary-layer primitives that will be called by N consumers over Y years, the cycle cost is trivial. For internal utility code with one caller, it is overkill.

---

## How to actually run it

The mechanical process used in the 2026-05-04 worked example:

**Setup.** The facilitator (cursor session in this case) reads the existing plan, identifies the proposed primitives, and prepares a focused message for the consumer session. The message contains: the proposed primitive sketch, three to five specific questions the consumer should answer concretely, references to any background documents the consumer needs.

**Cycle 1 dispatch.** The facilitator sends the message to the consumer session via tmux paste-buffer. The consumer is given context to respond in their own working session (not asked to relocate). The consumer replies with verdict per question plus suggested refinements.

**Cycle 2 dispatch.** The facilitator updates the proposed primitives based on Cycle 1 input, then sends a follow-up to the consumer asking for a real codegen attempt. The consumer is given the IR target documentation, the spec, and the directive to generate complete production-shaped artifacts (code + tests) into a clean branch. The consumer self-reviews against pass criteria the facilitator specifies.

**Cycle 3 dispatch.** The facilitator briefs the owner session on the consumer's findings, including the real artifacts and any missing-primitive reports from Cycle 2. The owner ratifies, pushes back on overclaims, applies retroactive Design Review Gates to related pre-existing todos, and (often) provides architectural constraints the facilitator missed.

**Cycle 3 follow-up to consumer.** The facilitator notifies the consumer of any precision changes from Cycle 3 so the consumer can revise their generated code. The consumer often surfaces real-world implementation constraints during this revision that become follow-up items.

**Plan commit.** The facilitator commits all amendments (new todos, updated existing todos, scope changes, design review gates, worked-example sections) to the plan file.

The whole cycle takes roughly two to four hours of wall-clock time across the three sessions. Most of that is the consumer's Cycle 2 codegen work — Cycles 1 and 3 are typically minutes-to-tens-of-minutes per session.

---

## What's open

Future iterations of this methodology should explore:

- **Two-consumer validation.** The Primitive Review Cycle as documented uses one consumer in three cycles. The stronger validation is to run a second consumer through Cycle 1 only after the first consumer has completed all three cycles — does the primitive feel right to the second consumer too, or did it overfit the first consumer's domain? Open question: when is the right time to surface the second consumer? Too early and the cycle becomes confused; too late and overfit damage is already done.
- **Owner self-cycle.** When the owner is also the only consumer (early stage of a primitive), the cycle collapses to a single reviewer and loses its blind-spot-rotation property. Open question: can a single-reviewer modified cycle still capture some of the value, or is multi-stakeholder structurally required?
- **Cycle compression for small primitives.** Not every new field on a command warrants three cycles. Open question: what is the lightweight version that preserves the blind-spot-rotation property without the full ceremony?

These are all suitable topics for a future iteration that adds primitives to BENE (e.g., when the second entity-actor consumer arrives and exercises this same method).

---

## See also

- `philosophy.md` — Why BENE is structured around evolving harnesses; the foundation that makes primitive review possible at all
- `codegen.md` — The codegen-into-IR vision that motivates getting primitive design honest before code locks in
- `bene/runtime/handle.py` (protocol) + `bene/runtime/core.py` (DTOs) — the boundary the Cycle 1-3 worked example above converged on
- The Cycle-2 reference implementation was produced internally against a private downstream consumer (not public); the boundary primitive it drove — `submit_side_effect` — is in `bene/runtime/local.py` + `bene/temporal/runtime_impl.py`
