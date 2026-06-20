/* GA-BENE-1 — Agent roster + Agent-Pane genome HUD (build-ahead, bene-core).
 *
 * Renders the dashboard roster + the per-agent "Agent Pane" genome HUD from a GA-CORE-5
 * /me/agents envelope (session-authed, owner-scoped, ratified shape #539). Pure +
 * framework-free so it drops into the GA-BENE-1 SPA; data is pluggable (a fixture now,
 * the live /me/agents fetch later — the SPA swaps loadAgents()'s URL).
 *
 * genome_summary fields (ratified #539): {harness_id, move_selection_strategy, generation,
 * allow_switch (or params), prompt_summary}. Per adx-core #578 it is populated from a
 * last-used-genome capture (agent_genome event) as a FOLLOW-UP, so genome_summary may be
 * null today (contract: {...}|null) — the HUD degrades gracefully (roster/rating/W-L come
 * from the agent root, not genome_summary).
 */

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}

function winRate(a) {
  const n = (a.wins || 0) + (a.losses || 0);
  return n > 0 ? Math.round((100 * (a.wins || 0)) / n) : null;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}

/* Compact roster; clicking a row calls onSelect(index). */
export function renderRoster(agents, mount, onSelect) {
  mount.innerHTML = "";
  agents.forEach((a, i) => {
    const g = a.genome_summary;
    const wr = winRate(a);
    const row = el("div", "agent" + (i === 0 ? " sel" : ""));
    row.dataset.i = String(i);
    row.innerHTML =
      `<div class="a-name">${esc(a.agent_name)}</div>` +
      `<div class="a-meta mono">${Math.round(a.rating)} elo · ${a.wins}–${a.losses}` +
      `${wr == null ? "" : " · " + wr + "%"}` +
      `${g ? ` · <span class="a-gen">gen-${g.generation}</span>` : ` · <span class="a-gen pending">no genome</span>`}</div>`;
    row.addEventListener("click", () => onSelect(i));
    mount.appendChild(row);
  });
}

/* The Agent Pane genome HUD for one /me/agents entry. */
export function renderAgentPane(a, mount) {
  mount.innerHTML = "";
  const g = a.genome_summary; // may be null (genome capture pending)
  const wr = winRate(a);

  const card = el("div", "card ap");
  const head = el("div", "ch");
  head.appendChild(el("h3", null, "Agent Pane"));
  head.appendChild(
    el("div", "r dim mono", g ? esc(g.harness_id) : "genome pending")
  );
  card.appendChild(head);

  const body = el("div", "cb");

  // name + generation badge
  const name = el("div", "ap-name-row");
  name.appendChild(el("span", "ap-name", esc(a.agent_name)));
  name.appendChild(
    el("span", "gen" + (g ? "" : " pending"), g ? `gen-${g.generation}` : "gen —")
  );
  body.appendChild(name);

  // stats (from the agent root — independent of genome_summary)
  const stats = el("div", "ap-stats");
  const stat = (k, v, cls) => {
    const s = el("div", "stat");
    s.appendChild(el("div", "k", k));
    s.appendChild(el("div", "v " + (cls || ""), v));
    return s;
  };
  stats.appendChild(stat("Elo", String(Math.round(a.rating)), "elo"));
  stats.appendChild(stat("Win&nbsp;rate", wr == null ? "—" : wr + "%", "wr"));
  stats.appendChild(stat("W / L", `${a.wins}–${a.losses}`, "mono"));
  stats.appendChild(stat("Games", `${a.games}<span class="rd"> ±${Math.round(a.rd)}rd</span>`, "mono"));
  body.appendChild(stats);

  // genome block — graceful when the capture is still pending
  const gen = el("div", "ap-genome");
  if (g) {
    const kv = (k, vHtml, cls) => {
      const r = el("div", "kv" + (cls ? " " + cls : ""));
      r.appendChild(el("span", "k", k));
      r.appendChild(el("span", "vv", vHtml));
      return r;
    };
    gen.appendChild(kv("strategy", `<span id="g-strat">${esc(g.move_selection_strategy)}</span>`));
    const sw = g.allow_switch != null ? g.allow_switch : (g.params && g.params.allow_switch);
    gen.appendChild(
      kv("tool_policy", `<span class="pill ${sw ? "on" : "off"}" id="g-switch">allow_switch: ${!!sw}</span>`)
    );
    const prompt = g.prompt_summary && g.prompt_summary.trim();
    gen.appendChild(
      el("div", "prompt" + (prompt ? "" : " empty"), prompt ? `“${esc(prompt)}”` : "— no system prompt —")
    );
  } else {
    gen.appendChild(
      el("div", "genome-pending", "genome capture pending — populated on the next run (agent_genome event)")
    );
  }
  body.appendChild(gen);

  card.appendChild(body);
  mount.appendChild(card);

  return {
    agent_name: a.agent_name,
    elo: Math.round(a.rating),
    winRate: wr,
    hasGenome: !!g,
    generation: g ? g.generation : null,
    strategy: g ? g.move_selection_strategy : null,
    allowSwitch: g ? !!(g.allow_switch != null ? g.allow_switch : g.params && g.params.allow_switch) : null,
  };
}

/* Wire the roster to the pane (select → re-render pane). Returns the first summary. */
export function mountAgentHud(data, rosterEl, paneEl) {
  const agents = (data && data.agents) || [];
  if (!agents.length) {
    paneEl.innerHTML = '<div class="err">no agents</div>';
    return null;
  }
  const select = (i) => {
    rosterEl.querySelectorAll(".agent").forEach((e) =>
      e.classList.toggle("sel", +e.dataset.i === i)
    );
    return renderAgentPane(agents[i], paneEl);
  };
  renderRoster(agents, rosterEl, select);
  return select(0);
}

export async function loadAgents(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`/me/agents ${url}: HTTP ${res.status}`);
  return res.json();
}
