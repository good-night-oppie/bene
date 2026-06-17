#!/usr/bin/env python3
"""Static docs builder: bene-main/docs/**/*.md -> site/docs/**/*.html.

Deterministic and idempotent — the generated tree is a pure function of docs/.
Run:  uv run --with markdown --with pygments python site/build-docs.py
Then sync site/ to the deploy copies (4-copy chain; see
[[bene-site-deploy-pipeline]]).

Template matches the landing's light theme: warm off-white canvas, ink text,
one amber accent, dark terminal code blocks. VHS demo GIFs are injected on the
pages whose subject they prove (README / cli-reference / mcp-integration).
"""

from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter

ROOT = Path(__file__).resolve().parent.parent  # bene-main
# Wrong-tree sentinel: if this script gets copied into a non-bene-main checkout
# (e.g. the agentdex-cli sync copy) and someone runs it, ROOT.parent.parent
# resolves to that wrong repo and DOCS/OUT clobber its committed site/docs/
# in place with a sparse, wrong-source build. The bene/ subpackage existence
# is the cheapest invariant for "I am in bene-main".
if not (ROOT / "bene").is_dir():
    sys.exit(
        f"build-docs.py: ROOT={ROOT} has no bene/ subpackage — this script "
        "must run from a bene-main checkout. (Sync copies in agentdex-cli "
        "etc. ship the file but are not the canonical source-of-truth.)"
    )
DOCS = ROOT / "docs"
OUT = ROOT / "site" / "docs"
GITHUB_BLOB = "https://github.com/EdwardTang/bene-site/blob/main/docs"

GROUPS = [
    ("Start, operate, recover", "."),
    ("Recipes", "recipes"),
    ("Design and claims", "design"),
    ("Evidence and research", "research"),
    ("Benchmarks and gates", "benchmarks"),
    ("Tutorial playbooks", "tutorials"),
    ("Case studies", "case-studies"),
    ("Infrastructure", "infra"),
]

# page (relpath without .md) -> (gif relative to site/assets, caption)
DEMO_EMBEDS = {
    "README": (
        "demo-keyless.gif",
        "Demo — keyless first value: bene init && bene demo --no-ui, 0.3s, recorded live against bene-main HEAD.",
    ),
    "cli-reference": (
        "demo-litany.gif",
        "Demo — rewind a bad turn: an agent scaled replicas 3 → 0; checkpoint → diff → restore puts it back.",
    ),
    "mcp-integration": (
        "demo-honesty.gif",
        "Demo — what a connected agent inherits: experiments ls / show + senses --md.",
    ),
}

