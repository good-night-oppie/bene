"""SKILL.md discovery for bene.

Walks a list of root directories looking for `*/SKILL.md` files with
YAML frontmatter. Each file becomes one skill, ready to insert into the
shared SkillStore.

Mirrors the layout used by Claude Code skills (see
~/src-fresh/.claude/skills/<name>/SKILL.md) so bene can pull in the
existing team-curated skill library without rewriting it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse a leading YAML-ish frontmatter block delimited by '---' lines.

    Returns (metadata, body). If no frontmatter is present, returns ({}, text).
    We use a permissive line-based parser instead of PyYAML so bene stays
    dependency-light; SKILL.md frontmatter in practice only uses simple
    'key: value' pairs.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    metadata: dict[str, str] = {}
    body_start = len(lines)
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = i + 1
            break
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip()
    body = "\n".join(lines[body_start:]).lstrip("\n")
    return metadata, body


def discover_skills(paths: Iterable[Path | str]) -> list[dict[str, object]]:
    """Walk paths for `*/SKILL.md`; return one dict per discovered skill.

    Each dict has: name, description, template (the body), tags (from
    frontmatter), source_path (absolute path string for traceability).
    """
    out: list[dict[str, object]] = []
    for root in paths:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        for skill_md in root_path.glob("*/SKILL.md"):
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            except UnicodeDecodeError:
                # Skip files that are not valid UTF-8 rather than crashing the
                # whole discovery. SKILL.md is documented as text; bad encoding
                # is a content issue, not a discovery infrastructure problem.
                continue
            meta, body = _parse_frontmatter(text)
            name = meta.get("name") or skill_md.parent.name
            tags_raw = meta.get("tags", "")
            tags = (
                [t.strip() for t in tags_raw.split(",") if t.strip()]
                if tags_raw
                else [skill_md.parent.name]
            )
            out.append(
                {
                    "name": name,
                    "description": meta.get("description", ""),
                    "template": body,
                    "tags": tags,
                    "source_path": str(skill_md.resolve()),
                }
            )
    return out
