---
title: "Arena typed line-protocol — |TYPE|args message set (adx-sim/client/view)"
status: validated
owner: "@EdwardTang"
created: 2026-06-17
updated: 2026-06-17
type: reference
scope: packages/adx_showdown
layer: types
cross_cutting: true
enforced_by:
  - "packages/adx_showdown/src/adx_showdown/lineproto.py — the typed parser + MESSAGE_TYPES registry"
  - "packages/adx_showdown/tests/test_lineproto.py — parser behavior gated against ground-truth lines"
  - "tests/test_lineproto.py::test_protocol_doc_covers_registry — this doc's table MUST enumerate every MESSAGE_TYPES entry"
provenance: "wf_f583f25f-cda (5 agents, 362k tokens): @pkmn/protocol + smogon SIM-PROTOCOL.md fetched, cross-checked against a real pokemon-showdown 0.11.10 gen9randombattle capture (774 lines). Verdict ok=True, 0 mismatches, 40 confirmations. Implements digest §2 + P1-a of docs/references/2026-06-17-showdown-ux-hvai-digest.md."
---

# Arena typed line-protocol

This is the **single battle wire format** for the agentdex arena (digest §2 /
P1-a). The engine (adx-sim) emits an append-only `|TYPE|args|[kwargs]` line
stream; every renderer — TUI, web, replay — is a **pure reducer** over it, so
live play and replay share one render path. The hyphen-prefix is the **tier
signal**, "the renderer's animation-lane router":

- **major** — no hyphen; structures the turn timeline; rendered as headline
  lines (`|move|`, `|switch|`, `|faint|`, `|turn|`, `|win|`).
- **minor** — hyphen-prefixed; a consequence animated *underneath* its parent
  major; indented (`|-damage|`, `|-boost|`, `|-status|`, `|-reasoning|`).
- **meta** — preamble / control / divider / non-event (the bare `|` divider,
  `|t:|` timestamps, `|player|`, `|split|`, `|request|`, `|upkeep|`).

The typed model lives in `adx_showdown.lineproto`. `tier_of(type)` consults the
`MESSAGE_TYPES` registry first, then falls back to the hyphen rule, so an
**unknown** message still parses and routes to a safe lane — it never raises
(digest §7: malformed event → safe placeholder, never crash).

## Faithfulness + sanitization contract

`ProtocolEvent.raw` is the verbatim line and is **never mutated**, so the
protocol log round-trips for re-simulation hashing (P1-c). The A6 sanitizer
(`[A-Za-z0-9 _-]` allowlist) is applied ONLY to the one opponent-controlled
free-text field — the nickname inside a Pokémon ident (`PokemonIdent.name`),
which is what reaches a human renderer or an agent context. Numeric/structural
args (HP `176/298`, kwargs) stay verbatim — sanitizing them would corrupt the
stream.

## Cross-cutting rules (drive Phase 5 verify + Phase 8 perspective streams)

These five rules are ground-truthed against `pokemon-showdown` 0.11.10 and are
load-bearing for the downstream phases.

### 1. `|split|SIDE` secret-sharing — the native fog-of-war primitive

Every `|split|pX` is **immediately followed by exactly two consecutive lines of
the same message type**: the first is the PRIVATE/omniscient view (full HP
`num/den`, e.g. `176/298`, or `0 fnt`); the second is the PUBLIC view (percent,
e.g. `60/100`). Kwargs are identical across the pair.

- Consumer rule: the omniscient / replay / *named-player* stream keeps line 1
  and **drops** line 2; a spectator / the opponent keeps line 2 and **drops**
  line 1. `|split|` itself is never shown.
- A naive concatenating renderer **double-renders every HP event** — this is the
  bug the perspective-multiplexing layer (digest §4, Phase 8) exists to prevent.
- Observed split-paired types: `switch` (full DETAILS repeats; only HP differs),
  `-damage`, `-heal`. `|split|` appears only in the sim `update` block, never in
  `sideupdate`.

### 2. `|t:|<unixtime>` non-determinism — strip before any hash

