SUPERGOAL_PHASE_START
Phase: 5 of 6 — Docs + public API + fact catalog
Task: Write the BENE-language design doc, finalize public API exports, document future-consumer fact catalogs, and add the no-LLM/no-network source-scan test.
Type: brownfield · core-infra · kernel-feature
Mandatory commands: uv run python -m pytest tests/kernel/test_truth.py -v ; uv run python -c "from bene.kernel.truth import emit_fact, reconcile_beliefs, list_beliefs, list_active_beliefs, explain_belief, quarantine_belief, TruthStore, ensure_truth; print('ok')" ; uv run ruff check bene/kernel/truth/
Acceptance criteria: 5
Evidence required: import 'ok'+exit; pytest no-LLM+import output; grep proof of 5 statements + disclaimer + 3 catalogs
Depends on phases: 3, 4

## Why

The contract must be explained in BENE language and the public seam (API + future-consumer fact kinds) made explicit, without implementing consumer integrations yet.

## Work

- `docs/design/TRUTH-MAINTENANCE.md` — explain in BENE language:
  - The five statements verbatim in spirit: BENE engrams remember what happened; BENE facts structure what was observed or claimed; BENE beliefs represent the current accepted state; BENE decisions explain why the accepted state changed; BENE admissibility flags decide whether a belief can be used for context, promotion, or action.
  - Explicit disclaimer: this is NOT RAG, NOT vector memory, NOT a full expert system — it is a deterministic truth-maintenance layer for agent runs.
  - The lifecycle diagram (states + transitions), the 10 reconciliation rules, the reconciliation key `(subject,relation,scope)`, scope semantics, provenance/lineage (evidence_uri/derived_from, value_hash via genome_canonical).
  - CLI usage (the 6 `bene belief …` commands) + Python API usage.
  - **Future-consumer fact catalogs** (documented, NOT implemented):
    - agentdex-cli: `baseline.status`, `baseline.error_type`, `trace.completeness`, `judge.verdict`, `mutation_seed.proposed`, `probe.verdict`, `infra_fault.classification`.
    - eddie-agi-kb: `paper.proposes.technique`, `tool.implements.capability`, `concept.alias`, `claim.freshness`, `claim.conflicts_with`.
    - BENE itself: `tool_call.status`, `checkpoint.restored`, `context.pollution_detected`, `probe.verdict`, `promotion.blocked`, `autonomy.grant`.
- Finalize `bene/kernel/truth/__init__.py` exports: `emit_fact, reconcile_beliefs, list_beliefs, list_active_beliefs, explain_belief, quarantine_belief, TruthStore, ensure_truth, value_hash` + contract classes + constants. Add module docstring in BENE language.
- `tests/kernel/test_truth.py`: add Test 13 — a source-scan test that reads every `.py` under `bene/kernel/truth/` and asserts NONE import/use `litellm`, `openai`, `httpx`, `requests`, `urllib.request`, `socket`, `clips`, `neo4j`, `networkx`, `chromadb`, `faiss`, `pinecone`, `threading`, `multiprocessing`, `subprocess`, `asyncio` (no LLM/network/vector/graph/CLIPS/daemon). Plus a public-import test importing the full API surface.

## Acceptance criteria (all must pass — verify each in transcript)

- `from bene.kernel.truth import emit_fact, reconcile_beliefs, list_beliefs, list_active_beliefs, explain_belief, quarantine_belief, TruthStore, ensure_truth` succeeds.
- `docs/design/TRUTH-MAINTENANCE.md` contains the 5 BENE-language statements AND the "not RAG / not vector memory / not a full expert system" disclaimer (grep-verified).
- The doc lists all three fact catalogs (agentdex-cli, eddie-agi-kb, BENE) including representative kinds (`baseline.status`, `paper.proposes.technique`, `tool_call.status`).
- Test 13 passes: the source-scan finds no banned imports/usage in `bene/kernel/truth/`.
- Provenance/lineage (evidence_uri, derived_from, value_hash via genome_canonical) is documented.

## Mandatory commands (run each, surface last ~10 lines + exit code)

- `uv run python -m pytest tests/kernel/test_truth.py -v`
- `uv run python -c "from bene.kernel.truth import emit_fact, reconcile_beliefs, list_beliefs, list_active_beliefs, explain_belief, quarantine_belief, TruthStore, ensure_truth; print('ok')"`
- `uv run ruff check bene/kernel/truth/`

## Evidence required in transcript

- import command output (`ok`) + exit code
- pytest output (no-LLM source-scan + import tests pass)
- `grep` proof the doc contains the 5 statements + disclaimer + the 3 fact catalogs
- ruff exit code

## Notes

Put the doc under `docs/design/` (NOT the published site nav) so no `site/*.html` artifact is needed. No work-trace / agent-session text in the doc (repo doc policy). The source-scan test is the honest proof of the "no LLM/network/vector/graph/daemon" constraint — make its banned-list explicit and asserted.
