/* GA-BENE-3 — Ladder panel (build-ahead, bene lineage).
 *
 * Renders the dashboard "Ladder" panel from a /me/ladder JSON payload.
 * Pure + framework-free; drops into the GA-BENE-1 SPA as a panel component.
 *
 * /me/ladder shape (owner-scoped public ladder slice):
 *   { owner_agents: string[], entrants: LadderEntry[] }
 *   LadderEntry: { name, rating, rd, games, wins, losses,
 *                  is_goal_line?, is_owner?, is_baseline?, live?, genome_summary? }
 *   Entrants arrive pre-sorted by rating desc.
 *
 * US-5.1 (Epic 5): leaderboard with owner highlight, baselines anchored at
 * bottom, north-star goal-line row at top. Selecting an owner agent dispatches
 * a global "ladder-agent-select" CustomEvent({detail:agentName}) so app.js can
 * load the matching roster entry into the Agent Pane (US-5.1 AC2).
 *
 * ADR-0011 invariant: anti-pay-to-rank — memberships do NOT boost rating;
 * the ladder renders raw Glicko ratings only and marks baselines clearly.
 */

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}

function fmtWL(wins, losses, games) {
  if (games === 0) return '<span class="ld-new">new</span>';
  const pct = games > 0 ? Math.round((wins / games) * 100) : 0;
  return `<span class="ld-wl">${wins}W/${losses}L</span> <span class="ld-pct dim">${pct}%</span>`;
}

function strategyBadge(gs) {
  if (!gs || !gs.move_selection_strategy) return "";
  return `<span class="ld-strat">${esc(gs.move_selection_strategy)}</span>`;
}

function liveBadge(entry) {
  if (!entry.is_owner) return "";
  return entry.live
    ? '<span class="ld-live">● live</span>'
    : '<span class="ld-idle dim">○ idle</span>';
}

function glickoRD(rd) {
  // visually convey rating uncertainty — high RD = unplaced
  const cls = rd >= 200 ? "ld-rd hi" : "ld-rd";
  return `<span class="${cls}">±${Math.round(rd)}</span>`;
}

/* Build a single ladder row. `rank` is 1-based (or null for goal-line).
 * Owner rows are clickable and dispatch "ladder-agent-select". */
function buildRow(entry, rank) {
  const row = document.createElement("div");
  const cls = ["ld-row"];
  if (entry.is_goal_line) cls.push("ld-goalline");
  else if (entry.is_owner) cls.push("ld-owner");
  else if (entry.is_baseline) cls.push("ld-baseline");
  row.className = cls.join(" ");

  if (entry.is_owner) {
    row.tabIndex = 0;
    row.title = `Select ${entry.name} in Agent Pane`;
    const activate = () =>
      document.dispatchEvent(new CustomEvent("ladder-agent-select", { detail: entry.name }));
    row.addEventListener("click", activate);
    row.addEventListener("keydown", (ev) => ev.key === "Enter" && activate());
  }

  const rankCell = el("div", "ld-rank");
  if (entry.is_goal_line) {
    rankCell.textContent = "★";
    rankCell.title = "north-star goal line (top-10 PS player tier)";
  } else {
    rankCell.textContent = String(rank ?? "—");
  }

  const nameCell = el("div", "ld-name");
  let nameHtml = `<span class="ld-nameval">${esc(entry.name)}</span>`;
  if (entry.is_baseline) nameHtml += ' <span class="ld-tag baseline">baseline</span>';
  if (entry.is_owner) nameHtml += ' <span class="ld-tag mine">mine</span>';
  if (entry.is_goal_line) nameHtml += ' <span class="ld-tag goal">goal</span>';
  nameCell.innerHTML = nameHtml;

  const ratingCell = el("div", "ld-rating");
  ratingCell.innerHTML =
    `<span class="ld-elo">${Number(entry.rating).toFixed(0)}</span>${glickoRD(entry.rd)}`;

  const wlCell = el("div", "ld-wlcell");
  wlCell.innerHTML = fmtWL(entry.wins, entry.losses, entry.games);

  const infoCell = el("div", "ld-info");
  infoCell.innerHTML = strategyBadge(entry.genome_summary) + liveBadge(entry);

  row.appendChild(rankCell);
  row.appendChild(nameCell);
  row.appendChild(ratingCell);
  row.appendChild(wlCell);
  row.appendChild(infoCell);
  return row;
}

/* Render the Ladder panel for `data` into `mount` (replacing its contents).
 * Returns a summary object for render-verify assertions. */
export function renderLadderPanel(data, mount) {
  mount.innerHTML = "";
  const card = el("div", "card ladder");

  const head = el("div", "ch");
  head.appendChild(el("h3", null, "Ladder"));
  head.appendChild(el("div", "r dim mono", "gen9randombattle · Glicko"));
  card.appendChild(head);

  const body = el("div", "cb ld-body");

  const entrants = (data && data.entrants) || [];
  if (!entrants.length) {
    body.appendChild(el("div", "ld-empty", "No agents enrolled yet — enroll your first harness to join the ladder."));
    card.appendChild(body);
    mount.appendChild(card);
    return { rowCount: 0, ownerCount: 0, baselineCount: 0, goalLine: false };
  }

  // header row
  const hdr = el("div", "ld-row ld-hdr");
  hdr.innerHTML =
    '<div class="ld-rank">#</div>' +
    '<div class="ld-name">agent</div>' +
    '<div class="ld-rating">rating ± RD</div>' +
    '<div class="ld-wlcell">W/L</div>' +
    '<div class="ld-info">strategy / status</div>';
  body.appendChild(hdr);

  let rank = 0;
  let ownerCount = 0;
  let baselineCount = 0;
  let goalLine = false;

  for (const entry of entrants) {
    if (entry.is_goal_line) {
      goalLine = true;
    } else {
      rank++;
    }
    if (entry.is_owner) ownerCount++;
    if (entry.is_baseline) baselineCount++;
    body.appendChild(buildRow(entry, entry.is_goal_line ? null : rank));
  }

  card.appendChild(body);
  mount.appendChild(card);
  return { rowCount: entrants.length, ownerCount, baselineCount, goalLine };
}
