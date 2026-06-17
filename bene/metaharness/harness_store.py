"""HarnessEngine — the bene-owned half of the autogenesis HarnessStore.

The cross-team split (autogenesis-harness-evo INTERFACE): adx CONSUMES (load /
apply / rollback, git-backed, in its own run), bene is the ENGINE (propose /
validate). This module is the engine's clean call surface:

- ``validate(source)`` — AST + smoke gate, the reusable MetaHarnessSearch
  validator. **B1 contract:** across the team boundary the smoke step runs the
  candidate in a SUBPROCESS (timeout, minimal env) so a malformed or hostile
  candidate can never execute top-level code inside the engine that also holds
  the kill-gate keys. Pure: no apply, no run-for-real.
- ``propose`` — reflective LLM mutation. This is genuinely search-integrated
  (archive VFS + a configured proposer model); it is driven through the existing
  ``MetaHarnessSearch`` / ``ProposerAgent`` machinery, not reinvented here. See
  ``bene.metaharness.search``.

Promotion stays gated on a hash-locked held-out probe ACCEPT (C2) — that lives in
the eval/evolve layer, not here.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import dataclass

#: AST + smoke runner executed in a subprocess (never exec'd in-process).
_SMOKE_RUNNER = """
import sys
src = sys.stdin.read()
ns = {}
try:
    exec(compile(src, "<candidate>", "exec"), ns)
except BaseException as e:  # noqa: BLE001 - any import-time failure is a smoke fail
    print("SMOKE_ERR:" + type(e).__name__ + ": " + str(e)[:200])
    sys.exit(2)
fn = ns.get("run")
if not callable(fn):
    print("SMOKE_ERR: run is not callable after import")
    sys.exit(3)
print("SMOKE_OK")
"""


@dataclass
class ValidationResult:
    ok: bool
    ast_ok: bool
    smoke_ok: bool | None  # None = smoke not run
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "ast_ok": self.ast_ok,
            "smoke_ok": self.smoke_ok,
            "error": self.error,
        }


class HarnessEngine:
    """Engine-side propose/validate surface adx drives per generation."""

    def __init__(self, *, smoke_timeout: int = 5) -> None:
        self.smoke_timeout = smoke_timeout

    # ---- validate (the reusable gate; B1-sandboxed) ----

    @staticmethod
    def _ast_check(source: str) -> tuple[bool, str]:
        """Stage 1 — parse only, never execute. Require a run(problem) callable."""
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return False, f"Syntax error: {e}"
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
                if len(node.args.args) + len(node.args.posonlyargs) >= 1:
                    return True, ""
                return False, "run() must accept at least one argument (problem)"
        return False, "No run() function found in harness source"

    def _smoke_subprocess(self, source: str) -> tuple[bool, str]:
        """Stage 2 — import the candidate in an ISOLATED subprocess (B1).

        A hostile/malformed candidate's top-level code runs in a throwaway
        process with a timeout and a minimal env — it cannot touch the engine.
        """
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", _SMOKE_RUNNER],
                input=source,
                text=True,
                capture_output=True,
                timeout=self.smoke_timeout,
                env={"PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired:
            return (
                False,
                f"smoke timed out after {self.smoke_timeout}s (blocking import / infinite loop)",
            )
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and "SMOKE_OK" in out:
            return True, ""
        for line in out.splitlines():
            if line.startswith("SMOKE_ERR:"):
                return False, line[len("SMOKE_ERR:") :].strip()
        return False, (proc.stderr or "").strip()[:200] or f"smoke failed (exit {proc.returncode})"

    def validate(self, source: str, *, smoke: bool = True) -> ValidationResult:
        """AST gate, then (optionally) a sandboxed smoke import. Pure."""
        ast_ok, ast_err = self._ast_check(source)
        if not ast_ok:
            return ValidationResult(ok=False, ast_ok=False, smoke_ok=False, error=ast_err)
        if not smoke:
            return ValidationResult(ok=True, ast_ok=True, smoke_ok=None)
        smoke_ok, smoke_err = self._smoke_subprocess(source)
        return ValidationResult(ok=smoke_ok, ast_ok=True, smoke_ok=smoke_ok, error=smoke_err)

    # ---- propose (pointer to the search-integrated engine) ----

    @staticmethod
    def propose_via_search_note() -> str:
        """``propose`` runs through the existing MetaHarnessSearch machinery
        (archive VFS + a configured proposer model), not a thin per-call shim.
        Drive it with ``MetaHarnessSearch(SearchConfig(...)).run()`` /
        ``ProposerAgent.propose`` — see ``bene.metaharness.search``."""
        return (
            "propose: drive bene.metaharness.search.MetaHarnessSearch(SearchConfig(..., "
            "proposer_model=...)).run(); candidates are validated via HarnessEngine.validate "
            "and promoted only behind a hash-locked held-out probe ACCEPT."
        )
