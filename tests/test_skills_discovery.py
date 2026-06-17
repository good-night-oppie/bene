"""Tests for src-fresh-style SKILL.md discovery (closes #13, partial).

This PR adds skill-discovery only; auto-registration of MCP servers from
bene.yaml is tracked separately as a follow-up (the agent_sdk provider
needs additional plumbing to pass mcp_servers through to ClaudeAgentOptions).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bene.core import Bene
from bene.skills import SkillStore
from bene.skills_discovery import discover_skills


def _write_skill(root: Path, name: str, frontmatter: str, body: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    md = skill_dir / "SKILL.md"
    md.write_text(f"---\n{frontmatter}\n---\n{body}")
    return md


def test_discover_skills_finds_skill_md_files(tmp_path):
    _write_skill(
        tmp_path,
        "debug-test-failure",
        "name: debug-test-failure\ndescription: Disciplined debugging.",
        "# Debugging\n\nUnderstand before fixing.",
    )
    _write_skill(
        tmp_path,
        "triage-ninja",
        "name: triage-ninja\ndescription: Query CI failures.",
        "# Triage Ninja\n\nUse --where rules.",
    )
    skills = discover_skills([tmp_path])
    names = {s["name"] for s in skills}
    assert names == {"debug-test-failure", "triage-ninja"}
    # Body content is preserved as the skill template.
    body = next(s["template"] for s in skills if s["name"] == "debug-test-failure")
    assert "Understand before fixing." in body


def test_discover_skills_ignores_dirs_without_skill_md(tmp_path):
    (tmp_path / "empty-dir").mkdir()
    _write_skill(tmp_path, "real-skill", "name: real-skill\ndescription: A real one.", "body")
    skills = discover_skills([tmp_path])
    assert [s["name"] for s in skills] == ["real-skill"]


def test_discover_skills_multiple_paths(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write_skill(a, "skill-a", "name: skill-a\ndescription: A.", "body-a")
    _write_skill(b, "skill-b", "name: skill-b\ndescription: B.", "body-b")
    skills = discover_skills([a, b])
    assert {s["name"] for s in skills} == {"skill-a", "skill-b"}


def test_skillstore_import_from_paths_inserts_each_skill(tmp_path):
    db_path = tmp_path / "bene.db"
    afs = Bene(db_path=str(db_path))
    store = SkillStore(afs.conn)

    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "debug-test-failure",
        "name: debug-test-failure\ndescription: Disciplined debugging.",
        "Understand before fixing.",
    )

    inserted = store.import_from_paths([skills_root])
    assert inserted == 1

    hits = store.search("debugging")
    assert any(s.name == "debug-test-failure" for s in hits)


def test_skillstore_import_is_idempotent(tmp_path):
    db_path = tmp_path / "bene.db"
    afs = Bene(db_path=str(db_path))
    store = SkillStore(afs.conn)

    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "x-skill",
        "name: x-skill\ndescription: X.",
        "body",
    )

    first = store.import_from_paths([skills_root])
    second = store.import_from_paths([skills_root])
    assert first == 1
    assert second == 0, "second import must skip names that already exist"


def test_discover_skills_skips_non_utf8_files(tmp_path):
    """A SKILL.md with non-UTF-8 bytes must not crash the whole discovery —
    the bad file should be skipped and the others returned."""
    good_dir = tmp_path / "good-skill"
    good_dir.mkdir()
    (good_dir / "SKILL.md").write_text("---\nname: good-skill\ndescription: A good one.\n---\nbody")

    bad_dir = tmp_path / "bad-skill"
    bad_dir.mkdir()
    # Latin-1 byte 0xFF is not valid UTF-8 start.
    (bad_dir / "SKILL.md").write_bytes(b"---\nname: bad\n---\n\xff\xfe\xfdcontent")

    skills = discover_skills([tmp_path])
    names = {s["name"] for s in skills}
    assert "good-skill" in names, f"good skill missing; got {names}"
    # bad skill is acceptable to either skip entirely OR include with
    # replacement chars; the requirement is "no crash".
    assert "good-skill" in names


def test_import_from_paths_survives_single_save_failure(tmp_path):
    """If one skill row fails to insert (e.g. a constraint violation),
    the remaining skills must still be imported. Today a raised exception
    inside the loop drops the batch."""
    db_path = tmp_path / "bene.db"
    afs = Bene(db_path=str(db_path))
    store = SkillStore(afs.conn)

    skills_root = tmp_path / "skills"
    for n in ("alpha", "beta", "gamma"):
        _write_skill(skills_root, n, f"name: {n}\ndescription: D.", "body")

    real_save = store.save
    call_count = {"n": 0}

    def flaky_save(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated DB constraint failure")
        return real_save(*args, **kwargs)

    with patch.object(store, "save", side_effect=flaky_save):
        inserted = store.import_from_paths([skills_root])

    # 3 candidates, 1 raises => 2 succeed.
    assert inserted == 2, f"expected 2 inserts despite 1 failure, got {inserted}"
    names = {s.name for s in store.search("body", limit=10)}
    assert len(names) == 2