MERMAID_JS = '<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"; mermaid.initialize({startOnLoad: true, theme: "neutral"});</script>'

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap');
:root { --bg:#F0EEE8; --surface:#EDE9E4; --border:#CFCCC8; --ink:#1F1D1C; --mute:#62666D; --accent:#EE6018; --gold:#B46A35; --term-bg:#0A0908; --term-fg:#EDE9E4; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.65 Geist,ui-sans-serif,system-ui,sans-serif; }
a { color:var(--gold); text-decoration-color: color-mix(in srgb, var(--gold) 40%, transparent); text-underline-offset:3px; }
a:hover { color:var(--accent); }
.top { position:sticky; top:0; z-index:10; background:color-mix(in srgb, var(--bg) 92%, transparent); backdrop-filter:blur(8px); border-bottom:1px solid var(--border); }
.top-in { max-width:1200px; margin:0 auto; padding:0 24px; height:56px; display:flex; align-items:center; gap:24px; }
.brand { font-family:Geist,ui-sans-serif,sans-serif; font-weight:700; letter-spacing:.12em; color:var(--ink); text-decoration:none; }
.top a.nav { color:var(--mute); text-decoration:none; font-size:14px; }
.top a.nav:hover { color:var(--accent); }
.wrap { max-width:1200px; margin:0 auto; padding:24px; display:grid; grid-template-columns:260px minmax(0,1fr); gap:40px; }
aside.sb { position:sticky; top:80px; align-self:start; max-height:calc(100vh - 100px); overflow-y:auto; font-size:13.5px; border-left:1px solid var(--border); padding-left:16px; }
.sb h4 { margin:18px 0 6px; font:600 11px/1 "Geist Mono",ui-monospace,monospace; letter-spacing:.14em; text-transform:uppercase; color:var(--accent); }
.sb a { display:block; padding:3px 0; color:var(--mute); text-decoration:none; }
.sb a:hover { color:var(--accent); }
.sb a.cur { color:var(--ink); font-weight:600; }
main { min-width:0; max-width:760px; }
main h1 { font-family:Geist,ui-sans-serif,sans-serif; font-size:2.1rem; line-height:1.2; margin:.2em 0 .5em; }
main h2 { font-family:Geist,ui-sans-serif,sans-serif; font-size:1.45rem; margin-top:2em; border-bottom:1px solid var(--border); padding-bottom:.35em; }
main h3 { font-size:1.12rem; margin-top:1.7em; }
main img { max-width:100%; border:1px solid var(--border); border-radius:8px; }
main table { border-collapse:collapse; width:100%; font-size:14.5px; display:block; overflow-x:auto; }
main th, main td { border:1px solid var(--border); padding:8px 12px; text-align:left; vertical-align:top; }
main th { background:var(--surface); font-weight:600; }
main blockquote { margin:1em 0; padding:.2em 1.2em; border-left:3px solid var(--accent); color:var(--mute); background:var(--surface); border-radius:0 4px 4px 0; }
main :not(pre) > code { background:var(--surface); border:1px solid var(--border); border-radius:3px; padding:.08em .35em; font:.86em "Geist Mono",ui-monospace,monospace; }
.codehilite, main pre { background:var(--term-bg); color:var(--term-fg); border-radius:6px; padding:16px 18px; overflow-x:auto; font:13.5px/1.55 "Geist Mono",ui-monospace,monospace; }
.codehilite pre, pre code { background:none; padding:0; margin:0; border:none; }
.demo-embed { margin:20px 0 28px; }
.demo-embed .frame { background:var(--term-bg); border-radius:6px; padding:14px; }
.demo-embed .dots { display:flex; gap:6px; margin-bottom:10px; }
.demo-embed .dots i { width:10px; height:10px; border-radius:50%; background:#3a3344; }
.demo-embed img { border:none; border-radius:6px; display:block; width:100%; }
.demo-embed p { font:12.5px "Geist Mono",ui-monospace,monospace; color:var(--mute); margin:8px 2px 0; }
.crumbs { font:12.5px "Geist Mono",ui-monospace,monospace; color:var(--mute); margin-bottom:8px; }
.crumbs a { color:var(--mute); }
.src { font:12.5px "Geist Mono",ui-monospace,monospace; margin-top:48px; padding-top:16px; border-top:1px solid var(--border); color:var(--mute); }
footer.ft { border-top:1px solid var(--border); margin-top:40px; }
footer.ft .in { max-width:1200px; margin:0 auto; padding:24px; font:13px "Geist Mono",ui-monospace,monospace; color:var(--mute); display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; }
.idx-group h2 { font-family:Geist,ui-sans-serif,sans-serif; border:none; margin-top:1.6em; }
.idx-group ul { list-style:none; padding:0; margin:.4em 0; }
.idx-group li { padding:6px 0; border-bottom:1px dashed var(--border); }
.idx-group .path { font:11.5px "Geist Mono",ui-monospace,monospace; color:var(--mute); margin-left:8px; }
/* Mobile overrides — kept at the end so source order beats base rules.
   Earlier this rule sat between base rules and got overridden by a later
   `aside.sb { position:sticky }`, leaving the sidebar stuck on top of
   main content on phones. */
@media (max-width: 860px) {
  .wrap { grid-template-columns:1fr; gap:24px; padding:16px; }
  aside.sb { position:static; max-height:none; border-left:none; border-bottom:1px solid var(--border); padding-left:0; padding-bottom:16px; font-size:13px; }
  .sb h4 { margin:12px 0 4px; }
  main { max-width:none; }
  main h1 { font-size:1.6rem; }
  main h2 { font-size:1.2rem; }
  main h3 { font-size:1.05rem; }
  .top-in { padding:0 16px; gap:14px; }
}
"""

MD_EXTS = ["tables", "fenced_code", "codehilite", "toc", "sane_lists"]
MD_CFG = {"codehilite": {"guess_lang": False, "noclasses": False}}


def all_docs() -> list[Path]:
    return sorted(DOCS.rglob("*.md"))


def title_of(md_text: str, rel: Path) -> str:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return re.sub(r"[#*`]", "", line[2:]).strip()
    return rel.stem


def rewrite_links(body: str) -> str:
    # href="...md" or href="...md#anchor" -> .html (internal relative links only)
    body = re.sub(
        r'(href=")(?!https?://)([^"]+?)\.md(#[^"]*)?(")',
        lambda m: m.group(1) + m.group(2) + ".html" + (m.group(3) or "") + m.group(4),
        body,
    )

    # Markdown <img> tags reference assets (demos/*.gif, hero-v04.png, etc.) that
    # are not part of the doc tree shipped to the site. Without a fallback they
    # render as broken-image icons across 20+ pages. Hide them silently.
    def _inject_onerror(m: re.Match) -> str:
        tag = m.group(0)
        if "onerror=" in tag:
            return tag
        return re.sub(
            r"\s*/?>$",
            " onerror=\"this.style.display='none'\" />",
            tag,
            count=1,
        )

    body = re.sub(r"<img\b[^>]*>", _inject_onerror, body)
    return body


def sidebar(cur_rel: Path, depth: int) -> str:
    pre = "../" * depth
    out = []
    docs = all_docs()
    for label, sub in GROUPS:
        if sub == ".":
            members = [d for d in docs if d.parent == DOCS]
        else:
            members = [d for d in docs if d.parent == DOCS / sub]
        if not members:
            continue
        out.append(f"<h4>{html.escape(label)}</h4>")
        for d in members:
            rel = d.relative_to(DOCS)
            href = pre + str(rel.with_suffix(".html"))
            cls = ' class="cur"' if rel == cur_rel else ""
            name = rel.stem
            out.append(f'<a{cls} href="{href}">{html.escape(name)}</a>')
    return "\n".join(out)


def demo_block(rel_no_ext: str, depth: int) -> str:
    if rel_no_ext not in DEMO_EMBEDS:
        return ""
    gif, caption = DEMO_EMBEDS[rel_no_ext]
    src = "../" * depth + "../assets/demos/" + gif  # site/docs/<depth>/ -> site/assets/demos
    return (
        '<div class="demo-embed"><div class="frame"><div class="dots"><i></i><i></i><i></i></div>'
        f'<img src="{src}" alt="{html.escape(caption)}" loading="lazy" '
        "onerror=\"this.closest('.demo-embed').style.display='none'\"></div>"
        f"<p>{html.escape(caption)}</p></div>"
    )


def page(
    rel: Path,
    body: str,
    title: str,
    needs_mermaid: bool,
    is_index: bool = False,
    lang: str = "en",
) -> str:
    depth = len(rel.parts) - 1
    pre = "../" * depth
    sibling_rel = rel.with_suffix(".html").as_posix() if not is_index else "index.html"
    if lang == "zh":
        # /bene/zh/docs/... — landing is one extra level up
        landing = pre + "../../index.html"
        idx = pre + "index.html"
        skill = pre + "../../SKILL.md"
        llms = pre + "../../llms.txt"
        # toggle goes back to the EN sibling path
        toggle_href = pre + "../../docs/" + sibling_rel
        toggle_label = "EN"
        toggle_title = "Switch to English"
        html_lang = "zh-CN"
        title_suffix = "BENE 文档"
        meta_desc = f"BENE 0.2.0 文档 — {html.escape(title)}"
        nav_landing = "Landing"
        nav_idx = "文档索引"
        nav_skill_title = "把 BENE 交给你的 agent，一个 URL"
        nav_copy_title = "把 llms.txt 索引拷到剪贴板 — 粘贴进你 agent 的 context"
        nav_copy_label = "复制 llms.txt"
        nav_copied = "✓ 已复制"
        nav_opened = "↗ 已打开"
        banner = (
            '<div class="zh-banner" style="background:rgba(238,96,24,.07);border-bottom:1px solid rgba(238,96,24,.2);padding:12px 24px;font-size:13px;line-height:1.5;color:rgb(var(--muted))">'
            '<strong style="color:rgb(var(--text))">本页中文版正在按照 4-book methodology 翻译（Mom Test / Pressfield / Zinsser / Dicks）—— 不放 AI 翻译稿。</strong>'
            f' 下方是英文原文，点上方 <a href="{toggle_href}" style="color:rgb(var(--accent));text-decoration:underline">EN</a> 直接到英文页面，'
            ' 或在 <a href="https://github.com/EdwardTang/bene-site/discussions" target="_blank" rel="noopener noreferrer" style="color:rgb(var(--accent));text-decoration:underline">Discussions</a> 里贡献翻译。'
            "</div>"
        )
    else:
        landing = pre + "../index.html"
        idx = pre + "index.html"
        skill = pre + "../SKILL.md"
        llms = pre + "../llms.txt"
        # toggle goes to the zh sibling path
        toggle_href = pre + "../zh/docs/" + sibling_rel
        toggle_label = "文"
        toggle_title = "切换到中文"
        html_lang = "en"
        title_suffix = "BENE docs"
        meta_desc = f"BENE 0.2.0 documentation — {html.escape(title)}"
        nav_landing = "Landing"
        nav_idx = "Docs index"
        nav_skill_title = "Hand BENE to your agent in one URL"
        nav_copy_title = "Copy the llms.txt site map (an LLM-friendly index pointing at SKILL.md + every doc). Paste it into your agent's context."
        nav_copy_label = "Copy llms.txt"
        nav_copied = "✓ copied"
        nav_opened = "↗ opened"
        banner = ""
    gh = f"{GITHUB_BLOB}/{rel.as_posix()}"
    mermaid = MERMAID_JS if needs_mermaid else ""
    crumbs = (
        ""
        if is_index
        else f'<div class="crumbs"><a href="{idx}">docs</a> / {html.escape(rel.as_posix())}</div>'
    )
    src_line = (
        ""
        if is_index
        else (
            f'<div class="src">source: <a href="{gh}" target="_blank" rel="noopener noreferrer">docs/{html.escape(rel.as_posix())}</a>'
            " · generated by site/build-docs.py — edit the .md, not this file</div>"
        )
    )
    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{html.escape(title)} — {title_suffix}</title>
<meta name="description" content="{meta_desc}" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>{CSS}</style>
{mermaid}
</head>
<body>
<div class="top"><div class="top-in">
  <a class="brand" href="{landing}">BENE</a>
  <a class="nav" href="{landing}">{nav_landing}</a>
  <a class="nav" href="{idx}">{nav_idx}</a>
  <a class="nav" href="{skill}" target="_blank" rel="noopener noreferrer" title="{nav_skill_title}">SKILL.md ↗</a>
  <button class="nav copy-llms" data-llms-url="{llms}" data-copied-label="{nav_copied}" data-opened-label="{nav_opened}" title="{nav_copy_title}">{nav_copy_label}</button>
  <a class="nav" href="https://github.com/EdwardTang/bene-site" target="_blank" rel="noopener noreferrer">GitHub</a>
  <a class="nav" href="{toggle_href}" title="{toggle_title}" style="border:1px solid rgba(136,136,136,.4);padding:2px 8px;border-radius:3px">{toggle_label}</a>
</div></div>
{banner}
<script>
(function() {{
  document.querySelectorAll('button.copy-llms').forEach(function(btn) {{
    var original = btn.textContent;
    btn.addEventListener('click', function() {{
      var url = btn.getAttribute('data-llms-url');
      fetch(url, {{ cache: 'no-cache' }})
        .then(function(r) {{ if (!r.ok) throw new Error('fetch ' + r.status); return r.text(); }})
        .then(function(text) {{
          if (navigator.clipboard && navigator.clipboard.writeText) {{
            return navigator.clipboard.writeText(text).then(function() {{
              btn.textContent = btn.getAttribute('data-copied-label') || '✓ copied';
              setTimeout(function() {{ btn.textContent = original; }}, 2200);
            }});
          }}
          window.open(url, '_blank', 'noopener,noreferrer');
          btn.textContent = btn.getAttribute('data-opened-label') || '↗ opened';
          setTimeout(function() {{ btn.textContent = original; }}, 2200);
        }})
        .catch(function() {{
          window.open(url, '_blank', 'noopener,noreferrer');
          btn.textContent = btn.getAttribute('data-opened-label') || '↗ opened';
          setTimeout(function() {{ btn.textContent = original; }}, 2200);
        }});
    }});
  }});
}})();
</script>
<div class="wrap">
<aside class="sb">{sidebar(rel, depth)}</aside>
<main>
{crumbs}
{body}
{src_line}
</main>
</div>
<footer class="ft"><div class="in"><span>BENE 0.2.0 · local-first · SQLite · built in the open</span>
<a href="https://github.com/EdwardTang/bene-site/discussions" target="_blank" rel="noopener noreferrer">Building something on bene? Open a Discussion.</a></div></footer>
</body>
</html>
"""


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # pygments css appended once into shared CSS (dark scheme on term background)
    global CSS
    pyg = HtmlFormatter(style="monokai").get_style_defs(".codehilite")
    CSS = CSS + "\n" + pyg + "\n.codehilite { background: var(--term-bg) !important; }\n"

    # docs/assets (logo/banner pngs referenced by some pages)
    if (DOCS / "assets").exists():
        shutil.copytree(DOCS / "assets", OUT / "assets")

    # examples/ (15+ docs link to ../examples/*.py and ../../examples/*.py — those
    # resolve to site/examples/ when served, so mirror the dir here)
    if (ROOT / "examples").exists():
        examples_out = OUT.parent / "examples"
        if examples_out.exists():
            shutil.rmtree(examples_out)
        shutil.copytree(ROOT / "examples", examples_out)

    entries: list[tuple[Path, str]] = []
    for src in all_docs():
        rel = src.relative_to(DOCS)
        text = src.read_text(encoding="utf-8")
        title = title_of(text, rel)
        entries.append((rel, title))

        needs_mermaid = "```mermaid" in text
        if needs_mermaid:
            text = re.sub(
                r"```mermaid\n(.*?)```",
                lambda m: '<div class="mermaid">\n' + m.group(1) + "</div>",
                text,
                flags=re.S,
            )

        md = markdown.Markdown(extensions=MD_EXTS, extension_configs=MD_CFG)
        body = md.convert(text)
        body = rewrite_links(body)
        depth = len(rel.parts) - 1
        # inject the matching VHS demo right after the first h1
        demo = demo_block(rel.with_suffix("").as_posix(), depth)
        if demo:
            body = re.sub(r"(</h1>)", r"\1" + demo, body, count=1)

        dst = OUT / rel.with_suffix(".html")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(page(rel, body, title, needs_mermaid), encoding="utf-8")

        # zh-tree mirror: same EN body, prefixed with a translation-in-progress
        # banner; nav toggle routes back to the EN sibling. As per-page zh.md
        # sources land in docs/zh/, this will be replaced with the translated
        # markdown body.
        zh_out = OUT.parent / "zh" / "docs"
        zh_dst = zh_out / rel.with_suffix(".html")
        zh_dst.parent.mkdir(parents=True, exist_ok=True)
        zh_dst.write_text(page(rel, body, title, needs_mermaid, lang="zh"), encoding="utf-8")

    # index page
    groups_html = []
    for label, sub in GROUPS:
        if sub == ".":
            members = [(r, t) for r, t in entries if len(r.parts) == 1]
        else:
            members = [(r, t) for r, t in entries if r.parts[0] == sub]
        if not members:
            continue
        lis = "\n".join(
            f'<li><a href="{r.with_suffix(".html").as_posix()}">{html.escape(t)}</a>'
            f'<span class="path">docs/{html.escape(r.as_posix())}</span></li>'
            for r, t in members
        )
        groups_html.append(
            f'<div class="idx-group"><h2>{html.escape(label)}</h2><ul>{lis}</ul></div>'
        )

    index_body = (
        "<h1>BENE documentation</h1>"
        f"<p>{len(entries)} documents, generated from <code>docs/</code>. Pick the job you are doing: start local, "
        "rewind a bad turn, connect an agent, verify a claim, or scale a run. These are the same files you can read "
        f'<a href="https://github.com/EdwardTang/bene-site/tree/main/docs" target="_blank" rel="noopener noreferrer">on GitHub</a>. '
        "Edit the markdown, rerun <code>site/build-docs.py</code>; never edit the HTML.</p>"
        + demo_block("README", 0)
        + "".join(groups_html)
    )
    (OUT / "index.html").write_text(
        page(Path("index.md"), index_body, "BENE documentation", False, is_index=True),
        encoding="utf-8",
    )

    zh_index_body = (
        "<h1>BENE 文档</h1>"
        f"<p><strong>翻译进行中。</strong>共 {len(entries)} 个文档，源在 <code>docs/</code>。"
        "本站采用 4-book methodology（Mom Test / Pressfield / Zinsser / Dicks）逐页翻译——不放 AI 翻译稿。"
        "下方每个条目点开是英文原文，顶部 nav 的 <code>EN</code> 按钮直接回到对应的英文页面。"
        f' 想贡献翻译，请在 <a href="https://github.com/EdwardTang/bene-site/discussions" target="_blank" rel="noopener noreferrer">Discussions</a> 留言。</p>'
        + "".join(groups_html)
    )
    zh_out_dir = OUT.parent / "zh" / "docs"
    zh_out_dir.mkdir(parents=True, exist_ok=True)
    (zh_out_dir / "index.html").write_text(
        page(
            Path("index.md"),
            zh_index_body,
            "BENE 文档",
            False,
            is_index=True,
            lang="zh",
        ),
        encoding="utf-8",
    )
    print(f"built {len(entries)} pages + index -> {OUT} (and zh mirror at {zh_out_dir})")


if __name__ == "__main__":
    build()
