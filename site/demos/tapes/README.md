# Gap VHS Demos — recording recipe + craft rules

Source `.tape` files for the per-Gap terminal demos on the BENE landing.
Each tape produces a GIF in `site/assets/demos/gap-N-*.gif`, embedded under
the matching Gap card via the `<GapDemo>` component in `site/index.html`
and `site/zh/index.html`.

## Recording (host-side)

```bash
# from repo root
cd site/demos/tapes
vhs gap-1-killgate.tape
vhs gap-2-engram.tape
vhs gap-3-trust.tape
vhs gap-4-sqlite.tape
```

Each tape produces ~10-15s of video (~100-180KB GIF) by recording against
`bene-main` HEAD with no edits — every command runs for real, every line of
output is whatever the binary returns at that commit.

## Prerequisites

- VHS ≥ 0.11.0 (`charmbracelet/vhs`)
- JetBrains Mono installed in `fontconfig` (the font specified in every
  tape). On this dev box:
  ```bash
  curl -sL https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip -o /tmp/jbm.zip
  mkdir -p ~/.local/share/fonts/jbm
  unzip -j /tmp/jbm.zip 'fonts/ttf/JetBrainsMono-Regular.ttf' 'fonts/ttf/JetBrainsMono-Bold.ttf' -d ~/.local/share/fonts/jbm/
  fc-cache -f ~/.local/share/fonts/
  fc-match "JetBrains Mono"   # → JetBrainsMono-Regular.ttf
  ```
  If JetBrains Mono isn't installed, VHS falls back to a default sans-serif
  with wider tracking — that was the "字母间距好大" bug observed
  2026-06-15.

## Craft rules (distilled from `harness-engineering` corpus)

Applied to every gap tape; future tapes should keep these.

1. **"上下文是稀缺资源"** (harness-engineering video #06 — 
   `data/silver/lists/vibe-coding/06_OpenAI提出新概念Harness Engineering`).
   The viewer's attention budget is the constraint, same as Codex's context
   budget. Use VHS `Hide` for every setup line (`cd`, `bene init`,
   `bene demo --no-ui`, `DEMO_DB=$(...)`) and `Show` only the
   one-question-one-punchline pair.

2. **"渐近式披露"** — one demo, one punchline. Each gap tape ends in ONE
   line of evidence the viewer should remember:
   - Gap 1 (kill gate): the verdict row `story-probe -> ACCEPT`.
   - Gap 2 (engrams): the tier-distribution table (5 rows, 3 columns).
   - Gap 3 (trust): the 4 signal values + composite (5 aligned lines).
   - Gap 4 (sqlite): `ls -lh` showing a real ≈330KB file + 3 rows of
     engrams pulled by stdlib sqlite3 in a one-liner.

3. **"找到那个 moment"** — add 3-4s `Sleep` after the punchline so the
   viewer's eye lands on it. Then ONE trailing comment line explains
   what the moment means (~150ms `TypingSpeed` × short comment → 1.5s of
   landing time).

4. **"减 token、改得准"** (harness-engineering video #14 — CodeGraph).
   Output verbosity is taxed. Pipe heavy commands through `head -N`,
   `grep -B1 -A1`, `tail -N`, or a helper `bash _show_*.sh` that
   pre-shapes the output to ~5 aligned lines. The trust demo would have
   been 28 raw JSON lines without `_show_trust.sh`; now it's 5 aligned.

5. **"实跑、零输出修改"** — never type expected output into the tape.
   The bilingual landing footer claims "recorded against bene-main HEAD";
   that claim is only true if no `Sleep`-and-`Type "fake output"` patterns
   exist anywhere. Every visible character below the prompt is whatever
   the binary actually emitted.

## Helper scripts

The tapes call these so VHS Type strings stay free of nested quotes
(the parser failed loudly on `\"SELECT...\"`-style escapes 2026-06-14):

| Script | Purpose |
|---|---|
| `_extract_demo_db.sh` | runs `bene demo --no-ui` and emits the demo db path |
| `_show_engrams.sh DB` | tier distribution + sample row per tier |
| `_show_trust.sh DB` | 5-line trust composite from first agent |
| `_show_sqlite.sh DB` | `ls -la` + stdlib `python3 -c` reading engrams |

## Re-recording when bene changes

`bene` evolves. If a command name changes, the tape will record whatever
the binary says (including "no such command"). When that happens:

1. Read the tape file.
2. Update the visible command line (after `Show`) to the new shape.
3. Re-run `vhs gap-N-*.tape`.
4. Commit both the updated tape AND the new GIF.

Do NOT amend a tape to hide a real regression. If `bene` broke, the demo
should fail visibly; fix the binary first.
