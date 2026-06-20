/*
 * lineproto.js — a faithful JS port of adx_showdown/lineproto.py (the typed
 * Showdown line-protocol). The web renderer is a *pure reducer* over a
 * |TYPE|args|[kwargs] line stream, exactly like the TUI / replay paths, so live
 * and replay share one render path (LIVE_VIEWER_CONTRACT.md "US-3.2 shared
 * renderer"). This module owns nothing about presentation or the engine — it is
 * the typed boundary both fold over.
 *
 * Two cross-cutting facts the renderer + the GA-CORE-3 projector depend on,
 * ground-truthed against the Python source:
 *   - `|split|SIDE` is the secret-sharing marker: the line AFTER it is the
 *     PRIVATE (full-HP, e.g. 176/298) view for SIDE; the line after that is the
 *     PUBLIC (percent, 60/100) view for everyone. This is the native fog-of-war
 *     primitive the projector routes on.
 *   - `|t:|<unixtime>` lines are non-deterministic wall-clock stamps; the verify
 *     path strips them before hashing and they are never rendered.
 *
 * UMD-ish: works as a browser global (window.LineProto) and a CommonJS module
 * (require('./lineproto.js')) so the same code drives the browser viewer and the
 * Node correctness test — no build step.
 */
;(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.LineProto = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // --- special meta sentinels (mirror lineproto.py) ------------------------
  const DIVIDER_TYPE = "";
  const TIMESTAMP_TYPE = "t:";
  const SPLIT_TYPE = "split";
  const NONDETERMINISTIC_TYPES = new Set([TIMESTAMP_TYPE]);

  // Types whose payload ends in ONE opaque field that may itself contain `|`
  // (JSON/HTML/free text). Value = count of leading structured fields before the
  // opaque tail. Splitting these on every pipe would corrupt them.
  const OPAQUE_PAYLOAD_TYPES = {
    request: 0, raw: 0, html: 0, error: 1, inactive: 0, inactiveoff: 0,
    message: 0, "-message": 0, popup: 0, bigerror: 0, debug: 0,
    uhtml: 1, uhtmlchange: 1, chat: 1, c: 1, "c:": 2,
  };

  // Known majors / metas. Anything else: hyphen-prefix => minor, else major,
  // "" => meta (the hyphen-prefix is the load-bearing tier signal).
  const MAJORS = new Set([
    "turn", "move", "switch", "drag", "faint", "win", "tie", "cant", "swap",
    "replace", "detailschange", "start", "message",
  ]);
  const METAS = new Set([
    DIVIDER_TYPE, TIMESTAMP_TYPE, SPLIT_TYPE, "gametype", "player", "teamsize",
    "gen", "tier", "rule", "clearpoke", "poke", "teampreview", "updatepoke",
    "rated", "seed", "badge", "upkeep", "done", "request", "inactive",
    "inactiveoff", "error",
  ]);

  const Tier = { MAJOR: "major", MINOR: "minor", META: "meta" };

  function tierOf(msgType) {
    if (MAJORS.has(msgType)) return Tier.MAJOR;
    if (METAS.has(msgType)) return Tier.META;
    if (msgType === DIVIDER_TYPE) return Tier.META;
    if (msgType.startsWith("-")) return Tier.MINOR;
    return Tier.MAJOR;
  }

  // A6 sanitizer: the nickname is the only opponent-controlled free-text field
  // in the wire protocol; allowlist [A-Za-z0-9 _-] so an injection payload in a
  // visiting-agent nickname can never reach a renderer/prompt surface verbatim.
  function sanitizeName(s) {
    return String(s == null ? "" : s).replace(/[^A-Za-z0-9 _-]/g, "").trim();
  }

  const IDENT_RE = /^(p[1-9])([a-z]?):\s*(.*)$/;
  const KWARG_RE = /^\[([a-z0-9]+)\]\s?(.*)$/i;

  function parseIdent(token) {
    const m = IDENT_RE.exec(String(token).trim());
    if (!m) return { raw: token, side: "", position: "", name: sanitizeName(token) };
    return { raw: token, side: m[1], position: m[2] || "", name: sanitizeName(m[3]) };
  }

  function splitArgs(parts) {
    const positional = [];
    const kwargs = {};
    let inKwargs = false;
    let lastKey = null;
    for (const arg of parts) {
      const m = KWARG_RE.exec(arg);
      if (m) {
        inKwargs = true;
        lastKey = m[1].toLowerCase();
        kwargs[lastKey] = m[2].trim();
      } else if (!inKwargs) {
        positional.push(arg);
      } else if (lastKey != null) {
        kwargs[lastKey] = (kwargs[lastKey] + "|" + arg).replace(/^\|+|\|+$/g, "");
      }
    }
    return { positional, kwargs };
  }

  function parseLine(line, index) {
    if (index === undefined) index = -1;
    let parts;
    if (line.startsWith("|")) parts = line.split("|").slice(1);
    else parts = line.split("|");
    const msgType = parts.length ? parts[0] : "";

    let positional, kwargs;
    if (Object.prototype.hasOwnProperty.call(OPAQUE_PAYLOAD_TYPES, msgType) && line.startsWith("|")) {
      let lead = OPAQUE_PAYLOAD_TYPES[msgType];
      const prefix = "|" + msgType + "|";
      const body = line.startsWith(prefix) ? line.slice(prefix.length) : parts.slice(1).join("|");
      if (msgType === "error") {
        const first = body.split("|", 1)[0];
        if (first !== "p1" && first !== "p2") lead = 0;
      }
      if (lead) {
        // split into `lead` structured fields + one opaque tail
        const out = [];
        let rest = body;
        for (let i = 0; i < lead; i++) {
          const bar = rest.indexOf("|");
          if (bar === -1) { out.push(rest); rest = null; break; }
          out.push(rest.slice(0, bar));
          rest = rest.slice(bar + 1);
        }
        if (rest != null) out.push(rest);
        positional = out;
      } else {
        positional = [body];
      }
      kwargs = {};
    } else {
      const r = splitArgs(parts.slice(1));
      positional = r.positional;
      kwargs = r.kwargs;
    }

    const idents = [];
    for (const a of positional) if (IDENT_RE.test(String(a).trim())) idents.push(parseIdent(a));
    for (const key of Object.keys(kwargs)) {
      if (IDENT_RE.test(String(kwargs[key]).trim())) {
        const id = parseIdent(kwargs[key]);
        idents.push(id);
        kwargs[key] = id.side ? `${id.side}${id.position}: ${id.name}` : id.name;
      }
    }

    let turnNo = null;
    if (msgType === "turn" && positional.length) {
      const n = parseInt(positional[0], 10);
      if (!Number.isNaN(n)) turnNo = n;
    }

    return {
      raw: line, type: msgType, tier: tierOf(msgType),
      args: positional, kwargs, idents, index, turnNo,
    };
  }

  function parseStream(lines) {
    return lines.map((ln, i) => parseLine(ln, i));
  }

  function lineType(line) {
    if (line.startsWith("|")) {
      const body = line.slice(1);
      const bar = body.indexOf("|");
      return bar === -1 ? body : body.slice(0, bar);
    }
    return line;
  }

  function stripNondeterministic(lines) {
    return lines.filter((ln) => !NONDETERMINISTIC_TYPES.has(lineType(ln)));
  }

  function isDivider(ev) { return ev.raw === "|"; }
  function isSectionBreak(ev) { return ev.type === "turn" || ev.raw === "|"; }

  /*
   * parseHPStatus — turn an HPSTATUS field ("176/298", "60/100", "0 fnt",
   * "100/100 par", "248/248 tox") into {hpFrac, fainted, status, cur, max}.
   * The public twin is always cur/100, so its hpFrac == cur/100; an owner's
   * private twin is cur/max with the SAME fraction but exact numbers.
   */
  function parseHPStatus(s) {
    const t = String(s == null ? "" : s).trim();
    const sp = t.split(/\s+/);
    const hp = sp[0] || "";
    const tail = sp[1] || "";
    if (hp === "0" && tail === "fnt") return { hpFrac: 0, fainted: true, status: null, cur: 0, max: 0 };
    if (/fnt/.test(t)) return { hpFrac: 0, fainted: true, status: null, cur: 0, max: 0 };
    const slash = hp.indexOf("/");
    if (slash === -1) return { hpFrac: null, fainted: false, status: tail || null, cur: null, max: null };
    const cur = parseFloat(hp.slice(0, slash));
    const max = parseFloat(hp.slice(slash + 1));
    const hpFrac = max > 0 ? Math.max(0, Math.min(1, cur / max)) : 0;
    const STATUS = new Set(["par", "brn", "slp", "frz", "psn", "tox", "fnt"]);
    const status = STATUS.has(tail) ? tail : null;
    return { hpFrac, fainted: false, status, cur, max };
  }

  // "Azumarill, L82, M" -> "Azumarill"; "Rotom-Wash" stays whole.
  function speciesOf(details) {
    return String(details == null ? "" : details).split(",")[0].trim();
  }

  return {
    Tier, tierOf, parseLine, parseStream, parseIdent, splitArgs,
    sanitizeName, lineType, stripNondeterministic, isDivider, isSectionBreak,
    parseHPStatus, speciesOf,
    DIVIDER_TYPE, TIMESTAMP_TYPE, SPLIT_TYPE, OPAQUE_PAYLOAD_TYPES,
    NONDETERMINISTIC_TYPES,
  };
});
