"""Continuation: resolve a prior work item and build a seed for continuation.

Given a task reference (``"last"`` or an explicit task id), this module resolves
the work item, loads its artifact, guards against continuing a completed or
missing work item, and returns a seed text that embeds the full continuation
record plus the original request verbatim.

Two seams build the seed body (#411, t17):

- **the prose recap** — :func:`colleague.escalation.build_continuation` over the
  artifact (today's path, always available);
- **the task ledger** — when the caller says the ``agents`` mode is ARMED and
  ``<repo>/.colleague/ledger/<task_id>.jsonl`` reads cleanly
  (:func:`colleague.agents.state.read_ledger`, fail-closed), the seed is
  rendered from the replay-derived :class:`~colleague.agents.state.TaskSnapshot`
  by :func:`build_ledger_seed` instead — the verbatim original request, the
  latest operator input ABOVE every summary line, authority, constraints,
  acceptance, changed paths, verification, open loops, open delegations,
  promised follow-ups.

The artifact stays the wrong-run guard's source in both cases: the
missing/corrupt/finished-ok guards run BEFORE the ledger is consulted, and the
ledger only ever replaces the prose BODY. An unreadable ledger (torn tail,
bumped schema, digest mismatch, ...) records a warning and falls back to the
prose recap; a ledger present while unarmed records an "ignored" warning; no
ledger at all is byte-identical to the pre-t17 behaviour.

Pure stdlib. Imports only from
``colleague.{artifact,feedback,escalation,contract,agents.state}``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from colleague.agents.state import (
    LedgerEvent,
    LedgerUnreadable,
    TaskSnapshot,
    ledger_path,
    read_ledger,
)
from colleague.artifact import find_artifact
from colleague.contract import OK, TaskResult
from colleague.escalation import build_continuation

#: The ``kind`` every continuation-ledger warning dict carries.
LEDGER_WARNING_KIND = "continuation-ledger"

#: Authority facts rendered from the ``operator_request`` / ``decision`` events
#: (the ledger's ``AUTHORITY_KEYS`` plus ``profile``); latest event wins.
_AUTHORITY_FACT_KEYS: tuple[str, ...] = (
    "no_pr",
    "mode",
    "role",
    "profile",
    "approval_ref",
    "thought_id",
)


class ContinuationError(Exception):
    """A continuation operation that cannot be honored."""


def resolve_continuation(
    repo: str | Path,
    ref: str,
    *,
    allow_completed: bool = False,
    agents_armed: bool = False,
    warnings: Optional[list[dict[str, Any]]] = None,
) -> tuple[str, str]:
    """Resolve *ref* to a prior work item and return ``(task_id, seed_text)``.

    Parameters
    ----------
    repo:
        The repository root path.
    ref:
        Either ``"last"`` (resolved via :func:`colleague.feedback.get_last_work`)
        or an explicit task-id string.
    allow_completed:
        When ``True``, allow continuing from a work item whose status is ``"ok"``.
        Default ``False`` raises :class:`ContinuationError` for completed items.
    agents_armed:
        The resolved ``agents`` mode flag (the caller passes it; default
        ``False`` keeps today's behaviour). When ``True`` AND the task ledger
        reads cleanly, the seed body is :func:`build_ledger_seed` over the
        rehydrated snapshot instead of the prose recap.
    warnings:
        Optional out-param. When a list is given, one
        ``{"kind": "continuation-ledger", "detail": ..., "ledger": ...}`` dict
        is appended for: a ledger present while unarmed (ignored); a ledger
        that is unreadable (reason + prose fallback). ``None`` records nothing.

    Returns
    -------
    tuple[str, str]
        ``(task_id, seed_text)`` where *seed_text* is a preamble + either the
        :func:`colleague.escalation.build_continuation` record + the original
        request verbatim (the prose path), or the :func:`build_ledger_seed`
        section (armed + readable ledger).

    Raises
    ------
    ContinuationError
        When the artifact is missing, corrupt, or the work item finished ok
        (unless *allow_completed* is ``True``).
    """
    repo_path = Path(repo)

    # Resolve the task id from the ref.
    if ref == "last":
        from colleague.feedback import get_last_work

        task_id = get_last_work(repo_path)
        if task_id is None:
            raise ContinuationError("no 'last' work item recorded for this repo yet")
    else:
        task_id = ref

    # Load the artifact.
    artifact_path = find_artifact(repo_path, task_id)
    if artifact_path is None:
        raise ContinuationError(f"no artifact for {task_id}")

    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        raise ContinuationError(f"corrupt artifact for {task_id}") from None
    # Valid JSON is not enough: a non-dict payload or one missing required keys
    # must stay inside the ContinuationError boundary, never a raw traceback.
    if not isinstance(data, dict):
        raise ContinuationError(f"corrupt artifact for {task_id}")
    try:
        result = TaskResult.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ContinuationError(f"corrupt artifact for {task_id}") from exc

    # Guard: ok-status artifact unless allow_completed.
    if result.status == OK and not allow_completed:
        raise ContinuationError(f"nothing to continue: {task_id} finished ok")

    request = result.stats.request
    preamble = f"You are CONTINUING work item {task_id} that stopped early. Prior state:\n\n"

    # The ledger seam (t17): only the BODY below the preamble is ever replaced,
    # and only when armed + readable. Every other outcome is the prose path.
    ledger = _ledger_read(repo_path, task_id, agents_armed=agents_armed, warnings=warnings)
    if ledger is not None:
        events, snapshot = ledger
        body = build_ledger_seed(
            snapshot,
            request=_request_text(events, fallback=request),
            latest_input=_latest_operator_input(events),
            request_facts=_request_authority_facts(events),
        )
        return (task_id, f"{preamble}{body}")

    # Build the seed text: preamble + continuation record + original request.
    record = build_continuation(result, result.stats)
    seed_text = f"{preamble}{record}\n\nOriginal request:\n\n{request}"

    return (task_id, seed_text)


# ---------------------------------------------------------------------------
# The ledger seam (t17)
# ---------------------------------------------------------------------------


def _warn(warnings: Optional[list[dict[str, Any]]], detail: str, ledger: Path) -> None:
    if warnings is not None:
        warnings.append({"kind": LEDGER_WARNING_KIND, "detail": detail, "ledger": str(ledger)})


def _ledger_read(
    repo_path: Path,
    task_id: str,
    *,
    agents_armed: bool,
    warnings: Optional[list[dict[str, Any]]],
) -> Optional[tuple[tuple[LedgerEvent, ...], TaskSnapshot]]:
    """``(events, snapshot)`` when armed and the task ledger reads cleanly,
    else ``None`` (with the warning recorded when the caller asked for it).
    Never raises: a ledger defect is a warning + the prose path."""
    try:
        path = ledger_path(repo_path, task_id)
    except ValueError:
        return None  # an id that cannot name a ledger has no ledger
    if not path.is_file():
        return None  # no ledger → byte-identical to the pre-t17 path, no warning
    if not agents_armed:
        _warn(
            warnings,
            "task ledger present but agents mode is not armed — ignored; "
            "seed built from the prose recap",
            path,
        )
        return None
    try:
        read = read_ledger(path)
    except LedgerUnreadable as exc:
        _warn(
            warnings,
            f"task ledger unreadable ({exc.reason}) — seed built from the prose recap",
            path,
        )
        return None
    return (read.events, read.snapshot)


def rehydrate_snapshot(repo: str | Path, task_id: str) -> Optional[TaskSnapshot]:
    """The replay-derived snapshot of ``task_id``'s ledger, or ``None`` when no
    ledger exists. Raises :class:`~colleague.agents.state.LedgerUnreadable`
    (fail-closed) for a ledger that is present but cannot be trusted."""
    path = ledger_path(repo, task_id)
    if not path.is_file():
        return None
    return read_ledger(path).snapshot


def _request_text(events: Sequence[LedgerEvent], *, fallback: str) -> str:
    """The verbatim original request: the first ``operator_request`` event's
    ``text`` when the ledger carries it, else the artifact's own verbatim copy
    (``stats.request``) — the ledger may hold only a ref to the message."""
    for e in events:
        if e.kind == "operator_request":
            text = e.data.get("text")
            if isinstance(text, str) and text:
                return text
            break
    return fallback


def _latest_operator_input(events: Sequence[LedgerEvent]) -> str:
    """The LATEST ``operator_input`` event's text (or its ref), ``""`` if none."""
    latest = ""
    for e in events:
        if e.kind == "operator_input":
            text = e.data.get("text")
            latest = text if isinstance(text, str) and text else str(e.data.get("ref", ""))
    return latest


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _label(entry: Mapping[str, Any]) -> str:
    """One deterministic bullet for a ledger entry: ``[id] text`` with the
    remaining facts (minus the replay-owned ``seq``) as ``key: value`` tail."""
    ident = entry.get("id") or entry.get("ref")
    text = entry.get("text")
    head = ""
    if ident:
        head += f"[{ident}] "
    if text:
        head += str(text)
    rest = {
        k: v
        for k, v in entry.items()
        if k not in ("id", "ref", "text", "seq") and v not in ("", None)
    }
    tail = ", ".join(f"{k}: {_scalar(rest[k])}" for k in sorted(rest))
    head = head.rstrip()
    if head and tail:
        return f"{head} ({tail})"
    return head or tail or f"seq:{entry.get('seq', '?')}"


def _bullets(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "_none_"


def _authority_facts(snapshot: TaskSnapshot) -> dict[str, Any]:
    """Authority flags carried by the decisions (latest wins); the original
    request's flags are not in the snapshot's decisions, so the caller folds
    them in via :func:`_request_facts`."""
    facts: dict[str, Any] = {}
    for d in snapshot.decisions:
        for k in _AUTHORITY_FACT_KEYS:
            if k in d:
                facts[k] = d[k]
    return facts


def build_ledger_seed(
    snapshot: TaskSnapshot,
    *,
    request: str,
    latest_input: str = "",
    request_facts: Optional[Mapping[str, Any]] = None,
) -> str:
    """Render the continuation seed BODY from a rehydrated task snapshot.

    Deterministic markdown (same snapshot + inputs → same text), in this fixed
    order: the original request VERBATIM; the latest operator input (ABOVE every
    summary line — it outranks the snapshot's summaries); authority (digest +
    the ``no_pr``/``mode``/``role``/``profile``/... facts the request and the
    decisions carry, latest decision wins); constraints; acceptance; changed
    paths; verification (failed checks first); open loops (incl. unreturned
    delegations, as replay derives them); open delegations; promised follow-ups
    (``decision`` events tagged ``follow_up: true`` — the ledger has no
    first-class follow-up kind, so the section is OMITTED when none is tagged);
    decisions. Empty collections render ``_none_`` — never invented.

    ``request_facts`` are the authority-bearing keys of the ``operator_request``
    event (``_request_authority_facts`` extracts them from the events);
    :func:`resolve_continuation` passes them through.
    """
    parts: list[str] = []
    parts.append(f"## Original request (verbatim)\n\n{request}\n")
    if latest_input:
        parts.append(
            "## Latest operator input (outranks every summary below)\n\n" f"{latest_input}\n"
        )

    facts: dict[str, Any] = dict(request_facts or {})
    facts.update(_authority_facts(snapshot))
    authority_lines = [f"authority_digest: `{snapshot.authority_digest}`"]
    if snapshot.original_request_ref:
        authority_lines.append(f"original_request_ref: {snapshot.original_request_ref}")
    if snapshot.active_thought:
        authority_lines.append(f"active_thought: {snapshot.active_thought}")
    for k in _AUTHORITY_FACT_KEYS:
        if k in facts:
            authority_lines.append(f"{k}: {_scalar(facts[k])}")
    if snapshot.episode:
        authority_lines.append(f"episode: {snapshot.episode}")
    parts.append("## Authority\n\n" + _bullets(authority_lines) + "\n")

    parts.append("## Constraints\n\n" + _bullets([_label(c) for c in snapshot.constraints]) + "\n")
    parts.append("## Acceptance\n\n" + _bullets([_label(a) for a in snapshot.acceptance]) + "\n")
    parts.append(
        "## Changed paths\n\n" + _bullets([f"`{p}`" for p in snapshot.changed_paths]) + "\n"
    )

    failed = [
        v for v in snapshot.verification if str(v.get("status", "")).lower() in _FAILED_STATUSES
    ]
    other = [v for v in snapshot.verification if v not in failed]
    verification_lines = [f"FAILED {_label(v)}" for v in failed] + [_label(v) for v in other]
    parts.append(
        f"## Verification ({len(failed)} failed)\n\n" + _bullets(verification_lines) + "\n"
    )

    open_delegations = [d for d in snapshot.delegations if not d.get("returned")]
    loops = [loop for loop in snapshot.open_loops if not (loop.get("kind") == "delegate")]
    parts.append("## Open loops\n\n" + _bullets([_label(loop) for loop in loops]) + "\n")
    parts.append(
        "## Open delegations\n\n"
        + _bullets(
            [f"[{d.get('id')}] child_ref: {d.get('child_ref') or '?'}" for d in open_delegations]
        )
        + "\n"
    )

    follow_ups = [d for d in snapshot.decisions if d.get("follow_up") is True]
    if follow_ups:
        parts.append(
            "## Promised follow-ups\n\n" + _bullets([_label(d) for d in follow_ups]) + "\n"
        )
    decisions = [d for d in snapshot.decisions if d not in follow_ups]
    parts.append("## Decisions\n\n" + _bullets([_label(d) for d in decisions]) + "\n")

    return "\n".join(parts)


#: Verification statuses rendered as failed checks (case-insensitive).
_FAILED_STATUSES = frozenset({"failed", "fail", "error", "errored", "red"})


def _request_authority_facts(events: Sequence[LedgerEvent]) -> dict[str, Any]:
    """The authority-bearing facts the first ``operator_request`` event carries."""
    for e in events:
        if e.kind == "operator_request":
            return {k: e.data[k] for k in _AUTHORITY_FACT_KEYS if k in e.data}
    return {}
