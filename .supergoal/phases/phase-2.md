SUPERGOAL_PHASE_START
Phase: 2 of 10 — Mastermind BENE 2.0 design
Task: Design BENE 2.0 through the fused Hassabis/Sutskever/Karpathy lenses — architecture, kernel spec, and a three-perspective design-rationale log.
Type: brownfield, design, docs
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check .
Acceptance criteria: 8
Evidence required: doc excerpts, decision-count grep, subsumption table shown, pytest tail
Depends on phases: 1

## Why

The redesign IS the three-perspective synthesis — this document trio is the engineering blueprint for phases 4–9 AND the centerpiece interview artifact for phase 3.

## Context you need

- Inputs: docs/research/SYNTHESIS.md + GAP-AUDIT.md (phase 1), .supergoal/THINKING.md, the current codebase (read bene/core.py, bene/schema.py, bene/skills.py, bene/memory.py, bene/metaharness/, bene/storage/protocol.py headers to design against reality).
- The three mastermind lenses — READ THESE FILES (do not just invoke skills):
  - ~/.claude/skills/hassabis-perspective/SKILL.md — expect: solve-intelligence-then-use-it, games as stepping stones/testbeds, scale + breakthrough, scientific falsifiability, multi-disciplinary fusion
  - ~/.claude/skills/ilya-sutskever-perspective/SKILL.md — expect: compression-is-understanding/prediction, scale conviction, simple unified objectives, learn-from-data over hand-engineering
  - ~/.claude/skills/andrej-karpathy-perspective/SKILL.md — expect: LLM-OS framing, Software 2.0/3.0, autonomy sliders, march of nines, jagged intelligence, build-to-understand, verification realism
- The unifying kernel concept (from THINKING.md): **everything is an engram** — one typed, append-only substrate where traces, memories, skills, eval verdicts, experiments, strategies are engram kinds with provenance links and a compression ladder: raw trace → episodic → semantic → procedural (skill) → strategic (gene). Sutskever's compression made architectural; the Dune "Other Memory" made literal; Karpathy's LLM-OS kernel made concrete.
- Dune naming is retained and extended (BENE = Breeding-program · Evolutionary · Nexus · Engrams; Missionaria Protectiva = skill propagation; Litany = checkpoint/restore; Bene Gesserit lore in README).
- The five pillars (THINKING.md). Pillar 5 (Trust & Experience) is the user's own addition — Apple-grade zero-config UX + "engineers trust agents because every claim is checkable."

## Work

- Read all inputs above.
- docs/design/MASTERMIND-RATIONALE.md — for ≥10 major design decisions, write: the decision, what each lens (H/S/K) pushes for, the tension, the resolution BENE 2.0 adopts. Required decisions include at least: (1) unified engram substrate vs separate stores; (2) compression ladder vs flat memory; (3) evolution with kill gates vs unconstrained self-improvement; (4) autonomy ladder vs full autonomy; (5) local-first SQLite vs server-first; (6) falsifiable probes vs benchmark scores; (7) text-evolution (GEPA) vs RL/fine-tuning; (8) trust ledger design; (9) context OS strategy selection vs fixed compaction; (10) port-over vs rewrite of legacy modules.
- docs/design/BENE2-DESIGN.md — the architecture: kernel diagram (ASCII), the five pillars each with subsystem API sketch + the papers (cited from SYNTHESIS.md) that ground it + the lore mapping; the COMPLETED subsumption table (fill every blank row from phase 1's skeleton: every KAOS capability and every bene capability → its BENE-2.0 mechanism — no row left blank, "kept as-is via X" is a legal answer); the autonomy ladder L0–L4 with per-level verification gates; the "beyond both" section: ≥5 capabilities neither rival has (e.g. context-pollution recovery, trust ledger, autonomy enforcement, strategy genes w/ Pareto frontier, engram compression ladder).
- docs/design/KERNEL-SPEC.md — buildable spec: complete SQL DDL for additive v2 tables (engrams, engram_links, capabilities, probes, verdicts, experiments, trust_events — design carefully against bene/schema.py conventions: ULIDs, created_at, agent_id scoping); Python API signatures (class + method stubs with docstrings) for bene/kernel/{engrams,bus,capabilities}.py, bene/kernel/eval/, bene/kernel/evolve/, bene/kernel/memory/, bene/kernel/harness/; the port plan table: every legacy module → keep / adapt(phase 9) / supersede, with phase numbers.
- Keep docs tight: DESIGN ≤ ~600 lines, RATIONALE ≤ ~400, KERNEL-SPEC ≤ ~600.

## Acceptance criteria (all must pass — verify each in transcript)

- All three SKILL.md files read (quote one signature idea from each in RATIONALE's preamble)
- RATIONALE: ≥10 decisions, each with explicit H/S/K analysis + tension + resolution (grep decision headers, show count)
- DESIGN covers all 5 pillars, each citing ≥1 SYNTHESIS.md paper by name
- Engram substrate + 5-tier compression ladder fully specified (show the ladder section)
- Subsumption table: zero blank mechanism cells (show the table or its row count + spot rows)
- Autonomy ladder L0–L4 with per-level gates specified
- KERNEL-SPEC: complete DDL (show CREATE TABLE count ≥6) + API signatures for all 5 kernel subsystems + port-plan table covering every bene/ top-level module
- Both mandatory commands exit 0

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .

## Evidence required

- ls -la docs/design/
- Decision-count grep; one full sample decision pasted
- Subsumption table excerpt; DDL table count
- pytest tail + ruff exit code

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
