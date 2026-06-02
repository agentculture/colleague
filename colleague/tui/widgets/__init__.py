"""Colleague TUI widgets — pure functions from CockpitState to str.

Each widget module exposes a single render function that accepts a
:class:`~colleague.tui.state.CockpitState` (or a relevant slice) and
returns a ``str``.  All widgets are stdlib-only; zero third-party imports.
"""
