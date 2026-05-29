"""Shared approval-file helpers for the ``commands`` / ``hooks`` CLI nouns.

Both nouns read and write the same ``<repo>/.convertible/approvals.json`` ledger
(the approval gate's policy file). Centralizing the read/write/verify primitives
here keeps the two command modules free of duplicated JSON plumbing and a
repeated ``".convertible"`` literal — the path is built once, from
:data:`convertible.configdir.CONFIG_DIR_NAME`.

Stdlib only; no third-party imports.
"""

from __future__ import annotations

import json
from pathlib import Path

from convertible.configdir import CONFIG_DIR_NAME
from convertible.policy import POLICY_FILENAME, verify_checksum


def approvals_path(repo: Path) -> Path:
    """Path to the repo-level approvals ledger (``<repo>/.convertible/approvals.json``)."""
    return repo / CONFIG_DIR_NAME / POLICY_FILENAME


def read_section(repo: Path, section: str) -> dict | None:
    """Return one section of the approvals ledger, or ``None``.

    ``None`` means: the ledger file is absent, unreadable, not a JSON object, or
    has no (dict-valued) entry for *section*. Callers treat ``None`` as
    "category not gated"; a present-but-empty section (``{}``) is returned as an
    empty dict, which gates everything in that category as unapproved.
    """
    path = approvals_path(repo)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    value = raw.get(section)
    return value if isinstance(value, dict) else None


def write_approval(repo: Path, category: str, name: str, checksum: str) -> None:
    """Merge a single ``{name: checksum}`` approval into *category* of the ledger.

    Creates ``.convertible/`` and the ledger on first write; preserves every
    other section. A malformed existing ledger is replaced rather than raising.
    """
    path = approvals_path(repo)
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


def verify_status(path: Path, approval: str) -> str:
    """``"approved"`` when *path*'s checksum matches *approval*, else ``"drifted"``.

    A missing file cannot be verified, so it is reported as ``"drifted"`` — the
    approval no longer corresponds to a present, matching artifact.
    """
    path = Path(path)
    if path.is_file() and verify_checksum(path, approval):
        return "approved"
    return "drifted"
