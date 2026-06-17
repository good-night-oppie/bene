"""BENE — Breeding-program Evolutionary Nexus for Engrams."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # Single source of truth: the installed distribution's metadata (driven by
    # pyproject.toml's version). Every other version surface derives from this.
    __version__ = _pkg_version("bene")
except PackageNotFoundError:  # running from a source tree with no installed dist
    __version__ = "0.0.0+unknown"

from bene.core import Bene

__all__ = ["Bene", "__version__"]
