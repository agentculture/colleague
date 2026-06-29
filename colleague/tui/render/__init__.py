"""Colleague TUI render package — the surviving live-terminal driver.

The generic renderers (boxed ANSI, borderless flat, Markdown, layout) live in
:mod:`agentfront.taui.render` and are imported, not duplicated (issue #249). The
only renderer code colleague keeps is :mod:`colleague.tui.render.driver`, the
foreground raw-terminal cockpit loop for ``colleague tui live`` — agentfront
ships no equivalent raw-input driver. Stdlib-only beyond ``agentfront``.
"""
