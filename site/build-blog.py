#!/usr/bin/env python3
"""Static blog builder: bene-main/blog/**/*.md -> site/blog/**/*.html (+ zh mirror).

Parallel to (and deliberately independent of) site/build-docs.py — the blog has a
single-column prose layout with a byline, not the docs sidebar layout, and keeping
it in its own file avoids clobbering concurrent edits to build-docs.py.

Posts live in blog/*.md (English) and blog/zh/*.md (Chinese). Each post starts with
a `# Title` h1 followed by a byline line of the form:

    *BENE blog · the WHY · 2026-06-17*

The middle field is the post's kind/series label; the last field is an ISO date used
to sort the index (newest first). Both are optional — a post with no byline still
renders, it just sorts last.

Run:  uv run --with markdown --with pygments python site/build-blog.py
Never hand-edit the generated HTML; edit the markdown and rerun.
"""

from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
BLOG = ROOT / "blog"
SITE = ROOT / "site"
OUT = SITE / "blog"
ZH_OUT = SITE / "zh" / "blog"

MD_EXTS = ["tables", "fenced_code", "codehilite", "toc", "sane_lists"]
MD_CFG = {"codehilite": {"guess_lang": False, "noclasses": False}}

# Shared design tokens — kept byte-identical to site/build-docs.py's :root so the
# blog feels native next to the docs. Blog-specific layout overrides follow.
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap');
:root { --bg:#F0EEE8; --surface:#EDE9E4; --border:#CFCCC8; --ink:#1F1D1C; --mute:#62666D; --accent:#EE6018; --gold:#B46A35; --term-bg:#332E2B; --term-fg:#EDE9E4; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.65 Geist,ui-sans-serif,system-ui,sans-serif; }
a { color:var(--gold); text-decoration-color: color-mix(in srgb, var(--gold) 40%, transparent); text-underline-offset:3px; }
a:hover { color:var(--accent); }
.top { position:sticky; top:0; z-index:10; background:color-mix(in srgb, var(--bg) 92%, transparent); backdrop-filter:blur(8px); border-bottom:1px solid var(--border); }
.top-in { max-width:1200px; margin:0 auto; padding:0 24px; height:56px; display:flex; align-items:center; gap:24px; }
.brand { font-family:Geist,ui-sans-serif,sans-serif; font-weight:700; letter-spacing:.12em; color:var(--ink); text-decoration:none; }
.top .spacer { flex:1; }
.top a.nav { color:var(--mute); text-decoration:none; font-size:14px; }
.top a.nav:hover { color:var(--accent); }
.top a.nav.cur { color:var(--ink); font-weight:600; }
.wrap { max-width:760px; margin:0 auto; padding:40px 24px 24px; }
main { min-width:0; }
.crumbs { font:12.5px "Geist Mono",ui-monospace,monospace; color:var(--mute); margin-bottom:14px; }
.crumbs a { color:var(--mute); }
main h1 { font-family:Geist,ui-sans-serif,sans-serif; font-size:2.1rem; line-height:1.2; margin:.1em 0 .25em; }
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
.byline { font:13px "Geist Mono",ui-monospace,monospace; color:var(--mute); margin:0 0 28px; }
.byline .kind { color:var(--accent); }
.src { font:12.5px "Geist Mono",ui-monospace,monospace; margin-top:48px; padding-top:16px; border-top:1px solid var(--border); color:var(--mute); }
.posts { list-style:none; padding:0; margin:8px 0 0; }
.posts li { padding:20px 0; border-bottom:1px dashed var(--border); }
.posts a.title { display:block; font-family:Geist,ui-sans-serif,sans-serif; font-size:1.3rem; font-weight:600; color:var(--ink); text-decoration:none; }
.posts a.title:hover { color:var(--accent); }
.posts .meta { font:12px "Geist Mono",ui-monospace,monospace; color:var(--mute); margin:4px 0 8px; }
.posts .meta .kind { color:var(--accent); }
.posts .excerpt { color:var(--mute); margin:0; }
.empty { color:var(--mute); background:var(--surface); border:1px dashed var(--border); border-radius:6px; padding:24px; margin-top:8px; }
footer.ft { border-top:1px solid var(--border); margin-top:40px; }
footer.ft .in { max-width:760px; margin:0 auto; padding:24px; font:13px "Geist Mono",ui-monospace,monospace; color:var(--mute); display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; }
@media (max-width: 860px) {
  .wrap { padding:24px 16px 16px; }
  main h1 { font-size:1.6rem; }
  main h2 { font-size:1.2rem; }
  .top-in { padding:0 16px; gap:14px; }
}
"""

# UI strings per language.
STRINGS = {
    "en": {
        "brand": "BENE",
        "nav_landing": "Landing",
        "nav_docs": "Docs",
        "nav_blog": "Blog",
        "lang_switch_label": "文",
        "lang_switch_title": "切换到中文",
        "index_title": "BENE blog",
        "index_h1": "Blog",
        "index_intro": (
            "Notes from building BENE — the harness behind the agents. "
            "The opening series walks the <b>why</b>, the <b>what</b>, and the <b>how</b>."
        ),
        "empty": (
            "The first posts are being written. Check back soon — or read the "
            '<a href="../docs/index.html">docs</a> in the meantime.'
        ),
        "back_to_index": "← All posts",
        "edit_note": "Edit the markdown in blog/, rerun site/build-blog.py; never edit the HTML.",
    },
    "zh": {
        "brand": "BENE",
        "nav_landing": "Landing",
        "nav_docs": "文档",
        "nav_blog": "Blog",
        "lang_switch_label": "EN",
        "lang_switch_title": "Switch to English",
        "index_title": "BENE 博客",
        "index_h1": "Blog",
        "index_intro": (
            "构建 BENE 的手记——agent 背后的那套 harness。"
            "开篇这一组讲清楚 <b>为什么</b>、<b>是什么</b>、<b>怎么做</b>。"
        ),
        "empty": (
            "首批文章还在写。过几天再来——或者先看看"
            '<a href="../docs/index.html">文档</a>。'
        ),
        "back_to_index": "← 全部文章",
        "edit_note": "翻译进行中。改 blog/zh/ 的 markdown，重跑 site/build-blog.py；不要手改 HTML。",
    },
}

BYLINE_RE = re.compile(r"^\*(.+?)\*\s*$", re.M)


def shell(lang: str, title: str, body: str, *, cur: str) -> str:
    """Wrap rendered body in the full page (head + nav + footer)."""
    s = STRINGS[lang]
    # Relative links from site/blog/ (EN) or site/zh/blog/ (zh) — both depth-1 under
    # their language root, so ../ reaches the language root and ../../ the site root.
    landing = "../index.html"
    docs = "../docs/index.html"
    blog = "index.html"
    if lang == "en":
        lang_switch = "../zh/blog/index.html"
    else:
        lang_switch = "../../blog/index.html"

    def navlink(href: str, label: str, key: str) -> str:
        klass = "nav cur" if key == cur else "nav"
        return f'<a class="{klass}" href="{href}">{html.escape(label)}</a>'

    nav = (
        '<div class="top"><div class="top-in">'
        f'<a class="brand" href="{landing}">{html.escape(s["brand"])}</a>'
        f'{navlink(landing, s["nav_landing"], "landing")}'
        f'{navlink(docs, s["nav_docs"], "docs")}'
        f'{navlink(blog, s["nav_blog"], "blog")}'
        '<span class="spacer"></span>'
        f'<a class="nav" href="{lang_switch}" title="{html.escape(s["lang_switch_title"])}">'
        f'{html.escape(s["lang_switch_label"])}</a>'
        "</div></div>"
    )
    footer = (
        '<footer class="ft"><div class="in">'
        f'<span>{html.escape(s["edit_note"])}</span>'
        '<a href="https://github.com/EdwardTang/bene-site" target="_blank" rel="noopener noreferrer">GitHub</a>'
        "</div></footer>"
    )
    return (
        "<!doctype html><html lang=\"" + ("zh-Hans" if lang == "zh" else "en") + "\"><head>"
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        '<link rel="icon" href="../assets/bene-logo.svg">'
        f"<style>{CSS}</style></head><body>"
        f"{nav}"
        f'<div class="wrap"><main>{body}</main></div>'
        f"{footer}"
        "</body></html>"
    )


def rewrite_links(body: str) -> str:
    """Rewrite internal `*.md` links to `*.html` so cross-post links resolve.

    A post that links to a sibling post by its source name — e.g.
    `[next](what-bene.md)` — would otherwise 404, since this builder writes
    `what-bene.html`. Only relative links are rewritten; external `http(s)://`
    links are left alone. Mirrors site/build-docs.py's rewrite_links.
    """
    return re.sub(
        r'(href=")(?!https?://)([^"]+?)\.md(#[^"]*)?(")',
        lambda m: m.group(1) + m.group(2) + ".html" + (m.group(3) or "") + m.group(4),
        body,
    )


def parse_post(md_path: Path) -> dict:
    """Pull slug/title/kind/date/excerpt/body_html out of a post markdown file."""
    text = md_path.read_text(encoding="utf-8")
    # Title = first markdown h1.
    m_title = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    title = m_title.group(1).strip() if m_title else md_path.stem

    kind, date = "", ""
    body_src = text
    if m_title:
        rest = text[m_title.end():]
        m_by = BYLINE_RE.search(rest.lstrip("\n")[:300])
        if m_by:
            parts = [p.strip() for p in m_by.group(1).split("·")]
            # parts like ["BENE blog", "the WHY", "2026-06-17"]
            for p in parts:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
                    date = p
                elif p and p.lower() not in ("bene blog", "bene 博客"):
                    kind = p
            # Drop the title + byline lines from the rendered body.
            body_src = rest[m_by.end():]

    md = markdown.Markdown(extensions=MD_EXTS, extension_configs=MD_CFG)
    body_html = rewrite_links(md.convert(body_src.strip()))

    # Excerpt = first rendered paragraph, stripped of tags, clipped.
    m_p = re.search(r"<p>(.*?)</p>", body_html, re.S)
    excerpt = re.sub(r"<[^>]+>", "", m_p.group(1)).strip() if m_p else ""
    if len(excerpt) > 220:
        excerpt = excerpt[:219].rstrip() + "…"

    return {
        "slug": md_path.stem,
        "title": title,
        "kind": kind,
        "date": date,
        "excerpt": excerpt,
        "body_html": body_html,
    }


def render_post(post: dict, lang: str) -> str:
    s = STRINGS[lang]
    by_bits = []
    if post["kind"]:
        by_bits.append(f'<span class="kind">{html.escape(post["kind"])}</span>')
    if post["date"]:
        by_bits.append(html.escape(post["date"]))
    byline = (
        f'<p class="byline">{" · ".join(by_bits)}</p>' if by_bits else ""
    )
    body = (
        f'<div class="crumbs"><a href="index.html">{html.escape(s["back_to_index"])}</a></div>'
        f'<h1>{html.escape(post["title"])}</h1>'
        f"{byline}"
        f'{post["body_html"]}'
        f'<p class="src"><a href="index.html">{html.escape(s["back_to_index"])}</a></p>'
    )
    return shell(lang, f'{post["title"]} — {s["index_title"]}', body, cur="blog")


def render_index(posts: list[dict], lang: str) -> str:
    s = STRINGS[lang]
    if posts:
        items = []
        for p in posts:
            meta_bits = []
            if p["kind"]:
                meta_bits.append(f'<span class="kind">{html.escape(p["kind"])}</span>')
            if p["date"]:
                meta_bits.append(html.escape(p["date"]))
            meta = (
                f'<div class="meta">{" · ".join(meta_bits)}</div>' if meta_bits else ""
            )
            excerpt = (
                f'<p class="excerpt">{html.escape(p["excerpt"])}</p>'
                if p["excerpt"]
                else ""
            )
            items.append(
                "<li>"
                f'<a class="title" href="{p["slug"]}.html">{html.escape(p["title"])}</a>'
                f"{meta}{excerpt}</li>"
            )
        listing = '<ul class="posts">' + "\n".join(items) + "</ul>"
    else:
        listing = f'<div class="empty">{s["empty"]}</div>'

    body = (
        f'<h1>{html.escape(s["index_h1"])}</h1>'
        f'<p>{s["index_intro"]}</p>'
        f"{listing}"
    )
    return shell(lang, s["index_title"], body, cur="blog")


def collect(src_dir: Path) -> list[dict]:
    if not src_dir.is_dir():
        return []
    posts = [parse_post(p) for p in sorted(src_dir.glob("*.md"))]
    # Newest first; dateless posts sort last (empty string < any date when reversed,
    # so invert with a presence key).
    posts.sort(key=lambda p: (p["date"] != "", p["date"]), reverse=True)
    return posts


def build() -> None:
    # Clear stale output first so a renamed/deleted post's old <slug>.html can't
    # linger and keep being deployed (the index would no longer list it). Keeps
    # the build reproducible from sources alone, like site/build-docs.py.
    for out_dir in (OUT, ZH_OUT):
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    en_posts = collect(BLOG)
    zh_posts = collect(BLOG / "zh")

    for post in en_posts:
        (OUT / f'{post["slug"]}.html').write_text(render_post(post, "en"), encoding="utf-8")
    (OUT / "index.html").write_text(render_index(en_posts, "en"), encoding="utf-8")

    for post in zh_posts:
        (ZH_OUT / f'{post["slug"]}.html').write_text(render_post(post, "zh"), encoding="utf-8")
    (ZH_OUT / "index.html").write_text(render_index(zh_posts, "zh"), encoding="utf-8")

    print(
        f"built blog: {len(en_posts)} EN post(s) + index -> {OUT}, "
        f"{len(zh_posts)} zh post(s) + index -> {ZH_OUT}"
    )


if __name__ == "__main__":
    build()
