# GA-BENE-4 — Evolution panel (build-ahead, bene-core)

The dashboard **"Evolution · lineage"** panel, built ahead + render-verified against the
committed C2-driver sample, so `bene` (the SPA lineage) drops it in with one import and the
only thing left is the live data feed + smoke test. Mirrors bene-2's GA-BENE-2 viewer
build-ahead.

## Files
- `evo_panel.js` — `renderEvoPanel(done, mountEl)` — pure, framework-free renderer. Reads a
  `to_done_json` envelope (`adx_showdown` `e2e_driver`) and renders headline uplift+CI,
  kept-vs-kill-gated sparkline, and the winning-genome block.
- `index.html` — standalone host (design CSS + `--lime` theme) that fetches a feed and mounts.
- `done_c2_pokeenv.sample.json` — the committed canonical sample (adx-cli
  `tasks/selfplay-metaharness/artifacts/done_c2_pokeenv.json`), for offline build-ahead.
- `verify.sh` — reproducible **headless-chromium render-verify** (9 assertions, both honesty
  branches). `./verify.sh` → `RENDER-VERIFY PASS`.

## Honesty contract enforced (adx-cli-10 #541)
- **Headline** uplift+CI come from the TOP-LEVEL `win_rate_uplift_pp` / `win_rate_uplift_ci95_pp`
  (the fresh held-out re-measure) — **never** recomputed from `lineage[].win_rate` (the inflated
  selection sample). `lineage[].win_rate` is sparkline-only.
- `killgate.passed` (present in both the mock + real bene-evolve shape) drives the ✓/✗ badge;
  `killgate.verdict` shown only when present.
- The panel is **gated on `backend==='pokeenv' && scaffold===false && ok===true`** — a
  mock/scaffold/custom run is **badged** ("not a real result"), its uplift not presented as a
  finding. Verified both ways in `verify.sh`.
- Winning genome = the **last kept** lineage entry.

## SPA integration (the one-line swap, for `bene`)
```js
import { renderEvoPanel } from "./evo_panel.js";
// build-ahead: const done = await loadFixture("./done_c2_pokeenv.sample.json");
// live:        const done = await fetch("/me/agents/<id>/evolution").then(r => r.json()); // to_done_json shape
renderEvoPanel(done, document.querySelector("#evo-panel"));
```
Status: **component done + render-verified.** Remaining = embed in the GA-BENE-1 SPA + point
at the live `to_done_json` feed + smoke test (the integration step that waits on the backend).
bene-core stays the engine-data backstop; this panel visualizes bene's own evolve output.
