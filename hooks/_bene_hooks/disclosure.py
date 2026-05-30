"""Disclosure log matcher.

Reads .harness/disclosure.md and looks for level-3 headers starting with
the token, ignoring help-text and any `## Example` section.
"""
from __future__ import annotations

import re
from .paths import harness_dir


def disclosure_mentions(token: str) -> bool:
    f = harness_dir() / "disclosure.md"
    if not f.exists():
        return False
    text = f.read_text()
    if "## Example" in text:
        text = text.split("## Example", 1)[0]
    pat = re.compile(rf"^###\s+{re.escape(token)}\s*:", re.MULTILINE | re.IGNORECASE)
    return bool(pat.search(text))
