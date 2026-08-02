# bene

> LLM agent runtime with persistent cross-run skill graph.

`bene` is the substrate layer for [agentdex](https://github.com/good-night-oppie/agentdex) — the agent battle platform (Pokémon Showdown for AI agents).

## What it will provide

- **Per-agent sandboxed VFS** — isolated filesystems backed by SQLite
- **Protocol-registered resources** — prompts, agents, tools, environments,
  memory policies, and candidates versioned as auditable evolution targets
- **Cross-run skill graph** — FTS5 + BM25 store that compounds across runs (the moat)
- **Evolutionary search** — AlphaEvolve-style loop over agent harnesses
- **Pareto / MAP-Elites archive** — multi-objective candidate selection

## Status

**Phase 1** — API surface extraction. Soft-rebuild discipline: spec first, tests next, implementation last. See `docs/spec/` once written.

No `src/bene/` runtime code yet — that lands in Phase 2 after the spec is frozen.

## Architecture stack

```
oppie (future product)
   ↑
agentdex (Python meta-orchestration / agent battle platform)
   ↑
   ├─ bene   (Python: this repo — runtime + skill graph)
   └─ helios (Go:     fast content-addressable VCS)
```

## License

Apache 2.0. See `LICENSE`.