`|t:|` is wall-clock UNIX seconds and opens every output chunk. It varies
run-to-run, so the `(seed, inputLog)` determinism/verify hash (digest §1, Phase
5) MUST strip all `|t:|` lines before diffing or hashing. Re-simulation must
reproduce byte-identical protocol output **after `|t:|` stripping** — that is
what makes signed replays verifiable. `NONDETERMINISTIC_TYPES` is the canonical
strip-set.

### 3. Tier = hyphen rule with a meta carve-out

major = no-hyphen battle events that structure the turn. minor = every
hyphen-prefixed consequence. meta = preamble/control/divider/non-event:
`t:`, `gametype`, `player`, `teamsize`, `gen`, `tier`, `rated`, `seed`, `rule`,
`clearpoke`, `poke`, `teampreview`, `updatepoke`, `badge`, `request`,
`inactive(off)`, `upkeep`, `split`, and the bare `|` divider. `request` and
`upkeep`/`split` are no-hyphen yet meta by this carve-out (control-plane /
divider).

### 4. Kwargs are trailing `[key] value` tokens, order-significant

Kwargs follow the positional args: `[from]EFFECT` (the causing
move/item/ability — `item: Life Orb`, `ability: Trace`, `recoil`, `drain`,
`U-turn`); `[of]POKEMON` (the other mon that owns the `[from]` effect); flag-only
`[still]` (anim suppressed = move blocked), `[eat]`, `[silent]`, `[miss]`,
`[notarget]`, `[upkeep]`, `[spread]`, `[zeffect]`. **The actual cause of many
minors lives ONLY in `[from]`/`[of]`, not positionally** (e.g. `-damage` from
Life Orb).

### 5. Empty-field + arg-order traps

- Naive split-on-`|` **must keep empty positionals**: `|player|p1|Alpha||`
  (empty avatar+rating) and `|move|...|Protect||[still]` (empty target) both
  rely on it. `_split_args` preserves them.
- HP_STATUS is **one** field (`num/num [status]`, e.g. `264/291 par`), not two.
- DETAILS gender is omitted for genderless mons (`Jirachi, L80`).
- `|tier|` (format name with literal `[Gen 9]`) must NEVER be mis-split into a
  phantom `|tie|` — the false-tie determinism trap (see the showdown-determinism
  trilogy). The registry classifies them distinctly.
- `-clearpositiveboost` order is `TARGET|POKEMON|EFFECT` (cleared mon first).
- Ordering is meaningful: `-crit`/`-resisted`/`-supereffective`/`-status`
  precede their damage split; end-of-turn `-heal`/`-item`/`-enditem` interleave
  around `|upkeep|`.

## agentdex additions

`|-reasoning|SIDE|TEXT` is the **only** agentdex-added type (not emitted by
Showdown) — the trainer-agent's rationale on the same ordered timeline as its
move (digest §3, P1-d). `|say|` is its persona-chatter alias. Both are minors on
the dedicated `reasoning` lane so they never pollute the action timeline.

## Message-set registry

The table below is generated from `lineproto.MESSAGE_TYPES` (the single source
of truth) — a guard test asserts every entry here matches the registry. Anything
not listed still parses, tiered by the hyphen rule.

<!-- BEGIN MESSAGE_TYPES (generated from lineproto.MESSAGE_TYPES) -->

