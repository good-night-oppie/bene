/*
 * projector.js — the GA-CORE-3 *reference* projector. Turns a raw Showdown
 * protocol log into the per-side SSE frame stream that LIVE_VIEWER_CONTRACT.md
 * specifies. This is the load-bearing fog-of-war boundary: get it wrong and a
 * spectator (or an opponent) sees hidden state.
 *
 * It is also a deliverable in its own right: GA-CORE-3 (adx-core) must emit
 * exactly this projection, so this module + its node test double as an
 * executable spec adx-core can port + diff against. (Surfaced to adx-core/adx-cli
 * on the A2A bus.)
 *
 * Three redactions, all ground-truthed against the contract:
 *   1. |split|SIDE blocks (LVC-08/09): the marker is NEVER emitted; for the
 *      owner's OWN block keep the PRIVATE twin, for the opponent's block keep the
 *      PUBLIC twin; the spectator projection keeps the PUBLIC twin for every block.
 *   2. |player| rating (LVC-11): blank the RATING value, keep positional
 *      delimiters — |player|p1|Alpha||1500 -> |player|p1|Alpha|| .
 *   3. |t:| timestamps (LVC-18): stripped (non-deterministic; never rendered).
 */
;(function (root, factory) {
  if (typeof module !== "undefined" && module.exports)
    module.exports = factory(require("./lineproto.js"), require("./scene.js"));
  else root.Projector = factory(root.LineProto, root.SceneReducer);
})(typeof globalThis !== "undefined" ? globalThis : this, function (LP, SR) {
  "use strict";

  // |player|SIDE|NAME|AVATAR|RATING -> blank the RATING value, keep delimiters.
  function redactPlayer(line) {
    const toks = line.split("|"); // ['', 'player', side, name, avatar, rating?]
    if (toks[1] !== "player") return line;
    if (toks.length >= 6) toks[5] = ""; // blank rating value, keep the slot
    // drop any further stray fields' values too (defensive)
    for (let i = 6; i < toks.length; i++) toks[i] = "";
    return toks.join("|");
  }

  /*
   * projectLines(rawLines, side) -> redacted, projected line list for `side`.
   * side ∈ {'spectator','p1','p2'}. Removes |split| markers, resolves each
   * twin per side, strips |t:|, blanks |player| ratings. Never emits hidden info
   * the side is not entitled to.
   */
  function projectLines(rawLines, side) {
    const out = [];
    for (let i = 0; i < rawLines.length; i++) {
      const line = rawLines[i];
      const lt = LP.lineType(line);

      if (lt === LP.SPLIT_TYPE) {
        // |split|SIDE  -> next line = PRIVATE (SIDE-only), then = PUBLIC (all).
        const splitSide = LP.parseLine(line).args[0]; // 'p1' | 'p2'
        const priv = rawLines[i + 1];
        const pub = rawLines[i + 2];
        // Owner stream viewing its OWN block keeps the private twin; everyone
        // else (opponent block, or the spectator projection) keeps the public.
        const keepPrivate = side !== "spectator" && side === splitSide;
        const kept = keepPrivate ? priv : pub;
        if (kept !== undefined) out.push(kept);
        i += 2; // consume marker's two twin lines
        continue;
      }
      if (LP.NONDETERMINISTIC_TYPES.has(lt)) continue; // strip |t:|
      if (lt === "player") { out.push(redactPlayer(line)); continue; }
      out.push(line);
    }
    return out;
  }

  /*
   * project(rawLines, side, opts) -> { battleId, side, frames[], replayUrl }
   * Frames are chunked at bare '|' section dividers; each carries
   * {battle_id, turn, seq, side, lines, scene, ts_ms}. seq is monotonic from 0.
   */
  function project(rawLines, side, opts) {
    opts = opts || {};
    const battleId = opts.battleId || "b_demo";
    const baseTs = opts.baseTs || 0;
    const stepMs = opts.stepMs == null ? 2100 : opts.stepMs; // contract ≤2s budget stand-in
    const lines = projectLines(rawLines, side);

    const scene = SR.newScene();
    const frames = [];
    let cur = [];
    let seq = 0;
    let replayUrl = null;

    const flush = () => {
      if (!cur.length) return;
      const ev = cur.map((l) => LP.parseLine(l));
      for (const e of ev) SR.applyEvent(scene, e);
      frames.push({
        battle_id: battleId,
        turn: scene.turn,
        seq: seq,
        side: side,
        lines: cur.slice(),
        scene: SR.snapshot(scene),
        ts_ms: baseTs + seq * stepMs,
      });
      seq += 1;
      cur = [];
    };

    for (const line of lines) {
      // bare '|' divider = a frame boundary; the divider itself is not rendered.
      if (line === "|" || (line === "" )) { flush(); continue; }
      if (LP.lineType(line) === "win") replayUrl = `/replay/${battleId}`;
      cur.push(line);
    }
    flush();

    if (!replayUrl) replayUrl = `/replay/${battleId}`;
    return { battleId, side, frames, replayUrl };
  }

  return { project, projectLines, redactPlayer };
});
