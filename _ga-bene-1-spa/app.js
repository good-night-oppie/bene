/* GA-BENE-1 — dashboard SPA assembly (bene lineage).
 *
 * Assembles the three render-verified build-ahead panels into one dashboard and
 * wires the live `/me/*` + SSE feeds, per the ga-bene memories ("bene assembles
 * the GA-BENE-1 SPA from the 3 + wires live /me/* + SSE + smoke"):
 *
 *   • GA-BENE-1  agent_hud.js   → roster (#roster) + Agent Pane genome HUD (#agent-pane)
 *   • GA-BENE-2  battle-scene   → live battle viewer (<battle-scene id=scene>)
 *   • GA-BENE-4  evo_panel.js   → Evolution · lineage (#evo-panel)
 *
 * ONE data seam, flipped by `?live=1` (everything else is the same call shape):
 *   roster   fixture ./fixtures/me_agents.json      ⇄  GET /me/agents            (session token)
 *   evo      fixture ./fixtures/done.json           ⇄  GET /me/agents/<id>/evolution
 *   battle   MockLiveSource(golden-fixture frames)  ⇄  SseLiveSource(battleId,"own",{sessionToken})  (GA-CORE-3)
 *
 * Selecting an agent re-renders the Agent Pane + Evolution panel and (re)starts
 * its live battle — the headline interaction (US-2.1 AC2 + US-3.1 adjacency).
 */
import { renderRoster, renderAgentPane } from "./vendor/agent_hud.js";
import { renderEvoPanel } from "./vendor/evo_panel.js";
import { renderLadderPanel } from "./vendor/ladder_panel.js";

const qs = new URLSearchParams(location.search);
const LIVE = qs.get("live") === "1";
const SESSION_TOKEN =
  window.AGENTDEX_SESSION_TOKEN ||
  qs.get("session_token") ||
  window.localStorage?.getItem("agentdex_session_token") ||
  "";
// render-verify drives the battle fast so frames have applied by dump-DOM time
const STEP_MS = parseInt(qs.get("interval") || (qs.get("fast") ? "40" : "700"), 10);

const rosterEl = document.getElementById("roster");
const paneEl = document.getElementById("agent-pane");
const evoEl = document.getElementById("evo-panel");
const ladderEl = document.getElementById("ladder-panel");
const scene = document.getElementById("scene");
const battleLabel = document.getElementById("battle-label");

function mark(state) {
  document.documentElement.setAttribute("data-spa", state);
}

