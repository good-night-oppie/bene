from __future__ import annotations

from bene.fts import fallback_fts_query


def test_fallback_fts_query_quotes_hyphenated_user_text() -> None:
    assert fallback_fts_query("de-kaos") == '"de kaos"'


def test_fallback_fts_query_drops_bare_operators() -> None:
    assert fallback_fts_query("x AND") == "x"
    assert fallback_fts_query("!!!") == ""
