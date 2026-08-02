# THINKING — bene-core next-phase roadmap

## Goals
Ship the bene-core-owned framework help that the adx-trace research (wf_bbd991f2) identified as highest-leverage + verified, so bene's verification layer (probe/kill-gate) becomes genuinely adoptable by a sibling consumer, and bene's own observability adapter stops being green-but-dead. Adx-side recommendations are posted to adx (A2A), NOT built here.

## Constraints
- Python 3.11 + `uv` only. No litellm, no openai SDK.
- Suite invariant: 0 failed (993/8/0 baseline). Every phase keeps it green.
- Multi-writer origin: rebase-on-reject; bene-9 sibling editing docs — coordinate, tiny scoped commits.
- ISOLATED supergoal root; never touch top-level .supergoal/STATE.md.
- READ-ONLY toward adx-cli — bene-core does not edit the adx repo.

## Risks (top 3)
1. **langfuse 4.x real surface unknown + SDK not installed.** L2 must introspect the actually-installed SDK (after adding the extra) rather than guess the session_id mechanism — guessing reproduces the exact bug we're fixing. Mitigation: phase L2 installs the extra, introspects `Langfuse`/span objects, and the test runs against the real surface (or a fake generated from the real signatures), never a hand-invented `update_trace`.
2. **Probe admissibility footgun.** A probe authored as a naive absolute `<=0` gate registers inadmissible→silent VOID. Mitigation: L1 + L4 author "buggy-incumbent-must-fail" gates and assert `status=='admissible'` in the test.
3. **Scope creep into adx.** Tempting to "just fix" adx's quota reorder. Mitigation: hard rule — adx-side items are A2A recommendations only; bene-core phases touch only bene/ + docs + the reference recipe doc.

## Dependencies
- L3 (`probe run` CLI) must land before L1's lighthouse can be advertised as CI-wirable (L1 example can be written against the Python API in parallel, but the "adoptable" claim needs L3).
- L2 is independent (own module) — do first, it's a real bug + unblocks honest trace advocacy.
- L4 depends on L1 (guide references the lighthouse as the worked example).
- L5 is a standalone reference doc + helper, independent.
- Polish depends on all.

## Open questions (assumed; correctable at plan review)
- New CLI command name `bene probe run` (vs `bene probe check`) — assume `run` (mirrors `eval_probe_run` MCP tool + `mh search` verb style).
- Reference recipe lives at `docs/recipes/atomic-completion.md` (new) — assume yes; it's a customer-facing recipe consistent with the existing 8-recipe set.
- langfuse extra name `bene[langfuse]` (vs `[observe]`) — assume `[langfuse]`.

## Memory hits applied
See applied-memories.md — accuracy-gate-vs-docs-review (ground-truth every claim), handoff-reverify-inflight-suite (re-run suite), bene-claims-reality (center the verified moat, de-scope Temporal durability), feedback-fix-all (one /goal, whole queue).

## Tools/skills relied on
Workflow tool for any in-phase fan-out/verify; A2A bus for the adx reaction loop. pal MCP is DOWN — not relied on. langfuse not installed — L2 handles.

## Best practices applied
- Probe authoring: relative-to-baseline against a healthy baseline (or absolute against a broken baseline) so the admissibility self-test has teeth.
- CLI: mirror the established `bene --json failure localize` pattern (`@click.pass_context` → kernel call → `_json_out`) for `probe run`.
- Tests: run against real installed surfaces, not hand-faked ones (the langfuse lesson).
- Tiny scoped commits, rebase-on-reject, suite-green per phase.
