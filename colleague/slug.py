"""Deterministic request → filesystem/branch slug (stdlib only, zero deps).

A work item's request is free text; a *slug* of it makes the work item recognisable in an
``ls`` of ``.colleague/`` or a ``git branch`` listing without quoting an opaque
task-id. The slug is a stable, lossy label — never an identifier (the ``task_id``
stays the key; see :mod:`colleague.feedback`). Two callers share this one
implementation so the artifact filename and the work branch always agree:
:func:`colleague.artifact.write` and :func:`colleague.handoff._branch_name`.

Stdlib ``re`` only — keeps ``dependencies = []`` and the zero-deps / module
boundary guards (``tests/test_zero_deps.py`` / ``tests/test_boundary.py``) green.
"""

from __future__ import annotations

import re

#: Default maximum slug length (characters). Sized to keep a slugged filename
#: (``<task_id>.<slug>.json``) comfortably within filesystem name limits while
#: leaving the request recognisable.
DEFAULT_MAX_LEN = 40

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = DEFAULT_MAX_LEN) -> str:
    """Return a lowercase ``-``-separated slug of ``text``, capped at ``max_len``.

    Lowercases, replaces every run of non-alphanumeric characters with a single
    ``-``, strips leading/trailing ``-``, then truncates to ``max_len`` on a
    ``-`` boundary where possible (so a word is not cut mid-token). Returns ``""``
    for empty / whitespace-only / all-punctuation input — callers fall back to the
    bare ``task_id``. Deterministic: same input always yields the same slug.
    """
    if not text:
        return ""
    slug = _NON_ALNUM.sub("-", text.lower()).strip("-")
    if len(slug) <= max_len:
        return slug
    clipped = slug[:max_len]
    # If the cut already lands on a word boundary (next char is a separator), the
    # clip is clean. Otherwise we cut a token in half — back off to the last
    # boundary (or keep the hard cut when there is none, e.g. one long token).
    if slug[max_len] != "-":
        boundary = clipped.rfind("-")
        if boundary > 0:
            clipped = clipped[:boundary]
    return clipped.strip("-")
