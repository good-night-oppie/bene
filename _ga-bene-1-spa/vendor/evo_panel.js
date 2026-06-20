/* GA-BENE-4 — Evolution panel (build-ahead, bene-core).
 *
 * Renders the dashboard "Evolution · lineage" panel from a C2-driver DONE_JSON
 * (adx_showdown e2e_driver.to_done_json). Pure + framework-free so it drops into
 * the GA-BENE-1 SPA as a component; data is pluggable (a fixture now, the live
 * to_done_json feed later — the one-line source swap, mirroring bene-2's viewer).
 *
 * Honesty contract (from adx-cli-10 #541, the load-bearing gotchas):
 *   - HEADLINE uplift+CI come from the TOP-LEVEL win_rate_uplift_pp / _ci95_pp —
 *     the FRESH held-out re-measure — NEVER recomputed from lineage[].win_rate
 *     (that's the inflated selection sample). lineage[].win_rate is sparkline-only.
 *   - killgate.passed is present in BOTH the mock and the real (bene evolve) shape;
 *     show killgate.verdict only when present.
 *   - GATE the whole panel on backend==='pokeenv' && scaffold===false && ok===true.
 *     A mock / custom / scaffold run's uplift is NOT a real result → badge it, do
 *     not present the number as a finding.
 *   - winning mutation = the LAST kept lineage entry.
 */

const REAL_BACKEND = "pokeenv";

function isRealResult(d) {
  return d && d.ok === true && d.scaffold === false && d.backend === REAL_BACKEND;
}

function pp(x) {
  // already in percentage points
  return (x >= 0 ? "+" : "") + Number(x).toFixed(1) + "pp";
}

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}

// strategy/labels come from evolved backend data (not constants) and are interpolated into
// innerHTML — escape them so a corrupted/hostile to_done_json cannot inject script. (matches agent_hud.js)
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}

/* Render the Evolution panel for `done` into `mount` (replacing its contents).
 * Returns a small summary object (handy for the render-verify assertions). */
export function renderEvoPanel(done, mount) {
  mount.innerHTML = "";
  const card = el("div", "card evo");

  const real = isRealResult(done);
  const gens = Number(done.gens_completed ?? (done.lineage || []).length ?? 0);

  // header
  const head = el("div", "ch");
  head.appendChild(el("h3", null, "Evolution · lineage"));
  head.appendChild(el("div", "r dim mono", `${gens} generation${gens === 1 ? "" : "s"}`));
  card.appendChild(head);

  const body = el("div", "cb");

  // provenance badge — a mock/scaffold/custom run is NOT a real result.
  if (!real) {
    const why =
      done.ok !== true ? "run not ok" :
      done.scaffold === true ? "scaffold run" :
      `backend=${done.backend ?? "?"} (not ${REAL_BACKEND})`;
    body.appendChild(
      el("div", "evo-badge mock", `⚠ not a real result — ${why} · uplift shown for shape only`)
    );
  }

  // HEADLINE — top-level fresh re-measure (never the lineage selection sample).
  const upliftPP = Number(done.win_rate_uplift_pp ?? 0);
  const ci = done.win_rate_uplift_ci95_pp || [];
  const ciExcludesZero = done.ci_excludes_zero === true;
  const kg = done.killgate || {};
  const passed = kg.passed === true;
  const verdict = kg.verdict; // present only on the real bene-evolve shape

  const lead = el("div", "lead");
  lead.appendChild(el("span", "up" + (real ? "" : " muted"), pp(upliftPP)));
  const ciBits = [];
  ciBits.push("win-rate uplift vs seed");
  if (ci.length === 2) {
    const band = `95% CI [${Number(ci[0]).toFixed(1)}, ${Number(ci[1]).toFixed(1)}]`;
    ciBits.push(`<span class="${ciExcludesZero ? "ci-sig" : "ci-ns"}">${band}</span>`);
  }
  ciBits.push(
    `<span class="kg ${passed ? "ok" : "no"}">kill-gate ${passed ? "✓" : "✗"}${
      verdict ? " (" + verdict + ")" : ""
    }</span>`
  );
  lead.appendChild(el("span", "ci", ciBits.join(" · ")));
  body.appendChild(lead);

  // SPARKLINE — per-gen win-rate, kept (●) vs kill-gated (○). lineage-only.
  const lineage = Array.isArray(done.lineage) ? done.lineage : [];
  const spark = el("div", "spark");
  spark.id = "evo-spark";
  const wrs = lineage.map((g) => Number(g.win_rate) * (Number(g.win_rate) <= 1 ? 100 : 1));
  const mx = wrs.length ? Math.max(...wrs) : 1;
  lineage.forEach((g, i) => {
    const wr = wrs[i];
    const col = el("div", "gcol " + (g.kept ? "kept" : "killed"));
    col.innerHTML =
      `<span class="mk">${g.kept ? "●" : "○"}</span>` +
      `<div class="bar" style="height:${(28 + (56 * wr) / (mx || 1)).toFixed(0)}px" ` +
      `title="gen-${g.gen} · ${esc(g.strategy ?? "")} · ${wr.toFixed(0)}% win-rate · ${
        g.kept ? "kept" : "kill-gated"
      }"></div>` +
      `<span class="gl">g${g.gen}</span>`;
    spark.appendChild(col);
  });
  body.appendChild(spark);

  // WINNING MUTATION — the last kept lineage entry.
  const kept = lineage.filter((g) => g.kept);
  const win = kept.length ? kept[kept.length - 1] : null;
  if (win) {
    const denom = [];
    if (done.battles_played != null) denom.push(`${done.battles_played} battles`);
    if (done.n_battles_per_matchup != null) denom.push(`${done.n_battles_per_matchup}/matchup`);
    if (Array.isArray(done.held_out_baselines) && done.held_out_baselines.length)
      denom.push(`held-out: ${done.held_out_baselines.join(", ")}`);
    const mut = el("div", "mut");
    mut.appendChild(
      el("div", "h", `gen-${win.gen} winning genome · <span class="nonprompt">${esc(win.strategy ?? "—")}</span>`)
    );
    mut.appendChild(
      el(
        "div",
        "b",
        `best win-rate ${(Number(win.win_rate) * (win.win_rate <= 1 ? 100 : 1)).toFixed(1)}% — ` +
          `beats seed by ${pp(upliftPP)} on a fresh held-out re-measure` +
          (kg.required_margin_pp != null ? ` (≥${kg.required_margin_pp}pp gate)` : "") +
          (denom.length ? ` · ${denom.join(" · ")}` : "")
      )
    );
    body.appendChild(mut);
  }

  card.appendChild(body);
  mount.appendChild(card);

  return {
    real,
    gens,
    upliftPP,
    ci,
    ciExcludesZero,
    killgatePassed: passed,
    sparkCols: lineage.length,
    keptCount: kept.length,
    winningStrategy: win ? win.strategy : null,
  };
}

/* Pluggable data source — fixture now, the live to_done_json feed later (the SPA
 * swaps FixtureSource → an HTTP source the same way bene-2's viewer swaps Mock→Sse). */
export async function loadFixture(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`fixture ${url}: HTTP ${res.status}`);
  return res.json();
}
