# GA-BENE-1 — dashboard SPA assembly (bene lineage, build-ahead)

The **agentdex.builders dashboard**, assembled from the three render-verified
build-ahead panels into one SPA and wired to the live `/me/*` + SSE feeds — the
explicit `bene` deliverable ("`bene` assembles the GA-BENE-1 SPA from the 3 +
wires live /me/* + SSE + smoke"). Both GA backends are merged (GA-CORE-5 #370,
GA-CORE-3 #377), so the only step beyond this is the DNS/TLS-gated live smoke.

Built ahead in this scratch dir (untracked, same convention as the 3 panels);
offered to adx-cli for integration into `agentdex-cli/tasks/agentdex-builders-ga/`
and deploy (adx-cli owns the agentdex.builders deploy lane).

## What it is

One dashboard composing the three panels against the canonical layout
(`tasks/agentdex-builders-ga/DESIGN/dashboard.html`, USER_STORIES Epic 2/3/4):

| region | panel | source module | renders from |
|--------|-------|---------------|--------------|
| roster + Agent Pane genome HUD | GA-BENE-1 | `vendor/agent_hud.js` | `/me/agents` (#539 `genome_summary`) |
| live battle scene (US-3.1) | GA-BENE-2 | `vendor/live/*` (`<battle-scene>`) | GA-CORE-3 SSE frames |
| Evolution · lineage (US-4.2) | GA-BENE-4 | `vendor/evo_panel.js` | `to_done_json` (held-out re-measure) |
| ladder (US-5.1) | GA-BENE-3 | `vendor/ladder_panel.js` | `/me/ladder` owner-scoped slice |

Selecting an agent re-renders the Agent Pane + Evolution panel and (re)starts its
live battle adjacent to the pane (US-2.1 AC2 + US-3.1 adjacency).

## Run / verify

```bash
python3 -m http.server 8096 && open http://localhost:8096/index.html   # fixtures
./verify.sh        # headless-chromium render-verify — 14 assertions, PASS
```

`verify.sh` asserts the assembly boots (`data-spa=ready` ⇒ all 3 panels mounted +
battle started without throwing), the roster + genome HUD + battle scene + Evolution
all render, and the honesty gate holds (a real `pokeenv` result is NOT mock-badged).
`assembly.png` is a 1440×900 render snapshot.

## The one data seam — `?live=1` flips fixtures → live (same call shape)

```text
roster   ./fixtures/me_agents.json          ⇄  GET /me/agents                    (session token)
evo      ./fixtures/done.json               ⇄  GET /me/agents/<id>/evolution
ladder   ./fixtures/me_ladder.json          ⇄  GET /me/ladder
battle   MockLiveSource(golden fixture)     ⇄  SseLiveSource(battleId, "own", {sessionToken})
```

`SseLiveSource` encodes the endpoint-by-intent rule: owner
`/me/battle/<id>/live` uses `fetch` + `ReadableStream` so it can send a
Bearer smoke token or same-site browser session cookies, while public
`/battle/<id>/live` remains native `EventSource` with no credentials. `app.js`
accepts the token from `window.AGENTDEX_SESSION_TOKEN`, `?session_token=...` for
operator smoke, or `localStorage.agentdex_session_token`; the production shell
should inject it without putting tokens in URLs. For live smoke against a known
active battle, append `?live=1&battle_id=<id>` (or `live_battle_id`) to override
the first selected roster row's `live_battle_id` without falling back to demo
data.

## Remaining for integration / live gates

1. **Live smoke** — run `https://agentdex.builders/dashboard/?live=1&battle_id=<active>&session_token=<smoke-token>` (or cookie-backed login) once an operator supplies a real session token + active battle id. Without those, the page correctly fails closed rather than using fixtures in live mode.
2. **Deployment** — `agentdex.builders` currently serves `/dashboard/` from the bundled `web/dashboard` static mount; legacy `agentdex.ai-builders.space/dashboard/` still returns 404 and should either be redeployed or retired.
3. **Design polish** — the shell now uses the Arena design-token family (Chakra Petch / IBM Plex Mono); a visual pass can still tune weights and spacing after live data is captured.
