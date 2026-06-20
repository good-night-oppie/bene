# Live battle viewer — frame contract (A-CLI-2)

The wire contract for **US-3.1** (watch an agent battle live, scene adjacent to the
Agent Pane). adx-cli owns this schema; **adx-core (GA-CORE-3)** emits it, **bene-core
(GA-BENE-2)** renders it. Built on the existing line-protocol (`packages/adx_showdown`
`lineproto.py`, PR #200) + the determinism trilogy — reuse, don't reinvent.

## Transport — TWO endpoints (auth split, do NOT collapse)
A live battle carries **two distinct projections**; they must NOT share one anonymous
endpoint (review #3440679563 — otherwise anyone who guesses a battle id sees owner-only
hidden state):

- **Public spectator** — `GET /battle/{battle_id}/live` — **SSE**, **no auth**, emits the
  **spectator projection ONLY**: public HP percent, no hidden info, **no rating** (the
  `side` field is always `"spectator"`). This is the route for **third-party / open
  spectating** (e.g. a shared battle link). Mirrors `/replay`'s public posture.
- **Owner side** — `GET /me/battle/{battle_id}/live` (or `…/live?side=mine`) — **SSE,
  authenticated**. Emits the owner's `p1`/`p2` per-side frame WITH their own hidden info
  (their own `|split|` private lines). The server verifies the token's owner actually owns a
  side of this battle before upgrading from the spectator projection; a mismatch falls back
  to spectator-only. **The logged-in dashboard's own-agent view (US-2.1 / US-3.1 fog-of-war)
  MUST use THIS endpoint, not the public one** (review #3440779169) — the public stream has
  no hidden info and would fail the own-side fog-of-war requirement.
  - **Browser auth carrier (review #3440779176): DECIDED for launch.** The shipped
    gateway is Bearer-only for `GET /me/battle/{battle_id}/live`, so GA-BENE-2 uses a
    **fetch-based SSE client** (`fetch` + `ReadableStream`) that attaches
    `Authorization: Bearer <sessionToken>`. Native `EventSource` remains correct for the
    public spectator endpoint; an HTTP-only cookie carrier is a non-critical follow-up if
    the product adds that auth surface later.

- Backpressure: a client connecting mid-battle first gets the buffered frames `[0..now]`
  (its own projection), then streams live.
- Both end with a terminal `event: end` carrying the `/replay/{id}` url.

## Frame schema (one SSE `data:` JSON per frame)
```jsonc
{
  "battle_id": "b_…",
  "turn": 7,                     // 0 = team preview / lead
  "seq": 42,                     // monotonic; client dedups/orders on this
  "side": "p1" | "p2" | "spectator",
  "lines": ["|move|p1a: Garchomp|Earthquake|p2a: Rotom", "|-damage|p2a: Rotom|41/100"],
  "scene": {                     // pre-parsed convenience (renderer may use lines instead)
    "p1": {"species":"garchomp","hp_frac":1.0,"hp_label":"357/357","status":null,"name":"adx…"},
    "p2": {"species":"rotom-wash","hp_frac":0.41,"status":null,"name":"…"},
    "weather": null, "field": []
  },
  "ts_ms": 0                     // server stamp; client computes lag
}
```

## Fog-of-war + meta redaction (load-bearing — the determinism trilogy)
- The server emits **per-side** frames. A `|split|pX` block is a **three-line sentinel**: the
  `|split|pX` marker, then the **private** line for side pX (exact HP), then its **public** twin
  (percent HP). The `|split|pX` marker is a **control sentinel — it is NEVER emitted into
  `lines`** ("`|split|` itself is never shown",
  `docs/references/2026-06-17-arena-line-protocol.md:62`); it is not a renderable HP event, and a
  stray marker would make a downstream reducer treat `lines` as a two-line secret-share sentinel
  instead of a clean event stream. For each block the projection **drops the marker** and keeps
  exactly ONE of the two data lines (review #3440779183 / #3440834887):
  - **`side="p1"` owner** stream: for the **own** block (`|split|p1`) keep the **private** line
    (p1's OWN exact HP — the owner is allowed to see it) and drop the public twin; for the
    **opponent** block (`|split|p2`) keep the **public** twin (opponent HP%) and drop the private
    line. Mirror for `side="p2"`.
  - **Public spectator** stream: for **every** block keep only the **public** twin (no `|split|`
    markers, no privates).
- **`lines` must be the REDACTED line set, not the raw runner preamble** (review
  #3440679575): before emitting on the **public** stream the server strips/redacts every
  rating-bearing or hidden meta line — `|teampreview` hidden sets, both `|split|` privates, and
  the rating on `|player|` lines. **Redact a rating by BLANKING the value while keeping the
  positional delimiters** (review #3440779172): `|player|p1|Alpha||1500` → `|player|p1|Alpha||`
  (the empty AVATAR field is preserved; `SIDE|NAME|AVATAR|RATING` stays parseable per
  `docs/references/2026-06-17-arena-line-protocol.md:208`), **or** drop the whole `|player|`
  meta line — never delete just the RATING field positionally (that shifts the slots and
  misparses). Forwarding raw `lines` would satisfy the schema while leaking a rating, so
  redaction is a hard requirement, not advisory.
- `|t:|` timestamp lines are **stripped before any hash** (replay/live must hash-match).
- The scene's `hp_frac` is the HP fraction. Public/opponent projections expose only the
  public fraction. An authenticated owner projection MAY additionally include `hp_label`
  for the owner's own active mon when the kept `|split|` private twin carried an exact
  denominator; public frames and opponent mons MUST omit it. The opponent's exact HP is
  never shown on either stream, and
  `scene.*.name` / `rating` never carry a ladder rating on the public stream.

## Renderer requirements (GA-BENE-2)
- The battle scene mounts **adjacent to the Agent Pane** (side-by-side at ≥1024px; stacked
  below on mobile). Selecting one of **MY** live agents opens the **owner** stream
  (`/me/battle/{id}/live`, authenticated, own-side fog-of-war); a third-party / shared link
  opens the **public spectator** stream — never the public stream for the dashboard's own-agent view.
- ≤2s end-to-end lag (AC3); render incrementally per `seq` (never wait for battle end).
- On `event: end`, swap to the replay control bound to the same scene component (US-3.2),
  so live + replay share one renderer.

## Open items to freeze with adx-core before GA-CORE-3 build
1. SSE vs WebSocket (SSE preferred — one-way, proxy-friendly, auto-reconnect).
2. Buffer retention window per battle (default: full battle, dropped on replay-commit).
3. ~~Auth split~~ **DECIDED** (above): public spectator endpoint (no auth, redacted
   projection) + authenticated owner endpoint (`/me/battle/{id}/live`,
   `Authorization: Bearer <sessionToken>` via fetch streaming). Open sub-item: exact
   owner-ownership check against the battle's side bindings.
