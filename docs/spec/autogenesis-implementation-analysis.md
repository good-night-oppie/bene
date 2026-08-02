# Autogenesis implementation analysis for bene

## Scope

This note captures the implementation-level findings from cloning
`https://github.com/DVampire/Autogenesis` for the Autogenesis paper
`arXiv:2604.15034`.

The repo is directly tied to the paper:

- `README.md` identifies the project as a self-evolution protocol and runtime.
- The citation block uses title `Autogenesis: A Self-Evolving Agent Protocol`.
- The citation points at `https://arxiv.org/abs/2604.15034`.
- The downloaded paper text includes the same GitHub URL.

Analysis was performed as a SourceAtlas-style overview and flow trace. The
SourceAtlas slash commands/tools were not callable in this Codex environment,
so the trace below is derived from static source inspection.

Follow-up tooling status:

- Serena CLI is installed at `/home/admin/.local/bin/serena`.
- Autogenesis has been indexed with Serena as a Python project; the generated
  metadata lives under `/home/admin/gh/Autogenesis/.serena/`.
- Serena MCP symbol tools are usable for this repo and confirmed the key symbols
  in `ToolCallingAgent`, `ToolContextManager`, and `ReflectionOptimizer`.
- PAL tracer exists at `/home/admin/gh/pal-mcp-server`, but it is an MCP
  workflow/prompt generator for precision or dependency traces. It does not
  provide symbol indexing itself. Starting the PAL MCP server currently requires
  a provider env var such as `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
  `GEMINI_API_KEY`, or `CUSTOM_API_URL`.

## Architecture read

Autogenesis is a research runtime with protocol-managed resources:

- `src/registry.py` defines registries for agents, tools, environments, memory,
  prompts, benchmarks, processors, downloaders, indicators, metrics, and skills.
- Each major resource type has a context manager:
  `src/agent/context.py`, `src/tool/context.py`, `src/environment/context.py`,
  `src/memory/context.py`, `src/prompt/context.py`, and `src/skill/context.py`.
- Context managers load classes from registries plus persisted JSON, build
  model-facing function/text/schema exports, write a contract file, and keep a
  per-resource version history.
- `src/version/server.py` tracks version metadata for component types but does
  not by itself provide an atomic multi-resource commit layer.
- `src/tracer/tracer.py` records session/task/action traces and persists them
  as JSON.
- `src/optimizer/` contains reflection and RL-style optimizers that ask managers
  for trainable variables, propose changes, apply changes through manager
  `set_variables()` calls, re-run the agent, evaluate, and store memory events.

The important implementation pattern is resource indirection:

```text
registry class or persisted JSON
  -> context manager config
  -> version record
  -> model-facing contract/export
  -> runtime instance
  -> trainable Variable view
  -> set_variables() creates a new version
```

## Runtime flow

The working tool-calling example follows this path:

```text
examples/run_tool_calling_agent.py
  -> initialize config/model/version/prompt/memory/tool/skill/agent managers
  -> create SessionContext
  -> call agent_manager(name="tool_calling_agent", input={task, files})
  -> ToolCallingAgent builds prompt messages from:
       agent context + memory + todo + tool contract + skill context
  -> model returns ThinkOutput
  -> each action is routed to tool_manager or skill_manager
  -> memory records TASK_START, TOOL_STEP, TASK_END
  -> tracer records observation/action and saves tracer.json
```

The reflection optimizer flow is:

```text
ReflectionOptimizer.optimize()
  -> run agent once for baseline result
  -> collect prompt/tool trainable variables
  -> generate reflection from task + variables + execution result + memory
  -> generate improved variables
  -> apply prompt updates through prompt_manager.set_variables()
  -> apply tool updates through tool_manager.set_variables()
  -> re-run agent with updated variables
  -> optionally improve final solution
  -> evaluate early-stop condition
  -> record optimization events in memory
```

Prompt evolution is relatively safe: prompt variables are grouped by parent
prompt and persisted as new prompt versions. Tool evolution is more powerful and
riskier: generated source is dynamically loaded into a class and then registered
as a new tool version.

## Mapping to bene

The Autogenesis implementation validates the direction already in
`bene.resources`, but bene should not vendor the runtime wholesale. The useful
translation is:

| Autogenesis concept | bene concept |
|---|---|
| Registry + context manager | `ResourceRegistry` plus typed adapters |
| `ToolConfig`/`PromptConfig`/`AgentConfig` | `ResourceRecord` |
| `require_grad` | `evolvable` |
| `Variable` | proposed `ResourceDelta` target field |
| `contract.md` | `exports["contract_text"]` |
| per-manager JSON history | archive VFS resource records |
| `VersionManager` current version | `EvolutionCommit.resource_versions` |
| `Tracer` and memory events | evaluator trace refs and archive events |
| optimizer `set_variables()` | validated delta -> materialized eval snapshot -> commit |

## Bene integration proposal

1. Keep `bene.resources` as the integration spine.
   Autogenesis proves prompts, tools, skills, agents, memory, and environments
   need one uniform resource protocol. Bene should implement that protocol on
   top of its VFS/event-journal substrate instead of adopting MMEngine
   registries.

2. Make commits the activation boundary.
   Autogenesis managers can update current versions directly. Bene should keep
   the stricter rule: proposer deltas are staged, evaluator materializes an
   isolated snapshot, and only `EvolutionCommit` updates `/resources/active.json`.

3. Add resource adapters before optimizers.
   First implement adapters for prompt, tool, skill, and candidate resources:
   `register`, `export_contract`, `get_trainable_fields`, `materialize`, and
   `validate_delta`. Then optimizers/search can use the same interface.

4. Start with prompt and candidate evolution.
   Tool source evolution should be behind stronger validation, sandboxing, and
   tests because Autogenesis dynamically loads model-generated code. Prompt and
   candidate deltas give most of the design value with less blast radius.

5. Feed contracts into the proposer before raw source.
   Autogenesis writes compact contracts and injects them into agent context.
   Bene should make `archive_resource_contract` the default view, with raw VFS
   reads reserved for diagnosis.

6. Record exact resource snapshots in every evaluation.
   Evaluator outputs should include `resource_versions.json` and trace refs so
   Agentdex can replay a winning point exactly.

7. Connect Agentdex at the commit boundary.
   Agentdex should treat a winning agent as:
   `agent_version -> evolution_commit_id -> resource_versions + trajectory`.
   That avoids binding Agentdex to Bene's internal resource storage.

## Risks to account for

- The Autogenesis repo states it is under active refactoring; use it as a design
  reference, not a dependency.
- The dependency surface is broad and not appropriate for Bene's minimal core.
- Dynamic tool-code evolution is powerful but needs sandboxed execution,
  deterministic validation, and rollback.
- Per-resource semver is not enough for reproducibility. Bene needs commit-level
  snapshots across all active resources.

## Phase 2 cut

The first useful implementation slice is:

```text
ResourceRecord/ResourceDelta/EvolutionCommit dataclasses
  -> ResourceRegistry backed by archive VFS
  -> prompt + candidate adapters
  -> proposer archive_delta_submit
  -> evaluator materialize snapshot + resource_versions.json
  -> search accepts/commits winning deltas
```

This is the smallest slice that connects Autogenesis-style resource evolution
with Bene's existing archive search loop and gives Agentdex a stable
`evolution_commit_id` to visualize.