async function getJSON(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

function authOpts() {
  return SESSION_TOKEN
    ? { headers: { Authorization: `Bearer ${SESSION_TOKEN}` } }
    : { credentials: "include" };
}

const loadAgents = () =>
  LIVE
    ? getJSON("/me/agents", authOpts())
    : getJSON("./fixtures/me_agents.json");

const loadEvolution = (agent) =>
  LIVE
    ? getJSON(`/me/agents/${encodeURIComponent(agent.agent_id || agent.agent_name)}/evolution`, {
        ...authOpts(),
      })
    : getJSON("./fixtures/done.json");

const loadLadder = () =>
  LIVE
    ? getJSON("/me/ladder", authOpts())
    : getJSON("./fixtures/me_ladder.json");

let battleSource = null;
let current = null;
let selectSeq = 0; // monotonic guard: ignore async results from a superseded selection

function startBattle(agent) {
  if (battleSource) battleSource.close();
  scene.reset();
  if (LIVE) {
    if (!agent.live_battle_id) {
      // owner dashboard, idle agent: leave the scene in its reset/empty state — NEVER demo data.
      battleSource = null;
      battleLabel.textContent = `idle · ${agent.agent_name} — no live battle`;
      return;
    }
    // GA-CORE-3 wiring — owner stream, endpoint chosen by intent ("own" => /me/battle/<id>/live).
    // Owner stream is Bearer-only for launch; public spectator streams remain native EventSource.
    battleSource = new LiveSource.SseLiveSource(agent.live_battle_id, "own", {
      sessionToken: SESSION_TOKEN,
    });
    battleLabel.textContent = `live · ${agent.agent_name}`;
  } else {
    // build-ahead: the same frame seam, fed by the golden battle through the GA-CORE-3 reference projector
    const proj = Projector.project(globalThis.FIXTURE_BATTLE_LOG, "p1", {
      battleId: "b_demo",
      stepMs: STEP_MS,
    });
    battleSource = new LiveSource.MockLiveSource(proj.frames, {
      intervalMs: STEP_MS,
      replayUrl: proj.replayUrl,
    });
    battleLabel.textContent = agent.live ? `demo stream · ${agent.agent_name}` : "idle — demo stream";
  }
  battleSource.onmessage = (e) => scene.pushFrame(e.data);
  battleSource.addEventListener("end", (e) => scene.bindEnd(e.data));
  // surface an async stream failure (e.g. an expired token -> 401) instead of a frozen "live" scene
  battleSource.addEventListener("error", (e) => {
    const reason = (e && e.detail && e.detail.message) || (e && e.message) || "stream error";
    battleLabel.textContent = `live · ${agent.agent_name} — disconnected (${reason})`;
  });
  battleSource.start();
}

async function select(agents, i) {
  const seq = ++selectSeq;
  current = agents[i];
  rosterEl.querySelectorAll(".agent").forEach((e) => e.classList.toggle("sel", +e.dataset.i === i));
  renderAgentPane(current, paneEl);
  try {
    const evo = await loadEvolution(current);
    if (seq !== selectSeq) return; // a newer selection superseded this one — drop the stale evo
    renderEvoPanel(evo, evoEl);
  } catch (e) {
    if (seq !== selectSeq) return;
    evoEl.innerHTML = `<div class="card"><div class="cb"><div class="err">evolution: ${e.message}</div></div></div>`;
  }
  if (seq !== selectSeq) return; // do not (re)start a battle for a stale selection
  startBattle(current);
}

// US-3.1 AC4: at battle end the scene offers "next battle". In live mode the prior battle id is
// spent, so refetch the agent to pick up a NEW live_battle_id before reconnecting (not the ended stream).
scene.addEventListener("next-battle", async () => {
  if (!current) return;
  if (LIVE) {
    try {
      const data = await loadAgents();
      const key = current.agent_id || current.agent_name;
      const fresh = ((data && data.agents) || []).find((a) => (a.agent_id || a.agent_name) === key);
      if (fresh) current = fresh;
    } catch (e) {
      battleLabel.textContent = `live · ${current.agent_name} — could not refresh (${e.message})`;
      return;
    }
  }
  startBattle(current);
});

(async () => {
  try {
    const [data, ladderData] = await Promise.all([loadAgents(), loadLadder()]);
    const agents = (data && data.agents) || [];
    document.getElementById("data-mode").textContent = LIVE ? "live · /me/*" : "build-ahead · fixtures";

    // GA-BENE-3: render ladder immediately; it's not agent-selection-dependent
    renderLadderPanel(ladderData, ladderEl);

    // ladder-agent-select: clicking an owner row in the ladder selects that agent in the roster
    document.addEventListener("ladder-agent-select", (ev) => {
      const name = ev.detail;
      const idx = agents.findIndex((a) => (a.agent_name || a.agent_id) === name);
      if (idx >= 0) select(agents, idx);
    });

    if (!agents.length) {
      rosterEl.innerHTML = '<div class="err" style="padding:12px">no agents — enroll your first harness</div>';
      mark("ready");
      return;
    }
    renderRoster(agents, rosterEl, (i) => select(agents, i));
    await select(agents, 0);
    mark("ready");
  } catch (e) {
    rosterEl.innerHTML = `<div class="err" style="padding:12px">roster: ${e.message}</div>`;
    mark("error:" + e.message);
    console.error(e);
  }
})();
