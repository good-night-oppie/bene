# Internal docs (not published)

These are internal-by-nature artifacts — agent-generated roadmaps, build
contracts, and research notes. They are kept as source-of-record but are
**excluded from the public site** (relocated out of `docs/` so the site builder
never republishes them), the same pattern as `ops/runbooks/`.

- `design/` — kernel/build specs and the agent-generated v0.3 roadmap. Reader-
  facing architecture lives in the blog (WHY/WHAT) and `docs/architecture.md`.
- `research/` — gap audits, synthesis, and product-comms reading notes.

Do not write agent/dev-process work-trace (Status / LOC / Verdict / adversarial
axes / `wf_` ids / pane scenes) into `docs/`; that belongs here or in
`.supergoal/`.
