# Tools detected this session

- **Context7** (`mcp__claude_ai_Context7__*`) — library docs. Low need: this is an internal SQLite/stdlib feature.
- **WebSearch / WebFetch** (deferred) — available. Optional: NeuSymMS is inspiration-only; no implementation needed.
- **prisma_deep_plan** / **pal** (thinkdeep, codereview, secaudit) — architecture/review delegation. Optional adversarial review pass in Polish phase.
- **serena** — semantic code navigation (optional).

Decision: this is a deterministic stdlib+SQLite kernel feature. Plan against repo conventions + Python stdlib (`sqlite3`, `json`, `hashlib`); no external SDKs. Use `ulid` (already a dep). Reuse `bene/kernel/genome_canonical.py` canonical hashing for value-equality. No LLM/network/vector/graph deps by hard constraint.
