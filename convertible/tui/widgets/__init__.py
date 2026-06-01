"""Convertible TUI widgets — pure functions from CockpitState to str.

Each widget module exposes a single render function that accepts a
:class:`~convertible.tui.state.CockpitState` (or a relevant slice) and
returns a ``str``.  All widgets are stdlib-only; zero third-party imports.
"""
