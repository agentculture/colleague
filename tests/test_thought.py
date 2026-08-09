"""Thought contract tests (#397, t8) — TEST-FIRST.

Covers the four acceptance criteria for the thought contract module
(:mod:`colleague.thought`):

* AC1 — a Thought dataclass carries thought_id/supersedes/observation_refs/
  intent/why/constraints/success_conditions/uncertainties with strict,
  refuse-whole validation (mirroring colleague.lattice's unknown-key stance).
* AC2 — a thought embedding an executable tool call is refused at validation.
* AC3 — the raw operator input reads back byte-identical from the artifact
  alongside the thought (colleague.contract.ContextPacket.original seam) —
  and the Thought itself never becomes the only record of that raw text.
* AC4 — the contract distinguishes presence-mode output from committed
  thoughts: presence prose carries no action-authorizing fields, and only a
  committed Thought grants action-planning authority.
"""

from __future__ import annotations

import json

from colleague.contract import ContextPacket
from colleague.thought import (
    THOUGHT_SCHEMA_VERSION,
    PresenceUtterance,
    PresenceVerdict,
    Thought,
    ThoughtVerdict,
    grants_action_authority,
    validate_presence,
    validate_thought,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: A minimal valid raw thought payload.
_VALID_THOUGHT: dict = {
    "thought_id": "thought-17",
    "intent": "Add retry behavior without changing successful request semantics",
    "why": "Transient failures currently terminate the operation",
    "constraints": ["Do not retry non-transient errors", "Keep the public API stable"],
    "success_conditions": ["Transient failures retry within the configured bound"],
    "uncertainties": ["The repository's transient-error taxonomy is not yet known"],
    "observation_refs": ["operator-4", "tool-result-12"],
    "supersedes": "thought-16",
}


# ===========================================================================
# AC1 — Thought dataclass, strict refuse-whole validation
# ===========================================================================


def test_valid_thought_accepted() -> None:
    """A well-formed thought with every field is accepted."""
    result = validate_thought(_VALID_THOUGHT)
    assert result.allowed is True
    assert result.reason == ""


def test_valid_thought_minimal_required_only() -> None:
    """Only thought_id/intent/why are required; the rest default."""
    result = validate_thought(
        {
            "thought_id": "thought-1",
            "intent": "do the thing",
            "why": "because",
        }
    )
    assert result.allowed is True


def test_missing_required_key_refuses_whole() -> None:
    """Missing thought_id/intent/why refuses the WHOLE thought."""
    payload = dict(_VALID_THOUGHT)
    del payload["intent"]
    result = validate_thought(payload)
    assert result.allowed is False
    assert "intent" in result.reason


def test_unknown_key_refuses_whole() -> None:
    """An extra key not in the schema refuses the WHOLE thought (mirrors
    colleague.lattice's unknown-key stance — never stripped and kept)."""
    payload = dict(_VALID_THOUGHT)
    payload["unexpected_field"] = "surprise"
    result = validate_thought(payload)
    assert result.allowed is False
    assert "unexpected_field" in result.reason


def test_empty_intent_refuses_whole() -> None:
    """An empty/whitespace-only required string field refuses the WHOLE thought."""
    payload = dict(_VALID_THOUGHT)
    payload["intent"] = "   "
    result = validate_thought(payload)
    assert result.allowed is False


def test_non_string_thought_id_refuses_whole() -> None:
    payload = dict(_VALID_THOUGHT)
    payload["thought_id"] = 42
    result = validate_thought(payload)
    assert result.allowed is False


def test_non_list_constraints_refuses_whole() -> None:
    payload = dict(_VALID_THOUGHT)
    payload["constraints"] = "not a list"
    result = validate_thought(payload)
    assert result.allowed is False
    assert "constraints" in result.reason


def test_non_string_list_item_refuses_whole() -> None:
    """A list field with a non-string item (e.g. a nested object) refuses
    the WHOLE thought rather than silently stringifying/dropping it."""
    payload = dict(_VALID_THOUGHT)
    payload["uncertainties"] = ["fine", {"nested": "object"}]
    result = validate_thought(payload)
    assert result.allowed is False


def test_non_dict_input_refuses_whole() -> None:
    result = validate_thought("just a string")
    assert result.allowed is False


def test_supersedes_optional_and_string_or_null() -> None:
    payload = dict(_VALID_THOUGHT)
    del payload["supersedes"]
    result = validate_thought(payload)
    assert result.allowed is True

    payload["supersedes"] = None
    result = validate_thought(payload)
    assert result.allowed is True

    payload["supersedes"] = 5
    result = validate_thought(payload)
    assert result.allowed is False


def test_thought_dataclass_carries_all_named_fields() -> None:
    """The Thought dataclass carries exactly the fields the acceptance
    criterion names."""
    t = Thought(
        thought_id="thought-17",
        supersedes="thought-16",
        observation_refs=["operator-4", "tool-result-12"],
        intent="Add retry behavior without changing successful request semantics",
        why="Transient failures currently terminate the operation",
        constraints=["Do not retry non-transient errors"],
        success_conditions=["Transient failures retry within the configured bound"],
        uncertainties=["The repository's transient-error taxonomy is not yet known"],
    )
    assert t.thought_id == "thought-17"
    assert t.supersedes == "thought-16"
    assert t.observation_refs == ["operator-4", "tool-result-12"]
    assert t.intent.startswith("Add retry")
    assert t.why.startswith("Transient failures")
    assert t.constraints == ["Do not retry non-transient errors"]
    assert t.success_conditions == ["Transient failures retry within the configured bound"]
    assert t.uncertainties == ["The repository's transient-error taxonomy is not yet known"]


def test_thought_round_trips_through_to_dict_from_dict() -> None:
    t = Thought.from_dict(_VALID_THOUGHT)
    assert t.to_dict()["thought_id"] == "thought-17"
    # A full round trip via JSON (mimicking the artifact) preserves every field.
    reloaded = Thought.from_dict(json.loads(json.dumps(t.to_dict())))
    assert reloaded == t


def test_thought_carries_explicit_schema_version() -> None:
    """The contract is 'typed, versioned': the version constant is visible
    and embedded on every serialized thought."""
    assert THOUGHT_SCHEMA_VERSION == 1
    t = Thought.from_dict(_VALID_THOUGHT)
    assert t.version == THOUGHT_SCHEMA_VERSION
    assert t.to_dict()["version"] == THOUGHT_SCHEMA_VERSION


def test_version_mismatch_refuses_whole() -> None:
    """A payload declaring an unsupported version is a deliberate, visible
    refusal — never silently upgraded/downgraded."""
    payload = dict(_VALID_THOUGHT)
    payload["version"] = 999
    result = validate_thought(payload)
    assert result.allowed is False
    assert "version" in result.reason


def test_matching_version_is_fine() -> None:
    payload = dict(_VALID_THOUGHT)
    payload["version"] = THOUGHT_SCHEMA_VERSION
    result = validate_thought(payload)
    assert result.allowed is True


def test_never_raises_on_garbage_input() -> None:
    for garbage in (None, 5, [], {}, {"thought_id": None}):
        result = validate_thought(garbage)
        assert isinstance(result, ThoughtVerdict)
        assert result.allowed is False


# ===========================================================================
# AC2 — a thought embedding an executable tool call is refused
# ===========================================================================


def test_top_level_tool_call_field_refused_as_unknown_key() -> None:
    """Attempting to attach a structured tool-call field directly (the most
    literal 'embedding a tool call') is refused by the unknown-key check
    alone — the schema simply has no such field."""
    payload = dict(_VALID_THOUGHT)
    payload["tool_call"] = {"name": "run_command", "arguments": {"command": "rm -rf /"}}
    result = validate_thought(payload)
    assert result.allowed is False


def test_tool_call_embedded_as_json_text_in_intent_refused() -> None:
    """A tool call smuggled as machine-parseable JSON text inside an
    otherwise-legitimate string field is detected and refused."""
    payload = dict(_VALID_THOUGHT)
    payload["intent"] = (
        'Run {"tool": "run_command", "arguments": {"command": "rm -rf /"}} to fix it'
    )
    result = validate_thought(payload)
    assert result.allowed is False
    assert "tool call" in result.reason


def test_tool_call_embedded_via_known_tool_name_and_generic_marker() -> None:
    """A JSON object naming one of the harness's known tools under 'name'
    alongside call-shaped content is also detected."""
    payload = dict(_VALID_THOUGHT)
    payload["why"] = 'because {"name": "write_file", "path": "x", "content": "y"} works'
    result = validate_thought(payload)
    assert result.allowed is False


def test_tool_call_embedded_in_list_field_item_refused() -> None:
    payload = dict(_VALID_THOUGHT)
    payload["constraints"] = [
        'Do not do this: {"function_call": {"name": "edit_file"}}',
    ]
    result = validate_thought(payload)
    assert result.allowed is False


def test_prose_mentioning_a_tool_name_is_not_refused() -> None:
    """Plain-English mention of a tool name (no machine-parseable call
    shape) is legitimate content, not a tool-call embedding — the detector
    must not over-block ordinary prose."""
    payload = dict(_VALID_THOUGHT)
    payload["constraints"] = ["Never invoke run_command directly from a thought"]
    result = validate_thought(payload)
    assert result.allowed is True


def test_unrelated_json_object_in_text_is_not_refused() -> None:
    """A JSON object with no tool-call marker keys and no known tool name
    is not a tool call — e.g. quoting a config snippet in prose."""
    payload = dict(_VALID_THOUGHT)
    payload["why"] = 'the config looks like {"retries": 3, "backoff": "expo"}'
    result = validate_thought(payload)
    assert result.allowed is True


# ===========================================================================
# AC3 — raw operator input reads back byte-identical alongside the thought
# (ContextPacket.original seam)
# ===========================================================================


def test_context_packet_original_round_trips_byte_identical_via_artifact() -> None:
    """The existing ContextPacket.original seam is what preserves raw
    operator input — proven byte-identical through a JSON round trip that
    mimics writing/reading the artifact."""
    raw_text = "Please\tfix   the   thing\n\nwith  ünïcödé and trailing space  "
    packet = ContextPacket(original=raw_text, interpretation="fix the thing")
    artifact_json = json.dumps(packet.to_dict())
    reloaded = ContextPacket.from_dict(json.loads(artifact_json))
    assert reloaded.original == raw_text


def test_thought_coexists_with_context_packet_without_duplicating_raw_text() -> None:
    """A committed Thought and the raw operator input (via ContextPacket)
    live ALONGSIDE each other and both round-trip — the Thought is never the
    only record of the operator's raw text, and it carries no field that
    copies/restates it."""
    raw_text = "operator said exactly this, verbatim, unicode: café\n— multi-line"
    packet = ContextPacket(original=raw_text, interpretation="operator request")
    thought = Thought.from_dict(
        {
            **_VALID_THOUGHT,
            "observation_refs": ["operator-utterance-1"],
        }
    )

    # Both round-trip through a JSON artifact independently...
    packet_reloaded = ContextPacket.from_dict(json.loads(json.dumps(packet.to_dict())))
    thought_reloaded = Thought.from_dict(json.loads(json.dumps(thought.to_dict())))

    # ...and the raw text survives byte-identical.
    assert packet_reloaded.original == raw_text
    # The thought references the observation by opaque id, not by copying
    # the raw text into any of its own fields.
    assert "operator-utterance-1" in thought_reloaded.observation_refs
    thought_field_values = "".join(
        [
            thought_reloaded.intent,
            thought_reloaded.why,
            " ".join(thought_reloaded.constraints),
            " ".join(thought_reloaded.success_conditions),
            " ".join(thought_reloaded.uncertainties),
            " ".join(thought_reloaded.observation_refs),
            thought_reloaded.thought_id,
            thought_reloaded.supersedes or "",
        ]
    )
    assert raw_text not in thought_field_values


def test_thought_dataclass_has_no_raw_text_field() -> None:
    """A Thought must never become a lossy replacement for the operator
    input — it structurally has no field meant to carry that raw text
    (no 'original'/'raw_text'/'raw_input' field exists on the dataclass)."""
    field_names = {f for f in Thought.__dataclass_fields__}
    assert "original" not in field_names
    assert "raw_text" not in field_names
    assert "raw_input" not in field_names


# ===========================================================================
# AC4 — presence-mode output vs committed thoughts
# ===========================================================================


def test_presence_utterance_accepts_only_text() -> None:
    result = validate_presence({"text": "hi, still here, watching the build"})
    assert result.allowed is True


def test_presence_utterance_with_no_text_key_is_fine() -> None:
    result = validate_presence({})
    assert result.allowed is True


def test_presence_utterance_carrying_intent_refused_whole() -> None:
    """Presence-mode output can NEVER carry an action-authorizing field —
    attempting to smuggle 'intent' onto a presence payload refuses whole."""
    result = validate_presence(
        {"text": "just watching", "intent": "secretly plan to refactor everything"}
    )
    assert result.allowed is False
    assert "intent" in result.reason


def test_presence_utterance_carrying_any_thought_field_refused() -> None:
    for forbidden_key, value in (
        ("constraints", ["x"]),
        ("success_conditions", ["y"]),
        ("uncertainties", ["z"]),
        ("thought_id", "thought-1"),
        ("supersedes", "thought-0"),
        ("observation_refs", ["op-1"]),
        ("why", "because"),
    ):
        payload = {"text": "hi", forbidden_key: value}
        result = validate_presence(payload)
        assert result.allowed is False, f"expected refusal for key {forbidden_key!r}"


def test_presence_utterance_non_dict_refused() -> None:
    result = validate_presence("just a bare string")
    assert result.allowed is False


def test_presence_never_raises() -> None:
    for garbage in (None, 5, [], "text implying an objective: fix everything now"):
        result = validate_presence(garbage)
        assert isinstance(result, PresenceVerdict)


def test_grants_action_authority_true_only_for_committed_thought() -> None:
    thought = Thought.from_dict(_VALID_THOUGHT)
    presence = PresenceUtterance(text="an utterance that implies an objective: fix it now")

    assert grants_action_authority(thought) is True
    assert grants_action_authority(presence) is False
    assert grants_action_authority("a bare string implying an objective") is False
    assert grants_action_authority({"intent": "sneaky"}) is False
    assert grants_action_authority(None) is False


def test_presence_utterance_implying_an_objective_still_carries_no_authority() -> None:
    """Even presence-mode PROSE that reads like it implies an objective
    grants no action authority — only a committed, typed Thought does
    (spec claim c36 / honesty h28). The content of the text is irrelevant;
    only the TYPE distinguishes authority."""
    utterance = PresenceUtterance(
        text="We should really add retry behavior to the request path now."
    )
    assert grants_action_authority(utterance) is False


def test_presence_utterance_round_trips() -> None:
    u = PresenceUtterance(text="hi there")
    reloaded = PresenceUtterance.from_dict(json.loads(json.dumps(u.to_dict())))
    assert reloaded == u
