"""Atomic-completion reference helpers (substrate-agnostic; a reference for
consumers, not a bene runtime feature)."""

from bene.recipes.idempotent_append import (
    append_once,
    complete_in_order,
    complete_side_effect_first,
    ensure_log,
    replay_projection,
)

__all__ = [
    "append_once",
    "complete_in_order",
    "complete_side_effect_first",
    "ensure_log",
    "replay_projection",
]
