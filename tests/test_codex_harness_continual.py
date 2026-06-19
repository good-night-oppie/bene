"""SECH B3 (bene-core) — in-episode continual hot-swap tests (Continual-Harness pillar).

Covers the falsifiable-DONE surface for ``ContinualCodexMutator`` + ``run_continual_episode``:
  SWAP    a failing seed is hot-swapped to a Refiner-proposed NON-PROMPT fix behind the gate
  BEATS   the continually-adapted episode beats the static seed (continual_uplift_vs_static>0)
  GATE    a built child that gains < CONTINUAL_MIN_UPLIFT is REJECTED (incumbent holds)
  SAFE    an unbuildable proposal is rolled back, never swapped to
  BOUND   per-episode swap budget + cooldown cap thrash
  FALSIFY an identity (no-op) swap shows 0 uplift -> the gate kills it (admissible probe)
  VOID    an empty replay window is inadmissible (VOID), never a silent pass
  TAMPER  editing the locked gate spec makes the probe refuse to run (LockTamperError)
  L3      the swap respects the autonomy-L3 capability gate

All tests use the mock Refiner/apply/eval (no codex run, no arena server).
"""

from __future__ import annotations

import pytest

from bene.kernel.codex_harness import (
    ACCEPTED_SWAPPED,
    CONTINUAL_MIN_UPLIFT,
    CONTINUAL_PROBE_NAME,
    REJECTED,
    SKIPPED,
    ContinualCodexMutator,
    ContinualEpisodeOutput,
    Mutation,
    build_continual_killgate,
    mock_codex_eval,
    mock_refiner,
    mock_replay_eval,
    open_eval_db,
    run_continual_episode,
    seed_codex_harness,
)
from bene.kernel.codex_harness.continual import VOIDED, CODEX_IN_EPISODE_SWAP
from bene.kernel.codex_harness.killgate import CONTINUAL_GATES
from bene.kernel.eval.gates import lock_hash


# ---------------------------------------------------------------------------
# helpers — scenario-specific Refiners (deterministic)


def _mut(
    kind="module",
    path="modules/lookahead.py",
    delta=0.06,
    body="def best_move(state, depth=2):\n    return _minimax(state, depth)\n",
    **prov,
):
    return Mutation(
        kind=kind, target_path=path, diff=body, provenance={"strength_delta": delta, **prov}
    )


def strong_refiner(harness, trajectory, sigs):
    """One genuine +6pp non-prompt fix — clears the +5pp continual bar."""
    return [_mut(delta=0.06)]


def weak_refiner(harness, trajectory, sigs):
    """A buildable but weak +4pp fix — does NOT clear the +5pp bar -> REJECT."""
    return [
        _mut(
            kind="tool",
            path="tools/turn_budget.py",
            delta=0.04,
            body="def turn_budget(state):\n    return 5\n",
        )
    ]


def identity_refiner(harness, trajectory, sigs):
    """A no-op (+0pp) non-prompt change — 0 uplift -> the gate must kill it."""
    return [
        _mut(
            kind="protocol",
            path="protocols/decide.md",
            delta=0.0,
            body="# observe -> plan -> act\n",
        )
    ]


def unbuildable_only_refiner(harness, trajectory, sigs):
    """Only an unbuildable proposal — must be rolled back, never swapped to."""
    return [
        _mut(
            kind="module",
            path="modules/experimental.py",
            delta=0.5,
            body="def best_move(state):\n    return  # SYNTAX_ERROR\n",
            unbuildable=True,
        )
    ]


class _DenyAutonomy:
    def check(self, agent_id, capability):
        return False


class _AllowAutonomy:
    def __init__(self):
        self.calls = []

    def check(self, agent_id, capability):
        self.calls.append((agent_id, capability))
        return True


# ---------------------------------------------------------------------------
# SWAP / BEATS — the driver happy path


def test_continual_basic_shape():
    out = run_continual_episode(
        seed_codex_harness(),
        mock_refiner,
        mock_replay_eval,
        run_seed=7,
        bus_path=False,
    )
    assert isinstance(out, ContinualEpisodeOutput)
    assert out.n_swaps >= 1
    assert out.decisions  # at least one swap attempt was made
    assert out.final_harness.harness_id == (out.swaps[-1]["to_harness_id"])


def test_continual_beats_static():
    out = run_continual_episode(
        seed_codex_harness(),
        mock_refiner,
        mock_replay_eval,
        run_seed=7,
        bus_path=False,
    )
    assert out.static_win_rate == pytest.approx(0.50, abs=1e-9)
    assert out.final_win_rate > out.static_win_rate
    assert out.continual_uplift_vs_static > 0


