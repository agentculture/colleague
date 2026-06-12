"""colleague.resident.channels — channel selection for resident promotion.

When a colleague instance graduates to a Culture resident it OWNS its own
channel (``#<nick>``) and JOINS a set of relevant channels chosen by querying
the operator-installed roster CLI (``steward`` / ``culture``).  This module
owns the pure selection logic: parse candidates from the roster output, rank
them, run the optional operator-confirm gate, and always include the owned
channel in the result.

Subprocess confinement
----------------------
This module must **not** import ``subprocess``.  All CLI communication goes
through :func:`colleague.resident.steward.run_steward`, which is the one
sanctioned subprocess consumer under ``colleague/resident/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from colleague.identity import resolve_identity
from colleague.resident.steward import StewardError, parse_steward_output, run_steward

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

#: Regex that matches an IRC-style channel token anywhere on a line.
_CHANNEL_RE = re.compile(r"#\S+")

#: Default channel name when no identity can be resolved.
_DEFAULT_OWNED = "#colleague"


@dataclass
class ChannelSelection:
    """The result of a channel-selection step.

    Attributes:
        owned:    The resident's own channel (``#<nick>`` or ``#colleague``).
        chosen:   Ordered list of channels the resident will join — always
                  includes *owned*, even after a confirm gate that rejected it.
        degraded: ``True`` when the roster CLI was unavailable and the
                  selection fell back to *owned*-only.
        note:     Human-readable explanation for a degraded result; empty
                  string when not degraded.
    """

    owned: str
    chosen: list[str]
    degraded: bool = False
    note: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_owned(repo_path: Path) -> str:
    """Return the owned channel name for *repo_path*.

    Uses :func:`colleague.identity.resolve_identity` (culture.yaml first,
    then ``.colleague/identity.json``).  Falls back to ``#colleague`` when
    no identity is found.
    """
    nick = resolve_identity(repo_path)
    return f"#{nick}" if nick else _DEFAULT_OWNED


def _parse_channels(roster_output: str) -> list[str]:
    """Extract IRC-style channel tokens (``#...``) from *roster_output*.

    Parses leniently: any whitespace-separated token that starts with ``#``
    is treated as a channel name.  The ``exit=<code>`` prefix line emitted
    by :func:`~colleague.resident.steward.run_steward` is handled naturally
    (it contains no ``#`` tokens).

    Args:
        roster_output: The raw string returned by :func:`run_steward`.

    Returns:
        Deduplicated list of channel tokens, in first-seen order.
    """
    seen: set[str] = set()
    channels: list[str] = []
    for token in _CHANNEL_RE.findall(roster_output):
        if token not in seen:
            seen.add(token)
            channels.append(token)
    return channels


def _default_rank(nick: str | None, candidates: list[str]) -> list[str]:
    """Rank *candidates* by relevance to *nick*.

    Heuristic (documented):
    1. Exact match to the owned channel (``#<nick>``).
    2. Substring match of nick in the channel name.
    3. Remaining channels in alphabetical order.

    This keeps the most nick-relevant channel at the top while producing a
    stable, deterministic ordering for everything else.

    Args:
        nick:       The resolved nick, or ``None``.
        candidates: Parsed channel list to rank.

    Returns:
        A new list in ranked order (no deduplication — callers handle that).
    """
    owned_ch = f"#{nick}" if nick else _DEFAULT_OWNED
    nick_lower = (nick or "").lower()

    def _key(ch: str) -> tuple[int, str]:
        ch_lower = ch.lower()
        if ch == owned_ch:
            return (0, ch_lower)
        if nick_lower and nick_lower in ch_lower:
            return (1, ch_lower)
        return (2, ch_lower)

    return sorted(candidates, key=_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_channels(
    repo_path: str | Path,
    *,
    roster_cli: str = "steward",
    confirm: Callable[[list[str]], list[str]] | None = None,
    rank: Callable[[list[str]], list[str]] | None = None,
) -> ChannelSelection:
    """Select channels for the resident to own and join.

    The resident OWNS ``#<nick>`` (falling back to ``#colleague`` when no
    identity is resolvable) and JOINS a confirmed, ranked subset of candidates
    returned by the operator's roster CLI.

    Args:
        repo_path:  The repo root.  Used for identity resolution and as the
                    ``cwd`` for the roster CLI subprocess (via
                    :func:`~colleague.resident.steward.run_steward`).
        roster_cli: The allow-listed CLI to query for channel candidates
                    (``"steward"`` or ``"culture"``).  Forwarded verbatim to
                    :func:`run_steward`.
        confirm:    Optional operator gate — called with the ranked candidate
                    list and returns the accepted subset.  The owned channel is
                    always included in the final result regardless of what
                    *confirm* returns.  Default (``None``) accepts all
                    candidates.
        rank:       Optional ranking callable — called with the raw parsed
                    candidate list and returns it in the desired order.
                    Default (``None``) uses the built-in nick-relevance
                    heuristic.

    Returns:
        A :class:`ChannelSelection` whose ``owned`` is always in ``chosen``.
        When the roster CLI is unavailable the result is *degraded*
        (``degraded=True``, ``note`` set) and ``chosen`` contains only the
        owned channel.
    """
    root = Path(repo_path).resolve()
    owned = _resolve_owned(root)
    nick = resolve_identity(root)

    # --- Query the roster CLI -------------------------------------------
    try:
        roster_output = run_steward(roster_cli, ["roster"], root=root)
    except StewardError as exc:
        note = f"roster CLI unavailable — degraded to owned channel only ({exc})"
        return ChannelSelection(owned=owned, chosen=[owned], degraded=True, note=note)

    # A non-zero exit means the roster CLI ran but failed — degrade rather than
    # parse channels out of its error output (qodo correctness flag).
    exit_code, roster_body = parse_steward_output(roster_output)
    if exit_code != 0:
        note = (
            f"roster CLI exited {exit_code} — degraded to owned channel only "
            "(refusing to parse channels from error output)"
        )
        return ChannelSelection(owned=owned, chosen=[owned], degraded=True, note=note)

    # --- Parse candidates -----------------------------------------------
    raw_candidates = _parse_channels(roster_body)

    # --- Rank -----------------------------------------------------------
    if rank is not None:
        ranked = rank(raw_candidates)
    else:
        ranked = _default_rank(nick, raw_candidates)

    # --- Operator confirm gate ------------------------------------------
    if confirm is not None:
        accepted: list[str] = confirm(ranked)
    else:
        accepted = list(ranked)

    # --- Ensure owned is always present ---------------------------------
    chosen: list[str] = list(dict.fromkeys(accepted))  # deduplicate, preserve order
    if owned not in chosen:
        chosen.insert(0, owned)

    return ChannelSelection(owned=owned, chosen=chosen)
