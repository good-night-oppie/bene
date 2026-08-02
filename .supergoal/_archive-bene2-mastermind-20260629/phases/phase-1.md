SUPERGOAL_PHASE_START
Phase: 1 of 10 — Mine corpus, audit rivals
Task: Mine the eddie-agi-kb gold corpus into a paper→capability synthesis and produce an evidence-backed KAOS/the 0.1.0 predecessor shortcoming audit.
Type: brownfield, research, docs
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider, uv run ruff check .
Acceptance criteria: 7
Evidence required: SYNTHESIS.md + GAP-AUDIT.md excerpts in transcript, citation count grep, pytest tail, ruff exit code
Depends on phases: none

## Why

Every BENE 2.0 capability must trace to a paper and every "beyond KAOS/the 0.1.0 predecessor" claim to an evidenced shortcoming — this file pair is the ground truth for phases 2, 3, and 10.

## Context you need (executor has zero prior context)

- Repo: /home/admin/gh/bene-main — BENE v0.1.0, a local-first multi-agent orchestration framework (rebranded from the 0.1.0 predecessor). Read CLAUDE.md and README.md first.
- Gold corpus: /home/admin/gh/eddie-agi-kb/data/gold/lists/ — 11 list dirs, ~100 entries. Each entry is a directory named `NN_<chinese title>` containing `transcript.txt` (full readable transcript — the deep-read target), `slides.json`, `slides.pdf`, `slides/`.
  - Lists + entry counts: agent-auto-opt-papers(16), agent-context-memory(10), agent-loop-papers(10), agent-multi-prompt-opt(6), agent-skills-mgmt-papers(8), agent-theory-research(4), agent-kv-cache(2), agent-fun-research(2), harness-engineering(32), vibe-coding(10), apple-em-aidev-2026(empty).
- Rival 1: KAOS v0.9.1 at /home/admin/gh/kaos — read its CLAUDE.md, README.md, and `ls kaos/` module tree. Notable: dream/, eval/harness (falsifiable probes, ISA.lock kill gates), experiments.py, ideal_state.py, neuroplasticity in skills.py, GEPA router, 58 MCP tools.
- Rival 2: the 0.1.0 predecessor ≈ bene 0.1.0 itself (this repo IS the rebranded the 0.1.0 predecessor; original at $PREDECESSOR_SRC). Audit ./bene as the the 0.1.0 predecessor state. Notable edges: temporal/, storage/ protocol (sqlite+postgres), runtime/, intake.py, benchmarks/; 37 MCP tools; NO eval discipline, NO dream, NO experiments journal.
- Five pillars the synthesis maps onto (from .supergoal/THINKING.md — read it):
  1. KAOS-parity core (falsifiable eval, experiments, consolidation, plasticity)
  2. Evolution engine (GEPA/MIPRO, Trace2Skill, SkillClaw, SkillX, EvoMap genes)
  3. Memory & context OS (MemGAS, RF-Mem, AgentSwing, context-pollution ICLR26)
  4. Harness-engineering layer (OpenAI harness canon, LangChain harness series, Claude Code lessons)
  5. Trust & Experience (Apple-grade UX; engineers trust agents — audit, falsifiability, replay)

## Work

- Read .supergoal/THINKING.md and .supergoal/ROADMAP.md for full plan context.
- Enumerate all list dirs; build the candidate table (list, entry, title-derived topic).
- Define the selection rubric (relevance to the 5 pillars; prefer: all 6 multi-prompt-opt entries' techniques GEPA/MIPRO/ADOPT, auto-opt entries on Meta-Harness/SkillX/EvoMap/Trace2Skill/SkillClaw/Ctx2Skill, context-memory entries AgentSwing/MemGAS/RF-Mem/MemCoE/GAM, theory entries on context pollution, loop entries ReAct/Plan&Execute/AdaPlanner/ReCAP/RLM, harness-engineering: OpenAI series ①–⑦ + autonomy threshold ⑧ + debt ⑦/⑨ + Schmid + LangChain series + Claude Code lessons; kv-cache TokenDance; dedupe duplicate entries which exist in several lists).
- Deep-read transcript.txt for ~25 selected entries (they are long; read enough of each to extract the core mechanism honestly — typically the first 200-400 lines + skim). Skim slides.json titles for the rest.
- Write docs/research/SYNTHESIS.md: per-entry citation block (list/entry-dir-name, paper/technique name, core idea ≤2 lines, the BENE 2.0 capability it informs, pillar 1–5). End with a pillar→papers matrix.
- Inventory both rivals from source (module trees, MCP tool counts via grep, key mechanisms) into docs/research/GAP-AUDIT.md.
- Write shortcoming lists with evidence: ≥8 for KAOS (e.g. no durable/Temporal runtime, no storage protocol/Postgres path, no autonomy ladder, no context-pollution defense, no trust surface, single-process orientation, no benchmark data machinery like bene's, eval harness not unified with memory substrate — verify each against source before claiming), ≥8 for the 0.1.0 predecessor/bene (no falsifiable eval, no experiments journal, no dream/consolidation, static skills no plasticity, no pollution defense, no autonomy ladder, no trust ledger, FTS5-only retrieval — verify each).
- Add the subsumption-table skeleton: rows = every KAOS capability + every bene capability; columns = capability, rival mechanism, BENE-2.0 mechanism (leave blank — phase 2 fills), notes.

## Acceptance criteria (all must pass — verify each in transcript)

- SYNTHESIS.md cites ≥20 distinct gold-corpus entries by list + entry dir name, each with core idea, informed capability, and pillar number (grep -c the citation blocks and show the count)
- ≥12 distinct papers/techniques mapped; every pillar 1–5 has ≥2 papers in the matrix (show the matrix)
- Selection rubric section exists and names what was deep-read vs skimmed
- GAP-AUDIT.md contains both rival inventories with module trees and MCP tool counts taken from source (show the inventory headers)
- ≥8 evidenced KAOS shortcomings + ≥8 evidenced bene/the 0.1.0 predecessor shortcomings (each cites a file/module or its absence — show 3 examples of each in transcript)
- Subsumption-table skeleton present with every rival capability as a row
- Both mandatory commands exit 0

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider
- uv run ruff check .

## Evidence required

- File existence: ls -la docs/research/
- Citation count: grep output showing ≥20 entry citations
- 3 sample KAOS + 3 sample bene shortcomings pasted
- pytest tail + ruff exit code

[Print SUPERGOAL_PHASE_VERIFY with per-criterion pass/fail, then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
