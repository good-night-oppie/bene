# GA-BENE-2 — live battle viewer (reference renderer)

The bene-core frontend deliverable for **agentdex.builders US-3.1** ("watch my agent
battle LIVE, beside its Agent Pane"). A dependency-light, fixture-driven reference
implementation of the live battle viewer that **renders the frozen
`LIVE_VIEWER_CONTRACT.md` frame schema** and is ready to wire to adx-core's
**GA-CORE-3** SSE streams in one step.

Built ahead of the backend so the integration is a wiring change, not a from-scratch
build — and so the contract's renderability + fog-of-war semantics are proven *before*
GA-CORE-3 is written.

## Run it

```bash
# open the fixture-driven demo (no backend needed)
xdg-open index.html            # or: python3 -m http.server then visit /index.html

# render-verify (headless chromium): scene renders, fog-of-war holds, end→replay swaps
node test/render-verify.mjs    # 11 assertions; screenshots render-owner.png / render-spectator.png

# data-layer + fog-of-war projection correctness against the real golden battle
node test/test_datalayer.mjs   # 33 assertions
```

## Layout

```
src/lineproto.js     JS port of adx_showdown/lineproto.py (the |TYPE|args|[kwargs] parser)
src/scene.js         pure scene reducer: events -> {p1,p2,weather,field,turn} snapshot
src/projector.js     the GA-CORE-3 *reference* projector: raw log -> per-side SSE frames
src/live-source.js   pluggable frame source: MockLiveSource (demo) | SseLiveSource (real)
src/battle-scene.js  the <battle-scene> custom element (one renderer for live AND replay)
src/fixture.js       the real golden battle (adx_showdown protocol_log_sample.txt), embedded
index.html           the dashboard shell — Agent Pane | scene-card grid, design-token-matched
test/                render-verify (chromium) + data-layer fog-of-war proof
fixtures/            the contract, the line-protocol reference, lineproto.py, the golden log
```

## Wiring to GA-CORE-3 (the one-step swap)

The renderer consumes frames from a source that mimics the SSE `EventSource` surface.
Today the demo uses `MockLiveSource` (replays projector frames on a timer). To go live,
swap in `SseLiveSource`, which already encodes the contract's endpoint-by-intent rule:

```js
// own-agent view  -> AUTHENTICATED owner stream (own-side fog-of-war)
const src = new LiveSource.SseLiveSource(battleId, "own", {
  sessionToken,
});                                                              // GET /me/battle/{id}/live
// shared / third-party link -> PUBLIC spectator stream (redacted, no rating)
const src = new LiveSource.SseLiveSource(battleId, "spectate");   // GET /battle/{id}/live
src.onmessage = (e) => scene.pushFrame(e.data);
src.addEventListener("end", (e) => scene.bindEnd(e.data));
src.start();
```

The owner stream is Bearer-only for launch, matching the shipped gateway decision from
adx-cli #580: `SseLiveSource` uses `fetch` + `ReadableStream` and attaches
`Authorization: Bearer <sessionToken>`. The public spectator stream stays native
`EventSource` with no credentials.

## `projector.js` is also a GA-CORE-3 reference

The projector is the fog-of-war boundary GA-CORE-3 must implement: raw Showdown log →
per-side frames with the `|split|` private/public twins resolved per side, `|player|`
ratings blanked, and `|t:|` stripped. `test/test_datalayer.mjs` proves against the real
golden battle that the **spectator** projection never carries a private exact-HP twin, a
`|split|` marker, or a rating, while the **owner** projection keeps its own exact HP but
shows the opponent only as a percentage. adx-core can port + diff against it.

## Contract compliance (`LIVE_VIEWER_CONTRACT.md`)

| LVC | requirement | where |
|-----|-------------|-------|
| 01/02/03/19 | two endpoints by intent; owner-view never public; Bearer owner stream + public SSE | `live-source.js` `endpointFor` / `SseLiveSource` |
| 05/15 | `event:end` → replay control bound to the same scene component (US-3.2) | `battle-scene.js` `bindEnd`/`scrubTo` |
| 07 | dedup + order on `seq` | `battle-scene.js` `pushFrame` |
| 08/09/10/11 | `|split|` never rendered; per-side twin; redacted line set; rating blanked | `projector.js` |
| 12/16 | scene HP is the public fraction; spectator carries no hidden info/rating | `projector.js` + render-verify leak assertion |
| 13 | scene mounts adjacent to the Agent Pane; stacks <1024px | `index.html` `.row.top` + media query |
| 14 | incremental render per `seq`, ≤2s lag budget | `battle-scene.js` + the mock pace |
| 18 | `|t:|` stripped, never rendered | `lineproto.js` / `projector.js` |

## Status

Standalone reference, render-verified. **Not yet integrated** into the agentdex.builders
dashboard or deployed — it's the build-ahead deliverable for GA-BENE-2. GA-CORE-3 and
GA-CORE-5 are now merged; the remaining live wiring is to pass the dashboard session token
to `SseLiveSource` for `/me/battle/{id}/live` and mount the public spectator stream with
native `EventSource`.
