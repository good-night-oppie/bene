#!/usr/bin/env bash
# GA-BENE-4 Evolution-panel render-verify (build-ahead, bene-core).
# The only valid gate is a REAL headless-chromium render asserting the panel's #root
# is populated with the right data (a grep of source HTML proves bytes, not rendering).
# Mirrors bene-2's GA-BENE-2 viewer render-verify approach. EXIT 0 = all assertions hold.
set -u
cd "$(dirname "$0")"
CHROME=$(command -v chromium chromium-browser google-chrome 2>/dev/null | head -1)
[ -z "$CHROME" ] && { echo "no chromium"; exit 2; }
PORT=8099
python3 -m http.server "$PORT" >/dev/null 2>&1 &
SRV=$!; trap 'kill $SRV 2>/dev/null' EXIT
sleep 1
render() { "$CHROME" --headless --disable-gpu --no-sandbox --virtual-time-budget=3000 --dump-dom "$1" 2>/dev/null; }

fails=0
ok(){ echo "  ✓ $1"; }
no(){ echo "  ✗ $1"; fails=$((fails+1)); }

# 1) real pokeenv run renders the full panel from done_c2_pokeenv.sample.json
REAL=$(render "http://localhost:$PORT/index.html")
echo "[real pokeenv run]"
grep -Fq "+27.5pp" <<<"$REAL"                  && ok "headline +27.5pp (top-level fresh re-measure)"      || no "headline +27.5pp"
grep -Fq "95% CI [16.0, 39.0]" <<<"$REAL"      && ok "95% CI band"                                        || no "95% CI band"
grep -Fq "kill-gate ✓" <<<"$REAL"              && ok "kill-gate ✓ badge (killgate.passed)"                || no "kill-gate badge"
grep -Fq 'id="evo-spark"' <<<"$REAL"           && ok "sparkline mounted"                                  || no "sparkline"
grep -Fq "winning genome" <<<"$REAL"           && ok "winning genome block"                               || no "winning genome"
grep -Fq "max_damage" <<<"$REAL"               && ok "winning strategy (last kept lineage entry)"         || no "winning strategy"
grep -Fq "RandomPlayer" <<<"$REAL"             && ok "held-out denominator surfaced"                      || no "held-out denominator"
grep -Fq "not a real result" <<<"$REAL"        && no "mock-badge WRONGLY shown on a real run"             || ok "no mock-badge on a real pokeenv run"

# 2) honesty gate: a scaffold/mock run MUST be badged (uplift not presented as a real finding)
python3 -c "import json;d=json.load(open('done_c2_pokeenv.sample.json'));d['scaffold']=True;json.dump(d,open('done_mock.test.json','w'))"
MOCK=$(render "http://localhost:$PORT/index.html?src=./done_mock.test.json")
echo "[scaffold/mock run]"
grep -Fq "not a real result" <<<"$MOCK"        && ok "scaffold run IS badged"                             || no "scaffold run NOT badged (honesty gate broken)"
rm -f done_mock.test.json

echo "----"
[ "$fails" -eq 0 ] && { echo "RENDER-VERIFY PASS (all assertions)"; exit 0; } || { echo "RENDER-VERIFY FAIL ($fails)"; exit 1; }
