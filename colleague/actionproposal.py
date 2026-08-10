"""ActionProposal contract: binds one proposed repository action to exactly one Thought (t9).

Pure stdlib, no I/O, no subprocess, no network — same discipline as
:mod:`colleague.thought`.

This module defines the worker-seat contract for binding a proposed action
to a single committed thought. An ``ActionProposal`` carries the *what*
(proposed_action) and the *why it should work* (expected_effect), plus
optional evidence references and a consequentiality flag.

Refuse-whole validation (mirrors :mod:`colleague.thought` / :mod:`colleague.lattice`)
--------------------------------------------------------------------------------------

Unknown/extra keys, wrong-typed fields, missing required fields, and a
thought_id that is not live (or is superseded) all refuse the WHOLE
proposal — never stripping the offending part and keeping the rest. A
refused proposal is not a partial or repaired proposal; the caller gets
an :class:`ActionProposalVerdict` with ``allowed=False`` and a legible
``reason``, and **never raises**.

Thought-id lifecycle validation
--------------------------------

``validate_action_proposal(raw_dict, live_thought_ids, superseded_thought_ids)``
additionally checks the thought_id against the caller's live/superseded sets:

* If ``thought_id`` is not in ``live_thought_ids``, the proposal is refused
  with a reason naming the missing thought_id.
* If ``thought_id`` is in ``superseded_thought_ids``, the proposal is refused
  with a DISTINCT reason that mentions re-evaluation — the action must route
  back for re-evaluation and is never silently retargeted to another thought.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, FrozenSet, Optional

#: The only valid keys on a raw ActionProposal payload. Anything else
#: refuses the WHOLE proposal (unknown-key stance, mirroring
#: colleague.thought / colleague.lattice).
_ALLOWED_KEYS = frozenset(
    {
        "thought_id",
        "action_id",
        "proposed_action",
        "expected_effect",
        "evidence_refs",
        "consequential",
    }
)

#: Required, non-empty string keys on a raw ActionProposal payload.
_REQUIRED_STRING_KEYS = frozenset({"thought_id", "action_id", "proposed_action", "expected_effect"})


# ---------------------------------------------------------------------------
# ActionProposalVerdict — structured acceptance / refusal result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionProposalVerdict:
    """The outcome of validating one raw action-proposal payload.

    Attributes
    ----------
    allowed:
        ``True`` when the payload passes every check.
    reason:
        A human-readable explanation, populated ONLY when ``allowed`` is
        ``False`` (an allowed verdict carries an empty reason).
    """

    allowed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# ActionProposal — the proposed action bound to exactly one thought
# ---------------------------------------------------------------------------


@dataclass
class ActionProposal:
    """A proposed repository action bound to exactly one thought.

    Fields
    ------
    thought_id:
        The ``thought_id`` of the thought this action is bound to.
    action_id:
        An opaque, caller-assigned identifier for this action.
    proposed_action:
        What the action proposes to do in the repository.
    expected_effect:
        The observable effect the action is expected to produce.
    evidence_refs:
        Opaque reference ids a reader resolves back to actual evidence
        (tool results, prior thoughts, etc.). Defaults to ``[]``.
    consequential:
        Whether this action is consequential (e.g. destructive,
        irreversible, or security-sensitive). Defaults to ``False``.
    """

    thought_id: str
    action_id: str
    proposed_action: str
    expected_effect: str
    evidence_refs: list[str] = field(default_factory=list)
    consequential: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize this proposal to a plain dict.

        The output is suitable for JSON round-tripping and is accepted by
        :func:`from_dict` to produce an equal :class:`ActionProposal`.
        """
        return {
            "thought_id": self.thought_id,
            "action_id": self.action_id,
            "proposed_action": self.proposed_action,
            "expected_effect": self.expected_effect,
            "evidence_refs": list(self.evidence_refs),
            "consequential": self.consequential,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionProposal":
        """Coerce an already-validated action-proposal-shaped mapping into
        an :class:`ActionProposal`. Callers that read untrusted input should
        run :func:`validate_action_proposal` first — this constructor does
        not re-validate; it is the artifact-readback half of the round-trip."""
        return cls(
            thought_id=str(data.get("thought_id", "")),
            action_id=str(data.get("action_id", "")),
            proposed_action=str(data.get("proposed_action", "")),
            expected_effect=str(data.get("expected_effect", "")),
            evidence_refs=[str(x) for x in data.get("evidence_refs", [])],
            consequential=bool(data.get("consequential", False)),
        )


# ---------------------------------------------------------------------------
# validate_action_proposal — the public refuse-whole entry point
# ---------------------------------------------------------------------------


def _refuse_not_dict(
    data: object,
    live_thought_ids: FrozenSet[str] = frozenset(),
    superseded_thought_ids: FrozenSet[str] = frozenset(),
) -> Optional[ActionProposalVerdict]:
    if isinstance(data, dict):
        return None
    return ActionProposalVerdict(
        False, f"refused: input is not a JSON object (got {type(data).__name__})"
    )


def _refuse_unknown_keys(
    data: dict[str, Any],
    live_thought_ids: FrozenSet[str] = frozenset(),
    superseded_thought_ids: FrozenSet[str] = frozenset(),
) -> Optional[ActionProposalVerdict]:
    extra = [k for k in data if k not in _ALLOWED_KEYS]
    if not extra:
        return None
    return ActionProposalVerdict(
        False,
        f"refused: unknown key(s) {extra!r} on action-proposal payload "
        f"(only {sorted(_ALLOWED_KEYS)!r} are valid)",
    )


def _refuse_missing_required(
    data: dict[str, Any],
    live_thought_ids: FrozenSet[str] = frozenset(),
    superseded_thought_ids: FrozenSet[str] = frozenset(),
) -> Optional[ActionProposalVerdict]:
    missing = [k for k in _REQUIRED_STRING_KEYS if k not in data]
    if not missing:
        return None
    return ActionProposalVerdict(False, f"refused: missing required key(s) {missing!r}")


def _refuse_bad_string_fields(
    data: dict[str, Any],
    live_thought_ids: FrozenSet[str] = frozenset(),
    superseded_thought_ids: FrozenSet[str] = frozenset(),
) -> Optional[ActionProposalVerdict]:
    for key in _REQUIRED_STRING_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            return ActionProposalVerdict(
                False,
                f"refused: {key!r} must be a non-empty (non-whitespace) string",
            )
    return None


def _refuse_bad_list_fields(
    data: dict[str, Any],
    live_thought_ids: FrozenSet[str] = frozenset(),
    superseded_thought_ids: FrozenSet[str] = frozenset(),
) -> Optional[ActionProposalVerdict]:
    if "evidence_refs" not in data:
        return None
    value = data["evidence_refs"]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return ActionProposalVerdict(False, "refused: 'evidence_refs' must be a list of strings")
    return None


def _refuse_bad_bool_fields(
    data: dict[str, Any],
    live_thought_ids: FrozenSet[str] = frozenset(),
    superseded_thought_ids: FrozenSet[str] = frozenset(),
) -> Optional[ActionProposalVerdict]:
    if "consequential" not in data:
        return None
    value = data["consequential"]
    if not isinstance(value, bool):
        return ActionProposalVerdict(False, "refused: 'consequential' must be a boolean")
    return None


def _refuse_thought_id_superseded(
    data: dict[str, Any],
    live_thought_ids: FrozenSet[str] = frozenset(),
    superseded_thought_ids: FrozenSet[str] = frozenset(),
) -> Optional[ActionProposalVerdict]:
    thought_id = data.get("thought_id")
    if thought_id not in superseded_thought_ids:
        return None
    return ActionProposalVerdict(
        False,
        f"refused: thought_id {thought_id!r} is superseded — this action must "
        f"route back for re-evaluation and is never silently retargeted to "
        f"another thought",
    )


def _refuse_thought_id_not_live(
    data: dict[str, Any],
    live_thought_ids: FrozenSet[str],
    superseded_thought_ids: FrozenSet[str] = frozenset(),
) -> Optional[ActionProposalVerdict]:
    thought_id = data.get("thought_id")
    if thought_id in live_thought_ids:
        return None
    return ActionProposalVerdict(
        False,
        f"refused: thought_id {thought_id!r} is not in the set of live thoughts "
        f"(only {sorted(live_thought_ids)!r} are live)",
    )


def validate_action_proposal(
    proposal: object,
    live_thought_ids: FrozenSet[str],
    superseded_thought_ids: FrozenSet[str],
) -> ActionProposalVerdict:
    """Validate a raw action-proposal payload against the fixed schema.

    A valid payload is a ``dict`` carrying ``thought_id``/``action_id``/
    ``proposed_action``/``expected_effect`` (non-empty strings), optionally
    ``evidence_refs`` (a list of strings, defaulting to empty), and
    optionally ``consequential`` (a bool, defaulting to ``False``).
    Unknown keys, missing required keys, wrong-typed fields, a thought_id
    not in ``live_thought_ids``, or a thought_id in ``superseded_thought_ids``
    all refuse the WHOLE proposal — never stripping the offending part and
    keeping the rest.

    The superseded-thought refusal carries a DISTINCT reason that mentions
    re-evaluation; it is never silently retargeted to another thought.

    Returns an :class:`ActionProposalVerdict`. **Never raises.**
    """
    for refuse in (
        _refuse_not_dict,
        _refuse_unknown_keys,
        _refuse_missing_required,
        _refuse_bad_string_fields,
        _refuse_bad_list_fields,
        _refuse_bad_bool_fields,
        _refuse_thought_id_superseded,
        _refuse_thought_id_not_live,
    ):
        verdict = refuse(
            proposal, live_thought_ids, superseded_thought_ids
        )  # type: ignore[arg-type]
        if verdict is not None:
            return verdict
    return ActionProposalVerdict(True)
