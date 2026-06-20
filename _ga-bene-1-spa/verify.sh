#!/usr/bin/env bash
# GA-BENE-1 dashboard SPA assembly render-verify (bene lineage).
# Proves the three build-ahead panels ASSEMBLE into one dashboard and boot together
# (roster + Agent Pane + live battle scene + Evolution), driven by fixtures, 0 errors.
# EXIT 0 = all assertions hold.  Live wiring (?live=1) is smoke-tested separately
# (needs a session token + a live battle id; DNS/TLS-gated).
set -u
cd "$(dirname "$0")"
CHROME=$(command -v chromium chromium-browser google-chrome 2>/dev/null | head -1)
[ -z "$CHROME" ] && { echo "no chromium"; exit 2; }
PORT=8099
python3 -m http.server "$PORT" >/dev/null 2>&1 &
SRV=$!; trap 'kill $SRV 2>/dev/null' EXIT
sleep 1
render(){ "$CHROME" --headless --disable-gpu --no-sandbox --virtual-time-budget=6000 --dump-dom "$1" 2>/dev/null; }
fails=0; ok(){ echo "  ✓ $1"; }; no(){ echo "  ✗ $1"; fails=$((fails+1)); }

# fast=1 → the battle steps quickly so frames have applied by dump-DOM time
DOM=$(render "http://localhost:$PORT/index.html?fast=1")

echo "[assembly boots — all 3 panels wired without throwing]"
grep -Fq 'data-spa="ready"' <<<"$DOM"        && ok "boot complete (data-spa=ready: roster+pane+evo+battle all mounted)" || no "boot did not reach ready (assembly threw)"

echo "[GA-BENE-1 · roster + Agent Pane genome HUD (agent_hud.js)]"
grep -Fq "litany-vii" <<<"$DOM"              && ok "roster lists my agents (/me/agents shape)"           || no "roster"
grep -Fq "max-damage-baseline" <<<"$DOM"     && ok "roster lists multiple agents"                        || no "roster multi"
grep -Fq "h_8f3c91ad" <<<"$DOM"              && ok "Agent Pane harness_id (genome_summary, #539)"        || no "harness_id"
grep -Fq "llm_freeform" <<<"$DOM"            && ok "Agent Pane strategy (move_selection_strategy)"       || no "strategy"
grep -Fq "allow_switch:" <<<"$DOM"           && ok "Agent Pane tool_policy pill"                         || no "tool_policy"
grep -Eq "147[0-9]|14[0-9][0-9]" <<<"$DOM"   && ok "Agent Pane Elo/rating from agent root"               || no "rating"

echo "[GA-BENE-2 · live battle scene (battle-scene.js, light DOM)]"
grep -q "bscene" <<<"$DOM"                    && ok "battle scene rendered frames (bscene markup)"        || no "battle scene"
grep -q "bscene-ticker\|bscene-arena\|bscene-fog" <<<"$DOM" && ok "scene arena/ticker/fog present"       || no "scene internals"

echo "[GA-BENE-4 · Evolution · lineage (evo_panel.js)]"
grep -Fq "+27.5pp" <<<"$DOM"                  && ok "Evolution headline uplift (top-level re-measure)"    || no "uplift"
grep -Fq "kill-gate" <<<"$DOM"               && ok "kill-gate verdict badge"                             || no "kill-gate"
grep -Eq "g1|g7|gen-" <<<"$DOM"              && ok "lineage sparkline / winning-genome block"            || no "lineage"
# real pokeenv result => NO mock badge
grep -Fq "not a real result" <<<"$DOM"       && no "real pokeenv run wrongly badged mock" || ok "real result not mock-badged (honesty gate)"

echo "----"
[ "$fails" -eq 0 ] && { echo "RENDER-VERIFY PASS (all assertions)"; exit 0; } || { echo "RENDER-VERIFY FAIL ($fails)"; exit 1; }
