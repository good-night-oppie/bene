/*
 * render-verify.mjs — the REAL render gate for the GA-BENE-2 viewer (per the
 * render-verify discipline: bytes/grep prove nothing, a headless-chromium render
 * asserting populated DOM does). Loads index.html in headless chromium, streams
 * the fixture fast, and asserts the scene actually renders + fog-of-war holds +
 * the event:end -> replay swap fires. Screenshots both projections.
 *
 * Run: node test/render-verify.mjs   (serves the dir, drives chromium, exit 0 = pass)
 */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join, extname } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".txt": "text/plain" };

const server = createServer(async (req, res) => {
  try {
    const p = join(root, decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "") || "index.html");
    const body = await readFile(p);
    res.writeHead(200, { "content-type": MIME[extname(p)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404); res.end("404");
  }
});

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log("  ✓", m); } else { fail++; console.error("  ✗ FAIL:", m); } };

await new Promise((r) => server.listen(0, r));
const port = server.address().port;
const base = `http://127.0.0.1:${port}/index.html`;

const CHROME = process.env.CHROME_PATH || "/usr/bin/chromium";
const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
const errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  // real JS exceptions only; ignore benign network 404s (favicon, offline fonts)
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));

  // ---- OWNER stream (default intent=own, side=p1), fast stream ----
  await page.goto(`${base}?interval=35`, { waitUntil: "load" });
  await page.waitForFunction(() => globalThis.__viewerReady === true, { timeout: 5000 });

  // all data-layer + renderer scripts loaded (no silent 404 on a critical src/)
  const globalsOk = await page.evaluate(() =>
    !!(globalThis.LineProto && globalThis.SceneReducer && globalThis.Projector && globalThis.LiveSource && globalThis.BattleScene)
  );
  ok(globalsOk, "all src/ scripts loaded (LineProto/SceneReducer/Projector/LiveSource/BattleScene)");

  console.log("\n== owner stream renders incrementally ==");
  // both active mons appear (the fixture leads Azumarill vs Lumineon)
  await page.waitForSelector("#scene .bscene-species", { timeout: 5000 });
  await page.waitForFunction(() => {
    const s = [...document.querySelectorAll("#scene .bscene-species")].map((n) => n.textContent);
    return s.some((x) => x && x !== "—");
  }, { timeout: 5000 });
  const species = await page.$$eval("#scene .bscene-species", (ns) => ns.map((n) => n.textContent));
  ok(species.filter((x) => x && x !== "—").length === 2, `both active mons rendered: ${JSON.stringify(species)}`);

  // HP bars have a real width (incremental render touched them)
  const hpWidths = await page.$$eval("#scene .bscene-hp-fill", (ns) => ns.map((n) => n.style.width));
  ok(hpWidths.every((w) => /\d+%/.test(w)), `HP fills have width: ${JSON.stringify(hpWidths)}`);

  // wait for the battle to reach the end -> replay controls appear (LVC-05/15, AC4)
  await page.waitForSelector("#scene .bscene-controls .bscene-btn", { timeout: 8000 });
  const ended = await page.$eval("#scene .bscene-live", (n) => n.textContent);
  ok(/ENDED|REPLAY/.test(ended), `live indicator flipped to ended: "${ended}"`);
  const replayHref = await page.$eval("#scene .bscene-replay-link", (n) => n.getAttribute("href")).catch(() => null);
  ok(replayHref && replayHref.includes("/replay/"), `replay control bound to ${replayHref}`);

  // ticker accumulated real events
  const ticks = await page.$$eval("#scene .bscene-tick", (ns) => ns.length);
  ok(ticks > 5, `event ticker has ${ticks} lines`);

  // fog caption shows the owner projection
  const fogOwner = await page.$eval("#scene .bscene-fog", (n) => n.textContent);
  ok(/owner stream/.test(fogOwner), `owner fog caption: "${fogOwner.trim()}"`);
  await page.screenshot({ path: join(here, "render-owner.png") });

  console.log("\n== spectator stream: fog-of-war holds (no hidden HP/rating in the DOM) ==");
  await page.click('#proj-seg button[data-intent="spectate"]');
  await page.waitForFunction(() => {
    const f = document.querySelector("#scene .bscene-fog");
    return f && /spectator/.test(f.textContent);
  }, { timeout: 5000 });
  await page.waitForSelector("#scene .bscene-controls .bscene-btn", { timeout: 8000 });
  // the WHOLE rendered scene text must not leak a private exact-HP integer
  // (max denominators 298/279/302/249 from the fixture's private twins) or a rating.
  const sceneText = await page.$eval("#scene", (n) => n.innerText);
  const leak = /\b\d+\/(298|279|302|249|247|248)\b/.test(sceneText);
  ok(!leak, "spectator scene shows NO private exact-HP twin (fog-of-war, LVC-12)");
  const fogSpec = await page.$eval("#scene .bscene-fog", (n) => n.textContent);
  ok(/no hidden info, no rating/.test(fogSpec), `spectator fog caption: "${fogSpec.trim()}"`);
  await page.screenshot({ path: join(here, "render-spectator.png") });

  console.log("\n== responsive: panes stack below 1024px (LVC-13) ==");
  await page.setViewportSize({ width: 800, height: 900 });
  const cols = await page.evaluate(() => getComputedStyle(document.querySelector(".row.top")).gridTemplateColumns);
  // a single-column grid reports one track; side-by-side reports two
  ok(cols.split(" ").length === 1, `row.top collapses to one column at 800px: "${cols}"`);

  console.log("\n== frame ordering + reset cleanup ==");
  const ordering = await page.evaluate(() => {
    const scene = document.querySelector("#scene");
    const base = {
      p1: { species: "Azu", hp_frac: 1, status: null, name: "Azu" },
      p2: { species: "Lum", hp_frac: 1, status: null, name: "Lum" },
      players: { p1: "p1", p2: "p2" },
      weather: null,
      field: [],
      winner: null,
    };
    scene.reset();
    scene.pushFrame({ battle_id: "b_order", seq: 1, side: "spectator", lines: [], scene: { ...base, turn: 2 }, ts_ms: 2 });
    const before = { maxSeq: scene.maxSeq, turn: scene.scene.turn };
    scene.pushFrame({ battle_id: "b_order", seq: 0, side: "spectator", lines: [], scene: { ...base, turn: 1 }, ts_ms: 1 });
    return { before, after: { maxSeq: scene.maxSeq, turn: scene.scene.turn } };
  });
  ok(ordering.before.maxSeq === -1 && ordering.before.turn === 0, `higher seq buffered until gap arrives: ${JSON.stringify(ordering.before)}`);
  ok(ordering.after.maxSeq === 1 && ordering.after.turn === 2, `buffer drained in seq order: ${JSON.stringify(ordering.after)}`);

  const replayCleanup = await page.evaluate(async () => {
    const scene = document.querySelector("#scene");
    const base = {
      p1: { species: "Azu", hp_frac: 1, status: null, name: "Azu" },
      p2: { species: "Lum", hp_frac: 1, status: null, name: "Lum" },
      players: { p1: "p1", p2: "p2" },
      weather: null,
      field: [],
      winner: null,
    };
    scene.reset();
    scene.pushFrame({ battle_id: "b_replay", seq: 0, side: "spectator", lines: [], scene: { ...base, turn: 1 }, ts_ms: 1 });
    scene.pushFrame({ battle_id: "b_replay", seq: 1, side: "spectator", lines: [], scene: { ...base, turn: 2 }, ts_ms: 2 });
    scene.bindEnd({ replay_url: "/replay/b_replay" });
    scene.elControls.querySelector(".bscene-btn").click();
    await new Promise((resolve) => setTimeout(resolve, 5));
    const hadTimer = !!scene._replayTimer;
    scene.reset();
    return { hadTimer, timerAfterReset: scene._replayTimer, mode: scene.mode, frameCount: scene.frames.length };
  });
  ok(replayCleanup.hadTimer === true, "replay timer starts during replay playback");
  ok(
    replayCleanup.timerAfterReset === null && replayCleanup.mode === "live" && replayCleanup.frameCount === 0,
    `reset cancels replay playback and clears state: ${JSON.stringify(replayCleanup)}`
  );

  console.log("\n== no console/page errors ==");
  ok(errors.length === 0, `zero JS errors${errors.length ? " — " + JSON.stringify(errors.slice(0, 3)) : ""}`);
} finally {
  await browser.close();
  server.close();
}

console.log(`\n${fail === 0 ? "✅ RENDER-VERIFY PASS" : "❌ RENDER-VERIFY FAIL"}: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
