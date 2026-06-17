SUPERGOAL_PHASE_START
Phase: 7 of 10 — Memory & context OS
Task: Implement multi-granularity memory with adaptive retrieval, the context-budget OS with strategy selection, and context-pollution detection + checkpoint recovery.
Type: brownfield, feature
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check ., uv run ruff format --check .
Acceptance criteria: 7
Evidence required: fast/slow path test output, pollution detection + recovery test output, pytest tails
Depends on phases: 4

## Why

Other Memory made real — beyond KAOS memory and bene FTS5: granularity, familiarity-driven adaptive retrieval, and the context-pollution defense neither rival has.

## Context you need

- Papers (SYNTHESIS.md): MemGAS (multi-granularity memory association + adaptive selection), RF-Mem (familiarity-driven fast/slow dual-path retrieval), MemCoE (learn how to remember before what), GAM (lightweight index + runtime research), AgentSwing (dynamic context-management strategy selection), ICLR26 best paper (multi-turn context pollution — once an agent commits to a wrong path the contaminated context keeps misleading it; recovery requires rollback, not more context).
- Memory granules are engrams at tiers: turn(0)/episode(1)/semantic(2)/procedural(3) — reuse the phase-4 ladder; promotion = consolidation.
- Pollution recovery WRAPS legacy checkpoints (bene/checkpoints.py) — do not port or modify the checkpoint module; call it.
- All heuristics deterministic + documented (no LLM calls in tests): familiarity = normalized token-overlap/похожесть scoring against recent query engrams; pollution signals = repeated failed tool calls on same target, contradiction markers, error-rate spike within a window. Pluggable scorer interface so an LLM scorer can replace heuristics later.

## Work

- bene/kernel/memory/granules.py — GranuleStore over EngramStore: write(turn), consolidate(episode→semantic) producing linked higher-tier engrams; association links between granules.
- bene/kernel/memory/retrieval.py — AdaptiveRetriever: fast path (familiarity index hit → cached/short-circuit result), slow path (FTS + association expansion); records which path served each query (as engram metadata) so tests can assert path choice.
- bene/kernel/memory/contextos.py — ContextOS: token-budget manager (estimate via chars/4 heuristic, pluggable), strategy registry (e.g., recency-window, relevance-topk, compress-then-pack), select_strategy(task_signals) choosing by signal rules (AgentSwing-style); assemble(budget) returns the packed context + a manifest of what was included/dropped (transparency — trust pillar).
- bene/kernel/memory/pollution.py — PollutionDetector: scan event/trace engram window for the documented signals → contamination score; on threshold, emit pollution engram + trigger recovery: restore latest pre-contamination checkpoint via legacy API and emit recovery event.
- tests/kernel/test_memory_os.py — granule promotion, fast-path on repeat query + slow-path on novel query (assert recorded path), strategy selection switches on signals, budget never exceeded (property-style test over random sizes), planted-contamination trace detected + checkpoint restored (use a real Bene tmp db with a checkpoint).

## Acceptance criteria (all must pass — verify each in transcript)

- Granule promotion (episodic→semantic) creates linked higher-tier engram (test)
- Fast vs slow retrieval paths both exercised and asserted via recorded path metadata (test output pasted)
- Strategy selection demonstrably switches strategy based on task signals (test)
- Context assembly never exceeds budget across randomized inputs; manifest lists included+dropped items (test)
- Pollution detector flags planted contamination and recovery restores a real checkpoint (test output pasted)
- ≥20 new tests passing
- Full suite green; ruff check + format clean

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .
- uv run ruff format --check .

## Evidence required

- Focused kernel-suite tail: uv run python -m pytest tests/kernel/ -q (evidence, not a pre-flight gate)

- Fast/slow path test output; pollution+recovery test output
- pytest tails

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
