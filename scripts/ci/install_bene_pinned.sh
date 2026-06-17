#!/usr/bin/env bash
# Install a pinned bene into a CI-isolated venv at $BENE_VENV (default: $RUNNER_TEMP/bene-pin).
# Source: .github/bene/pin.env (BENE_VERSION).
#
# Why a separate venv: keeps the CI tooling (regression gate, swarms)
# import-isolated from the bene source under review. The PR may break bene;
# the gate must not.
#
# Why a PyPI version (not a git SHA): main is squashed to one root commit
# before each release, which dangles any SHA pin. An immutable PyPI version
# (bene is published to PyPI) survives the rewrite.
set -euo pipefail

PIN_FILE="${PIN_FILE:-.github/bene/pin.env}"
[ -f "$PIN_FILE" ] || { echo "missing $PIN_FILE" >&2; exit 2; }
# shellcheck disable=SC1090
. "$PIN_FILE"
: "${BENE_VERSION:?BENE_VERSION must be set in $PIN_FILE}"

BENE_VENV="${BENE_VENV:-${RUNNER_TEMP:-/tmp}/bene-pin}"

uv venv "$BENE_VENV" --quiet
uv pip install --python "$BENE_VENV/bin/python" --quiet \
  "bene==${BENE_VERSION}"

echo "bene pinned to ${BENE_VERSION} (PyPI)"
echo "venv: $BENE_VENV"
echo "$BENE_VENV/bin" >> "${GITHUB_PATH:-/dev/null}" || true
echo "BENE_VENV=$BENE_VENV" >> "${GITHUB_ENV:-/dev/null}" || true
