# What BENE Is: The Seven Pillars

*BENE blog · the WHAT · 2026-06-18*

The [first post](why-bene.html) argued *why* a reactive language model needs a
harness to build instead of merely react. This one is concrete: **what is BENE,
actually?** Seven pillars, each a feature you can run today. Every command below
is real — copy it after `pip install bene`.

BENE is a **local-first, single-file, multi-agent harness**. One SQLite database
holds every agent's filesystem, every event, every checkpoint, every trace. No
server, no broker — `bene init` creates the file and you are running.

## 1. Per-agent VFS — sealed rooms in one file

Every agent gets its own virtual filesystem, scoped by `agent_id` at the SQL
layer. An agent *cannot* construct a query that reaches into another agent's
space — isolation is a property of the engine, not a convention.

```bash
bene init                       # create bene.db
bene run --name researcher "summarize the codebase"
bene ls                         # every agent + status
bene read researcher /notes.md  # read one agent's file
```

*Why it matters:* a dozen agents share one database and never clobber each other.

## 2. Checkpoints — face the failed turn, restore

Snapshot an agent's entire world and restore it on demand. This is the Litany
Against Fear as a feature: face a bad turn, let it pass, see its path, restore.

```bash
bene checkpoint researcher --label pre-refactor   # snapshot; returns a checkpoint id
bene checkpoints researcher                        # list checkpoint ids + labels
bene diff researcher --from <cp-a> --to <cp-b>     # what changed between two
bene restore researcher --checkpoint <cp-id>       # roll back
```

*Why it matters:* every run is reversible, so any dispute is settled by replay,
not argument.

## 3. Engrams — the next agent never starts cold

Execution traces are compressed into searchable **engrams** — a Reverend
Mother's Other Memory. By default every run drops a trace; later agents retrieve
the path already walked instead of rediscovering it.

```bash
bene retrieve "how did we fix the flaky auth test"
```

*Why it matters:* memory compounds across agents and sessions, not just within
one context window.

## 4. Eval-probe kill-gates — a gate you cannot fail is not a gate

A probe is a pre-registered, **hash-locked** falsifiable check. It must be able
to REJECT a broken baseline before it is allowed to ACCEPT a fix — an
inadmissible gate VOIDs instead of rubber-stamping.

```bash
bene probe run lighthouse --subject metrics.json --baseline base.json --json
# ACCEPT -> exit 0 ; REJECT/VOID -> exit 1   (CI-ready)
```

*Why it matters:* evolved strategies only get promoted past a gate that could
have killed them — no self-certifying progress.

## 5. Autonomy ladder — earn the next rung

Agents operate at a level L0–L4. Lower rungs are configurable defaults; the
highest stays a human grant. Trust is *computed* from four signals, not asserted.

```bash
bene autonomy show                       # effective level per domain
bene trust researcher                    # 4 computed signals + composite
bene autonomy grant researcher 3 --by human:eddie
```

*Why it matters:* autonomy is gated on observed behavior, with L4 reserved for a
human decision.

## 6. MCP server — drop BENE into any agent

`bene serve` exposes the whole substrate as an MCP server (37 tools) so Claude
Code, or any MCP client, can spawn agents, checkpoint, query, and coordinate.

```bash
bene serve --transport stdio    # 37 MCP tools over stdio
```

*Why it matters:* the harness is not a walled garden — it plugs into the agent
you already use.

## 7. Evolutionary meta-harness search — the breeding program

BENE breeds better harness strategies across generations on a benchmark, and
promotes a candidate only behind a kill-gated probe ACCEPT.

```bash
bene mh search --benchmark agentic_coding   # detached search worker
bene mh frontier                            # the Pareto frontier of strategies
```

*Why it matters:* the harness improves itself under the same falsifiable gate it
applies to everything else.

## One file, seven pillars

VFS, checkpoints, engrams, kill-gates, autonomy, MCP, evolution — all seated on
one auditable SQLite file you can copy, diff, or check into git. That is the
Nexus: many isolated agents, one substrate, nothing hidden.

*Next: **How we build BENE — harness engineering and eval-gated evolution.***
