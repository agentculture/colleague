"""Environment check-group — STUB.

Spec for the sibling agent who fills this in. This group verifies the broader
**operating environment** — the ``.convertible/`` config tree, the extensibility
layer, external tooling on ``PATH``, and CLI self-integrity. It must:

* **.convertible resolution** — report whether a ``.convertible/`` config dir
  resolves (repo-level overriding user-level ``~/.convertible/``, via
  :mod:`convertible.configdir`). Missing is ``info``/``warning``, not fatal.
* **hooks.json** — if ``.convertible/hooks.json`` exists, parse it as JSON and
  validate it loads (via :mod:`convertible.hooks`); a malformed hooks file is an
  ``error`` (it would break every drive's lifecycle).
* **command templates** — discover ``.convertible/commands/*.md`` and confirm
  they parse (via :mod:`convertible.commands`); a template that fails to parse is
  a ``warning``.
* **AGENTS / skills layering** — confirm the layered per-model config resolves
  (via :mod:`convertible.layers`): the AGENTS instruction chain and skills
  compose without error. Report as ``info``; a resolution error is a ``warning``.
* **external tools on PATH** — ``git`` (use :func:`shutil.which`): missing is an
  ``error`` (the handoff cannot branch/commit/push); ``gh`` missing is a
  ``warning`` (PR creation degrades, but offline/CI drives still work).
* **CLI integrity** — confirm the package imports, ``convertible.__version__``
  is present and non-empty, and the argument parser builds
  (``convertible.cli._build_parser()`` does not raise). A failure here is an
  ``error``.

Read-only: only reads files, env, ``PATH``, and builds the parser in-process; it
must not run ``git``/``gh`` or any drive. Catch every probe's error and return it
as a failed check; never raise.

Until implemented, returns ``[]``.
"""

from __future__ import annotations


def checks() -> list[dict]:
    """STUB — returns no checks yet. See module docstring for the spec."""
    return []
