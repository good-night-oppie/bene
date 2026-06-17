from __future__ import annotations

import json

from click.testing import CliRunner

from bene.cli.main import cli
from bene.core import Bene
from bene.memory import MemoryStore
from bene.skills import SkillStore


def test_memory_search_cli_finds_hyphenated_literal(tmp_path) -> None:
    db_path = tmp_path / "bene.db"
    db = Bene(str(db_path))
    agent = db.spawn("writer")
    MemoryStore(db.conn).write(agent, "De-KAOS rewrite complete", key="de-kaos")
    db.close()

    result = CliRunner().invoke(
        cli,
        ["--json", "memory", "search", "de-kaos", "--db", str(db_path)],
    )

    assert result.exit_code == 0, result.output
    hits = json.loads(result.output)
    assert any("De-KAOS" in hit["content"] for hit in hits)


def test_skills_search_cli_finds_hyphenated_literal(tmp_path) -> None:
    db_path = tmp_path / "bene.db"
    db = Bene(str(db_path))
    SkillStore(db.conn).save(
        name="de_kaos_docs",
        description="De-KAOS documentation rewrite workflow",
        template="Apply the De-KAOS rewrite checklist.",
        tags=["de-kaos"],
    )
    db.close()

    result = CliRunner().invoke(
        cli,
        ["--json", "skills", "search", "de-kaos", "--db", str(db_path)],
    )

    assert result.exit_code == 0, result.output
    hits = json.loads(result.output)
    assert any(hit["name"] == "de_kaos_docs" for hit in hits)
