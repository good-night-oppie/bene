/*
 * scene.js — the pure scene reducer. Folds parsed ProtocolEvents into a
 * renderable battle-state snapshot {p1, p2, weather, field, teams, turn}.
 *
 * Shared by two consumers (LIVE_VIEWER_CONTRACT.md "live + replay share one
 * render path"):
 *   - the projector (server/GA-CORE-3 reference) computes the `scene` snapshot
 *     it attaches to every frame ("pre-parsed convenience"), and
 *   - the renderer may fall back to it if a frame omits `scene`.
 *
 * hp_frac is always the fraction cur/max; on the public twin max==100 so it is
 * the public percentage, on an owner's own private twin it is the exact
 * fraction — same number, exact provenance (LVC-12).
 */
;(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory(require("./lineproto.js"));
  else root.SceneReducer = factory(root.LineProto);
})(typeof globalThis !== "undefined" ? globalThis : this, function (LP) {
  "use strict";

  function mon() {
    return { species: null, hpFrac: null, status: null, name: null, gender: null, fainted: false };
  }
  function newScene() {
    return {
      p1: mon(), p2: mon(),
      players: { p1: null, p2: null }, // trainer/agent handle (NEVER a rating)
      weather: null,
      field: [], // [{effect, side}]
      teams: { p1: {}, p2: {} }, // species -> {fainted}
      turn: 0,
      winner: null,
    };
  }

  // "Azumarill, L82, M" -> {species:"Azumarill", gender:"M"}
  function parseDetails(details) {
    const toks = String(details == null ? "" : details).split(",").map((s) => s.trim());
    const out = { species: toks[0] || null, gender: null };
    for (let i = 1; i < toks.length; i++) {
      const t = toks[i];
      if (t === "M" || t === "F") out.gender = t;
    }
    return out;
  }

  function sideOf(ev) {
    return ev.idents.length ? ev.idents[0].side : "";
  }

  // Apply ONE parsed event to the scene (mutates + returns scene).
  function applyEvent(scene, ev) {
    const t = ev.type;
    const a = ev.args;
    switch (t) {
      case "player": {
        // |player|SIDE|NAME|AVATAR|RATING — capture NAME only (rating dropped).
        const side = a[0];
        if (side === "p1" || side === "p2") scene.players[side] = LP.sanitizeName(a[1] || "");
        break;
      }
      case "switch":
      case "drag":
      case "replace": {
        const side = sideOf(ev);
        if (side !== "p1" && side !== "p2") break;
        const d = parseDetails(a[1]);
        const hp = LP.parseHPStatus(a[2]);
        scene[side] = {
          species: d.species, gender: d.gender,
          name: ev.idents[0].name || d.species,
          hpFrac: hp.hpFrac == null ? 1 : hp.hpFrac,
          status: hp.status, fainted: hp.fainted,
        };
        if (d.species) scene.teams[side][d.species] = scene.teams[side][d.species] || { fainted: false };
        break;
      }
      case "-damage":
      case "-heal":
      case "-sethp": {
        const side = sideOf(ev);
        if (side !== "p1" && side !== "p2") break;
        const hp = LP.parseHPStatus(a[1]);
        if (hp.hpFrac != null) scene[side].hpFrac = hp.hpFrac;
        if (hp.fainted) { scene[side].fainted = true; scene[side].hpFrac = 0; }
        if (hp.status) scene[side].status = hp.status;
        break;
      }
      case "-status": {
        const side = sideOf(ev);
        if (side === "p1" || side === "p2") scene[side].status = a[1] || scene[side].status;
        break;
      }
      case "-curestatus": {
        const side = sideOf(ev);
        if (side === "p1" || side === "p2") scene[side].status = null;
        break;
      }
      case "faint": {
        const side = sideOf(ev);
        if (side === "p1" || side === "p2") {
          scene[side].fainted = true;
          scene[side].hpFrac = 0;
          if (scene[side].species) (scene.teams[side][scene[side].species] = scene.teams[side][scene[side].species] || {}).fainted = true;
        }
        break;
      }
      case "-weather": {
        const w = a[0];
        scene.weather = !w || w === "none" ? null : w;
        break;
      }
      case "-fieldstart": {
        if (a[0]) scene.field.push({ effect: a[0], side: null });
        break;
      }
      case "-fieldend": {
        scene.field = scene.field.filter((f) => f.effect !== a[0]);
        break;
      }
      case "-sidestart": {
        if (a[1]) scene.field.push({ effect: a[1], side: a[0] });
        break;
      }
      case "-sideend": {
        scene.field = scene.field.filter((f) => f.effect !== a[1]);
        break;
      }
      case "turn": {
        if (ev.turnNo != null) scene.turn = ev.turnNo;
        break;
      }
      case "win": {
        scene.winner = LP.sanitizeName(a[0] || "");
        break;
      }
      default:
        break;
    }
    return scene;
  }

  function applyLine(scene, line) {
    return applyEvent(scene, LP.parseLine(line));
  }

  // A deep snapshot of the renderable subset (safe to attach to a frame).
  function snapshot(scene) {
    return {
      p1: Object.assign({}, scene.p1),
      p2: Object.assign({}, scene.p2),
      players: Object.assign({}, scene.players),
      weather: scene.weather,
      field: scene.field.map((f) => Object.assign({}, f)),
      turn: scene.turn,
      winner: scene.winner,
    };
  }

  return { newScene, applyEvent, applyLine, snapshot, parseDetails };
});
