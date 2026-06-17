"""Pytest path bootstrap for environments where pip<22 cannot install editable.

Adds the repo root to ``sys.path`` so ``import bene`` works without
``pip install -e``. Required by consumer test runners (e.g. triage-rag's
``/home/etang/bin/python``) that do not honor ``pyproject.toml``-only
editable installs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
