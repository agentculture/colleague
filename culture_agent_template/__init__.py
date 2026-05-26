"""culture-agent-template — agent-first CLI for an AgentCulture mesh agent."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("culture-agent-template")
except PackageNotFoundError:  # pragma: no cover - editable install without metadata
    __version__ = "0.0.0"

__all__ = ["__version__"]
