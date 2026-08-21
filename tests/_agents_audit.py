"""Test-side manifest audit for the agents mode (#411, t21 — c44/h31).

NOT a CLI verb and NOT runtime code: a tests-only helper that reads the
per-invocation ``token_estimate`` figures an armed run folds onto
``TaskResult.agents["invocations"]`` (the t9 :class:`InvocationRecord`
manifest) and reports how much of the advertised context the BIGGEST send
used. The scripted continuity run asserts ``manifest_ratio(...) < 0.5``
(:mod:`tests.test_agents_continuity`); the live proof (t23) imports the same
helper against a real rig's advertised context window.

Accepted sources — anything that carries invocation records:

- a :class:`colleague.contract.TaskResult` (its ``agents`` block, ``None`` =
  no invocations);
- the ``agents`` block itself (a mapping with an ``"invocations"`` list);
- a sequence of invocation records — :class:`InvocationRecord` instances,
  their ``to_dict()`` mappings, or bare ``{"token_estimate": ...}`` dicts.

``token_estimate`` is a PRE-SEND sizing figure (chars/4 or the ``/tokenize``
probe) — it is never ``Usage``; this helper compares it only with the context
the operator/rig advertises, never with billed tokens.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def invocations_of(source: Any) -> list[dict[str, Any]]:
    """Normalise *source* to a list of invocation dicts (``[]`` when none)."""
    if source is None:
        return []
    block = getattr(source, "agents", None)
    if block is not None and not isinstance(source, Mapping):
        return invocations_of(block)
    if isinstance(source, Mapping):
        if "invocations" in source:
            return invocations_of(source["invocations"])
        if "token_estimate" in source:
            return [dict(source)]
        return []
    if isinstance(source, (str, bytes)):
        return []
    if isinstance(source, Iterable):
        out: list[dict[str, Any]] = []
        for item in source:
            if isinstance(item, Mapping):
                out.append(dict(item))
            elif hasattr(item, "to_dict"):
                out.append(dict(item.to_dict()))
            elif hasattr(item, "token_estimate"):
                out.append(
                    {
                        "token_estimate": getattr(item, "token_estimate", 0),
                        "token_estimate_source": getattr(item, "token_estimate_source", ""),
                        "truncated": bool(getattr(item, "truncated", False)),
                    }
                )
        return out
    return []


def max_token_estimate(source: Any) -> int:
    """The largest ``token_estimate`` over every invocation (0 when none)."""
    estimates = [_as_int(i.get("token_estimate")) for i in invocations_of(source)]
    return max(estimates) if estimates else 0


def manifest_ratio(source: Any, advertised_context: int) -> float:
    """``max(token_estimate) / advertised_context`` over the run's invocations.

    ``0.0`` when the run recorded no invocations. ``advertised_context`` must
    be a positive integer (the rig's advertised window / the run's budget) —
    anything else is a caller error, never a silent ``inf``.
    """
    advertised = _as_int(advertised_context)
    if advertised <= 0:
        raise ValueError(f"advertised_context must be > 0, got {advertised_context!r}")
    return max_token_estimate(source) / float(advertised)


def audit_report(source: Any, advertised_context: int) -> dict[str, Any]:
    """A plain-dict audit of one run's manifests against *advertised_context*.

    Keys: ``advertised_context``, ``count`` (invocations seen),
    ``max_token_estimate``, ``ratio`` (:func:`manifest_ratio`),
    ``truncated`` (how many invocations were flagged truncated),
    ``sources`` (the sorted distinct ``token_estimate_source`` labels),
    ``over_half`` (``ratio >= 0.5`` — the t21/t23 line) and ``over``
    (``ratio >= 1.0`` — a send that claimed more than the window).
    """
    records = invocations_of(source)
    ratio = manifest_ratio(records, advertised_context)
    return {
        "advertised_context": _as_int(advertised_context),
        "count": len(records),
        "max_token_estimate": max_token_estimate(records),
        "ratio": ratio,
        "truncated": sum(1 for r in records if bool(r.get("truncated"))),
        "sources": sorted({str(r.get("token_estimate_source") or "") for r in records} - {""}),
        "over_half": ratio >= 0.5,
        "over": ratio >= 1.0,
    }


__all__: Sequence[str] = (
    "audit_report",
    "invocations_of",
    "manifest_ratio",
    "max_token_estimate",
)
