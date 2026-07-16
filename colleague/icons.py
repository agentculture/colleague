"""Icons vocabulary: resolve emoji | ascii | none and apply to panel labels.

A pure module resolving an icon vocabulary and applying it to
colleague-composed cockpit panel labels at build time. Default is `emoji`
(byte-identical to today). It resolves via the existing colleague config
precedence and is a strict no-op when unset.

Resolution precedence (highest wins):
1. An explicit resolved value passed by the caller (a ``flag`` argument, may be None).
2. Env var ``COLLEAGUE_ICONS`` (also honor legacy ``CONVERTIBLE_ICONS`` as a fallback).
3. ``.colleague/config.json`` top-level key ``"icons"``.
4. Default: ``"emoji"``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from colleague.config import _merged_config_json

ICON_MODES: tuple[str, ...] = ("emoji", "ascii", "none")
DEFAULT_ICON_MODE: str = "emoji"

#: The vocabulary: a semantic key -> the glyph for each mode.
#: Cover the semantic keys used by colleague-composed panels.
#:
#: NOTE (#285 / agentfront#50): this vocabulary switches only the glyphs in the
#: labels colleague itself composes. The renderer-OWNED glyphs (the moon-phase
#: state animation, the idle severity glyph, popup glyphs inside
#: ``agentfront.taui``) cannot be switched consumer-side without forking a
#: renderer (forbidden by the #249 "import, don't duplicate" rule). Upstream ask
#: to make those switchable: https://github.com/agentculture/agentfront/issues/50
ICONS: dict[str, dict[str, str]] = {
    "policy": {"emoji": "\U0001f6e1\ufe0f", "ascii": "[policy]", "none": ""},
    "context": {"emoji": "\U0001f7e2", "ascii": "[context]", "none": ""},
    "capacity": {"emoji": "\U0001f321\ufe0f", "ascii": "[capacity]", "none": ""},
    "mode": {"emoji": "\U0001f524", "ascii": "[mode]", "none": ""},
    "ledger": {"emoji": "\U0001f4d6", "ascii": "[ledger]", "none": ""},
    "activity": {"emoji": "\U0001f55b", "ascii": "[activity]", "none": ""},
    "next": {"emoji": "\u25b6\ufe0f", "ascii": "[next]", "none": ""},
    "ok": {"emoji": "\u2705", "ascii": "[ok]", "none": ""},
    "warn": {"emoji": "\u26a0\ufe0f", "ascii": "[warn]", "none": ""},
    "run": {"emoji": "\u25b6\ufe0f", "ascii": "[run]", "none": ""},
    "idle": {"emoji": "\u23f8\ufe0f", "ascii": "[idle]", "none": ""},
}


def _load_icons_config(repo_path: str | Path) -> str | None:
    """Read the ``icons`` key from .colleague/config.json (per-key merged).

    Uses :func:`colleague.config._merged_config_json` (the at-home per-key
    merge, #339) so a user-level ``icons`` value survives a repo config that
    omits the key. Returns the raw string value or ``None`` when absent /
    unreadable. Never raises — ``_merged_config_json`` degrades to ``{}``.
    """
    data = _merged_config_json(repo_path)
    value = data.get("icons")
    if isinstance(value, str) and value:
        return value
    return None


def _normalize(value: str | None) -> str | None:
    """Normalize a candidate value: lowercase and validate against ICON_MODES.

    Returns the lowercased value if it is a recognized mode, else ``None``.
    """
    if value is None:
        return None
    lower = value.strip().lower()
    return lower if lower in ICON_MODES else None


def resolve_icons(flag: Optional[str] = None, *, repo_path=".") -> str:
    """Resolve the icon mode via the precedence above. Returns one of ICON_MODES.

    Pure except for reading env + the config file; never raises.
    """
    # 1. Explicit flag
    if flag is not None:
        normalized = _normalize(flag)
        if normalized is not None:
            return normalized

    # 2. Environment variables
    env_value = os.environ.get("COLLEAGUE_ICONS")
    if not env_value:
        env_value = os.environ.get("CONVERTIBLE_ICONS")
    if env_value:
        normalized = _normalize(env_value)
        if normalized is not None:
            return normalized

    # 3. Config file
    file_value = _load_icons_config(repo_path)
    if file_value is not None:
        normalized = _normalize(file_value)
        if normalized is not None:
            return normalized

    # 4. Default
    return DEFAULT_ICON_MODE


def icon(key: str, mode: str) -> str:
    """Return the glyph for semantic ``key`` under ``mode``. Unknown key -> "".

    For mode "none" ALWAYS return "" regardless of key.
    """
    if mode == "none":
        return ""
    entry = ICONS.get(key)
    if entry is None:
        return ""
    return entry.get(mode, "")


def label(text: str, key: str, mode: str) -> str:
    """Compose a panel label: prefix ``text`` with the icon for (key, mode) + a space
    when the icon is non-empty; return ``text`` unchanged when the icon is empty
    (mode 'none' or unknown key).

    E.g. label('Run policy', 'policy', 'emoji') -> '\\U0001f6e1\\ufe0f Run policy';
    label('Run policy', 'policy', 'none') -> 'Run policy'.
    """
    glyph = icon(key, mode)
    if glyph:
        return f"{glyph} {text}"
    return text
