"""``.colleague/models.json`` loader: tracked sampling rows, per-model merge (t3).

``models.json`` is deliberately a **tracked** file — unlike the rest of
``.colleague/`` (self-ignored by :mod:`colleague.artifact`), it is NOT
gitignored. That is the whole point: ``work``/``drive`` run in a throwaway git
worktree checked out at ``HEAD`` (write isolation #196/#201,
:mod:`colleague.worktrees`). A gitignored file simply does not exist inside
that worktree, so an operator's declared sampling rows would silently vanish
the moment a run went isolated. A tracked ``.colleague/models.json`` commits
with the repo and comes along for the ride.

This module is a **pure parser/merger** — it knows nothing about
:mod:`colleague.sampling`'s frozen profile dataclass or the builtin table
(that module is being built in a sibling task and layers itself over this
one's output). It has no import of ``colleague.sampling`` and never will.

**File shape** — one JSON object at the top level, keyed by model id. Each
model's value is itself an object keyed by "half" (an operator-chosen label —
e.g. a thinking-mode vs. non-thinking-mode split), and each half is a flat
object of raw sampling key/value pairs, passed through unexamined::

    {
      "qwen3-8b": {
        "thinking": {"temperature": 1.0, "top_p": 0.95, "top_k": 20},
        "non_thinking": {"temperature": 0.7, "top_p": 0.8, "top_k": 20}
      },
      "some-other-model": {
        "default": {"temperature": 0.6}
      }
    }

Nothing about the half names or the inner keys is validated or interpreted
here — they are handed through verbatim as plain ``dict`` data. A downstream
consumer (the sibling ``colleague.sampling`` loader) is responsible for
mapping half labels and keys onto its own typed profile.

**Return shape** — :func:`load_models_file` returns
``dict[str, dict[str, dict[str, object]]]``: model id -> half label -> raw
key/value mapping.

**Merge granularity — per model key.** Every existing ``models.json`` across
:func:`colleague.configdir.config_roots` is read (repo before user, matching
every other configdir-backed loader in this codebase). Fold order is
lowest-precedence first, so a higher-precedence file's model entries
overwrite same-named entries afterwards: a repo-level file that names only
one model does not erase a user-level row for a *different* model — the two
merge, keyed by model id. Within one model id, the entry is taken *wholesale*
from whichever file supplies that model first (no deep merge inside a
model's halves), mirroring ``colleague.config_files``'s top-level-key
config.json merge one level deeper — model id instead of config.json's
top-level section name.

**Tolerant parsing — never a refusal.** A missing file, a file that is not
valid JSON, a top-level payload that is not a JSON object, or an individual
model entry that is not a JSON object are all silently skipped (the file, or
just that one model entry, contributes nothing) — :func:`load_models_file`
never raises.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague import configdir

#: Filename resolved across configdir roots (mirrors config.json's constant
#: name in colleague.config_defaults, kept private to this module since no
#: other module needs it yet).
MODELS_FILENAME = "models.json"


def _read_models_object(path: Path) -> dict:
    """Read *path* as a JSON object of model rows; never raises.

    A missing file, unreadable file, malformed JSON, or a top-level payload
    that isn't a JSON object all yield ``{}`` — the caller treats that as
    "this file contributes nothing" rather than a refusal.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_models_file(
    repo_path: str | Path, *, user_home: str | Path | None = None
) -> dict[str, dict[str, dict[str, object]]]:
    """Load + merge ``.colleague/models.json`` across configdir roots, PER MODEL KEY.

    See the module docstring for the exact file shape, merge granularity, and
    tolerant-parsing semantics. Returns ``{}`` when no root has the file, or
    every root's file is malformed/empty — never raises.

    Args:
        repo_path: Path to the repo being driven.
        user_home: (test fixture) Path to user's home; defaults to
            :func:`colleague.configdir._default_user_home` when omitted —
            forwarded verbatim to :func:`colleague.configdir.resolve_files`.

    Returns:
        ``dict[model_id, dict[half_label, dict[key, value]]]``.
    """
    paths = configdir.resolve_files(repo_path, MODELS_FILENAME, user_home=user_home)

    merged: dict[str, dict[str, dict[str, object]]] = {}
    # Fold lowest-precedence first so each higher-precedence file's model
    # entries overwrite it afterwards ("repo wins per model, user fills gaps"),
    # matching colleague.config_files._merged_config_json's fold order.
    for path in reversed(paths):
        rows = _read_models_object(path)
        for model_id, entry in rows.items():
            if not isinstance(model_id, str):
                continue
            if not isinstance(entry, dict):
                # Malformed individual row — skip just this entry, never raise
                # and never let it poison the rest of the file's rows.
                continue
            merged[model_id] = entry

    return merged
