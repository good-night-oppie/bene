#!/usr/bin/env bash
# GA-BENE-1 Agent-roster + genome-HUD render-verify (build-ahead, bene-core).
# Real headless-chromium render assertions against the GA-CORE-5 /me/agents shape, incl.
# the null-genome (capture-pending) degrade path. EXIT 0 = all assertions hold.
set -u
cd "$(dirname "$0")"
CHROME=$(command -v chromium chromium-browser google-chrome 2>/dev/null | head -1)
[ -z "$CHROME" ] && { echo "no chromium"; exit 2; }
PORT=8098
python3 -m http.server "$PORT" >/dev/null 2>&1 &
SRV=$!; trap 'kill $SRV 2>/dev/null' EXIT
sleep 1
render(){ "$CHROME" --headless --disable-gpu --no-sandbox --virtual-time-budget=3000 --dump-dom "$1" 2>/dev/null; }
fails=0; ok(){ echo "  ✓ $1"; }; no(){ echo "  ✗ $1"; fails=$((fails+1)); }

DOM=$(render "http://localhost:$PORT/index.html")
echo "[roster + Agent Pane on /me/agents sample]"
grep -Fq "litany-vii" <<<"$DOM"          && ok "roster lists agents"                                || no "roster"
grep -Fq "h_8f3c91ad" <<<"$DOM"          && ok "Agent Pane harness_id (genome_summary)"             || no "harness_id"
grep -Fq "gen-7" <<<"$DOM"               && ok "generation badge (ratified #539 field)"             || no "generation"
grep -Fq "llm_freeform" <<<"$DOM"        && ok "strategy (move_selection_strategy)"                 || no "strategy"
grep -Fq "allow_switch: true" <<<"$DOM"  && ok "tool_policy allow_switch (ratified #539 field)"     || no "allow_switch"
grep -Fq "Lead with your fastest" <<<"$DOM" && ok "prompt_summary (ratified #539 field)"            || no "prompt_summary"
grep -Fq "1487" <<<"$DOM"                && ok "Elo/rating from agent root"                         || no "rating"
grep -Fq "38–12" <<<"$DOM"               && ok "W/L"                                                || no "W/L"
# the null-genome agent must NOT crash and MUST degrade gracefully
grep -Fq "no genome" <<<"$DOM"           && ok "null-genome agent badged in roster (degrade path)"  || no "null-genome roster badge"

echo "[select the null-genome agent -> genome capture pending]"
# fresh-recruit is index 2; drive it directly via a single-agent fixture
python3 -c "import json;d=json.load(open('me_agents.sample.json'));json.dump({'agents':[d['agents'][2]]},open('me_agents.null.test.json','w'))"
NULLDOM=$(render "http://localhost:$PORT/index.html?src=./me_agents.null.test.json")
grep -Fq "genome capture pending" <<<"$NULLDOM" && ok "null genome_summary -> 'genome capture pending' (no crash)" || no "null-genome pane degrade"
grep -Fq "1500" <<<"$NULLDOM"            && ok "rating still shown when genome is null"             || no "root stats survive null genome"
rm -f me_agents.null.test.json

echo "----"
[ "$fails" -eq 0 ] && { echo "RENDER-VERIFY PASS (all assertions)"; exit 0; } || { echo "RENDER-VERIFY FAIL ($fails)"; exit 1; }
