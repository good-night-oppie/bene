"""bene — LLM agent runtime with persistent cross-run skill graph.

Substrate layer for agentdex (agent battle platform). Will provide:
- Per-agent sandboxed virtual filesystem
- Cross-run skill memory store (FTS5 + BM25)
- Evolutionary search loop over agent harnesses
- Pareto / MAP-Elites archive

Status: Phase 1 — API surface extraction from reference impl. No runtime
code yet. See ``docs/spec/`` for the contract being written.
"""

__version__ = "0.0.1"
