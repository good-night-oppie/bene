/*
 * battle-scene.js — the GA-BENE-2 live battle renderer, a <battle-scene> custom
 * element. ONE reusable scene component drives both the live stream and the
 * post-battle replay scrubber (LIVE_VIEWER_CONTRACT.md / US-3.2 "live + replay
 * share one render path").
 *
 * Ingestion is pushFrame({battle_id, turn, seq, side, lines, scene, ts_ms}):
 *   - frames are de-duped + ordered on `seq` (LVC-07);
 *   - the pre-parsed `scene` is the authoritative layout snapshot (active mon,
 *     HP%, status, weather); the raw `lines` drive the transient FX + the event
 *     ticker (parsed with the same lineproto reducer the projector uses);
 *   - HP is rendered as whatever the projection gives — the SERVER already did
 *     fog-of-war, so the renderer shows the opponent as % and (on an owner
 *     stream) the own mon's exact HP, and NEVER reconstructs hidden info (LVC-12).
 *
 * On the SSE "end" event the scene binds the /replay/{id} url and swaps to a
 * replay scrubber over the SAME stored frames (LVC-05/15, AC4).
 *
 * Depends on the global LineProto + SceneReducer (loaded before this script).
 */
(function () {
  "use strict";
  const LP = (typeof globalThis !== "undefined" && globalThis.LineProto) || null;
  const SR = (typeof globalThis !== "undefined" && globalThis.SceneReducer) || null;

  const STATUS_GLYPH = { par: "✦", brn: "♨", slp: "☾", frz: "❄", psn: "☣", tox: "☣" };

  function hpClass(frac) {
    if (frac == null) return "hp-ok";
    if (frac > 0.5) return "hp-ok";
    if (frac >= 0.2) return "hp-warn";
    return "hp-low";
  }
  function pct(frac) {
    if (frac == null) return "—";
    return Math.round(frac * 100) + "%";
  }
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  class BattleScene extends HTMLElement {
    connectedCallback() {
      if (this._built) return;
      this._built = true;
      this.frames = []; // by seq
      this.applied = new Set(); // seq dedup
      this.maxSeq = -1;
      this.nextSeq = null;
      this.replayUrl = null;
      this.mode = "live"; // 'live' | 'replay'
      this.sideLabel = "spectator";
      this.scene = SR ? SR.newScene() : { p1: {}, p2: {}, weather: null, field: [], turn: 0 };
      this._buildDom();
    }

    _buildDom() {
      this.innerHTML = "";
      this.classList.add("bscene");

      // top banner: turn + weather/field + live/seq + lag
      this.elBanner = el("div", "bscene-banner");
      this.elTurn = el("span", "bscene-turn mono", "lead");
      this.elWeather = el("span", "bscene-weather");
      this.elField = el("span", "bscene-field");
      this.elLive = el("span", "bscene-live mono", "● LIVE");
      this.elLag = el("span", "bscene-lag mono", "");
      const bannerRight = el("span", "bscene-banner-right");
      bannerRight.append(this.elField, this.elWeather, this.elLive, this.elLag);
      this.elBanner.append(this.elTurn, bannerRight);

      // arena: p1 (left) vs p2 (right)
      this.elArena = el("div", "bscene-arena");
      this.cardP1 = this._monCard("p1");
      this.elVs = el("div", "bscene-vs mono", "vs");
      this.cardP2 = this._monCard("p2");
      this.elArena.append(this.cardP1.root, this.elVs, this.cardP2.root);

      // fog caption (shown on owner stream — own-side hidden info)
      this.elFog = el("div", "bscene-fog mono", "");

      // event ticker
      this.elTicker = el("div", "bscene-ticker");

      // move banner overlay
      this.elMoveBanner = el("div", "bscene-move-banner");

      // end / replay controls
      this.elControls = el("div", "bscene-controls");
      this.elControls.style.display = "none";

      this.append(this.elBanner, this.elArena, this.elFog, this.elTicker, this.elMoveBanner, this.elControls);
    }

    _monCard(side) {
      const root = el("div", `bscene-mon bscene-${side}`);
      const dots = el("div", "bscene-dots");
      const name = el("div", "bscene-trainer mono");
      const species = el("div", "bscene-species");
      const token = el("div", "bscene-token");
      const hpRow = el("div", "bscene-hp-row");
      const hpTrack = el("div", "bscene-hp-track");
      const hpFill = el("div", "bscene-hp-fill hp-ok");
      hpTrack.append(hpFill);
      const hpPct = el("span", "bscene-hp-pct mono", "—");
      hpRow.append(hpTrack, hpPct);
      const statusPill = el("span", "bscene-status");
      statusPill.style.display = "none";
      const body = el("div", "bscene-mon-body");
      body.append(token, species, statusPill);
      root.append(dots, name, body, hpRow);
      return { root, dots, name, species, token, hpFill, hpPct, statusPill };
    }

    // ---- ingestion -------------------------------------------------------
    _frameSeqs() {
      return Object.keys(this.frames)
        .map((seq) => Number(seq))
        .filter((seq) => Number.isFinite(seq))
        .sort((a, b) => a - b);
    }

    pushFrame(frame) {
      if (frame == null || frame.seq == null) return;
      const seq = Number(frame.seq);
      if (!Number.isFinite(seq)) return;
      frame.seq = seq;
      this.frames[seq] = frame;
      if (this.mode === "replay") return; // replay drives via scrubTo
      if (this.applied.has(seq)) return; // dedup (LVC-07)
      if (this.nextSeq == null) this.nextSeq = seq;
      if (seq < this.nextSeq) return; // stale
      this._drainFrames();
    }

    bindEnd(detail) {
      this.replayUrl = (detail && (detail.replay || detail.replay_url)) || this.replayUrl;
      this.elLive.textContent = "■ ENDED";
      this.elLive.classList.add("ended");
      this._showReplayControls();
    }

    _drainFrames() {
      while (this.nextSeq != null && Object.prototype.hasOwnProperty.call(this.frames, this.nextSeq)) {
        const seq = this.nextSeq;
        const frame = this.frames[seq];
        if (!frame || this.applied.has(seq)) {
          this.nextSeq += 1;
          continue;
        }
        this.applied.add(seq);
        this.maxSeq = seq;
        this.nextSeq += 1;
        this.sideLabel = frame.side || this.sideLabel;
        this._apply(frame, /*animate=*/true);
      }
    }

    // ---- apply + render --------------------------------------------------
    _apply(frame, animate) {
      // authoritative layout from the pre-parsed snapshot, with a line-folding
      // fallback for live SSE frames that omit `scene`.
      this._applyFrameScene(frame);
      // …transient FX + ticker from the raw (already-redacted) lines.
      if (LP && frame.lines) {
        for (const line of frame.lines) this._reduceLine(line, animate);
      }
      this._render(frame, animate);
    }

    _applyFrameScene(frame) {
      if (!frame) return;
      if (frame.scene) {
        this.scene = frame.scene;
        return;
      }
      if (!SR || !frame.lines) return;
      for (const line of frame.lines) SR.applyLine(this.scene, line);
    }

    _reduceLine(line, animate) {
      const ev = LP.parseLine(line);
      const t = ev.type;
      if (t === "" || t === "upkeep" || t === LP.SPLIT_TYPE) return; // dividers/sentinels
      if (LP.NONDETERMINISTIC_TYPES.has(t)) return; // |t:| never rendered (LVC-18)
      const who = ev.idents.length ? ev.idents[0].name : "";
      let msg = null;
      let banner = null;
      switch (t) {
        case "move": banner = `${who} used ${ev.args[1]}!`; msg = banner; break;
        case "switch": case "drag": msg = `${who} — ${SR ? SR.parseDetails(ev.args[1]).species : ev.args[1]} sent out`; break;
        case "-damage": msg = `${who} took damage`; break;
        case "-heal": msg = `${who} restored HP`; break;
        case "-supereffective": msg = "It's super effective!"; break;
        case "-resisted": msg = "It's not very effective…"; break;
        case "-crit": msg = "A critical hit!"; break;
        case "-immune": msg = `${who} is immune`; break;
        case "-status": msg = `${who} is now ${ev.args[1]}`; break;
        case "-curestatus": msg = `${who} recovered`; break;
        case "-weather": msg = ev.args[0] && ev.args[0] !== "none" ? `Weather: ${ev.args[0]}` : null; break;
        case "faint": msg = `${who} fainted!`; break;
        case "-ability": msg = `${who}'s ${ev.args[1]}`; break;
        case "win": msg = `${LP.sanitizeName(ev.args[0])} wins!`; break;
        default: msg = null;
      }
      if (banner && animate) this._flashMoveBanner(banner);
      if (msg) this._tick(msg, t);
    }

    _tick(text, kind) {
      const line = el("div", "bscene-tick", text);
      if (/super|crit|faint|win/.test(kind || "")) line.classList.add("hot");
      this.elTicker.append(line);
      // keep the full transcript in the DOM-light array; cap visible to last ~40
      while (this.elTicker.childNodes.length > 60) this.elTicker.removeChild(this.elTicker.firstChild);
      this.elTicker.scrollTop = this.elTicker.scrollHeight;
    }

    _flashMoveBanner(text) {
      this.elMoveBanner.textContent = text;
      this.elMoveBanner.classList.add("show");
      clearTimeout(this._bannerTimer);
      this._bannerTimer = setTimeout(() => this.elMoveBanner.classList.remove("show"), 1400);
    }

    _renderMon(card, mon, side) {
      mon = mon || {};
      card.species.textContent = mon.species || "—";
      card.token.textContent = (mon.species || "?").slice(0, 1).toUpperCase();
      card.name.textContent = (this.scene.players && this.scene.players[side]) || side;
      const frac = mon.hp_frac == null ? mon.hpFrac : mon.hp_frac;
      card.hpFill.style.width = Math.round((frac == null ? 1 : frac) * 100) + "%";
      card.hpFill.className = "bscene-hp-fill " + hpClass(frac);
      card.hpPct.textContent = mon.fainted ? "KO" : (mon.hp_label || mon.hpLabel || pct(frac));
      card.root.classList.toggle("fainted", !!mon.fainted);
      if (mon.status) {
        card.statusPill.style.display = "";
        card.statusPill.textContent = (STATUS_GLYPH[mon.status] || "•") + " " + mon.status;
        card.statusPill.className = "bscene-status st-" + mon.status;
      } else {
        card.statusPill.style.display = "none";
      }
    }

    _render(frame, animate) {
      this.elTurn.textContent = this.scene.turn ? "turn " + this.scene.turn : "lead";
      this.elWeather.textContent = this.scene.weather ? "☁ " + this.scene.weather : "";
      const field = this.scene.field || [];
      this.elField.textContent = field.length ? field.map((f) => "◇ " + f.effect).join("  ") : "";
      this._renderMon(this.cardP1, this.scene.p1, "p1");
      this._renderMon(this.cardP2, this.scene.p2, "p2");

      // fog caption: owner stream surfaces own-side hidden info; spectator does not.
      if (this.sideLabel === "p1" || this.sideLabel === "p2") {
        this.elFog.textContent = `⊘ fog-of-war · owner stream (${this.sideLabel}) · only your side's hidden info`;
        this.elFog.style.display = "";
      } else {
        this.elFog.textContent = "⊘ spectator · public projection · no hidden info, no rating";
        this.elFog.style.display = "";
      }

      if (frame && this.mode === "live") {
        this.elLive.textContent = "● LIVE";
        // lag display (LVC-14): now - ts_ms; in the mock ts_ms is synthetic so show seq.
        this.elLag.textContent = "seq " + frame.seq;
      }
    }

    // ---- replay (US-3.2 — same component, scrub stored frames) -----------
    _showReplayControls() {
      this.elControls.innerHTML = "";
      this.elControls.style.display = "";
      const seqs = this._frameSeqs();
      const firstSeq = seqs.length ? seqs[0] : 0;
      const lastSeq = seqs.length ? seqs[seqs.length - 1] : 0;
      const replayBtn = el("button", "bscene-btn", "↺ Replay");
      const nextBtn = el("button", "bscene-btn", "▸ Next battle");
      const scrub = el("input", "bscene-scrub");
      scrub.type = "range";
      scrub.min = String(firstSeq);
      scrub.max = String(lastSeq);
      scrub.value = scrub.max;
      scrub.addEventListener("input", () => {
        this._stopReplayTimer();
        this.scrubTo(parseInt(scrub.value, 10));
      });
      replayBtn.addEventListener("click", () => {
        this._stopReplayTimer();
        this.mode = "replay";
        let i = 0;
        const step = () => {
          if (i >= seqs.length) {
            this._replayTimer = null;
            return;
          }
          const seq = seqs[i++];
          scrub.value = String(seq);
          this.scrubTo(seq);
          this._replayTimer = setTimeout(step, 420);
        };
        step();
      });
      nextBtn.addEventListener("click", () => {
        this._stopReplayTimer();
        this.dispatchEvent(new CustomEvent("next-battle"));
      });
      const link = el("a", "bscene-replay-link mono", this.replayUrl || "");
      if (this.replayUrl) link.href = this.replayUrl;
      this.elControls.append(replayBtn, scrub, nextBtn, link);
    }

    _stopReplayTimer() {
      if (this._replayTimer) clearTimeout(this._replayTimer);
      this._replayTimer = null;
    }

    scrubTo(seq) {
      // Re-fold from the start through `seq` — the SAME render path as live.
      this.mode = "replay";
      this.scene = SR ? SR.newScene() : this.scene;
      this.elTicker.innerHTML = "";
      for (const i of this._frameSeqs()) {
        if (i > seq) break;
        const f = this.frames[i];
        if (!f) continue;
        this._applyFrameScene(f);
        if (LP && f.lines && i === seq) for (const line of f.lines) this._reduceLine(line, false);
      }
      this.sideLabel = (this.frames[seq] && this.frames[seq].side) || this.sideLabel;
      this.elLive.textContent = "▮ REPLAY";
      this._render(this.frames[seq], false);
      const seqs = this._frameSeqs();
      const lastSeq = seqs.length ? seqs[seqs.length - 1] : seq;
      this.elLag.textContent = "frame " + seq + "/" + lastSeq;
    }

    reset() {
      this._stopReplayTimer();
      this.frames = [];
      this.applied = new Set();
      this.maxSeq = -1;
      this.nextSeq = null;
      this.mode = "live";
      this.scene = SR ? SR.newScene() : this.scene;
      this.elTicker.innerHTML = "";
      this.elControls.style.display = "none";
      this.elLive.classList.remove("ended");
      this._render(null, false);
    }
  }

  if (typeof customElements !== "undefined" && !customElements.get("battle-scene")) {
    customElements.define("battle-scene", BattleScene);
  }
  if (typeof globalThis !== "undefined") globalThis.BattleScene = BattleScene;
})();
