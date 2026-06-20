/*
 * test_datalayer.mjs — the correctness + fog-of-war proof for the GA-BENE-2
 * data layer, run against the REAL golden battle log
 * (fixtures/protocol_log_sample.txt, the Azumarill-vs-Lumineon Random Battle
 * that adx_showdown ships as its protocol golden).
 *
 * The security-critical assertions (LVC-08/09/10/11/12/16/18): the SPECTATOR
 * projection must NEVER carry a private exact-HP twin (max!=100), a |split|
 * marker, or a ladder rating; the OWNER projection may carry the owner's own
 * exact HP but the OPPONENT's HP must stay public.
 *
 * Run: node test/test_datalayer.mjs   (exit 0 = all pass)
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import LP from "../src/lineproto.js";
import SR from "../src/scene.js";
import Projector from "../src/projector.js";
import LiveSource from "../src/live-source.js";

const here = dirname(fileURLToPath(import.meta.url));
const raw = readFileSync(join(here, "../fixtures/protocol_log_sample.txt"), "utf8")
  .split("\n")
  .filter((l, i, arr) => !(l === "" && i === arr.length - 1)); // drop trailing newline only

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; } else { fail++; console.error("  ✗ FAIL:", msg); } };
const section = (s) => console.log("\n== " + s + " ==");

// real max-HP denominators that appear in PRIVATE twins of this battle
const PRIVATE_MAXES = ["298", "279", "302", "249", "247", "248"];
function hasPrivateHP(line) {
  // an HP token cur/max where max is NOT 100 -> a private exact-HP leak
  const m = line.match(/\b\d+\/(\d+)\b/);
  return m && m[1] !== "100";
}

section("lineproto: parse the golden stream");
const events = LP.parseStream(raw);
ok(events.length === raw.length, "every line parsed");
const turns = events.filter((e) => e.type === "turn");
ok(turns.length === 7, `7 |turn| majors (got ${turns.length})`);
const faints = events.filter((e) => e.type === "faint");
ok(faints.length >= 3, `≥3 faints (got ${faints.length})`);
// HPSTATUS parsing
ok(LP.parseHPStatus("176/298").hpFrac.toFixed(2) === "0.59", "176/298 -> 0.59");
ok(LP.parseHPStatus("0 fnt").fainted === true, "0 fnt -> fainted");
ok(LP.parseHPStatus("100/100 par").status === "par", "100/100 par -> status par");
// ident sanitization + side
const sw = LP.parseLine("|switch|p1a: Azumarill|Azumarill, L82, M|298/298");
ok(sw.idents[0].side === "p1", "switch ident side=p1");
ok(SR.parseDetails("Azumarill, L82, M").gender === "M", "details gender=M");
// opaque payload: a |request| JSON with a pipe in it stays one arg
const req = LP.parseLine('|request|{"active":[{"moves":["a|b"]}]}');
ok(req.args.length === 1 && req.args[0].includes("a|b"), "opaque |request| not split on inner pipe");

section("projector: SPECTATOR stream — no hidden state leaks (LVC-08/10/12/16)");
const spec = Projector.project(raw, "spectator", { battleId: "b_test" });
const specLines = spec.frames.flatMap((f) => f.lines);
ok(spec.frames.length > 0, `spectator produced ${spec.frames.length} frames`);
ok(spec.frames.every((f) => f.side === "spectator"), "every spectator frame side==spectator (LVC-16)");
ok(!specLines.some((l) => /^\|split\|/.test(l)), "NO |split| marker in spectator lines (LVC-08)");
const specLeaks = specLines.filter(hasPrivateHP);
ok(specLeaks.length === 0, `NO private exact-HP twin on spectator (LVC-12); leaks=${JSON.stringify(specLeaks.slice(0, 3))}`);
// seq monotonic from 0
ok(spec.frames.every((f, i) => f.seq === i), "seq monotonic from 0 (LVC-07)");
// scene fog: opponent (and own) hp shown as fraction, present
const lastSpec = spec.frames[spec.frames.length - 1].scene;
ok(typeof lastSpec.p1.hp_frac === "number" && typeof lastSpec.p2.hp_frac === "number", "scene hp_frac is numeric");
ok(!("hpFrac" in lastSpec.p1) && !("hpFrac" in lastSpec.p2), "scene snapshot uses contract hp_frac, not hpFrac");
// player rating redaction: no rating value survives (LVC-11)
const specPlayers = specLines.filter((l) => l.startsWith("|player|"));
ok(specPlayers.length >= 2, "player lines present");
ok(specPlayers.every((l) => /^\|player\|p[12]\|[^|]*\|\|?$/.test(l) || l.endsWith("||")), "player lines carry NO rating value (LVC-11)");
const metaProjection = Projector.projectLines([
  "|request|{\"active\":[{\"moves\":[\"Thunderbolt\"]}]}",
  "|inactive|Time left: 90 sec",
  "|error|p1|hidden decision payload",
  "|player|p1|Alpha||1500",
  "|turn|1",
  "|",
], "spectator");
ok(!metaProjection.some((l) => /^\|(request|inactive|error)\|/.test(l)), "hidden control/meta lines stripped before emission");
ok(metaProjection.some((l) => l === "|player|p1|Alpha||"), "public player meta survives with rating blanked");

section("projector: OWNER p1 stream — own exact HP allowed, opponent stays public (LVC-09)");
const p1 = Projector.project(raw, "p1", { battleId: "b_test" });
const p1Lines = p1.frames.flatMap((f) => f.lines);
ok(!p1Lines.some((l) => /^\|split\|/.test(l)), "NO |split| marker in owner lines (LVC-08)");
// p1's OWN mon (p1a) may carry exact HP; the OPPONENT (p2a) must NOT
const p2aOnOwner = p1Lines.filter((l) => /\|p2a:/.test(l) && /\b\d+\/\d+\b/.test(l));
const p2aLeaks = p2aOnOwner.filter(hasPrivateHP);
ok(p2aLeaks.length === 0, `opponent p2a HP stays public on owner stream (LVC-09); leaks=${JSON.stringify(p2aLeaks.slice(0, 3))}`);
// and the owner DID get at least one of its own exact-HP lines (proves projection picked private)
const p1aPrivate = p1Lines.filter((l) => /\|p1a:/.test(l) && hasPrivateHP(l));
ok(p1aPrivate.length > 0, `owner sees its OWN exact HP (got ${p1aPrivate.length} private p1a lines)`);
ok(p1.frames.some((f) => /\b\d+\/(298|279|302|249|247|248)\b/.test(f.scene.p1.hp_label || "")), "owner scene preserves own exact HP label");
ok(!p1.frames.some((f) => /\b\d+\/(298|279|302|249|247|248)\b/.test(f.scene.p2.hp_label || "")), "owner scene does not expose opponent exact HP label");

section("projector: SPECTATOR vs OWNER differ exactly on own-side privacy");
// the spectator's p1a damage lines must be the /100 twin where owner's are /max
const specP1aHP = specLines.filter((l) => /\|-damage\|p1a:/.test(l));
ok(specP1aHP.every((l) => !hasPrivateHP(l)), "spectator p1a damage is public %");

section("determinism: |t:| stripped (LVC-18)");
const withTs = ["|t:|1718000000", "|move|p1a: X|Tackle|p2a: Y", "|t:|1718000001", "|"];
const projTs = Projector.projectLines(withTs, "spectator");
ok(!projTs.some((l) => l.startsWith("|t:|")), "|t:| lines stripped from projection");

section("scene reducer: HP monotonic down as Lumineon is chipped");
const lumHp = spec.frames.map((f) => f.scene.p2.hp_frac).filter((x) => typeof x === "number");
ok(lumHp.some((x) => x < 1), "p2 hp dropped below full at some point");
ok(spec.frames.some((f) => f.scene.p1.fainted || f.scene.p2.fainted), "a faint reflected in scene");
const detailsScene = SR.newScene();
SR.applyLine(detailsScene, "|switch|p1a: Ditto|Ditto, L78|100/100");
SR.applyLine(detailsScene, "|detailschange|p1a: Ditto|Garchomp, L78, M|76/100");
ok(detailsScene.p1.species === "Garchomp" && detailsScene.p1.hp_frac === 0.76, "detailschange updates active species + HP");
const sideScene = SR.newScene();
SR.applyLine(sideScene, "|-sidestart|p1: Alpha|Reflect");
SR.applyLine(sideScene, "|-sidestart|p2: Beta|Reflect");
SR.applyLine(sideScene, "|-sideend|p1: Alpha|Reflect");
ok(
  sideScene.field.length === 1 && sideScene.field[0].side === "p2" && sideScene.field[0].effect === "Reflect",
  "side-condition end removes only the matching side"
);

section("live source: owner stream uses Bearer fetch, public stream uses EventSource");
ok(
  LiveSource.endpointFor("own", "b_123").url === "/me/battle/b_123/live" &&
    LiveSource.endpointFor("own", "b_123").auth === true,
  "own-agent stream routes to authenticated /me endpoint"
);
ok(
  LiveSource.endpointFor("spectate", "b_123").url === "/battle/b_123/live" &&
    LiveSource.endpointFor("spectate", "b_123").auth === false,
  "spectator stream routes to public endpoint"
);

const enc = new TextEncoder();
function streamFrom(chunks) {
  let i = 0;
  return {
    getReader() {
      return {
        async read() {
          if (i >= chunks.length) return { done: true };
          return { done: false, value: enc.encode(chunks[i++]) };
        },
      };
    },
  };
}

const seen = { url: null, auth: null, messages: [], ends: [], errors: [] };
const owner = new LiveSource.SseLiveSource("b_auth", "own", {
  sessionToken: "session-123",
  fetch: async (url, opts) => {
    seen.url = url;
    seen.auth = opts.headers.Authorization;
    return {
      ok: true,
      body: streamFrom([
        'data: {"battle_id":"b_auth","seq":1}\n\n',
        'event: end\ndata: {"replay_url":"/replay/b_auth"}\n\n',
      ]),
    };
  },
});
owner.onmessage = (ev) => seen.messages.push(ev.data);
owner.addEventListener("end", (ev) => seen.ends.push(ev.data));
owner.addEventListener("error", (ev) => seen.errors.push(ev.data || ev.detail));
owner.start();
await owner._streamTask;
ok(seen.url === "/me/battle/b_auth/live", "owner fetch hits authenticated live endpoint");
ok(seen.auth === "Bearer session-123", "owner fetch sends Authorization: Bearer token");
ok(seen.messages[0]?.seq === 1, "owner fetch stream parses message events");
ok(seen.ends[0]?.replay_url === "/replay/b_auth", "owner fetch stream parses end events");
ok(seen.errors.length === 0, "owner fetch stream had no errors");

let publicEventSource = null;
function FakeEventSource(url, opts) {
  this.listeners = {};
  this.closed = false;
  this.addEventListener = (type, fn) => { this.listeners[type] = fn; };
  this.close = () => { this.closed = true; };
  publicEventSource = { url, opts, instance: this };
}
const pub = new LiveSource.SseLiveSource("b_pub", "spectate", { EventSource: FakeEventSource }).start();
ok(publicEventSource.url === "/battle/b_pub/live", "public stream uses spectator endpoint");
ok(publicEventSource.opts.withCredentials === false, "public EventSource sends no credentials");
const publicEnds = [];
pub.addEventListener("end", (ev) => publicEnds.push(ev.data));
publicEventSource.instance.listeners.end({ data: "{\"replay_url\":\"/replay/b_pub\"}" });
ok(publicEnds[0]?.replay_url === "/replay/b_pub", "public EventSource forwards terminal end event");
ok(publicEventSource.instance.closed === true, "public EventSource closes on terminal end");

console.log(`\n${fail === 0 ? "✅ ALL PASS" : "❌ FAILURES"}: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
