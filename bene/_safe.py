"""Narrow defensive helpers — replaces bare ``except Exception:`` patterns.

The doctrine (PY-R17) bans broad catches because they mask real defects.
But there are legitimate cases where a parse-or-fallback pattern is exactly
what's needed: optional JSON fields in DB rows, user-supplied config files,
stream payloads from external sources. These helpers centralise the narrow
exception list so call sites stay clean and the doctrine stays honest.
"""

from __future__ import annotations

import json
from typing import Any


def safe_json_loads(s: str | bytes | None, default: Any = None) -> Any:
    """Parse JSON; return ``default`` on parse failure, empty, or wrong type.

    Use for optional JSON-encoded fields where a non-JSON value or empty
    string should fall back silently. Narrows the catch to the three
    exceptions ``json.loads`` actually raises: ``JSONDecodeError`` (bad
    syntax), ``TypeError`` (non-str/bytes input), ``ValueError`` (subclass
    of ``JSONDecodeError``, kept for explicitness).
    """
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default
