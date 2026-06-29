"""Colleague TUI — the thin, colleague-specific cockpit surface.

The generic TUI cockpit (state model, events, reducer, TAUI mirror, renderers,
selectors, snapshot/diagnose, widgets) is **imported from** :mod:`agentfront.taui`
— colleague no longer duplicates it (issue #249, the "import, don't duplicate"
migration). Only the colleague-coupled pieces live here:

* :mod:`colleague.tui.from_work` — the TaskResult/loop-trace → ``agentfront.taui``
  :class:`WorkStep` adapter (composes the ``[tool] summary`` feed label).
* :mod:`colleague.tui.render.driver` — the live raw-terminal cockpit loop for
  ``colleague tui live`` (agentfront ships no equivalent raw-input driver).

Both are stdlib-only beyond the sanctioned ``agentfront`` base dependency.
"""
