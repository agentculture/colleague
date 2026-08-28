"""colleague.resident.webtrust — the c43 ``web`` boundary for mesh turns.

This is NOT a second policy mechanism: it is the c19 trust boundary
(:mod:`colleague.resident.trust`) extended to one tool, expressed entirely
through the machinery that already exists —
:func:`colleague.tools.narrow_role_by_tool_set` (the composed value both
halves consume) and :func:`colleague.tools.curate_schemas` (the offered
half). Nothing here invents a refusal path: the SAME narrowed role is handed
to ``curate_schemas`` (never offered) and to ``ToolExecutor(allowlist=…)``
(refused if the model guesses the name anyway), exactly like the
change-content consumption lane does.

Two turn-scoped rules (spec decision c43):

1. **Withholding.** A turn that did NOT originate from the operator never
   sees ``web`` on its curated surface. A peer may ask the resident to read
   the repo (c19 downgrades it to the read-only ``explorer`` role); it may
   not steer the resident's outbound web access. :func:`turn_tool_set` /
   :func:`curate_turn_role` / :func:`curate_turn_schemas` express that as a
   narrowing of the turn's role — never a new allow/deny list.

2. **Relayed operator requests.** A request a Culture node forwards *on the
   operator's behalf* counts as operator-initiated (the operator, not the
   relaying node, is the author), but it must clear ONE explicit
   confirmation before the turn's first ``web`` fetch —
   :class:`WebConfirmationGate`. The first call yields the confirmation
   request and does not proceed; after an affirmative the gate is confirmed
   and further calls in the same turn proceed with no second prompt.

**Honest gap (reported, not invented).** The Culture protocol carries NO
marker for "this message relays the operator's own request" today: a
resident message reaches
:meth:`colleague.resident.appserver.AppserverHarness.feed_message` with a
``sender`` and a ``metadata`` mapping whose only transport-set key is
``mention`` (``colleague/resident/transport.py``), and whose only
colleague-read key is ``mode`` (``colleague/resident/trust.py``). Rather
than invent a field on the culture side, this module implements the rule
behind the marker one would expect —
:data:`RELAYED_OPERATOR_METADATA_KEY` — and defaults its ABSENCE to "peer"
(fail-safe: an unmarked message is never treated as the operator's). The
marker is only as trustworthy as the node that sets it, so it deliberately
grants the *web surface* only: write authority stays bound to the sender
identity in :func:`colleague.resident.trust.classify_request`, untouched
here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

from colleague.resident.trust import _is_operator
from colleague.web_schemas import WEB_TOOL_NAME, web_hidden

#: The metadata key a Culture node WOULD set to mark a message as carrying the
#: operator's own request (see the module docstring's honest gap). Absent — the
#: case today, always — means "peer", the fail-safe default. An accepted value
#: is either ``True`` or the operator identity string itself.
RELAYED_OPERATOR_METADATA_KEY = "relayed_operator"

#: The affirmatives that confirm a :class:`WebConfirmationGate`. Deliberately a
#: small closed set matched on the whole (stripped, lowercased, punctuation-free)
#: reply — never a substring search, so "no, go ahead and skip the web" cannot
#: read as a yes.
AFFIRMATIVES = frozenset(
    {
        "y",
        "yes",
        "yep",
        "yeah",
        "ok",
        "okay",
        "go",
        "go ahead",
        "confirm",
        "confirmed",
        "approve",
        "approved",
        "do it",
    }
)


@dataclass(frozen=True)
class TurnOrigin:
    """Where one inbound turn came from, for the c43 web boundary.

    Attributes:
        operator_initiated: ``True`` for the operator's own message AND for a
            message a node marked as relaying the operator's request.
        relayed: ``True`` only for the relayed case — the one that owes a
            confirmation before its first web fetch.
        reason: A human-readable explanation, suitable for a diagnostic line.
    """

    operator_initiated: bool
    relayed: bool
    reason: str


def classify_origin(
    *,
    sender: str,
    metadata: Optional[Mapping[str, object]] = None,
    operator_identity: Optional[str] = None,
) -> TurnOrigin:
    """Classify one turn's origin — direct operator, relayed operator, or peer.

    Reuses :func:`colleague.resident.trust._is_operator` (the SAME identity
    check every other resident trust decision makes — never a second one), so
    an unresolved *operator_identity* means "peer" here too: with no operator
    configured, nothing is operator-initiated and ``web`` is withheld from
    every turn (fail-safe).
    """
    metadata = metadata or {}
    if _is_operator(sender, operator_identity):
        return TurnOrigin(True, False, f"operator identity {sender!r} confirmed — web offered")

    marker = metadata.get(RELAYED_OPERATOR_METADATA_KEY)
    relayed = bool(operator_identity) and (marker is True or marker == operator_identity)
    if relayed:
        return TurnOrigin(
            True,
            True,
            f"{sender!r} relays operator {operator_identity!r}'s own request "
            f"({RELAYED_OPERATOR_METADATA_KEY}) — operator-initiated, one "
            "confirmation owed before the first web fetch",
        )

    return TurnOrigin(
        False,
        False,
        f"{sender!r} is not the operator (and marked no relayed operator request) — "
        f"withholding {WEB_TOOL_NAME!r} from this turn's tool surface",
    )


def _resolved_role(role: Any, repo_path: str, model: Optional[str]) -> Any:
    """Resolve a role NAME to its :class:`~colleague.roles.Role`, honouring overrides.

    A name is loaded through :func:`colleague.roles.load_role` — the same
    loader the loop uses — so an operator's ``.colleague/agents/<name>.md``
    override is what gets narrowed, never a stale built-in copy. ``None``
    (full surface) and an already-resolved ``Role`` pass through.
    """
    if not isinstance(role, str):
        return role
    from colleague.roles import load_role

    return load_role(role, repo_path, model) or role


def turn_tool_set(
    role: Any = None,
    *,
    allow_web: bool,
    repo_path: str = ".",
    model: Optional[str] = None,
) -> tuple[str, ...]:
    """The ``tool_set`` narrowing this turn must run under.

    ``()`` — the not-narrowed sentinel every consumer of
    :func:`colleague.tools.narrow_role_by_tool_set` already understands —
    whenever *allow_web* is ``True`` (an operator turn: byte-identical to a
    resident without this feature). Otherwise the role's own surface minus
    ``web`` AND ``web_survey`` (the purpose tool that reaches the web through a
    scout child — park v6 of the purpose-tools spec, gated at the purpose call):
    narrowing only ever REMOVES, so a role that never had them is unaffected.
    """
    if allow_web:
        return ()
    from colleague.tools import TOOL_NAMES

    resolved = _resolved_role(role, repo_path, model)
    allowlist = getattr(resolved, "tool_allowlist", None) or tuple(TOOL_NAMES)
    return tuple(name for name in allowlist if name not in (WEB_TOOL_NAME, "web_survey"))


def curate_turn_role(
    role: Any = None,
    *,
    allow_web: bool,
    repo_path: str = ".",
    model: Optional[str] = None,
) -> Any:
    """*role*, composed with this turn's web narrowing (the value BOTH halves take).

    Handed to :func:`colleague.tools.curate_schemas` (the offered half) and to
    ``ToolExecutor(allowlist=…)`` (the refusal half) — one value, so the two
    can never disagree.
    """
    from colleague.tools import narrow_role_by_tool_set

    tool_set = turn_tool_set(role, allow_web=allow_web, repo_path=repo_path, model=model)
    if not tool_set:
        return role
    return narrow_role_by_tool_set(_resolved_role(role, repo_path, model), tool_set)


def curate_turn_schemas(
    role: Any = None,
    *,
    allow_web: bool,
    repo_path: str = ".",
    model: Optional[str] = None,
) -> list[dict[str, Any]]:
    """The tool schemas actually OFFERED for this turn (``curate_schemas`` ∘ narrowing).

    The acceptance surface: a peer-originated turn's list never contains
    ``web``; an operator-originated turn's list contains it exactly when
    :func:`colleague.web_schemas.offered` says so (webglass on PATH,
    ``COLLEAGUE_WEB`` not ``0``).
    """
    from colleague.tools import curate_schemas

    return curate_schemas(
        curate_turn_role(role, allow_web=allow_web, repo_path=repo_path, model=model)
    )


def turn_lifecycle(
    role: Any = None,
    *,
    allow_web: bool,
    repo_path: str = ".",
    model: Optional[str] = None,
    existing: Any = None,
) -> Any:
    """The config attachment that carries this turn's narrowing into ``work()``.

    Both engines already read ``config.config_lifecycle``'s snapshot
    ``tool_set`` and feed it to :func:`colleague.tools.narrow_role_by_tool_set`
    before building the offered schemas AND the executor allow-list — that is
    the existing seam this rides, so no engine changes and no second gate.
    Returns *existing* unchanged when no narrowing is needed (``allow_web``),
    and otherwise a frozen, read-only
    :class:`colleague.subagents.FrozenChildConfigLifecycle` over *existing*'s
    snapshot with the narrowed ``tool_set`` folded in (an already-attached
    lifecycle keeps its other fields; there is none in the resident today).
    """
    tool_set = turn_tool_set(role, allow_web=allow_web, repo_path=repo_path, model=model)
    if not tool_set:
        return existing
    from colleague.configlifecycle import EpisodeConfigSnapshot
    from colleague.subagents import FrozenChildConfigLifecycle

    snapshot = getattr(existing, "snapshot", None) or EpisodeConfigSnapshot()
    return FrozenChildConfigLifecycle(replace(snapshot, tool_set=tool_set))


@dataclass(frozen=True)
class WebCallVerdict:
    """One relayed turn's verdict for one prospective ``web`` call.

    Attributes:
        allowed: Whether the call may proceed.
        confirmation_request: The ONE confirmation request to send, or
            ``None`` — either because the gate is confirmed, or because the
            request was already sent (c43 asks for exactly one per turn,
            never one per call).
        reason: A human-readable explanation for a diagnostic line.
    """

    allowed: bool
    confirmation_request: Optional[str]
    reason: str


class WebConfirmationGate:
    """The explicit confirmation a RELAYED operator request owes before web access.

    One gate per relayed turn. The first prospective ``web`` call yields the
    confirmation request and does NOT proceed; a further call while still
    unconfirmed is refused SILENTLY (no second prompt); an affirmative reply
    confirms the gate, and every call after it proceeds.

    Not a trust decision of its own: whether the turn is operator-initiated at
    all is :func:`classify_origin`'s answer (which reuses c19's identity
    check). This gate only adds the confirmation a *relayed* request owes.
    """

    def __init__(self, requester: str = "", *, operator_identity: Optional[str] = None) -> None:
        self.requester = requester
        self.operator_identity = operator_identity
        self.confirmed = False
        self.requested = False

    def awaiting(self) -> bool:
        """``True`` once the confirmation was asked for and no answer has confirmed it."""
        return self.requested and not self.confirmed

    def prompt(self) -> str:
        """The confirmation request text — names the relayer, the tool, and the answer."""
        return (
            f"{self.requester or 'a peer'} relayed a request from operator "
            f"{self.operator_identity or '(unresolved)'} that needs web access "
            f"(the {WEB_TOOL_NAME!r} tool). Reply 'yes' to authorize this turn's "
            "web fetches; anything else leaves them withheld."
        )

    def before_web_call(self) -> WebCallVerdict:
        """The verdict for ONE prospective ``web`` call in this turn."""
        if self.confirmed:
            return WebCallVerdict(True, None, "web access confirmed for this turn")
        if not self.requested:
            self.requested = True
            return WebCallVerdict(
                False,
                self.prompt(),
                "first web fetch of a relayed operator request — confirmation requested",
            )
        return WebCallVerdict(
            False,
            None,
            "still awaiting the operator's confirmation — the request was already sent once",
        )

    def affirm(self, text: str) -> bool:
        """Confirm the gate when *text* is an affirmative; return whether it now is.

        A non-affirmative answer leaves the gate unconfirmed (and still
        ``requested``, so it never re-prompts on its own).
        """
        if is_affirmative(text):
            self.confirmed = True
        return self.confirmed

    def reset(self) -> None:
        """Return to pristine state after granting one turn's web access.

        c43 owes the confirmation once per relayed TURN — not once per
        relaying sender for the rest of the harness lifetime. Called by
        :func:`resolve_web_access` the moment a confirmed gate grants a
        dispatch, so the NEXT relayed turn from the same sender starts over.
        """
        self.confirmed = False
        self.requested = False


@dataclass(frozen=True)
class WebAccessVerdict:
    """One turn's resolved web posture, as the resident needs it.

    Attributes:
        allow_web: Whether ``web`` may ride this turn's tool surface.
        reply: One line to send back — the confirmation request, or the
            acknowledgement of an affirmative — or ``None`` (the common case).
        handled: ``True`` when *body* was ONLY the operator's affirmative, so
            there is no work item to dispatch for it.
    """

    allow_web: bool
    reply: Optional[str]
    handled: bool = False


def resolve_web_access(
    gates: "dict[str, WebConfirmationGate]",
    *,
    sender: str,
    origin: TurnOrigin,
    body: str,
    operator_identity: Optional[str] = None,
) -> WebAccessVerdict:
    """Resolve one inbound turn's web posture under c43 (the resident's entry point).

    * A peer turn: ``web`` withheld, nothing said (the surface simply never
      carries it — c19 already told the peer what it may ask for).
    * The operator's own turn: ``web`` offered, byte-identical to before.
    * A RELAYED operator turn: offered only once the sender's gate is
      confirmed. The first such turn requests confirmation ONCE and runs with
      ``web`` withheld (the request is never held hostage — only its web
      access is); a bare affirmative from that sender confirms the gate and is
      answered instead of dispatched. The confirmation is spent by the NEXT
      dispatched relayed turn: granting it resets the gate (c43 — once per
      turn, never once per sender for the harness lifetime), so the turn
      after that owes a fresh confirmation.

    ``web`` being unofferable at all (no webglass on PATH, ``COLLEAGUE_WEB=0``)
    short-circuits: there is no fetch to confirm, so no confirmation is asked.
    """
    if not origin.operator_initiated:
        return WebAccessVerdict(False, None)
    if not origin.relayed:
        return WebAccessVerdict(True, None)
    if not web_offerable():
        return WebAccessVerdict(False, None)

    gate = gates.setdefault(
        sender, WebConfirmationGate(sender, operator_identity=operator_identity)
    )
    if gate.awaiting() and gate.affirm(body):
        return WebAccessVerdict(True, "web access confirmed for this turn.", handled=True)
    if gate.confirmed:
        gate.reset()  # c43: spent by THIS turn — the next one owes a fresh confirmation.
        return WebAccessVerdict(True, None)
    verdict = gate.before_web_call()
    return WebAccessVerdict(verdict.allowed, verdict.confirmation_request)


def is_affirmative(text: str) -> bool:
    """Whether *text* is one of :data:`AFFIRMATIVES` (whole answer, not a substring)."""
    cleaned = (text or "").strip().strip(".!,").lower()
    return cleaned in AFFIRMATIVES


def web_offerable() -> bool:
    """Whether ``web`` could be offered at all right now (webglass on PATH + knob).

    The resident asks before requesting a confirmation: with no web tool on
    the surface there is no fetch to confirm, so a relayed turn must not be
    prompted for one.
    """
    return not web_hidden()


__all__ = [
    "AFFIRMATIVES",
    "RELAYED_OPERATOR_METADATA_KEY",
    "TurnOrigin",
    "WebAccessVerdict",
    "WebCallVerdict",
    "WebConfirmationGate",
    "classify_origin",
    "curate_turn_role",
    "curate_turn_schemas",
    "is_affirmative",
    "resolve_web_access",
    "turn_lifecycle",
    "turn_tool_set",
    "web_offerable",
]
