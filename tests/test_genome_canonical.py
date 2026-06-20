"""Canonical genome serialization — identity must be stable across logically-identical
genomes (GA-CORE-5 genome-HUD review). Covers the serializer itself + both harness
genome types (CodexHarness, BattleHarness)."""

from __future__ import annotations

import unicodedata

import pytest

from bene.kernel.battle.genome import BattleHarness, seed_harness
from bene.kernel.codex_harness.genome import CodexHarness, seed_codex_harness
from bene.kernel.genome_canonical import (
    NonCanonicalizableGenome,
    canonical_genome_json,
    genome_hash,
)

# ── the serializer itself ────────────────────────────────────────────────────


def test_int_and_float_equal_collapse_to_one_identity():
    assert genome_hash({"p": {"t": 1}}) == genome_hash({"p": {"t": 1.0}})
    assert genome_hash({"p": {"t": 1}}) == genome_hash({"p": {"t": 1.00}})
    assert genome_hash({"x": 2}) == genome_hash({"x": 2.0})
    # negative zero and zero are the same value
    assert genome_hash({"x": 0}) == genome_hash({"x": -0.0})


def test_nfc_and_nfd_strings_collapse():
    nfc = unicodedata.normalize("NFC", "café 你好")
    nfd = unicodedata.normalize("NFD", "café 你好")
    assert nfc != nfd  # genuinely different code points
    assert genome_hash({"system_prompt": nfc}) == genome_hash({"system_prompt": nfd})
    # also applies to dict keys
    assert genome_hash({nfc: 1}) == genome_hash({nfd: 1})


def test_crlf_and_lf_line_endings_collapse():
    assert genome_hash({"s": "a\r\nb\rc"}) == genome_hash({"s": "a\nb\nc"})


def test_numbers_and_their_string_form_never_collide():
    assert genome_hash({"x": 1}) != genome_hash({"x": "1"})
    assert genome_hash({"x": 1.5}) != genome_hash({"x": "1.5"})


def test_distinct_genomes_differ_and_precision_is_kept():
    assert genome_hash({"p": {"t": 1}}) != genome_hash({"p": {"t": 2}})
    assert genome_hash({"x": 1.5}) != genome_hash({"x": 1.6})
    assert genome_hash({"x": 0.1}) == genome_hash({"x": 0.1})
    # canonical numeric form is plain fixed-point (no exponent), int/float-agnostic
    assert canonical_genome_json({"a": 10, "b": 100.0, "c": 0.10}) == '{"a":10,"b":100,"c":0.1}'


def test_key_order_and_nesting_are_canonical():
    a = canonical_genome_json({"b": 1, "a": {"z": [3, 2, 1], "y": True}})
    b = canonical_genome_json({"a": {"y": True, "z": [3, 2, 1]}, "b": 1})
    assert a == b == '{"a":{"y":true,"z":[3,2,1]},"b":1}'


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_rejected(bad):
    with pytest.raises(NonCanonicalizableGenome):
        genome_hash({"x": bad})


def test_key_collision_after_normalization_raises():
    nfc = unicodedata.normalize("NFC", "é")
    nfd = unicodedata.normalize("NFD", "é")
    with pytest.raises(NonCanonicalizableGenome):
        genome_hash({nfc: 1, nfd: 2})


# ── CodexHarness identity ────────────────────────────────────────────────────


def test_codex_content_hash_invariant_under_int_float_and_nfc_nfd():
    base = seed_codex_harness().to_dict()

    def mk(**over):
        d = dict(base)
        d.update(over)
        return CodexHarness.from_dict(d)

    assert (
        mk(params={"temperature": 1}).content_hash()
        == mk(params={"temperature": 1.0}).content_hash()
    )
    nfc = unicodedata.normalize("NFC", "你好 café")
    nfd = unicodedata.normalize("NFD", "你好 café")
    assert mk(system_prompt=nfc).content_hash() == mk(system_prompt=nfd).content_hash()


def test_codex_content_hash_stable_under_roundtrip():
    g = seed_codex_harness()
    assert g.content_hash() == CodexHarness.from_dict(g.to_dict()).content_hash()
    assert g.content_hash() == CodexHarness.from_json(g.to_json()).content_hash()


def test_codex_content_hash_still_distinguishes_genuine_changes():
    base = seed_codex_harness().to_dict()

    def mk(**over):
        d = dict(base)
        d.update(over)
        return CodexHarness.from_dict(d)

    assert (
        mk(params={"temperature": 1}).content_hash() != mk(params={"temperature": 2}).content_hash()
    )
    # harness_ref is folded (PR #64) — distinct on-disk dirs do not collide
    assert (
        mk(harness_ref="dir/A", resources={}).content_hash()
        != mk(harness_ref="dir/B", resources={}).content_hash()
    )


