"""Backend discovery: find and select engines via Python entry points (R4).

An engine becomes available to Colleague by advertising itself under the
``colleague.engines`` entry-point group. The two bundled engines do this in
this repo's ``pyproject.toml``; an out-of-tree wheel does the *identical* thing
in its own metadata, and :func:`catalog` discovers it with no change to
Colleague core (honesty condition h4).

This is the registry: ``colleague backends list`` reads :func:`catalog`, and
``colleague drive --engine <name>`` resolves the choice through :func:`load`.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from colleague.engine import Engine

ENTRY_POINT_GROUP = "colleague.engines"


class UnknownEngine(Exception):
    """Requested an engine name that no installed wheel registers."""


@dataclass(frozen=True)
class BackendInfo:
    """A discovered backend plugin: its selectable name and entry-point target."""

    name: str
    target: str


def _engine_entry_points() -> list[EntryPoint]:
    """All entry points in the colleague.engines group (monkeypatch seam for tests)."""
    return list(entry_points(group=ENTRY_POINT_GROUP))


def catalog() -> list[BackendInfo]:
    """Every discovered backend plugin, sorted by name."""
    infos = [BackendInfo(name=ep.name, target=ep.value) for ep in _engine_entry_points()]
    return sorted(infos, key=lambda b: b.name)


def names() -> list[str]:
    """Selectable engine names, sorted."""
    return [w.name for w in catalog()]


def load(name: str) -> Engine:
    """Instantiate the engine registered under ``name``.

    Raises :class:`UnknownEngine` listing the available names when not found.
    """
    for ep in _engine_entry_points():
        if ep.name == name:
            engine_cls = ep.load()
            return engine_cls()
    available = ", ".join(names()) or "(none installed)"
    raise UnknownEngine(f"unknown engine '{name}'; available: {available}")
