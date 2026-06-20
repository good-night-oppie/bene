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
 * the public percentage. Owner-only exact HP is carried separately as hp_label
 * when the projected line used a private max-HP denominator.
 */
;(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory(require("./lineproto.js"));
  else root.SceneReducer = factory(root.LineProto);
})(typeof globalThis !== "undefined" ? globalThis : this, function (LP) {
  "use strict";

  function mon() {
    return {
      species: null,
      hp_frac: null,
      hp_label: null,
      status: null,
      name: null,
      gender: null,
      fainted: false,
    };
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

  function sideArg(ev, raw) {
    const side = sideOf(ev);
    if (side === "p1" || side === "p2") return side;
    const parsed = LP.parseIdent(raw || "");
    return parsed.side;
  }

  function exactHpLabel(hp) {
    if (!hp || hp.cur == null || hp.max == null || hp.max === 100 || hp.fainted) return null;
    return `${hp.cur}/${hp.max}`;
  }

  function applyHp(monState, hp, defaultFull) {
    if (hp.hpFrac != null) {
      monState.hp_frac = hp.hpFrac;
      monState.hp_label = exactHpLabel(hp);
    } else if (defaultFull && monState.hp_frac == null) {
      monState.hp_frac = 1;
      monState.hp_label = null;
    }
    if (hp.fainted) {
      monState.fainted = true;
      monState.hp_frac = 0;
      monState.hp_label = null;
    }
    if (hp.status) monState.status = hp.status;
  }

  function applyActive(scene, ev, detailsArg, hpArg, defaultFull) {
    const side = sideOf(ev);
    if (side !== "p1" && side !== "p2") return;
    const d = parseDetails(detailsArg);
    const hp = LP.parseHPStatus(hpArg);
    scene[side].species = d.species || scene[side].species;
    scene[side].gender = d.gender;
    scene[side].name = (ev.idents[0] && ev.idents[0].name) || scene[side].name || d.species;
    scene[side].fainted = false;
    applyHp(scene[side], hp, defaultFull);
    if (d.species) scene.teams[side][d.species] = scene.teams[side][d.species] || { fainted: false };
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
        applyActive(scene, ev, a[1], a[2], true);
        break;
      }
      case "detailschange": {
        applyActive(scene, ev, a[1], a[2], false);
        break;
      }
      case "-damage":
      case "-heal":
      case "-sethp": {
        const side = sideOf(ev);
        if (side !== "p1" && side !== "p2") break;
        const hp = LP.parseHPStatus(a[1]);
        applyHp(scene[side], hp, false);
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
          scene[side].hp_frac = 0;
          scene[side].hp_label = null;
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
        const side = sideArg(ev, a[0]);
        if (a[1]) scene.field.push({ effect: a[1], side: side || null });
        break;
      }
      case "-sideend": {
        const side = sideArg(ev, a[0]);
        scene.field = scene.field.filter((f) => !(f.effect === a[1] && (!side || f.side === side)));
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

  function monSnapshot(m) {
    return {
      species: m.species,
      hp_frac: m.hp_frac,
      hp_label: m.hp_label,
      status: m.status,
      name: m.name,
      gender: m.gender,
      fainted: m.fainted,
    };
  }

  // A deep snapshot of the renderable subset (safe to attach to a frame).
  function snapshot(scene) {
    return {
      p1: monSnapshot(scene.p1),
      p2: monSnapshot(scene.p2),
      players: Object.assign({}, scene.players),
      weather: scene.weather,
      field: scene.field.map((f) => Object.assign({}, f)),
      turn: scene.turn,
      winner: scene.winner,
    };
  }

  return { newScene, applyEvent, applyLine, snapshot, parseDetails };
});
