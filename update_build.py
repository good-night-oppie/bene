import re

with open("site/build-docs.py", "r") as f:
    content = f.read()

# We need to change the zh_out logic in build-docs.py
replacement = """
        # zh-tree mirror
        zh_out = OUT.parent / "zh" / "docs"
        zh_dst = zh_out / rel.with_suffix(".html")
        zh_dst.parent.mkdir(parents=True, exist_ok=True)
        
        zh_src = DOCS / "zh" / rel
        if zh_src.exists():
            zh_text = zh_src.read_text(encoding="utf-8")
            zh_title = title_of(zh_text, rel)
            if needs_mermaid:
                zh_text = re.sub(
                    r"```mermaid\\n(.*?)```",
                    lambda m: '<div class="mermaid">\\n' + m.group(1) + "</div>",
                    zh_text,
                    flags=re.S,
                )
            zh_md = markdown.Markdown(extensions=MD_EXTS, extension_configs=MD_CFG)
            zh_body = zh_md.convert(zh_text)
            zh_body = rewrite_links(zh_body)
            zh_demo = demo_block(rel.with_suffix("").as_posix(), depth)
            if zh_demo:
                zh_body = re.sub(r"(</h1>)", r"\\1" + zh_demo, zh_body, count=1)
            
            # Write without banner, just pure zh html
            zh_dst.write_text(
                page(rel, zh_body, zh_title, needs_mermaid, lang="zh"), encoding="utf-8"
            )
        else:
            # Fallback to EN with banner
            zh_dst.write_text(
                page(rel, zh_reroot(body), title, needs_mermaid, lang="zh"), encoding="utf-8"
            )
"""

content = re.sub(
    r"# zh-tree mirror.*?zh_dst\.write_text\([^)]+\)", replacement.strip(), content, flags=re.S
)

with open("site/build-docs.py", "w") as f:
    f.write(content)
