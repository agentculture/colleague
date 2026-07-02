"""colleague.resident.trust — the c19 trust-policy classifier for mesh work requests.

Trust model (spec decision c19, plan task t13): **any** Culture mesh member may
*ask* the resident to do work; only the **operator** identity is *authoritative*.
Concretely:

* The operator's own requests are unrestricted (:data:`ALLOW_WRITE`) — the
  operator can always confirm/authorize consequential (write-capable) work,
  mirroring the ``devague`` destination tool's "only operator-confirmed claims
  are authoritative" convention documented in ``CLAUDE.md``.
* A non-operator's plain request is downgraded to a **read-only** role
  (:data:`ALLOW_READ_ONLY`) — a peer may ask the resident to investigate
  (explore/review), but not to write to the repo on their say-so alone. The
  read-only built-in roles (``colleague/roles.py`` ``BUILTIN_ROLES``)
  *provably* cannot mutate the tree (``write_file``/``edit_file``/
  ``run_command`` are all withheld), so this downgrade is a structural
  guarantee, not merely a prompt instruction.
* A non-operator's *explicit* request for write-capable work is **refused**
  (:data:`REFUSE`) — "beyond its limits" (spec c19): the resident does not
  silently grant write access to an unauthenticated peer just because they
  asked for it more insistently. The refusal reply names the operator so a
  requester knows how to escalate.

This module is deliberately synchronous and asyncio-free — pure classification
logic, unit-testable without a ``Harness``/``Supervisor`` in the loop, and
importable with **zero** third-party dependencies (no ``agent_lifecycle``
import here at all — only :class:`~agent_lifecycle.runtime.message.Message`'s
``sender``/``metadata`` *values* are read by the caller and passed in as plain
``str``/``Mapping``, so this module never needs the runtime seam). The single
caller is :mod:`colleague.resident.appserver`.

Follow-up (documented, not built): spec c19 says "in doubt, the resident MAY
consult peers" — there is no group-intelligence / peer-consultation hook here;
a plain binary operator/non-operator classification is v0. A future increment
could let :func:`classify_request` consult a peer roster before refusing, but
that is out of scope for this task.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

#: Metadata key a caller may set on a request ``Message`` to explicitly ask
#: for write-capable work (e.g. ``metadata={"mode": "write"}``). Absence, or
#: any other value, is treated as a plain (read-only-eligible) request.
MODE_METADATA_KEY = "mode"
WRITE_MODE_VALUE = "write"

#: The three possible trust-policy verdicts (:attr:`RequestDecision.outcome`).
ALLOW_WRITE = "allow_write"
ALLOW_READ_ONLY = "allow_read_only"
REFUSE = "refuse"

#: The read-only role name a downgraded (non-operator) request is dispatched
#: under — see ``colleague/roles.py`` ``BUILTIN_ROLES["explorer"]``.
READ_ONLY_ROLE = "explorer"


@dataclass(frozen=True)
class RequestDecision:
    """The trust-policy verdict for one inbound work request.

    Attributes:
        outcome: One of :data:`ALLOW_WRITE`, :data:`ALLOW_READ_ONLY`, or
            :data:`REFUSE`.
        reason: A human-readable explanation, suitable for echoing straight
            back to the requester (the refusal path) or for a diagnostic log
            line (the allow paths).
        role: The subagent role name to dispatch the work item under, or
            ``None`` for an unrestricted (operator, write-capable) dispatch.
            Always :data:`READ_ONLY_ROLE` for :data:`ALLOW_READ_ONLY`, always
            ``None`` for :data:`ALLOW_WRITE`, and irrelevant (also ``None``)
            for :data:`REFUSE` — a refused request is never dispatched.
    """

    outcome: str
    reason: str
    role: Optional[str] = None


def classify_request(
    *,
    sender: str,
    metadata: Optional[Mapping[str, object]] = None,
    operator_identity: Optional[str] = None,
) -> RequestDecision:
    """Classify one inbound work request under the c19 trust model.

    Args:
        sender: The requesting identity (``Message.sender``).
        metadata: The request's metadata mapping (``Message.metadata``); may
            carry ``{"mode": "write"}`` to explicitly ask for write access.
            ``None`` is treated as empty.
        operator_identity: The resolved operator identity (see
            :mod:`colleague.identity`). ``None`` (unresolved / unconfigured)
            means **every** requester — including one whose ``sender`` string
            happens to match nothing in particular — is treated as
            non-operator: an unresolved operator identity must never silently
            grant write access (fail-safe default).

    Returns:
        A :class:`RequestDecision` naming the verdict, the reason, and (for
        the two ``allow`` verdicts) the role to dispatch under.
    """
    metadata = metadata or {}
    wants_write = metadata.get(MODE_METADATA_KEY) == WRITE_MODE_VALUE

    is_operator = bool(operator_identity) and sender == operator_identity
    if is_operator:
        return RequestDecision(
            ALLOW_WRITE,
            f"operator identity {sender!r} confirmed — write-capable work authorized",
            role=None,
        )

    if wants_write:
        return RequestDecision(
            REFUSE,
            f"{sender!r} asked for write-capable work but is not the operator "
            f"({operator_identity!r}) — refusing beyond my limits; ask the operator "
            "to confirm, or request a read-only explore/review instead",
            role=None,
        )

    return RequestDecision(
        ALLOW_READ_ONLY,
        f"{sender!r} is not the operator — running read-only ({READ_ONLY_ROLE}); "
        "ask the operator for write-capable work",
        role=READ_ONLY_ROLE,
    )


__all__ = [
    "ALLOW_READ_ONLY",
    "ALLOW_WRITE",
    "MODE_METADATA_KEY",
    "READ_ONLY_ROLE",
    "REFUSE",
    "WRITE_MODE_VALUE",
    "RequestDecision",
    "classify_request",
]
