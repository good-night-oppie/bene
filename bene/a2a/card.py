"""The bene Agent Card — the A2A discovery document served at
``/.well-known/agent-card.json``.

Skills advertise what a peer agent can actually drive over A2A: SharedLog
coordination, and the engine side of the autogenesis HarnessStore
(``harness.propose`` / ``harness.validate``, kill-gate stays probe-ACCEPT gated).
"""

from __future__ import annotations

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from bene import __version__

DEFAULT_URL = "http://127.0.0.1:8710/"


def build_bene_agent_card(url: str = DEFAULT_URL, version: str | None = None) -> AgentCard:
    """Build bene's A2A Agent Card. ``url`` is the public JSON-RPC endpoint.

    ``version`` defaults to the installed bene version (single source of truth);
    note ``protocol_version`` below is the A2A spec version, not bene's.
    """
    if version is None:
        version = __version__
    skills = [
        AgentSkill(
            id="coordinate",
            name="Cross-agent coordination",
            description=(
                "SharedLog-backed coordination over A2A: intent / proposal / vote / "
                "decide / mail. Durable + auditable in bene's SQLite. Set part kind "
                'via message metadata {"kind": "intent|vote|decide|proposal|mail"}.'
            ),
            tags=["coordination", "shared-log", "a2a"],
            examples=[
                "send an intent: prune stale checkpoints",
                "cast a vote on intent 12",
                "mail bene a proposal",
            ],
        ),
        AgentSkill(
            id="harness.propose",
            name="Propose a harness mutation",
            description=(
                "Engine side of the autogenesis HarnessStore. Reflective LLM mutation of a "
                "harness control-flow program, driven through a MetaHarnessSearch run "
                "(archive VFS + a configured proposer model) — over A2A this returns the "
                "drive pointer; the live synchronous engine op is harness.validate."
            ),
            tags=["evolution", "metaharness", "autogenesis"],
            examples=["propose a mutation of this harness source"],
        ),
        AgentSkill(
            id="harness.validate",
            name="Validate a harness candidate",
            description=(
                "AST + smoke validation of a candidate harness program "
                "(HarnessCandidate.validate_interface). Promotion stays gated on a "
                "hash-locked held-out probe ACCEPT."
            ),
            tags=["evolution", "validation", "kill-gate"],
            examples=["validate this harness source"],
        ),
    ]
    return AgentCard(
        name="bene",
        description=(
            "BENE — engine/substrate. SharedLog coordination + kill-gated harness "
            "evolution (MetaHarnessSearch). A2A endpoint seated on bene's SQLite."
        ),
        url=url,
        version=version,
        protocol_version="0.3.0",
        preferred_transport="JSONRPC",
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["text/plain", "application/json"],
        skills=skills,
    )