| Type | Tier | Arg order | Lane | Notes |
|------|------|-----------|------|-------|
| `|cant|` | major | `POKEMON|REASON|MOVE` | headline | action prevented |
| `|detailschange|` | major | `POKEMON|DETAILS|HPSTATUS` | headline | permanent forme |
| `|drag|` | major | `POKEMON|DETAILS|HPSTATUS` | headline | forced switch-in |
| `|faint|` | major | `POKEMON` | headline | unit eliminated |
| `|message|` | major | `TEXT` | headline | engine narration line |
| `|move|` | major | `POKEMON|MOVE|TARGET` | headline | agent action |
| `|replace|` | major | `POKEMON|DETAILS|HPSTATUS` | headline | illusion reveal |
| `|start|` | major | `—` | headline | battle start (after preamble + divider) |
| `|swap|` | major | `POKEMON|POSITION` | headline | slot swap |
| `|switch|` | major | `POKEMON|DETAILS|HPSTATUS` | headline | loadout swap-in |
| `|tie|` | major | `—` | headline | battle end — draw |
| `|turn|` | major | `N` | rule | turn boundary; carries turn_no |
| `|win|` | major | `WINNER` | headline | battle end — winner name |
| `|-ability|` | minor | `POKEMON|ABILITY` | indent | ability revealed/triggered |
| `|-activate|` | minor | `POKEMON|EFFECT` | indent | effect activated (e.g. Protect) |
| `|-anim|` | minor | `POKEMON|MOVE|TARGET` | indent | animation-only |
| `|-block|` | minor | `POKEMON|EFFECT` | indent | move blocked |
| `|-boost|` | minor | `POKEMON|STAT|AMOUNT` | indent | stat raised |
| `|-center|` | minor | `—` | indent | triples recenter |
| `|-clearallboost|` | minor | `—` | indent | every side's boosts cleared |
| `|-clearboost|` | minor | `POKEMON` | indent | all boosts cleared |
| `|-clearnegativeboost|` | minor | `POKEMON` | indent | negative boosts cleared |
| `|-clearpositiveboost|` | minor | `TARGET|POKEMON|EFFECT` | indent | TARGET first — cleared mon |
| `|-combine|` | minor | `—` | indent | moves combined |
| `|-copyboost|` | minor | `SOURCE|TARGET` | indent | boosts copied |
| `|-crit|` | minor | `POKEMON` | indent-red | critical hit |
| `|-curestatus|` | minor | `POKEMON|STATUS` | indent | status cured |
| `|-damage|` | minor | `POKEMON|HPSTATUS` | indent-red | HP loss |
| `|-end|` | minor | `POKEMON|EFFECT` | indent | volatile ended |
| `|-endability|` | minor | `POKEMON` | indent | ability suppressed |
| `|-enditem|` | minor | `POKEMON|ITEM` | indent | item consumed/removed |
| `|-fail|` | minor | `POKEMON|ACTION` | indent | action failed |
| `|-fieldactivate|` | minor | `EFFECT` | indent | pseudo-weather activate |
| `|-fieldend|` | minor | `EFFECT` | indent | field effect ended |
| `|-fieldstart|` | minor | `EFFECT` | indent | field effect started |
| `|-formechange|` | minor | `POKEMON|SPECIES|HPSTATUS` | indent | temporary forme (carries HP/status) |
| `|-heal|` | minor | `POKEMON|HPSTATUS` | indent-green | HP gain |
| `|-hint|` | minor | `MESSAGE` | indent | rules hint |
| `|-hitcount|` | minor | `POKEMON|NUM` | indent | multi-hit count |
| `|-immune|` | minor | `POKEMON` | indent | immune |
| `|-invertboost|` | minor | `POKEMON` | indent | boosts inverted |
| `|-item|` | minor | `POKEMON|ITEM` | indent | item revealed |
| `|-message|` | minor | `TEXT` | indent | engine message |
| `|-miss|` | minor | `SOURCE|TARGET` | indent | attack missed |
| `|-mustrecharge|` | minor | `POKEMON` | indent | must recharge next turn |
| `|-notarget|` | minor | `POKEMON` | indent | no target |
| `|-ohko|` | minor | `—` | indent | one-hit KO |
| `|-prepare|` | minor | `POKEMON|MOVE` | indent | two-turn move charge |
| `|-reasoning|` | minor | `SIDE|TEXT` | reasoning | agentdex trainer rationale |
| `|-resisted|` | minor | `POKEMON` | indent | resisted |
| `|-restoreboost|` | minor | `POKEMON` | indent | boosts restored (Z-move) |
| `|-setboost|` | minor | `POKEMON|STAT|AMOUNT` | indent | stat set |
| `|-sethp|` | minor | `POKEMON|HPSTATUS` | indent | HP set |
| `|-sideend|` | minor | `SIDE|EFFECT` | indent | side condition ended |
| `|-sidestart|` | minor | `SIDE|EFFECT` | indent | side condition started |
| `|-singlemove|` | minor | `POKEMON|MOVE` | indent | single-move effect |
| `|-singleturn|` | minor | `POKEMON|MOVE` | indent | single-turn effect (Protect) |
| `|-start|` | minor | `POKEMON|EFFECT` | indent | volatile started |
| `|-status|` | minor | `POKEMON|STATUS` | indent | status inflicted (par/brn/…) |
| `|-supereffective|` | minor | `POKEMON` | indent | super-effective |
| `|-swapboost|` | minor | `SOURCE|TARGET|STATS` | indent | boosts swapped |
| `|-terastallize|` | minor | `POKEMON|TYPE` | indent | Terastallization |
| `|-transform|` | minor | `POKEMON|TARGET` | indent | Transform |
| `|-unboost|` | minor | `POKEMON|STAT|AMOUNT` | indent | stat lowered |
| `|-waiting|` | minor | `SOURCE|TARGET` | indent | waiting (Bide etc.) |
| `|-weather|` | minor | `WEATHER` | indent | weather set/upkeep |
| `|-zbroken|` | minor | `POKEMON` | indent | Z-protect broken |
| `|-zpower|` | minor | `POKEMON` | indent | Z-power surge |
| `|say|` | minor | `SIDE|TEXT` | reasoning | agentdex/persona chatter |
| `|` | meta | `—` | rule | bare \| — section/turn divider |
| `|badge|` | meta | `SIDE|TYPE|FORMAT|VALUE` | hidden | ladder-season badge |
| `|clearpoke|` | meta | `—` | hidden | team-preview clear |
| `|done|` | meta | `—` | hidden | request resolved |
| `|error|` | meta | `TEXT` | hidden | rejected choice (see sim fallback rail) |
| `|gametype|` | meta | `GAMETYPE` | hidden | singles/doubles |
| `|gen|` | meta | `NUM` | hidden | generation |
| `|inactive|` | meta | `TEXT` | hidden | timer message |
| `|inactiveoff|` | meta | `TEXT` | hidden | timer off |
| `|player|` | meta | `SIDE|NAME|AVATAR|RATING` | hidden | player intro |
| `|poke|` | meta | `SIDE|DETAILS|ITEM` | hidden | team-preview entry |
| `|rated|` | meta | `MESSAGE` | hidden | rated-battle marker |
| `|request|` | meta | `JSON` | hidden | decision request (see protocol.py) |
| `|rule|` | meta | `RULE` | hidden | clause announcement |
| `|seed|` | meta | `SEED` | hidden | PRNG seed echo |
| `|split|` | meta | `SIDE` | hidden | secret-share: next=private, then=public |
| `|t:|` | meta | `UNIXTIME` | hidden | NON-DETERMINISTIC wall clock |
| `|teampreview|` | meta | `—` | hidden | team-preview start |
| `|teamsize|` | meta | `SIDE|SIZE` | hidden | roster cardinality |
| `|tier|` | meta | `FORMAT` | hidden | format name |
| `|updatepoke|` | meta | `POKEMON|DETAILS` | hidden | team-preview detail reveal |
| `|upkeep|` | meta | `—` | hidden | end-of-turn housekeeping; ordering meaningful |

<!-- END MESSAGE_TYPES -->

## Downstream consumers

- **adx-client** (`client.py`, Phase 3) — folds this stream into `BattleState`.
- **adx-view** (`view.py`, Phase 6) — renders majors as headlines, minors
  indented under their parent, `|turn|`/divider as rules.
- **Phase 5** — strips `NONDETERMINISTIC_TYPES`, hashes the rest for `(seed,
  inputLog)` verify.
- **Phase 8** — uses `|split|` to derive omniscient / spectator / per-agent
  perspective streams.