def test_accepted_swaps_clear_the_gate():
    """The ENFORCED invariant: every landed swap is gate-verified — verdict ACCEPT and
    uplift >= the continual bar. maybe_swap guarantees these for every swap it commits."""
    out = run_continual_episode(
        seed_codex_harness(),
        mock_refiner,
        mock_replay_eval,
        run_seed=3,
        bus_path=False,
    )
    assert out.swaps  # at least one landed
    assert all(s["verdict"] == "ACCEPT" for s in out.swaps)
    assert all(s["uplift"] >= CONTINUAL_MIN_UPLIFT for s in out.swaps)


def test_mock_refiner_lands_nonprompt_fixes():
    """With mock_refiner (and the real Contract-R Refiner) the accepted swaps are
    code/tool/protocol fixes, not prompt tweaks. NOTE this is a property of the *Refiner*,
    NOT a guard in maybe_swap — a prompt-only mutation that cleared the gate would also be
    allowed to land (in-episode prompt swaps are legitimate). Pinning the mock's behaviour."""
    out = run_continual_episode(
        seed_codex_harness(),
        mock_refiner,
        mock_replay_eval,
        run_seed=3,
        bus_path=False,
    )
    assert out.swaps
    assert all(s["mutation_kind"] != "prompt" for s in out.swaps)


def test_swap_audit_genealogy_and_active_pointer():
    out = run_continual_episode(
        seed_codex_harness(),
        strong_refiner,
        mock_replay_eval,
        run_seed=1,
        bus_path=False,
    )
    # The first swap forks off the seed; each subsequent swap forks off the prior child.
    assert out.swaps[0]["from_harness_id"] == "H0-seed"
    for prev, nxt in zip(out.swaps, out.swaps[1:]):
        assert nxt["from_harness_id"] == prev["to_harness_id"]


# ---------------------------------------------------------------------------
# GATE — a built child that does not clear the bar is REJECTED (incumbent holds)


def test_gate_rejects_insufficient_uplift_via_driver():
    out = run_continual_episode(
        seed_codex_harness(),
        weak_refiner,
        mock_replay_eval,
        run_seed=5,
        bus_path=False,
    )
    assert out.n_swaps == 0  # +4pp never clears the +5pp gate
    assert out.final_harness.harness_id == "H0-seed"  # incumbent held
    assert any(d.status == REJECTED for d in out.decisions)
    assert out.continual_uplift_vs_static == pytest.approx(0.0, abs=1e-9)


def test_gate_rejects_insufficient_uplift_direct():
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store, conn, refine_fn=weak_refiner, replay_eval_fn=mock_replay_eval
    )
    d = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert d.status == REJECTED
    assert d.verdict == "REJECT"
    assert not d.swapped
    assert mut.swap_history("ep") == []


# ---------------------------------------------------------------------------
# FALSIFY — an identity (no-op) swap shows zero uplift; the gate kills it.


def test_identity_swap_is_rejected_falsifiable():
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store, conn, refine_fn=identity_refiner, replay_eval_fn=mock_replay_eval
    )
    d = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert d.status == REJECTED
    assert d.uplift == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# SAFE — an unbuildable proposal is rolled back, never swapped to.


def test_unbuildable_proposal_rolled_back():
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store, conn, refine_fn=unbuildable_only_refiner, replay_eval_fn=mock_replay_eval
    )
    d = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert d.status == SKIPPED
    assert "no buildable candidate" in d.reason
    assert d.rollbacks >= 1
    assert mut.swap_history("ep") == []


# ---------------------------------------------------------------------------
# BOUND — budget + cooldown cap thrash


def test_budget_caps_swaps():
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store,
        conn,
        refine_fn=strong_refiner,
        replay_eval_fn=mock_replay_eval,
        max_swaps_per_episode=1,
        min_turns_between_swaps=0,
    )
    h = seed_codex_harness()
    d1 = mut.maybe_swap("ep", h, {"reason": "t"}, turn=0)
    assert d1.status == ACCEPTED_SWAPPED
    d2 = mut.maybe_swap("ep", d1.new_harness, {"reason": "t"}, turn=1)
    assert d2.status == SKIPPED
    assert "max_swaps_per_episode" in d2.reason
    assert len(mut.swap_history("ep")) == 1