# ── BattleHarness identity ───────────────────────────────────────────────────


def test_battle_content_hash_invariant_under_int_float_and_nfc_nfd():
    base = seed_harness().to_dict()

    def mk(**over):
        d = dict(base)
        d.update(over)
        return BattleHarness.from_dict(d)

    assert (
        mk(params={"aggression": 1}).content_hash() == mk(params={"aggression": 1.0}).content_hash()
    )
    nfc = unicodedata.normalize("NFC", "策略 résumé")
    nfd = unicodedata.normalize("NFD", "策略 résumé")
    assert mk(system_prompt=nfc).content_hash() == mk(system_prompt=nfd).content_hash()


def test_battle_content_hash_stable_under_roundtrip_and_excludes_id():
    g = seed_harness()
    assert g.content_hash() == BattleHarness.from_json(g.to_json()).content_hash()
    # a rename alone (harness_id only) must not change identity
    renamed = BattleHarness.from_dict({**g.to_dict(), "harness_id": "renamed-xyz"})
    assert g.content_hash() == renamed.content_hash()


def test_battle_content_hash_distinguishes_genuine_changes():
    base = seed_harness().to_dict()

    def mk(**over):
        d = dict(base)
        d.update(over)
        return BattleHarness.from_dict(d)

    assert (
        mk(move_selection_strategy="max_damage").content_hash()
        != mk(move_selection_strategy="random").content_hash()
    )


# ── path/reference fields are byte-stable (PR #91 review) ────────────────────


def test_byte_stable_keys_keep_path_fields_byte_distinct():
    nfc = unicodedata.normalize("NFC", "/harnesses/café")
    nfd = unicodedata.normalize("NFD", "/harnesses/café")
    assert nfc != nfd
    # a TEXT field folds NFC==NFD ...
    assert genome_hash({"system_prompt": nfc}) == genome_hash({"system_prompt": nfd})
    # ... but a path/reference field stays byte-distinct (distinct on-disk dirs)
    assert genome_hash({"harness_ref": nfc}, byte_stable_keys=("harness_ref",)) != genome_hash(
        {"harness_ref": nfd}, byte_stable_keys=("harness_ref",)
    )


def test_byte_stable_subtree_keys_and_values_are_byte_distinct():
    nfc = unicodedata.normalize("NFC", "modules/café.py")
    nfd = unicodedata.normalize("NFD", "modules/café.py")
    # resources is a path->content dict; both the KEY (a path) and string VALUES are raw
    a = genome_hash({"resources": {nfc: "x"}}, byte_stable_keys=("resources",))
    b = genome_hash({"resources": {nfd: "x"}}, byte_stable_keys=("resources",))
    assert a != b
    # CRLF/CR is NOT folded inside a byte-stable subtree either
    assert genome_hash(
        {"resources": {"f": "a\r\nb"}}, byte_stable_keys=("resources",)
    ) != genome_hash({"resources": {"f": "a\nb"}}, byte_stable_keys=("resources",))


def test_byte_stable_subtree_still_canonicalizes_numbers_and_sorts_keys():
    # byte-stable only turns OFF string folding; numbers still collapse int<->float and
    # keys are still order-independent.
    assert genome_hash({"r": {"a": 1, "b": 2.0}}, byte_stable_keys=("r",)) == genome_hash(
        {"r": {"b": 2, "a": 1.0}}, byte_stable_keys=("r",)
    )


def test_byte_stable_keys_default_is_back_compatible():
    # no byte_stable_keys == the original full-NFC behavior (BattleHarness path: text-only)
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    assert genome_hash({"x": nfc}) == genome_hash({"x": nfd})


def test_codex_content_hash_treats_harness_ref_byte_stable():
    base = seed_codex_harness().to_dict()

    def mk(**over):
        d = dict(base)
        d.update(over)
        return CodexHarness.from_dict(d)

    nfc = unicodedata.normalize("NFC", "/store/café")
    nfd = unicodedata.normalize("NFD", "/store/café")
    # two byte-distinct on-disk dirs must NOT collide under one content hash
    assert (
        mk(harness_ref=nfc, resources={}).content_hash()
        != mk(harness_ref=nfd, resources={}).content_hash()
    )
    # but the text surface (system_prompt) still folds NFC==NFD
    assert mk(system_prompt=nfc).content_hash() == mk(system_prompt=nfd).content_hash()
