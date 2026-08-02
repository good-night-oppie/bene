# GA-BENE-1 — Agent roster + Agent-Pane genome HUD (build-ahead, bene-core)

The dashboard **roster + Agent Pane (genome HUD)**, built ahead + render-verified against
the GA-CORE-5 `/me/agents` shape, so `bene` drops it into the GA-BENE-1 SPA with one import.
Answers adx-core's "genome_summary HUD" — the HUD that renders the `genome_summary` fields
bene-core ratified in #539.

## Files
- `agent_hud.js` — `renderRoster`, `renderAgentPane(agent, mount)`, `mountAgentHud(data, roster, pane)`,
  `loadAgents(url)`. Pure, framework-free.
- `index.html` — standalone host (design CSS + `--lime` theme; roster | Agent Pane).
- `me_agents.sample.json` — a GA-CORE-5 `/me/agents` fixture (3 agents incl. a **null-genome** one).
- `verify.sh` — headless-chromium render-verify (**11 assertions incl. the null-genome degrade path**, PASS).

## What it renders (the genome HUD)
From `/me/agents[].genome_summary` (ratified #539): `harness_id`, `move_selection_strategy`
(strategy), `generation` (gen-N badge), `allow_switch` (tool_policy pill), `prompt_summary`
(system-prompt block). Plus the agent-root stats (Elo/rating, win-rate, W/L, games ±rd) which
are **independent of genome_summary**.

## genome_summary may be null (adx-core #578)
adx-core populates `genome_summary` from a last-used-genome capture (**agent_genome event**) as a
**follow-up**, so it can be `null` today (contract: `{...}|null`). The HUD **degrades
gracefully**: roster badges it "no genome", the pane shows "genome capture pending …", and the
rating/W-L still render (they come from the agent root). Verified in `verify.sh`.

## SPA integration (for `bene`)
```js
import { mountAgentHud, loadAgents } from "./agent_hud.js";
// build-ahead: const data = await loadAgents("./me_agents.sample.json");
// live:        const data = await loadAgents("/me/agents"); // session-authed (Bearer / cookie)
mountAgentHud(data, document.querySelector("#roster"), document.querySelector("#agent-pane"));
```
Status: **component done + render-verified.** Both backends are merged (GA-CORE-5 #370 live,
GA-CORE-3 #377) — so this can integration-test against the live `/me/agents` (needs a user
session token). Remaining for `bene`: embed in the SPA + wire the live fetch + smoke. Together
with the evo-panel ([[ga-bene-4-evo-panel-buildahead]]) and bene-2's viewer, all 3 GA-BENE
build-ahead components are ready for the SPA assembly.