def test_cooldown_blocks_rapid_swaps():
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store,
        conn,
        refine_fn=strong_refiner,
        replay_eval_fn=mock_replay_eval,
        max_swaps_per_episode=9,
        min_turns_between_swaps=50,
    )
    h = seed_codex_harness()
    d1 = mut.maybe_swap("ep", h, {"reason": "t"}, turn=0)
    assert d1.status == ACCEPTED_SWAPPED
    d2 = mut.maybe_swap("ep", d1.new_harness, {"reason": "t"}, turn=10)  # only 10 < 50
    assert d2.status == SKIPPED
    assert "min_turns_between_swaps" in d2.reason
    d3 = mut.maybe_swap("ep", d1.new_harness, {"reason": "t"}, turn=60)  # 60 >= 50
    assert d3.status == ACCEPTED_SWAPPED


# ---------------------------------------------------------------------------
# VOID — an empty replay window is inadmissible, never a silent pass.


def test_empty_replay_window_voids():
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store, conn, refine_fn=strong_refiner, replay_eval_fn=mock_replay_eval
    )
    d = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t", "replay_window": 0}, turn=0)
    assert d.status == VOIDED
    assert d.reason == "empty_replay_window"


# ---------------------------------------------------------------------------
# L3 — autonomy gate denies the swap even on an ACCEPT verdict.


def test_autonomy_l3_denied_skips_swap():
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store,
        conn,
        refine_fn=strong_refiner,
        replay_eval_fn=mock_replay_eval,
        autonomy=_DenyAutonomy(),
    )
    d = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert d.status == SKIPPED
    assert "autonomy denied" in d.reason
    assert d.verdict == "ACCEPT"  # gate passed; autonomy is the blocker
    assert mut.swap_history("ep") == []


def test_capability_is_l3():
    assert CODEX_IN_EPISODE_SWAP.autonomy_level == 3


# ---------------------------------------------------------------------------
# TAMPER — the continual gate is hash-locked; editing it makes run() refuse.


def test_continual_killgate_lock_is_stable():
    expected = lock_hash(CONTINUAL_GATES)
    assert lock_hash(CONTINUAL_GATES) == expected
    assert len(expected) == 64


def test_continual_killgate_tamper_raises(tmp_path):
    from bene.kernel.eval.probe import LockTamperError

    store, conn = open_eval_db(str(tmp_path / "k.db"))
    probe = build_continual_killgate()
    baseline = mock_replay_eval(seed_codex_harness()).fitness
    probe.register(store, conn, baseline=baseline)
    conn.execute(
        "UPDATE probe_registry SET gate_spec = ? WHERE name = ?", ("[]", CONTINUAL_PROBE_NAME)
    )
    conn.commit()
    with pytest.raises(LockTamperError):
        probe.run(subject=baseline, baseline=baseline, store=store, conn=conn)


# ---------------------------------------------------------------------------
# SAFE — rollback rail under the realistic (mixed) and raising apply paths.


def test_mixed_buildable_and_unbuildable_rolls_back_only_unbuildable():
    """mock_refiner (and the real Refiner) emit buildable fixes PLUS a deliberately
    unbuildable mutation — the dangerous MIXED case, not just all-unbuildable. The
    unbuildable proposal is rolled back while the best buildable fix is selected + lands."""
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store, conn, refine_fn=mock_refiner, replay_eval_fn=mock_replay_eval
    )
    d = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert d.status == ACCEPTED_SWAPPED
    assert d.rollbacks >= 1  # the unbuildable proposal was rolled back
    assert d.mutation_kind != "prompt"  # the buildable fix that landed
    assert len(mut.swap_history("ep")) == 1


def test_apply_fn_raises_is_rolled_back():
    """A Contract-S apply that RAISES (not just returns None) is a rollback, never a crash
    out of maybe_swap (mirrors B1's apply_fn-raises test)."""

    def raising_apply(harness, mutation):
        raise RuntimeError("sandbox build blew up")

    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store,
        conn,
        refine_fn=strong_refiner,
        replay_eval_fn=mock_replay_eval,
        apply_fn=raising_apply,
    )
    d = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert d.status == SKIPPED
    assert "no buildable candidate" in d.reason
    assert d.rollbacks >= 1
    assert mut.swap_history("ep") == []


# ---------------------------------------------------------------------------
# L3 ALLOW + cooldown boundary + multi-episode isolation


