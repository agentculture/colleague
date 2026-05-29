"""Shared approval-ledger writer for the ``commands`` / ``hooks`` CLI nouns.

Both ``approve`` verbs write the same ``<repo>/.convertible/approvals.json``
ledger. Centralizing the write here keeps the two command modules free of a
duplicated merge-and-write helper and a repeated ``".convertible"`` literal — the
path is built once, from :data:`convertible.configdir.CONFIG_DIR_NAME`, and
confined to the repo root.

Reading approvals for *display* deliberately goes through
:func:`convertible.policy.load_policy` (repo-over-user + per-model overlay), so
the ``list`` status reflects the same merged policy enforcement uses — not a raw
single-file read. This module only owns the repo-level *write*.

Stdlib only; no third-party imports.
"""

from __future__ import annotations

import json
from pathlib import Path

from convertible.configdir import CONFIG_DIR_NAME
from convertible.policy import POLICY_FILENAME


def write_approval(repo: Path, category: str, name: str, checksum: str) -> None:
    """Merge a single ``{name: checksum}`` approval into *category* of the ledger.

    The ledger lives at the fixed sub-path ``.convertible/approvals.json`` under
    *repo*. The target is resolved and **confined to the resolved repo root** —
    the same defense :meth:`convertible.tools.ToolExecutor._safe_path` applies —
    so the operator-supplied ``--repo`` can never steer the write outside the
    repository tree (``..`` segments, a symlinked root). Creates ``.convertible/``
    and the ledger on first write; preserves every other section; a malformed
    existing ledger is replaced rather than raising.
    """
    base = Path(repo).resolve()
    path = (base / CONFIG_DIR_NAME / POLICY_FILENAME).resolve()
    if path != base and base not in path.parents:
        raise ValueError(f"approvals path escapes the repo root: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            existing = {}

    section = existing.get(category)
    if not isinstance(section, dict):
        section = {}
    section[name] = checksum
    existing[category] = section

    path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
