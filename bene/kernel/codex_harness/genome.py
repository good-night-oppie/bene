"""CodexHarness genome — Contract H (typed head) + Contract M (Mutation) for SECH.

See ``tasks/codex-harness-evolution/SPEC.md``. The unit of evolution is the
harness-**AS-CODE** (Autogenesis RSPL: a versioned directory of resources), NOT a
prompt string:

    harness/<id>/
      prompt/system.md          # p — the policy text
      protocols/decide.md       # the turn protocol
      orchestration/agents.yaml # sub-agent wiring
      tools/*.py                # codex tooling exposed at decision time
      modules/*.py              # source modules the policy imports
      manifest.yaml             # architecture: wiring + version + parent

bene operates on the JSON head (``system_prompt`` + ``params`` +
``move_selection_strategy``) extended with a ``harness_ref`` pointer to the resource
dir, plus an in-memory ``resources`` map that stands in for the dir during the
mock-first B1 phase. The authoritative loader/applier live in adx-cli (Contract H)
and adx-core (Contract S); bene only needs the wire + a mutation-application hook so
the MetaHarnessSearch loop (Contract G) can ACT → OBSERVE → PROPOSE → ASSESS → GATE.

bene does NOT mutate the genome randomly: the mutation operator is the **Refiner**
(Contract R, codex-as-coding-agent). ``mock_refiner`` / ``mock_apply`` /
``mock_codex_eval`` here are deterministic stand-ins until adx-core's Refiner + adx's
arena eval land; ``evolve_codex_harness`` takes them as injected callables.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from typing import Any


# Mutation kinds (Contract M). Only "prompt" is a prompt tweak; the SPEC's DONE #2
# requires at least one ACCEPTED **non-prompt** mutation (a real code/tool/arch change).
MUTATION_KINDS = ("prompt", "tool", "module", "protocol", "orchestration", "architecture")
NON_PROMPT_KINDS = tuple(k for k in MUTATION_KINDS if k != "prompt")

# Strategy head — mirrors adx_showdown.harness.KNOWN_STRATEGIES (the typed contract
# head bene shares with adx). Ordered by approximate strength for the mock eval.
_STRATEGIES = [
    "random",
    "max_damage",
    "heuristic",
    "balance",
    "hyper_offense",
    "stall",
    "trick_room",
    "llm_freeform",
]


# ---------------------------------------------------------------------------
# Contract M — a JSON-serializable, applyable patch to a harness resource.


@dataclass
class Mutation:
    """A harness mutation proposed by the Refiner (Contract M)."""

    kind: str  # one of MUTATION_KINDS
    target_path: str  # e.g. "modules/lookahead.py" or "prompt/system.md"
    diff: str  # the patch content (mock phase: full new resource content)
    rationale: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in MUTATION_KINDS:
            raise ValueError(f"unknown mutation kind {self.kind!r}; allowed: {MUTATION_KINDS}")

    @property
    def is_prompt(self) -> bool:
        return self.kind == "prompt"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Contract H (head) — the bene-side wire for a harness-as-code genome.


@dataclass
class CodexHarness:
    """The typed head + resource map bene evolves (Contract H, bene wire form)."""

    harness_id: str
    system_prompt: str
    move_selection_strategy: str
    params: dict[str, Any] = field(default_factory=dict)
    harness_ref: str | None = None  # pointer to the on-disk resource dir (None = prompt-only/mock)
    resources: dict[str, str] = field(default_factory=dict)  # mock-phase {rel_path: content}
    parent_ids: list[str] = field(default_factory=list)
    generation: int = 0
    manifest: dict[str, Any] = field(default_factory=dict)

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CodexHarness:
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> CodexHarness:
        return cls.from_dict(json.loads(s))

    @classmethod
    def from_adx_dict(cls, d: dict) -> CodexHarness:
        """Adapt an ``adx_showdown.harness.BattleHarness`` dict / .model_dump().

        A prompt-only BattleHarness is a valid CodexHarness (SPEC back-compat). The
        ``harness_ref`` (if present) points at the resource dir for code resources.

        Invariant (PR #64 review): on the real ADX path a ``harness_ref`` must come with
        its loaded ``resources`` map — a harness that points at an on-disk resource dir
        but carries no resources would content-address by head alone, so distinct dirs
        could collide in the DGM archive. Reject it here rather than silently mis-hash.
        """
        harness_ref = d.get("harness_ref")
        resources = dict(d.get("resources") or {})
        if harness_ref and not resources:
            raise ValueError(
                f"harness {d.get('harness_id')!r}: harness_ref={harness_ref!r} is set but "
                "resources is empty — load the resource map before constructing the genome "
                "(else distinct on-disk harness dirs collide on content_hash)"
            )
        return cls(
            harness_id=d["harness_id"],
            system_prompt=d.get("system_prompt", ""),
            move_selection_strategy=d.get("move_selection_strategy", "max_damage"),
            params=dict(d.get("params") or {}),
            harness_ref=harness_ref,
            resources=resources,
            manifest=dict(d.get("manifest") or {}),
        )

    def content_hash(self) -> str:
        """Content address over the evolvable surface (prompt + params + resources +
        strategy + harness_ref) — identity for the DGM archive + lineage. Excludes
        ``harness_id`` so a rename alone never changes the hash.

        ``harness_ref`` (the pointer to the on-disk resource dir) is folded in so two
        genomes with identical heads but DIFFERENT on-disk resource trees — the common
        case once a real Contract-S apply materialises code on disk and leaves the
        in-memory ``resources`` map empty — never collide in the DGM archive. (PR #64 review)
        """
        payload = json.dumps(
            {
                "system_prompt": self.system_prompt,
                "move_selection_strategy": self.move_selection_strategy,
                "params": self.params,
                "resources": self.resources,
                "harness_ref": self.harness_ref,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    # -- mutation application (mock ASSESS; real one is adx-core Contract S) --
    def with_mutation(self, mutation: Mutation) -> CodexHarness:
        """Return a child genome with *mutation* applied to its resources.

        This is the in-memory mock of Contract S's apply step. The real sandbox
        apply+build+validate lives in adx-core; ``mock_apply`` wraps this with a
        build-validity check so an unbuildable mutation is rejected (rollback).
        """
        new_resources = dict(self.resources)
        new_params = dict(self.params)
        if mutation.is_prompt:
            new_prompt = mutation.diff
        else:
            new_prompt = self.system_prompt
            new_resources[mutation.target_path] = mutation.diff
        # The mock "strength" the eval reads accumulates the delta a real arena run
        # would realise from this code/tool/arch change.
        delta = float(mutation.provenance.get("strength_delta", 0.0))
        new_params["_mock_strength"] = float(new_params.get("_mock_strength", 0.0)) + delta
        child = CodexHarness(
            harness_id="",  # filled deterministically below
            system_prompt=new_prompt,
            move_selection_strategy=self.move_selection_strategy,
            params=new_params,
            harness_ref=self.harness_ref,
            resources=new_resources,
            parent_ids=[self.harness_id],
            generation=self.generation + 1,
            manifest={**self.manifest, "parent": self.harness_id},
        )
        # Deterministic child id, NOT a fresh time/random ULID. The mock eval seeds its RNG
        # off harness_id (mock_codex_eval), and the kill-gate/promotion consume that win_rate,
        # so a nondeterministic id would make the same parent+mutation+run yield a different
        # gate outcome across replays. Address the child by its own content hash so a given
        # (parent, mutation, run_seed) is reproducible. (PR #64 review)
        child.harness_id = f"{self.harness_id}-g{child.generation}-{child.content_hash()[:12]}"
        return child


# ---------------------------------------------------------------------------
# Contract-3 arena fitness vector (reused shape: 5 dims + anti-vacuous counters).


@dataclass
class CodexFitness:
    """Multi-dim arena fitness for a codex harness (Contract E output head)."""

    win_rate: float
    elo: float
    move_legibility: float
    no_forfeit_exploit: float
    turn_efficiency: float
    battles_played: int = 0
    gens_completed: int = 0

    def to_scores(self) -> dict[str, float]:
        return {
            "win_rate": self.win_rate,
            "elo": self.elo,
            "move_legibility": self.move_legibility,
            "no_forfeit_exploit": self.no_forfeit_exploit,
            "turn_efficiency": self.turn_efficiency,
            "battles_played": float(self.battles_played),
            "gens_completed": float(self.gens_completed),
        }

    def replace(self, **kwargs: Any) -> CodexFitness:
        d = asdict(self)
        d.update(kwargs)
        return CodexFitness(**d)


CONTRACT3_OBJECTIVES: dict[str, str] = {
    "win_rate": "maximize",
    "elo": "maximize",
    "move_legibility": "maximize",
    "no_forfeit_exploit": "maximize",
    "turn_efficiency": "maximize",
}


@dataclass
class CodexEvalResult:
    """Contract E result: fitness + trajectory + failure signatures (ACT/OBSERVE).

    ``training_tuples`` are the ``(task_id, seed, scenario_id)`` tuples this evaluation
    tuned on — bene unions them into the run's training_manifest for the held-out
    disjointness gate (``heldout ∩ training = ∅``; see ``codex_harness/heldout.py``).
    """

    fitness: CodexFitness
    trajectory: dict[str, Any] = field(default_factory=dict)
    failure_signatures: list[str] = field(default_factory=list)
    training_tuples: list[list] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Seed harness (H0).


def seed_codex_harness() -> CodexHarness:
    """The seed harness H0 — a reasonable, non-degenerate prompt-only-ish policy plus
    a couple of seed modules the Refiner can improve. The evolved harness must beat
    THIS on held-out (the kill gate) for a run to count."""
    return CodexHarness(
        harness_id="H0-seed",
        system_prompt=(
            "You are a competitive battler. Each turn pick the move or switch that "
            "maximizes win probability: favor high-damage and super-effective moves, "
            "switch away from a losing matchup, never pick an illegal move, never forfeit."
        ),
        move_selection_strategy="max_damage",
        params={"aggression": 1.0, "switch_threshold_hp": 0.25, "risk_tolerance": 0.5},
        harness_ref=None,
        resources={
            "modules/legality.py": "def legal_moves(state):\n    return state.legal_moves\n",
            "modules/lookahead.py": "def best_move(state, depth=1):\n    return max(state.legal_moves, key=lambda m: m.power)\n",
            "protocols/decide.md": "# observe -> plan -> act\nPick the legal move with the highest expected value.\n",
            "manifest.yaml": "version: 0\nmodules: [legality, lookahead]\n",
        },
        generation=0,
        manifest={"version": 0, "modules": ["legality", "lookahead"]},
    )


# ---------------------------------------------------------------------------
# Mock Refiner / apply / eval — deterministic stand-ins for B1 (mock-first).
# Injected into evolve_codex_harness; replaced by adx-core Contract R + adx Contract E.

# Per-signature mutation templates. Helpful (non-prompt) mutations carry a positive
# strength_delta; a deliberately broken one is emitted so rollback is exercised.
_SIG_TO_MUTATION: dict[str, dict[str, Any]] = {
    "loss_vs_baseline": {
        "kind": "module",
        "target_path": "modules/lookahead.py",
        "body": "def best_move(state, depth=2):\n    return _minimax(state, depth)\n",
        "delta": 0.06,
        "rationale": "deepen lookahead 1->2 to stop losing close games",
    },
    "illegal_move": {
        "kind": "module",
        "target_path": "modules/legality.py",
        "body": "def legal_moves(state):\n    return [m for m in state.legal_moves if m.is_valid]\n",
        "delta": 0.05,
        "rationale": "filter illegal moves at the source",
    },
    "stall": {
        "kind": "tool",
        "target_path": "tools/turn_budget.py",
        "body": "def turn_budget(state):\n    return max(1, 20 - state.turn)\n",
        "delta": 0.04,
        "rationale": "add a turn-budget tool to break stalls",
    },
    "forfeit_exploit": {
        "kind": "protocol",
        "target_path": "protocols/decide.md",
        "body": "# observe -> plan -> act\nNever forfeit; prefer a switch over a forfeit.\n",
        "delta": 0.03,
        "rationale": "protocol: forbid forfeit, prefer switch",
    },
}

_STRATEGY_BASE = {
    "random": 0.35,
    "max_damage": 0.46,
    "heuristic": 0.52,
    "balance": 0.55,
    "hyper_offense": 0.57,
    "stall": 0.56,
    "trick_room": 0.53,
    "llm_freeform": 0.62,
}


def mock_refiner(
    harness: CodexHarness,
    trajectory: dict[str, Any],
    failure_signatures: list[str],
    rng: random.Random | None = None,
) -> list[Mutation]:
    """Deterministic mock of the Refiner (Contract R).

    Reads the failure signatures and proposes harness mutations. Always proposes at
    least one **non-prompt** mutation when there is a failure to fix (so SPEC DONE #2
    is reachable), plus one deliberately-unbuildable mutation so the ASSESS/rollback
    path is exercised. With no failures it falls back to a small prompt refinement.
    """
    rng = rng or random.Random(0)
    mutations: list[Mutation] = []
    for sig in failure_signatures:
        tpl = _SIG_TO_MUTATION.get(sig)
        if not tpl:
            continue
        mutations.append(
            Mutation(
                kind=tpl["kind"],
                target_path=tpl["target_path"],
                diff=tpl["body"],
                rationale=tpl["rationale"],
                provenance={
                    "refiner": "mock_refiner",
                    "addresses": sig,
                    "strength_delta": tpl["delta"],
                    "parent": harness.harness_id,
                },
            )
        )
    if not mutations:
        # No failure to fix — propose a tiny prompt refinement (low strength).
        mutations.append(
            Mutation(
                kind="prompt",
                target_path="prompt/system.md",
                diff=harness.system_prompt + "\nPrefer moves with the best expected value.",
                rationale="prompt: nudge toward expected-value play",
                provenance={
                    "refiner": "mock_refiner",
                    "strength_delta": 0.005,
                    "parent": harness.harness_id,
                },
            )
        )
    else:
        # Emit one deliberately-broken mutation so apply/validate rejects it (rollback).
        mutations.append(
            Mutation(
                kind="module",
                target_path="modules/experimental.py",
                diff="def best_move(state):\n    return  # SYNTAX_ERROR: missing value\n",
                rationale="risky refactor (unbuildable on purpose — must be rolled back)",
                provenance={
                    "refiner": "mock_refiner",
                    "strength_delta": 0.20,
                    "parent": harness.harness_id,
                    "unbuildable": True,
                },
            )
        )
    return mutations


def mock_apply(harness: CodexHarness, mutation: Mutation) -> CodexHarness | None:
    """Mock of Contract S (sandbox apply + build/validate).

    Returns the child harness H' on success, or ``None`` to REJECT an unbuildable
    mutation (the rollback path). The build check here is a sentinel scan; the real
    one cargo/pytest-builds the mutated resource dir in an isolated worktree.
    """
    if "SYNTAX_ERROR" in mutation.diff or mutation.provenance.get("unbuildable"):
        return None  # unbuildable -> rejected, never evaluated (safety rail)
    return harness.with_mutation(mutation)


def mock_codex_eval(
    harness: CodexHarness, run_seed: int = 0, n_battles: int = 30
) -> CodexEvalResult:
    """Deterministic mock of Contract E (arena eval).

    Win-rate scales with the genome's strategy tier + aggression + the accumulated
    ``_mock_strength`` from applied code/tool mutations. Emits failure signatures for
    the weak dimensions so the Refiner has something to fix. ``battles_played`` is
    never zero (anti-vacuous); ``gens_completed`` is stamped by the evolver.
    """
    hid_int = int(hashlib.sha256(harness.harness_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(run_seed ^ hid_int)

    base = _STRATEGY_BASE.get(harness.move_selection_strategy, 0.50)
    aggression = float(harness.params.get("aggression", 1.0))
    base += 0.08 * (1.0 - abs(aggression - 0.65) / 0.65)
    base += float(harness.params.get("_mock_strength", 0.0))
    win_rate = min(1.0, max(0.0, base + rng.gauss(0.0, 0.01)))

    elo = 1000.0 + (win_rate - 0.5) * 800.0
    risk = float(harness.params.get("risk_tolerance", 0.5))
    no_forfeit = min(1.0, max(0.0, 0.82 + risk * 0.20 + rng.gauss(0.0, 0.01)))
    legibility = min(
        1.0,
        max(0.0, 0.60 + float(harness.params.get("_mock_strength", 0.0)) + rng.gauss(0.0, 0.01)),
    )
    turn_eff = min(
        1.0,
        max(
            0.05,
            0.70 + float(harness.params.get("_mock_strength", 0.0)) * 0.5 + rng.gauss(0.0, 0.01),
        ),
    )

    sigs: list[str] = []
    if win_rate < 0.55:
        sigs.append("loss_vs_baseline")
    if legibility < 0.70:
        sigs.append("illegal_move")
    if turn_eff < 0.80:
        sigs.append("stall")
    if no_forfeit < 0.88:
        sigs.append("forfeit_exploit")

    # The TRAINING tuples this eval tuned on (CRN windows). Keyed off run_seed so a
    # held-out manifest built from disjoint scenario ids stays disjoint; a test that
    # passes a held-out manifest overlapping these exercises the VOID path.
    training_tuples = [["train", int(run_seed), f"scenario{i}"] for i in range(3)]

    return CodexEvalResult(
        fitness=CodexFitness(
            win_rate=win_rate,
            elo=elo,
            move_legibility=legibility,
            no_forfeit_exploit=no_forfeit,
            turn_efficiency=turn_eff,
            battles_played=n_battles,
            gens_completed=0,
        ),
        trajectory={"harness_id": harness.harness_id, "run_seed": run_seed, "n_battles": n_battles},
        failure_signatures=sigs,
        training_tuples=training_tuples,
    )
