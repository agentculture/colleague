"""ActionProposal contract tests (t9).

Covers the acceptance criteria for the ActionProposal module
(:mod:`colleague.actionproposal`):

* AC1 — an ActionProposal dataclass carries thought_id/action_id/
  proposed_action/expected_effect/evidence_refs/consequential with strict,
  refuse-whole validation (mirroring colleague.thought's unknown-key stance).
* AC2 — validate_action_proposal refuses when thought_id is not in
  live_thought_ids, and refuses with a DISTINCT reason when thought_id is
  in superseded_thought_ids (must mention re-evaluation, never silently
  retarget).
* AC3 — to_dict / from_dict round-trip exactly.
"""

from __future__ import annotations

import json

from colleague.actionproposal import (
    ActionProposal,
    ActionProposalVerdict,
    validate_action_proposal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: A minimal valid raw action-proposal payload.
_VALID_PROPOSAL: dict = {
    "thought_id": "thought-17",
    "action_id": "action-1",
    "proposed_action": "Add retry logic to the request handler",
    "expected_effect": "Transient failures are absorbed without user-visible impact",
}

#: A fully-populated valid payload.
_FULL_PROPOSAL: dict = {
    "thought_id": "thought-17",
    "action_id": "action-1",
    "proposed_action": "Add retry logic to the request handler",
    "expected_effect": "Transient failures are absorbed without user-visible impact",
    "evidence_refs": ["tool-result-3", "thought-16"],
    "consequential": True,
}

#: Set of live (non-superseded) thought ids used in tests.
_LIVE_THOUGHT_IDS = frozenset({"thought-17", "thought-18"})

#: Set of superseded thought ids used in tests.
_SUPERSEDED_THOUGHT_IDS = frozenset({"thought-16"})


# ===========================================================================
# AC1 — ActionProposal dataclass, strict refuse-whole validation
# ===========================================================================


def test_valid_proposal_accepted() -> None:
    """A well-formed proposal with all required fields is accepted."""
    result = validate_action_proposal(_VALID_PROPOSAL, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is True
    assert result.reason == ""


def test_full_proposal_accepted() -> None:
    """A fully-populated proposal (with evidence_refs and consequential) is accepted."""
    result = validate_action_proposal(_FULL_PROPOSAL, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is True


def test_minimal_required_only_accepted() -> None:
    """Only thought_id/action_id/proposed_action/expected_effect are required;
    evidence_refs defaults to [] and consequential defaults to False."""
    result = validate_action_proposal(_VALID_PROPOSAL, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is True


def test_missing_required_key_refuses_whole() -> None:
    """Missing any of the four required keys refuses the WHOLE proposal."""
    for key in ("thought_id", "action_id", "proposed_action", "expected_effect"):
        payload = dict(_VALID_PROPOSAL)
        del payload[key]
        result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
        assert result.allowed is False, f"expected refusal for missing {key!r}"
        assert key in result.reason


def test_empty_required_string_refuses_whole() -> None:
    """An empty or whitespace-only required string field refuses the WHOLE proposal."""
    for key in ("thought_id", "action_id", "proposed_action", "expected_effect"):
        payload = dict(_VALID_PROPOSAL)
        payload[key] = "   "
        result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
        assert result.allowed is False, f"expected refusal for empty {key!r}"


def test_unknown_key_refuses_whole() -> None:
    """An extra key not in the schema refuses the WHOLE proposal."""
    payload = dict(_VALID_PROPOSAL)
    payload["unexpected_field"] = "surprise"
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False
    assert "unexpected_field" in result.reason


def test_non_string_thought_id_refuses_whole() -> None:
    payload = dict(_VALID_PROPOSAL)
    payload["thought_id"] = 42
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False


def test_non_string_action_id_refuses_whole() -> None:
    payload = dict(_VALID_PROPOSAL)
    payload["action_id"] = 42
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False


def test_non_string_proposed_action_refuses_whole() -> None:
    payload = dict(_VALID_PROPOSAL)
    payload["proposed_action"] = 42
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False


def test_non_string_expected_effect_refuses_whole() -> None:
    payload = dict(_VALID_PROPOSAL)
    payload["expected_effect"] = 42
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False


def test_non_list_evidence_refs_refuses_whole() -> None:
    payload = dict(_VALID_PROPOSAL)
    payload["evidence_refs"] = "not a list"
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False
    assert "evidence_refs" in result.reason


def test_non_string_item_in_evidence_refs_refuses_whole() -> None:
    """A list field with a non-string item refuses the WHOLE proposal."""
    payload = dict(_VALID_PROPOSAL)
    payload["evidence_refs"] = ["fine", {"nested": "object"}]
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False


def test_non_bool_consequential_refuses_whole() -> None:
    payload = dict(_VALID_PROPOSAL)
    payload["consequential"] = "yes"
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False


def test_consequential_true_accepted() -> None:
    payload = dict(_VALID_PROPOSAL)
    payload["consequential"] = True
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is True


def test_consequential_false_accepted() -> None:
    payload = dict(_VALID_PROPOSAL)
    payload["consequential"] = False
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is True


def test_non_dict_input_refuses_whole() -> None:
    result = validate_action_proposal("just a string", _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False


def test_never_raises_on_garbage_input() -> None:
    for garbage in (None, 5, [], {"thought_id": None}):
        result = validate_action_proposal(garbage, _LIVE_THOUGHT_IDS, frozenset())
        assert isinstance(result, ActionProposalVerdict)
        assert result.allowed is False


def test_action_proposal_dataclass_carries_all_named_fields() -> None:
    """The ActionProposal dataclass carries exactly the fields the acceptance
    criterion names."""
    ap = ActionProposal(
        thought_id="thought-17",
        action_id="action-1",
        proposed_action="Add retry logic",
        expected_effect="Transient failures absorbed",
        evidence_refs=["ref-1"],
        consequential=True,
    )
    assert ap.thought_id == "thought-17"
    assert ap.action_id == "action-1"
    assert ap.proposed_action == "Add retry logic"
    assert ap.expected_effect == "Transient failures absorbed"
    assert ap.evidence_refs == ["ref-1"]
    assert ap.consequential is True


def test_action_proposal_defaults() -> None:
    """Default values: evidence_refs=[], consequential=False."""
    ap = ActionProposal(
        thought_id="t1",
        action_id="a1",
        proposed_action="do it",
        expected_effect="it is done",
    )
    assert ap.evidence_refs == []
    assert ap.consequential is False


# ===========================================================================
# AC2 — thought_id lifecycle validation (live vs superseded)
# ===========================================================================


def test_thought_id_not_in_live_refuses() -> None:
    """A thought_id that is not in live_thought_ids refuses the proposal."""
    payload = dict(_VALID_PROPOSAL)
    payload["thought_id"] = "thought-99"  # not in _LIVE_THOUGHT_IDS
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is False
    assert "thought_id" in result.reason


def test_thought_id_in_superseded_refuses_with_re_evaluation_reason() -> None:
    """A thought_id that is in superseded_thought_ids refuses with a DISTINCT
    reason that mentions re-evaluation and never silently retargets."""
    payload = dict(_VALID_PROPOSAL)
    payload["thought_id"] = "thought-16"  # in _SUPERSEDED_THOUGHT_IDS
    result = validate_action_proposal(payload, _LIVE_THOUGHT_IDS, _SUPERSEDED_THOUGHT_IDS)
    assert result.allowed is False
    # The reason must mention re-evaluation
    assert "re-evaluation" in result.reason.lower() or "re-evaluate" in result.reason.lower()
    # The reason must NOT suggest silently retargeting to another thought
    assert "retarget" not in result.reason.lower() or "not" in result.reason.lower()


def test_superseded_reason_is_distinct_from_not_in_live_reason() -> None:
    """The refusal reason for a superseded thought_id must be distinct from
    the reason for a thought_id that simply doesn't exist in live set."""
    payload_live_missing = dict(_VALID_PROPOSAL)
    payload_live_missing["thought_id"] = "thought-99"
    result_live_missing = validate_action_proposal(
        payload_live_missing, _LIVE_THOUGHT_IDS, frozenset()
    )

    payload_superseded = dict(_VALID_PROPOSAL)
    payload_superseded["thought_id"] = "thought-16"
    result_superseded = validate_action_proposal(
        payload_superseded, _LIVE_THOUGHT_IDS, _SUPERSEDED_THOUGHT_IDS
    )

    # Both must refuse
    assert result_live_missing.allowed is False
    assert result_superseded.allowed is False
    # The reasons must be different
    assert result_live_missing.reason != result_superseded.reason
    # The superseded reason must mention re-evaluation
    assert (
        "re-evaluation" in result_superseded.reason.lower()
        or "re-evaluate" in result_superseded.reason.lower()
    )


def test_live_thought_id_accepted() -> None:
    """A thought_id that is in live_thought_ids is accepted."""
    result = validate_action_proposal(_VALID_PROPOSAL, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is True


def test_superseded_set_empty_is_fine() -> None:
    """When superseded_thought_ids is empty, a thought_id in live set is accepted."""
    result = validate_action_proposal(_VALID_PROPOSAL, _LIVE_THOUGHT_IDS, frozenset())
    assert result.allowed is True


# ===========================================================================
# AC3 — to_dict / from_dict round-trip
# ===========================================================================


def test_round_trip_minimal() -> None:
    """A minimal proposal round-trips through to_dict/from_dict."""
    ap = ActionProposal(
        thought_id="thought-17",
        action_id="action-1",
        proposed_action="Add retry logic",
        expected_effect="Transient failures absorbed",
    )
    d = ap.to_dict()
    ap2 = ActionProposal.from_dict(d)
    assert ap2 == ap


def test_round_trip_full() -> None:
    """A fully-populated proposal round-trips through to_dict/from_dict."""
    ap = ActionProposal(
        thought_id="thought-17",
        action_id="action-1",
        proposed_action="Add retry logic",
        expected_effect="Transient failures absorbed",
        evidence_refs=["ref-1", "ref-2"],
        consequential=True,
    )
    d = ap.to_dict()
    ap2 = ActionProposal.from_dict(d)
    assert ap2 == ap


def test_round_trip_via_json() -> None:
    """A full round trip via JSON (mimicking the artifact) preserves every field."""
    ap = ActionProposal(
        thought_id="thought-17",
        action_id="action-1",
        proposed_action="Add retry logic",
        expected_effect="Transient failures absorbed",
        evidence_refs=["ref-1"],
        consequential=True,
    )
    reloaded = ActionProposal.from_dict(json.loads(json.dumps(ap.to_dict())))
    assert reloaded == ap


def test_to_dict_contains_all_keys() -> None:
    """to_dict() produces a dict with all expected keys."""
    ap = ActionProposal(
        thought_id="thought-17",
        action_id="action-1",
        proposed_action="Add retry logic",
        expected_effect="Transient failures absorbed",
        evidence_refs=["ref-1"],
        consequential=True,
    )
    d = ap.to_dict()
    assert set(d.keys()) == {
        "thought_id",
        "action_id",
        "proposed_action",
        "expected_effect",
        "evidence_refs",
        "consequential",
    }


def test_from_dict_preserves_evidence_refs() -> None:
    """from_dict correctly preserves evidence_refs."""
    d = dict(_FULL_PROPOSAL)
    ap = ActionProposal.from_dict(d)
    assert ap.evidence_refs == ["tool-result-3", "thought-16"]


def test_from_dict_preserves_consequential() -> None:
    """from_dict correctly preserves consequential."""
    d = dict(_FULL_PROPOSAL)
    ap = ActionProposal.from_dict(d)
    assert ap.consequential is True


def test_from_dict_defaults_when_keys_missing() -> None:
    """from_dict defaults evidence_refs to [] and consequential to False
    when those keys are absent."""
    d = dict(_VALID_PROPOSAL)
    ap = ActionProposal.from_dict(d)
    assert ap.evidence_refs == []
    assert ap.consequential is False
