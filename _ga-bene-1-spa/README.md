# GA-BENE-1 — dashboard SPA assembly (bene lineage, build-ahead)

The **agentdex.builders dashboard**, assembled from the three render-verified
build-ahead panels into one SPA and wired to the live `/me/*` + SSE feeds — the
explicit `bene` deliverable ("`bene` assembles the GA-BENE-1 SPA from the 3 +
wires live /me/* + SSE + smoke"). Both GA backends are merged (GA-CORE-5 #370,
GA-CORE-3 #377), so the only step beyond this is the DNS/TLS-gated live smoke.

Built ahead in this scratch dir (untracked, same convention as the 3 panels);
offered to adx-cli for integration into `agentdex-cli/tasks/agentdex-builders-ga/`
+ deploy (adx-cli owns the agentdex.builders deploy lane).

## What it is

One dashboard composing the three panels against the canonical layout
(`tasks/agentdex-builders-ga/DESIGN/dashboard.html`, USER_STORIES Epic 2/3/4):

| region | panel | source module | renders from |
|--------|-------|---------------|--------------|
| roster + Agent Pane genome HUD | GA-BENE-1 | `vendor/agent_hud.js` | `/me/agents` (#539 `genome_summary`) |
| live battle scene (US-3.1) | GA-BENE-2 | `vendor/live/*` (`<battle-scene>`) | GA-CORE-3 SSE frames |
| Evolution · lineage (US-4.2) | GA-BENE-4 | `vendor/evo_panel.js` | `to_done_json` (held-out re-measure) |
| ladder (US-5.1) | — | static placeholder | next GA-BENE panel |

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

```
roster   ./fixtures/me_agents.json          ⇄  GET /me/agents                    (session token)
evo      ./fixtures/done.json               ⇄  GET /me/agents/<id>/evolution
battle   MockLiveSource(golden fixture)     ⇄  SseLiveSource(battleId, "own", {sessionToken})
```

`SseLiveSource` already encodes the endpoint-by-intent rule: owner
`/me/battle/<id>/live` uses `fetch` + `ReadableStream` with
`Authorization: Bearer <sessionToken>`, while public `/battle/<id>/live` remains native
`EventSource` with no credentials. `app.js` accepts the token from
`window.AGENTDEX_SESSION_TOKEN`, `?session_token=...` for smoke, or
`localStorage.agentdex_session_token`; the production shell should inject it without
putting tokens in URLs.

## Remaining for integration (adx-cli's deploy lane)

1. **Live smoke** — run with `?live=1` against a real session token + a live
   battle id (DNS/TLS-gated for agentdex.builders).
2. **Ladder panel** — US-5.1 owner-scoped slice (the 4th region, still a placeholder).
3. **Design polish (adx-cli design lane)** — agent_hud + evo were authored on the
   Geist token set; this shell unifies everything onto the DESIGN/dashboard.html
   tokens (Chakra Petch / IBM Plex Mono). A design pass can reconcile fonts/weights.
4. **Home** — land under `agentdex-cli/tasks/agentdex-builders-ga/` and mount on
   the deploy.