def test_autonomy_l3_allow_lands_swap():
    """The ALLOW path: autonomy.check -> True lets the gate-passed swap land, and check is
    called with (agent_id, the L3 capability)."""
    store, conn = open_eval_db()
    autono = _AllowAutonomy()
    mut = ContinualCodexMutator(
        store,
        conn,
        refine_fn=strong_refiner,
        replay_eval_fn=mock_replay_eval,
        autonomy=autono,
        agent_id="agentX",
    )
    d = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert d.status == ACCEPTED_SWAPPED
    assert len(mut.swap_history("ep")) == 1
    assert autono.calls and autono.calls[0][0] == "agentX"
    assert autono.calls[0][1] is CODEX_IN_EPISODE_SWAP


def test_cooldown_boundary_turn_equals_min_allows():
    """turn - last_turn == min_turns satisfies the `< min` guard (inclusive-allow at the
    boundary) — guards against a < vs <= off-by-one."""
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store,
        conn,
        refine_fn=strong_refiner,
        replay_eval_fn=mock_replay_eval,
        max_swaps_per_episode=9,
        min_turns_between_swaps=50,
    )
    d1 = mut.maybe_swap("ep", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert d1.status == ACCEPTED_SWAPPED
    d2 = mut.maybe_swap("ep", d1.new_harness, {"reason": "t"}, turn=50)  # exactly == min
    assert d2.status == ACCEPTED_SWAPPED
    d3 = mut.maybe_swap("ep", d2.new_harness, {"reason": "t"}, turn=99)  # 49 < 50 -> blocked
    assert d3.status == SKIPPED
    assert "min_turns_between_swaps" in d3.reason


def test_multi_episode_isolation_one_mutator():
    """budget/cooldown/history are keyed by episode_id: two episodes on ONE mutator (one
    shared conn — the persistent path) each reach their own budget independently, and the
    probe registration is reused (no UNIQUE-constraint crash on the 2nd episode)."""
    store, conn = open_eval_db()
    mut = ContinualCodexMutator(
        store,
        conn,
        refine_fn=strong_refiner,
        replay_eval_fn=mock_replay_eval,
        max_swaps_per_episode=1,
        min_turns_between_swaps=0,
    )
    a1 = mut.maybe_swap("epA", seed_codex_harness(), {"reason": "t"}, turn=0)
    assert a1.status == ACCEPTED_SWAPPED
    a2 = mut.maybe_swap("epA", a1.new_harness, {"reason": "t"}, turn=1)
    assert a2.status == SKIPPED and "max_swaps_per_episode" in a2.reason
    b1 = mut.maybe_swap("epB", seed_codex_harness(), {"reason": "t"}, turn=0)  # fresh budget
    assert b1.status == ACCEPTED_SWAPPED
    assert len(mut.swap_history("epA")) == 1
    assert len(mut.swap_history("epB")) == 1
    assert mut.active_harness_id("epA") != mut.active_harness_id("epB")


# ---------------------------------------------------------------------------
# PERSIST — the db_path multi-episode path (regression for the probe-reregister crash).


def test_persistent_db_two_episodes(tmp_path):
    """run_continual_episode twice against the same db_path both succeed — registration is
    idempotent (regression for the UNIQUE-constraint-on-probe_registry.name crash)."""
    db = str(tmp_path / "bene.db")
    o1 = run_continual_episode(
        seed_codex_harness(), mock_refiner, mock_replay_eval, run_seed=7, db_path=db, bus_path=False
    )
    o2 = run_continual_episode(
        seed_codex_harness(), mock_refiner, mock_replay_eval, run_seed=7, db_path=db, bus_path=False
    )
    assert o1.n_swaps >= 1 and o2.n_swaps >= 1


# ---------------------------------------------------------------------------
# INTEGRATION — the loop also drives with the noisy B1 arena eval (mock_codex_eval).


def test_continual_robust_under_noisy_eval():
    """Integration with the noisy B1 arena eval (mock_codex_eval). The mock's per-eval RNG
    is keyed off the random harness_id, so n_swaps is NOT reproducible run-to-run — but the
    ROBUST invariant holds every time: any landed swap cleared +5pp (which dominates the
    +-0.01 eval noise), so continual is never worse than static, and the audit is internally
    consistent (n_swaps == #ACCEPTED decisions == #rows, every landed swap has a swap_id)."""
    out = run_continual_episode(
        seed_codex_harness(),
        mock_refiner,
        mock_codex_eval,
        run_seed=13,
        bus_path=False,
    )
    assert isinstance(out, ContinualEpisodeOutput)
    assert out.continual_uplift_vs_static >= -1e-9
    accepted = [d for d in out.decisions if d.status == ACCEPTED_SWAPPED]
    assert out.n_swaps == len(accepted) == len(out.swaps)
    assert all(d.swap_id for d in accepted)
