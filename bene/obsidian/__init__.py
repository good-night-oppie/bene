"""Obsidian vault exporter — render a BENE database as a wikilinked markdown vault.

Usage (Python)::

    from bene.obsidian import VaultExporter
    VaultExporter("project.db", "~/vaults/bene-eng").export_all()

Usage (CLI)::

    bene obsidian export --vault ~/vaults/bene-eng --db project.db

The exporter is one-way and re-runnable: running it again against the same
vault refreshes the notes without disturbing Obsidian's own state (.obsidian/
cache, workspace layout). Pass --clean to wipe the vault before export.
"""

from bene.obsidian.exporter import VaultExporter

__all__ = ["VaultExporter"]
