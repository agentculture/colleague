"""``tools.tui_sim`` — simulate the colleague TUI and record it as asciinema casts.

The colleague TUI renders through **pure, deterministic** functions over a
:class:`~colleague.tui.state.CockpitState` (``render``, ``reduce``,
``render_slash_autocomplete``, …). This harness scripts realistic human flows
through those *real* render seams and serializes each flow to:

* an asciinema **v2 ``.cast``** recording (the replayable "video"), and
* a SGR-stripped ``.txt`` storyboard (diff-friendly, review-friendly),

plus a snapshot quad (``.taui.json`` / ``.ansi`` / ``.events.jsonl`` / ``.md``)
for event-driven scenarios.

Zero third-party imports — a ``.cast`` is just JSON, so the harness stays inside
colleague's ``dependencies = []`` convention. It adds no ``colleague`` CLI verb,
opens no socket, forks no daemon. Run it with::

    python -m tools.tui_sim --out tools/tui_sim/recordings

It is **dev tooling**, not a runtime feature: it lives under ``tools/`` and is
excluded from the shipped wheel (``packages = ["colleague"]``).
"""
