"""Reward-hack hook chain — synced across good-night-oppie repos.

Canonical source: agentdex/hooks/_bene_hooks/.
Mirrors: bene/_bene_hooks, helios/_helios_hooks, oppie/_oppie_hooks.

The .claude/hooks/ and .cursor/hooks/ shims in each repo delegate
here. To author new detector logic: PR to agentdex first, then run
agentdex/scripts/sync-hooks.sh to propagate downstream. The package
name (`_<repo>_hooks`) and env var (`<REPO>_HOOKS_BASE_REF`) are
sed-rewritten per target by the sync script.
"""
from __future__ import annotations

__version__ = "0.1.0"
