"""The ``TaskResult.agents`` artifact block — pure builders (#411, plan t13).

The run artifact carries a SMALL, versioned summary of the model-bound-agents
activity for the ROI/feedback readers (spec c17 / h24): the invocation
records, the agent-to-agent messages, the recorded role fallbacks, and the
task-ledger pointer + digest. The ledger (``colleague/agents/state/ledger.py``)
stays the authority — this block is a read-side mirror of what is already
appended there, never a second source of truth, and it is OMITTED from the
serialized artifact entirely when the increment is unarmed (the
``evaluation_ledger``/``senses``/``chain`` omit-when-None convention in
:class:`colleague.contract.TaskResult`).

Everything here is pure: plain dicts in, a plain dict out, no I/O, no clock.
The loop-side wiring (t15) calls :func:`build_agents_block` with what it
collected during the run; both engines' ``work()`` call
:func:`fold_agents_block` right before returning so that an ARMED run always
carries the key with the SAME shape on every backend (the all-engines rule —
``mock`` is the contract reference), while an unarmed run stays
byte-identical (key absent). The engine fold is a FLOOR: it only fills a
``None`` ``agents`` field, so a loop-authored block always wins.

Shape (``AGENTS_BLOCK_VERSION`` 1)::

    {
      "version": 1,
      "invocations": [InvocationRecord.to_dict(), ...],
      "messages":    [AgentMessage.to_dict(), ...],
      "fallbacks":   [{"purpose", "from_role", "resolved_model"}, ...],
      "ledger_path":   str | null,
      "ledger_digest": str | null,
    }
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

#: The schema version stamped on every block this module builds.
AGENTS_BLOCK_VERSION = 1

#: The top-level keys of the block, in serialization order (drift-tested).
AGENTS_BLOCK_KEYS: tuple[str, ...] = (
    "version",
    "invocations",
    "messages",
    "fallbacks",
    "ledger_path",
    "ledger_digest",
)

#: The keys of one ``fallbacks[]`` entry.
FALLBACK_ENTRY_KEYS: tuple[str, ...] = ("purpose", "from_role", "resolved_model")


def _as_dict(item: Any) -> dict[str, Any]:
    """A plain dict copy of *item* — a ``to_dict()``-bearing record
    (``InvocationRecord``, ``AgentMessage``) or an already-serialized
    mapping. Anything else is refused whole (a loud ``TypeError``), never
    guessed."""
    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if isinstance(item, Mapping):
        return dict(item)
    raise TypeError(f"agents block entry must be a record or a mapping, got {type(item).__name__}")


def fallback_entry(purpose: str, from_role: str, resolved_model: str) -> dict[str, Any]:
    """One recorded role fallback: *purpose* was carried from *from_role*
    (the role it could not run on) onto the seat whose served model id is
    *resolved_model* — trace data, never a constant."""
    return {
        "purpose": str(purpose),
        "from_role": str(from_role),
        "resolved_model": str(resolved_model),
    }


def fallbacks_from_invocations(invocations: Iterable[Any]) -> list[dict[str, Any]]:
    """Derive the ``fallbacks[]`` list from invocation records: one entry per
    record whose ``fallback_from_role`` is set (the purpose ran on the cortex
    floor instead of its own role), in record order. Records that ran on
    their own ready role contribute nothing."""
    out: list[dict[str, Any]] = []
    for item in invocations:
        rec = _as_dict(item)
        from_role = rec.get("fallback_from_role")
        if from_role:
            out.append(
                fallback_entry(
                    str(rec.get("purpose", "")),
                    str(from_role),
                    str(rec.get("resolved_model", "")),
                )
            )
    return out


def build_agents_block(
    invocations: Iterable[Any] = (),
    messages: Iterable[Any] = (),
    fallbacks: Optional[Iterable[Mapping[str, Any]]] = None,
    ledger_path: Optional[str] = None,
    ledger_digest: Optional[str] = None,
) -> dict[str, Any]:
    """Build the ``TaskResult.agents`` block (version
    :data:`AGENTS_BLOCK_VERSION`).

    *invocations* / *messages* accept records (``InvocationRecord`` /
    ``AgentMessage``) or their ``to_dict()`` mappings — each is copied into a
    plain dict. *fallbacks* defaults to the list DERIVED from *invocations*
    (:func:`fallbacks_from_invocations`); pass an explicit iterable to
    override it. *ledger_path* / *ledger_digest* are the task-ledger pointer
    and its state digest (``None`` when no ledger was written). Pure: same
    inputs → equal block.
    """
    inv = [_as_dict(i) for i in invocations]
    msgs = [_as_dict(m) for m in messages]
    if fallbacks is None:
        fb = fallbacks_from_invocations(inv)
    else:
        fb = [
            fallback_entry(
                str(f.get("purpose", "")),
                str(f.get("from_role", "")),
                str(f.get("resolved_model", "")),
            )
            for f in fallbacks
        ]
    return {
        "version": AGENTS_BLOCK_VERSION,
        "invocations": inv,
        "messages": msgs,
        "fallbacks": fb,
        "ledger_path": str(ledger_path) if ledger_path is not None else None,
        "ledger_digest": str(ledger_digest) if ledger_digest is not None else None,
    }


def empty_agents_block() -> dict[str, Any]:
    """The armed-but-nothing-recorded block: every list empty, no ledger
    pointer — the engine-level floor an ARMED run carries before (or without)
    any loop-side fold, so the key's SHAPE is identical on every backend."""
    return build_agents_block()


def fold_agents_block(result: Any, config: Any) -> Any:
    """Engine-side fold, called by every backend's ``work()`` right before it
    returns (the all-engines rule).

    ONLY when ``config.agents`` is truthy AND ``result.agents`` is still
    ``None`` does it set ``result.agents = empty_agents_block()`` — so a
    loop-authored block (t15) always takes precedence, and an UNARMED config
    leaves *result* untouched (byte-identical artifact, key absent). Returns
    *result* for call-site convenience.
    """
    if getattr(config, "agents", False) and getattr(result, "agents", None) is None:
        result.agents = empty_agents_block()
    return result
