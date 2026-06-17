"""SQLite FTS query helpers."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_OPERATORS = {"and", "or", "not", "near"}


def fallback_fts_query(query: str) -> str:
    """Return a literal-ish FTS5 query for malformed user input.

    BENE exposes FTS5 syntax for power users, but plain user searches often
    include punctuation that FTS5 treats as operators.  The common case is a
    hyphenated phrase such as ``de-kaos``: SQLite parses the hyphen as unary
    NOT and raises ``no such column``.  On those failures, retry with a quoted
    phrase made from lexical tokens.
    """
    terms = [t.lower() for t in _TOKEN_RE.findall(query) if t.lower() not in _OPERATORS]
    if not terms:
        return ""
    if len(terms) == 1:
        return terms[0]
    return '"' + " ".join(terms) + '"'
