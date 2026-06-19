"""Canonical genome serialization — a stable content address for a harness genome.

Logically-identical genomes MUST hash identically. The naive
``json.dumps(payload, sort_keys=True)`` does not achieve this: it sorts keys but
preserves three differences that the evolution loop introduces constantly, so one
genome's identity splits across several DGM-archive / lineage rows:

- **int vs float** — ``{"temperature": 1}`` and ``{"temperature": 1.0}`` are logically
  equal but ``json.dumps`` writes ``1`` vs ``1.0`` → different sha256.
- **unicode form** — an NFC ``system_prompt`` and its NFD twin are the same text but
  different code points → different bytes → different sha256.
- **line endings** — ``CRLF`` vs ``LF`` in a prompt → different bytes.

(Empirically, on ``CodexHarness.content_hash``: int/float ``1`` → ``00d92b5f`` vs
``489079f8``; NFC/NFD → ``abb97cf6`` vs ``1958056c``.)

``genome_hash`` normalizes the evolvable surface to ONE byte form before hashing:

- numbers → a single canonical decimal string via ``Decimal`` (``1``, ``1.0`` and
  ``1.00`` all collapse to ``"1"``; ``0.10`` → ``"0.1"``; ``-0.0`` → ``"0"``); ``NaN`` /
  ``Infinity`` are rejected (no stable identity);
- strings → ``unicodedata.normalize("NFC", s)`` + ``CRLF``/``CR`` → ``LF``;
- dict keys → NFC-normalized and sorted; lists keep their order;
- numbers are emitted UNQUOTED and strings QUOTED, so the number ``1`` and the string
  ``"1"`` never collide.

The serializer lives bene-side (where genomes are minted/mutated) so the identity is
stable regardless of which producer constructed the genome. ``canonical_genome_json``
exposes the canonical string itself for callers that want to store the blob alongside
its hash (hash + blob together).
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from decimal import Decimal
from typing import Any

__all__ = [
    "NonCanonicalizableGenome",
    "canonical_genome_json",
    "genome_hash",
]


class NonCanonicalizableGenome(ValueError):
    """A genome value has no stable canonical form (``NaN``/``Infinity``, an unsupported
    type, or a dict whose keys collide after NFC normalization)."""


def _norm_str(s: str) -> str:
    return unicodedata.normalize("NFC", s).replace("\r\n", "\n").replace("\r", "\n")


def _emit_str(s: str) -> str:
    # ensure_ascii=False so the bytes are the NFC code points themselves, quoted+escaped.
    return json.dumps(_norm_str(s), ensure_ascii=False)


def _emit_num(x: int | float) -> str:
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            raise NonCanonicalizableGenome(f"non-finite number in genome: {x!r}")
        d = Decimal(str(x))  # str(float) is the shortest round-trip repr in py3
    else:
        d = Decimal(x)
    if d == 0:  # collapse -0 and 0.0 etc. to a single "0"
        return "0"
    # normalize() strips trailing zeros (1.0 -> 1) but can yield exponent form (10 ->
    # 1E+1); format(..., "f") forces a plain fixed-point string.
    return format(d.normalize(), "f")


def _emit(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):  # MUST precede int — bool is an int subclass
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _emit_num(value)
    if isinstance(value, str):
        return _emit_str(value)
    if isinstance(value, dict):
        norm: dict[str, Any] = {}
        for k, v in value.items():
            nk = _norm_str(k) if isinstance(k, str) else _norm_str(str(k))
            if nk in norm:
                raise NonCanonicalizableGenome(
                    f"genome dict keys collide after NFC normalization: {nk!r}"
                )
            norm[nk] = v
        parts = [f"{_emit_str(k)}:{_emit(norm[k])}" for k in sorted(norm)]
        return "{" + ",".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_emit(v) for v in value) + "]"
    raise NonCanonicalizableGenome(
        f"unsupported genome value type {type(value).__name__}: {value!r}"
    )


def canonical_genome_json(surface: dict[str, Any]) -> str:
    """Return the canonical, deterministic string form of a genome's evolvable surface.

    ``surface`` is the identity-defining field dict the caller selects (e.g. a codex
    harness's ``{system_prompt, move_selection_strategy, params, resources, harness_ref}``).
    Identity is byte-stable across int↔float-equal numbers, NFC↔NFD strings, and
    CRLF↔LF line endings; ``NaN``/``Infinity`` raise ``NonCanonicalizableGenome``.
    """
    return _emit(surface)


def genome_hash(surface: dict[str, Any]) -> str:
    """sha256 hexdigest of :func:`canonical_genome_json` — the stable content address."""
    return hashlib.sha256(canonical_genome_json(surface).encode("utf-8")).hexdigest()
