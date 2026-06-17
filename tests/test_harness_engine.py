"""HarnessEngine — the engine-side validate gate (AST + sandboxed smoke, B1)."""

from __future__ import annotations

from bene.metaharness.harness_store import HarnessEngine

VALID = "def run(problem):\n    return {'answer': problem}\n"


def test_validate_accepts_a_well_formed_harness():
    res = HarnessEngine().validate(VALID)
    assert res.ok and res.ast_ok and res.smoke_ok and res.error == ""


def test_validate_rejects_syntax_error_at_ast_stage():
    res = HarnessEngine().validate("def run(problem:\n  pass")
    assert not res.ok and not res.ast_ok and "Syntax error" in res.error


def test_validate_rejects_missing_run():
    res = HarnessEngine().validate("def helper(x):\n    return x\n")
    assert not res.ok and not res.ast_ok and "No run()" in res.error


def test_validate_rejects_run_without_argument():
    res = HarnessEngine().validate("def run():\n    return 1\n")
    assert not res.ok and not res.ast_ok and "at least one argument" in res.error


def test_validate_ast_only_skips_smoke():
    res = HarnessEngine().validate(VALID, smoke=False)
    assert res.ok and res.ast_ok and res.smoke_ok is None


def test_smoke_runs_in_subprocess_and_catches_import_crash():
    # passes AST (run exists) but blows up at import time -> smoke fail, engine untouched
    src = "raise RuntimeError('boom at import')\ndef run(problem):\n    return problem\n"
    res = HarnessEngine().validate(src)
    assert res.ast_ok and not res.smoke_ok and not res.ok
    assert "RuntimeError" in res.error


def test_smoke_sandbox_times_out_on_blocking_import():
    src = "import time\ntime.sleep(30)\ndef run(problem):\n    return problem\n"
    res = HarnessEngine(smoke_timeout=2).validate(src)
    assert res.ast_ok and not res.smoke_ok and "timed out" in res.error


def test_smoke_isolation_blocks_hostile_toplevel_from_the_engine():
    # the candidate mutates os.environ in its OWN process; the engine's process is
    # unaffected because the smoke runs in a subprocess.
    import os

    os.environ["BENE_SMOKE_SENTINEL"] = "engine"
    src = "import os\nos.environ['BENE_SMOKE_SENTINEL'] = 'hijacked'\ndef run(p):\n    return p\n"
    res = HarnessEngine().validate(src)
    assert res.ok  # imports fine
    assert os.environ["BENE_SMOKE_SENTINEL"] == "engine"  # engine process untouched
    del os.environ["BENE_SMOKE_SENTINEL"]
