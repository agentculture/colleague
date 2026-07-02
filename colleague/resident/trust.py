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

**Media references (task t12).** A mesh request MAY reference local media via
a line-anchored ``attach: <path>`` token (parsed by
:mod:`colleague.resident.appserver`, which owns the token grammar/cap — this
module owns only the trust boundary a candidate path must clear).
:func:`check_attachment_path` applies the SAME operator/non-operator split as
:func:`classify_request` (via the shared :func:`_is_operator` check — no
second trust decision path): the operator may reference any local path; a
non-operator's path must resolve **inside** the target repo's working tree,
or it is refused before :func:`colleague.media.validate_attachment` (or
anything else) ever reads the file's content. This is the anti-exfiltration
rule — a non-operator asking the resident to read and possibly summarize/echo
back an arbitrary local file (e.g. ``~/.ssh/id_rsa``) is exactly the kind of
"beyond its limits" request c19 already refuses for write access; the same
posture applies to *reading* a path outside the repo on a stranger's say-so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class AttachmentDecision:
    """The trust-policy verdict for one mesh-referenced attachment path (t12).

    Attributes:
        allowed: Whether *path* may be handed to
            :func:`colleague.media.validate_attachment` for this requester.
        reason: A human-readable explanation for a recorded/diagnostic note —
            always names the path, and on refusal names the rule that
            refused it (the anti-exfiltration containment rule) so a denial
            is never a bare boolean.
    """

    allowed: bool
    reason: str


def _is_operator(sender: str, operator_identity: Optional[str]) -> bool:
    """The single operator-identity check shared by every trust decision here.

    :func:`classify_request` and :func:`check_attachment_path` both call
    this — deliberately, so an attachment's trust boundary can never drift
    from a request's trust boundary (this task must not invent a *second*
    trust decision path; it reuses this exact one). Same fail-safe default
    as ``classify_request``: an unresolved ``operator_identity`` (``None`` or
    empty) never matches, so an unconfigured operator never accidentally
    grants unrestricted access.
    """
    return bool(operator_identity) and sender == operator_identity


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

    if _is_operator(sender, operator_identity):
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


def check_attachment_path(
    path: str,
    *,
    repo_path: str,
    sender: str,
    operator_identity: Optional[str] = None,
) -> AttachmentDecision:
    """Anti-exfiltration containment check for one mesh ``attach:`` path (t12).

    Called BEFORE :func:`colleague.media.validate_attachment` — this function
    itself never reads a file's *content*, only path metadata (``Path.resolve()``
    stats components to follow symlinks; it does not open the target).

    * **Operator** (:func:`_is_operator` — the exact same check
      :func:`classify_request` uses, not a new trust decision path): any
      local path is allowed, mirroring the operator's unrestricted
      write-capable authority under c19.
    * **Non-operator**: *path* must resolve to somewhere INSIDE *repo_path*'s
      working tree. A **relative** *path* is anchored to *repo_path* (not the
      resident process's current working directory) before resolution — a
      repo-relative reference like ``docs/img.png`` must not depend on
      wherever the process happens to be running; an **absolute** *path* is
      resolved as-is. Both the candidate and *repo_path* are then resolved
      with ``Path.resolve()`` (which follows symlinks) before the strict
      containment check (``Path.is_relative_to``), so a symlink placed
      *inside* the repo that points *outside* it is caught too — not just a
      literal ``..`` escape. Anything not contained is refused with a reason
      naming both the path and the rule; refusal never raises — the caller
      drops the one attachment and continues the (read-only) request.

    Args:
        path: The raw ``attach:`` token value, exactly as parsed from the
            request text (not yet validated to exist).
        repo_path: The target repo's working-tree root the request will run
            against (``AppserverHarness._repo_path``).
        sender: The requesting identity (``Message.sender``).
        operator_identity: The resolved operator identity, or ``None`` if
            unconfigured (fail-safe: every requester is then non-operator).

    Returns:
        An :class:`AttachmentDecision`.
    """
    if _is_operator(sender, operator_identity):
        return AttachmentDecision(
            True,
            f"operator identity {sender!r} confirmed — any local path is allowed",
        )

    try:
        repo_root = Path(repo_path).resolve()
        candidate = Path(path)
        candidate_abs = candidate if candidate.is_absolute() else (repo_root / candidate)
        resolved = candidate_abs.resolve()
    except (OSError, RuntimeError) as exc:
        return AttachmentDecision(
            False,
            f"attach: {path!r} could not be resolved ({exc}) — refusing for "
            f"non-operator {sender!r} (anti-exfiltration containment rule)",
        )

    contained = resolved == repo_root or resolved.is_relative_to(repo_root)
    if not contained:
        return AttachmentDecision(
            False,
            f"attach: {path!r} resolves to {resolved} which is outside the repo "
            f"working tree {repo_root} — refusing for non-operator {sender!r} "
            "(anti-exfiltration containment rule: a non-operator's attachment "
            "must resolve inside the repo)",
        )

    return AttachmentDecision(
        True,
        f"attach: {path!r} resolves inside the repo working tree — allowed for "
        f"non-operator {sender!r}",
    )


__all__ = [
    "ALLOW_READ_ONLY",
    "ALLOW_WRITE",
    "MODE_METADATA_KEY",
    "READ_ONLY_ROLE",
    "REFUSE",
    "WRITE_MODE_VALUE",
    "AttachmentDecision",
    "RequestDecision",
    "check_attachment_path",
    "classify_request",
]
