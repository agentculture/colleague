"""Best-effort coercers split out of :mod:`colleague.contract` (task t13,
hard-1000-line-file-limit): the read-back-from-artifact tolerant parsers
(``_coerce_*``) and the detached-copy helpers (``_copy_*``) ``TaskResult``'s
``from_dict``/``to_dict`` lean on. Each degrades a malformed payload to a
safe default rather than raising — the codebase's consistent best-effort
stance on optional structured payloads read back from JSON. Re-exported
(where public) from ``colleague.contract`` so every existing ``from
colleague.contract import ...`` call site resolves unmodified.
"""

from __future__ import annotations

from typing import Any, Optional

from colleague.configevents import ConfigEvent
from colleague.contract_configevents import ConfigEventRecord
from colleague.contract_records import DeepthinkCall


def _copy_hire_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """A detached copy of ONE ``TaskResult.hires`` entry: the top-level dict
    plus one level of list/dict-entry copies (the ``_copy_agents_block``
    stance), so serializing or re-reading an artifact never aliases the
    in-memory roster entry or its ``assignments`` list. Tolerant of a
    malformed artifact: a non-list/non-dict value is kept as-is, never raises.
    """
    out: dict[str, Any] = {}
    for key, value in entry.items():
        if isinstance(value, list):
            out[key] = [dict(v) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    return out


def _copy_agents_block(block: dict[str, Any]) -> dict[str, Any]:
    """A detached copy of a ``TaskResult.agents`` block: the top-level dict
    plus one level of list/dict-entry copies, so serializing or re-reading an
    artifact never aliases the in-memory lists (``invocations``/``messages``/
    ``fallbacks``) the loop keeps appending to. Tolerant of a malformed
    artifact: a non-list where a list is expected is kept as-is, never raises.
    """
    out: dict[str, Any] = {}
    for key, value in block.items():
        if isinstance(value, list):
            out[key] = [dict(v) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    return out


def _coerce_omissions(value: Any) -> list[str]:
    """Coerce a raw ``omissions`` payload read back from an artifact.

    Mirrors :func:`colleague.senses._coerce_omissions` (kept as a standalone
    copy, not an import, to avoid a circular import: ``colleague.senses``
    already imports :class:`colleague.contract_senses.ContextPacket` from
    that module). A malformed artifact's ``omissions`` may be missing,
    ``None``, a non-string scalar (e.g. an int), or a bare string — none of
    those should crash or misbehave (a bare string previously iterated
    per-character via ``[str(o) for o in "abc"]``, Qodo finding #1 on the
    cortex/senses PR #281). A list/tuple becomes ``[str(x) for x in value]``;
    a bare string becomes a single-element list; anything else (``None``, a
    number, a dict) becomes ``[]`` — tolerant of a malformed artifact, never
    raises.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return []


#: Hard cap on ``ContextPacket.ack`` length, mirroring
#: :data:`colleague.senses._MAX_ACK_LEN` (kept as a standalone literal, not an
#: import, for the same circular-import reason as :func:`_coerce_ack` below).
_MAX_ACK_LEN = 500


def _coerce_ack(value: Any) -> Optional[str]:
    """Coerce a raw ``ack`` payload read back from an artifact.

    Mirrors :func:`colleague.senses._coerce_ack` (kept as a standalone copy,
    not an import, to avoid a circular import: ``colleague.senses`` already
    imports :class:`colleague.contract_senses.ContextPacket` from that
    module). A non-string value (e.g. a number or dict from a malformed
    artifact) degrades to ``None`` rather than raising downstream —
    ``session.py``'s ``_render_ack`` does ``(ack or "").strip()``, which
    would raise ``AttributeError`` on a truthy non-string ack. A string is
    stripped of surrounding whitespace and hard-capped to
    :data:`_MAX_ACK_LEN` characters; an empty/whitespace-only result
    degrades to ``None`` (matching :func:`colleague.senses._coerce_ack`'s
    "no usable ack is simply absent" stance).
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:_MAX_ACK_LEN]


def _coerce_acceptance_outcomes(
    raw: Optional[list[Any]],
) -> Optional[list[dict[str, Any]]]:
    """Coerce a raw ``acceptance_outcomes`` payload read back from an artifact.

    ``None`` in, ``None`` out (no acceptance criteria were set — the common
    case). When a list is present, each entry is expected to be a
    ``{"criterion": str, "met": bool, "evidence": str}`` mapping; a malformed
    (non-dict) entry is dropped rather than raising, matching the codebase's
    best-effort stance elsewhere on optional structured payloads read back
    from JSON (e.g. :class:`TestIntegrityReport`'s "never raises" contract).
    """
    if raw is None:
        return None
    outcomes: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        outcomes.append(
            {
                "criterion": str(entry.get("criterion", "")),
                "met": bool(entry.get("met", False)),
                "evidence": str(entry.get("evidence", "")),
            }
        )
    return outcomes


def _coerce_deepthink_calls(
    raw: Optional[list[Any]],
) -> Optional[list[DeepthinkCall]]:
    """Coerce a raw ``deepthink`` payload read back from an artifact.

    ``None`` in, ``None`` out (no dual-model config was present / no
    escalation occurred — the common case). When a list is present, each
    entry is expected to be a :class:`DeepthinkCall`-shaped mapping; a
    malformed (non-dict) entry is dropped rather than raising, matching the
    codebase's best-effort stance on optional structured payloads read back
    from JSON (see :func:`_coerce_acceptance_outcomes`).
    """
    if raw is None:
        return None
    calls: list[DeepthinkCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        calls.append(DeepthinkCall.from_dict(entry))
    return calls


def _coerce_config_events(raw: Optional[list[Any]]) -> list[ConfigEvent]:
    """Coerce a raw ``config_events`` payload read back from an artifact.

    ``None``/absent in, ``[]`` out (no config-event activity — the common
    case, matching ``sub_results``'s own default-empty-list stance rather
    than ``deepthink``'s default-``None`` stance, since ``config_events`` is
    itself list-shaped and omit-when-**empty**, not omit-when-None). A
    malformed (non-dict) entry is dropped rather than raising, matching the
    codebase's best-effort stance on optional structured payloads read back
    from JSON (see :func:`_coerce_deepthink_calls`).

    An entry carrying a non-empty ``"content"`` key (t8) is parsed via
    :meth:`colleague.contract_configevents.ConfigEventRecord.from_dict`
    instead of the bare :class:`ConfigEvent`'s own ``from_dict`` — every
    OTHER entry (the common case: an old artifact predating ``content``, or
    any event this fold never attaches content to) stays a plain
    :class:`ConfigEvent`, so ``restored.config_events == original_events``
    keeps holding for every pre-t8 round-trip test that compares against
    hand-built :class:`ConfigEvent` instances (dataclass equality requires
    the SAME class). Content-bearing entries opt into the richer subclass;
    everything else round-trips byte-for-byte and class-for-class exactly as
    before.
    """
    if not raw:
        return []
    events: list[ConfigEvent] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("content"):
            events.append(ConfigEventRecord.from_dict(entry))
        else:
            events.append(ConfigEvent.from_dict(entry))
    return events
