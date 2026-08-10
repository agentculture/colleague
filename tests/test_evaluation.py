"""Evaluation contract tests (#397, t10) — TEST-FIRST.

Covers the three acceptance criteria for the evaluation contract module
(:mod:`colleague.evaluation`):

* AC1 — the evaluation result validates ONLY the closed vocabulary (verdict
  + route); an unknown verdict/route string refuses the WHOLE payload
  (colleague.lattice's unknown-key stance).
* AC2 — a ``block`` route can never reach execution, and an ``aligned``
  verdict still passes approvals/hooks/policy before execution: the
  alignment-is-not-permission tests below drive the REAL approval gate
  (:func:`colleague.policy.load_policy`) and prove an aligned + ``execute``
  evaluation cannot run a gated command by itself.
* AC3 — the evaluator's input is a BOUNDED thought/action/evidence envelope;
  the tests assert on what is ABSENT (worker conversation history) as well as
  on what is present.
"""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from colleague.evaluation import (
    ENVELOPE_ALLOWED_KEYS,
    EVALUATION_SCHEMA_VERSION,
    MAX_ENVELOPE_EVIDENCE_ITEMS,
    MAX_ENVELOPE_LIST_ITEMS,
    MAX_ENVELOPE_TEXT_CHARS,
    ROUTE_BLOCK,
    ROUTE_EXECUTE,
    ROUTE_REPLAN,
    ROUTE_RETHINK,
    ROUTES,
    VERDICT_ACTION_DRIFT,
    VERDICT_ALIGNED,
    VERDICT_CONSTRAINT_VIOLATION,
    VERDICT_INTENT_NOT_SATISFIED,
    VERDICT_SUCCESS_CONDITIONS_UNMET,
    VERDICT_THOUGHT_AMBIGUOUS,
    VERDICT_UNSUPPORTED_EFFECT,
    VERDICTS,
    Evaluation,
    EvaluationCheck,
    EvaluationEnvelope,
    authorize_execution,
    build_evaluation_envelope,
    build_evaluation_instruction,
    build_evaluation_prompt,
    may_execute,
    parse_evaluation,
    validate_evaluation,
)
from colleague.policy import load_policy
from colleague.thought import Thought

# ---------------------------------------------------------------------------
# Fixtures / stand-ins
# ---------------------------------------------------------------------------

#: Sentinel strings that stand in for the worker's conversation history. If any
#: of these ever reaches the envelope, the containment property is broken.
WORKER_HISTORY_SENTINELS = (
    "SENTINEL-WORKER-TURN-1",
    "SENTINEL-WORKER-TURN-2",
    "SENTINEL-TOOL-RESULT",
    "SENTINEL-ASSISTANT-REASONING",
)


@dataclass
class FakeActionProposal:
    """Stand-in for t9's ``ActionProposal`` (built in a parallel worktree).

    Only the field NAMES this module depends on are modelled here:
    ``action_id`` / ``thought_id`` / ``proposed_action`` / ``expected_effect``
    / ``evidence_refs`` / ``command``. The extra ``messages`` / ``history`` /
    ``transcript`` attributes are deliberate contamination bait: a real worker
    seat object may well carry its conversation, and the envelope builder must
    never read it.
    """

    action_id: str = "action-1"
    thought_id: str = "thought-1"
    proposed_action: str = "add a bounds check to parse_move"
    expected_effect: str = "parse_move returns a refusal instead of raising"
    evidence_refs: list = field(default_factory=lambda: ["obs-1", "obs-2"])
    command: str = ""
    # --- contamination bait (must never be read) ---
    messages: list = field(
        default_factory=lambda: [
            {"role": "assistant", "content": WORKER_HISTORY_SENTINELS[0]},
            {"role": "tool", "content": WORKER_HISTORY_SENTINELS[2]},
        ]
    )
    history: str = WORKER_HISTORY_SENTINELS[1]
    transcript: str = WORKER_HISTORY_SENTINELS[3]


def make_thought(**overrides: object) -> Thought:
    data: dict = {
        "thought_id": "thought-1",
        "intent": "make parse_move refuse a malformed move",
        "why": "a hallucinated move must never reach a callback",
        "constraints": ["never raise", "no new dependency"],
        "success_conditions": ["tests/test_senses_moves.py passes"],
        "uncertainties": ["unsure whether the served model emits prose"],
        "observation_refs": ["obs-1"],
    }
    data.update(overrides)
    return Thought(**data)  # type: ignore[arg-type]


def make_evaluation(**overrides: object) -> dict:
    payload: dict = {
        "thought_id": "thought-1",
        "action_id": "action-1",
        "verdict": VERDICT_ALIGNED,
        "route": ROUTE_EXECUTE,
        "reason": "the action realizes the intent within every stated constraint",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AC1 — the closed vocabulary, and refuse-whole on anything outside it
# ---------------------------------------------------------------------------


class TestClosedVocabulary:
    def test_verdicts_are_exactly_the_enumerated_set(self) -> None:
        assert VERDICTS == frozenset(
            {
                VERDICT_ALIGNED,
                VERDICT_CONSTRAINT_VIOLATION,
                VERDICT_INTENT_NOT_SATISFIED,
                VERDICT_UNSUPPORTED_EFFECT,
                VERDICT_THOUGHT_AMBIGUOUS,
                VERDICT_ACTION_DRIFT,
                VERDICT_SUCCESS_CONDITIONS_UNMET,
            }
        )

    def test_routes_are_exactly_the_four_from_issue_397(self) -> None:
        assert ROUTES == frozenset({"execute", "rethink", "replan", "block"})
        assert (ROUTE_EXECUTE, ROUTE_RETHINK, ROUTE_REPLAN, ROUTE_BLOCK) == (
            "execute",
            "rethink",
            "replan",
            "block",
        )

    def test_unknown_verdict_string_refuses_whole(self) -> None:
        check = validate_evaluation(make_evaluation(verdict="probably_fine"))
        assert check.allowed is False
        assert check.evaluation is None, "a refused payload yields NO evaluation object"
        assert "probably_fine" in check.reason

    def test_unknown_route_string_refuses_whole(self) -> None:
        check = validate_evaluation(make_evaluation(verdict=VERDICT_ACTION_DRIFT, route="escalate"))
        assert check.allowed is False
        assert check.evaluation is None
        assert "escalate" in check.reason

    def test_a_near_miss_route_is_not_coerced(self) -> None:
        """'Execute' / 'EXECUTE' / ' execute ' are not the closed token."""
        for near_miss in ("Execute", "EXECUTE", " execute", "execute "):
            check = validate_evaluation(make_evaluation(route=near_miss))
            assert check.allowed is False, f"{near_miss!r} must not be coerced to 'execute'"
            assert check.evaluation is None

    def test_unknown_key_refuses_whole(self) -> None:
        check = validate_evaluation(make_evaluation(confidence=0.9))
        assert check.allowed is False
        assert check.evaluation is None
        assert "confidence" in check.reason

    def test_missing_required_field_refuses_whole(self) -> None:
        for key in ("thought_id", "action_id", "verdict", "route", "reason"):
            payload = make_evaluation()
            del payload[key]
            check = validate_evaluation(payload)
            assert check.allowed is False, f"missing {key!r} must refuse"
            assert key in check.reason

    def test_empty_reason_refuses_whole(self) -> None:
        check = validate_evaluation(make_evaluation(reason="   "))
        assert check.allowed is False

    def test_version_mismatch_refuses_whole(self) -> None:
        check = validate_evaluation(make_evaluation(version=EVALUATION_SCHEMA_VERSION + 1))
        assert check.allowed is False
        assert check.evaluation is None

    def test_non_dict_refuses_whole_and_never_raises(self) -> None:
        for bad in (None, "aligned", 3, ["aligned"]):
            check = validate_evaluation(bad)
            assert check.allowed is False
            assert check.evaluation is None

    def test_valid_payload_is_accepted_and_typed(self) -> None:
        check = validate_evaluation(make_evaluation())
        assert check.allowed is True
        assert check.reason == ""
        assert isinstance(check.evaluation, Evaluation)
        assert check.evaluation.verdict == VERDICT_ALIGNED
        assert check.evaluation.route == ROUTE_EXECUTE

    def test_execute_route_requires_the_aligned_verdict(self) -> None:
        """The ONLY cross-field rule: a non-aligned verdict may never carry
        ``execute``. Alignment is the necessary (never sufficient) condition."""
        for verdict in sorted(VERDICTS - {VERDICT_ALIGNED}):
            check = validate_evaluation(make_evaluation(verdict=verdict, route=ROUTE_EXECUTE))
            assert check.allowed is False, f"{verdict!r} must not be able to route to execute"
            assert check.evaluation is None

    def test_aligned_may_still_route_to_block(self) -> None:
        check = validate_evaluation(
            make_evaluation(
                route=ROUTE_BLOCK,
                reason="aligned, but an operator decision is required first",
            )
        )
        assert check.allowed is True
        assert check.evaluation is not None
        assert check.evaluation.route == ROUTE_BLOCK

    def test_evaluator_may_not_rewrite_the_thought_or_the_action(self) -> None:
        """The evaluator returns a fidelity verdict, never a competing
        implementation: a payload smuggling thought- or action-authoring
        content refuses whole (spec c28)."""
        for smuggled in (
            {"intent": "actually, do this instead"},
            {"constraints": ["a new constraint"]},
            {"success_conditions": ["a new success condition"]},
            {"expected_effect": "my own expected effect"},
            {"command": "rm -rf /"},
            {"patch": "--- a/x\n+++ b/x\n"},
            {"tool_calls": [{"name": "run_command"}]},
        ):
            check = validate_evaluation(make_evaluation(**smuggled))
            assert check.allowed is False, f"{smuggled!r} must refuse whole"
            assert check.evaluation is None

    def test_evaluation_round_trips(self) -> None:
        check = validate_evaluation(make_evaluation())
        assert check.evaluation is not None
        again = validate_evaluation(check.evaluation.to_dict())
        assert again.allowed is True
        assert again.evaluation == check.evaluation


class TestParseEvaluation:
    def test_parses_a_fenced_json_object_from_prose(self) -> None:
        raw = 'Here is my judgment:\n```json\n{"thought_id": "thought-1", '
        raw += '"action_id": "action-1", "verdict": "aligned", "route": "execute", '
        raw += '"reason": "matches the intent"}\n```\nHope that helps.'
        check = parse_evaluation(raw)
        assert check.allowed is True
        assert check.evaluation is not None
        assert check.evaluation.route == ROUTE_EXECUTE

    @pytest.mark.parametrize("raw", ["", "   ", "I think it looks fine to me!", "{{{{"])
    def test_unreadable_completion_refuses_and_never_defaults_to_aligned(self, raw: str) -> None:
        check = parse_evaluation(raw)
        assert check.allowed is False
        assert check.evaluation is None

    def test_parse_never_raises_on_any_input(self) -> None:
        for bad in (None, 3, [], {"verdict": "aligned"}):
            check = parse_evaluation(bad)  # type: ignore[arg-type]
            assert check.allowed is False


# ---------------------------------------------------------------------------
# AC2a — a 'block' route can never reach execution
# ---------------------------------------------------------------------------


class TestBlockNeverExecutes:
    @pytest.mark.parametrize("route", sorted(ROUTES - {ROUTE_EXECUTE}))
    def test_non_execute_routes_never_permit_execution(self, route: str) -> None:
        verdict = VERDICT_ALIGNED if route == ROUTE_BLOCK else VERDICT_ACTION_DRIFT
        check = validate_evaluation(make_evaluation(verdict=verdict, route=route))
        assert check.allowed is True
        assert check.evaluation is not None
        assert may_execute(check.evaluation) is False

    def test_block_is_denied_by_the_evaluation_before_policy_is_consulted(
        self, tmp_path: Path
    ) -> None:
        """A blocked evaluation is refused even under a WIDE-OPEN policy —
        so the refusal cannot be attributed to the gate."""
        # No approvals.json at all => the approval gate is a strict no-op.
        policy = load_policy(tmp_path, user_home=tmp_path / "home")
        assert policy.is_empty()
        assert policy.check_run_command("rm -rf /").allowed is True

        check = validate_evaluation(
            make_evaluation(route=ROUTE_BLOCK, reason="operator decision needed")
        )
        assert check.evaluation is not None
        decision = authorize_execution(check.evaluation, policy, "rm -rf /")
        assert decision.allowed is False
        assert decision.denied_by == "evaluation"

    def test_may_execute_rejects_anything_that_is_not_an_evaluation(self) -> None:
        for bogus in (None, "execute", {"route": "execute"}, object()):
            assert may_execute(bogus) is False


# ---------------------------------------------------------------------------
# AC2b — ALIGNMENT IS NOT PERMISSION (the load-bearing invariant)
# ---------------------------------------------------------------------------


def _armed_policy(tmp_path: Path, *, allow: list[str]) -> object:
    """A REAL approval gate (not a mock) with a present run_command section."""
    colleague_dir = tmp_path / ".colleague"
    colleague_dir.mkdir(parents=True, exist_ok=True)
    (colleague_dir / "approvals.json").write_text(
        json.dumps({"run_command": {"allow": allow, "deny": []}}), encoding="utf-8"
    )
    return load_policy(tmp_path, user_home=tmp_path / "home")


class TestAlignmentIsNotPermission:
    """An 'aligned' + 'execute' evaluation is the STRONGEST thing the evaluator
    can say. These tests prove it still cannot run a gated command."""

    def test_aligned_execute_cannot_run_a_gated_command(self, tmp_path: Path) -> None:
        policy = _armed_policy(tmp_path, allow=["git", "pytest"])
        check = validate_evaluation(make_evaluation())  # aligned + execute
        assert check.allowed is True
        assert check.evaluation is not None
        evaluation = check.evaluation
        assert may_execute(evaluation) is True, "the evaluator itself says 'execute'"

        decision = authorize_execution(evaluation, policy, "rm -rf /")

        assert decision.allowed is False, (
            "an aligned evaluation must NOT be able to execute a command the "
            "operator's approval gate does not allow"
        )
        assert decision.denied_by == "policy"
        assert "rm" in decision.reason
        # And the gate's own verdict is unchanged by the evaluation existing.
        assert policy.check_run_command("rm -rf /").allowed is False

    def test_aligned_execute_still_needs_the_gate_to_say_yes(self, tmp_path: Path) -> None:
        """The control case: permission comes from the gate, not the verdict."""
        policy = _armed_policy(tmp_path, allow=["git", "pytest"])
        check = validate_evaluation(make_evaluation())
        assert check.evaluation is not None
        decision = authorize_execution(check.evaluation, policy, "git status")
        assert decision.allowed is True
        assert decision.denied_by is None

    def test_an_aligned_verdict_cannot_approve_an_unapproved_hook(self, tmp_path: Path) -> None:
        """The same holds for the checksum half of the gate."""
        colleague_dir = tmp_path / ".colleague"
        colleague_dir.mkdir(parents=True, exist_ok=True)
        (colleague_dir / "approvals.json").write_text(
            json.dumps({"hooks": {"approved.sh": "sha256:" + "0" * 64}}), encoding="utf-8"
        )
        hook = tmp_path / "rogue.sh"
        hook.write_text("#!/bin/sh\necho rogue\n", encoding="utf-8")
        policy = load_policy(tmp_path, user_home=tmp_path / "home")

        check = validate_evaluation(make_evaluation())
        assert check.evaluation is not None
        assert may_execute(check.evaluation) is True
        # The evaluation is aligned; the hook is still unapproved.
        assert policy.check_file("hooks", "rogue.sh", hook).allowed is False

    def test_the_evaluation_carries_no_permission_granting_surface(self) -> None:
        """Structural: an Evaluation exposes no field or method that could
        approve, allow, grant, or widen anything."""
        banned = ("approve", "allow", "grant", "permit", "authorize", "bypass", "override")
        check = validate_evaluation(make_evaluation())
        assert check.evaluation is not None
        for name in dir(check.evaluation):
            if name.startswith("_"):
                continue
            lowered = name.lower()
            assert not any(word in lowered for word in banned), (
                f"Evaluation.{name} looks like a permission-granting surface — "
                "the evaluator may never grant tool permission (spec c28)"
            )

    def test_authorize_execution_requires_a_policy_object(self, tmp_path: Path) -> None:
        """A caller cannot skip the gate by passing None in its place."""
        check = validate_evaluation(make_evaluation())
        assert check.evaluation is not None
        decision = authorize_execution(check.evaluation, None, "git status")
        assert decision.allowed is False
        assert decision.denied_by == "policy"


# ---------------------------------------------------------------------------
# AC3 — the bounded thought/action/evidence envelope
# ---------------------------------------------------------------------------


class TestEnvelopeIsBounded:
    def test_envelope_carries_the_thought_action_and_evidence(self) -> None:
        envelope = build_evaluation_envelope(
            make_thought(),
            FakeActionProposal(),
            evidence=[{"ref": "obs-1", "text": "parse_move raised on '{{{'"}],
        )
        assert isinstance(envelope, EvaluationEnvelope)
        data = envelope.to_dict()
        assert data["thought"]["thought_id"] == "thought-1"
        assert data["action"]["action_id"] == "action-1"
        assert data["action"]["expected_effect"].startswith("parse_move returns")
        assert data["evidence"][0]["ref"] == "obs-1"

    def test_envelope_keys_are_a_closed_set(self) -> None:
        envelope = build_evaluation_envelope(make_thought(), FakeActionProposal())
        assert set(envelope.to_dict()) == set(ENVELOPE_ALLOWED_KEYS)

    def test_worker_conversation_history_is_absent(self) -> None:
        """The containment property: the envelope must NOT contain the worker's
        conversation, even when the action object it is built from carries it."""
        action = FakeActionProposal()
        # Precondition: the bait really is on the source object.
        assert WORKER_HISTORY_SENTINELS[0] in json.dumps(action.messages)

        envelope = build_evaluation_envelope(make_thought(), action)
        serialized = json.dumps(envelope.to_dict())

        for sentinel in WORKER_HISTORY_SENTINELS:
            assert sentinel not in serialized, (
                f"worker conversation history leaked into the envelope ({sentinel}) — "
                "the evaluator's judgment must be independent of the worker's framing"
            )
        # And it leaks into the rendered prompt no more than into the dict.
        prompt = build_evaluation_prompt(envelope)
        for sentinel in WORKER_HISTORY_SENTINELS:
            assert sentinel not in prompt

    def test_no_history_shaped_key_exists_anywhere_in_the_envelope(self) -> None:
        envelope = build_evaluation_envelope(
            make_thought(),
            FakeActionProposal(),
            evidence=[{"ref": "obs-1", "text": "a bounded excerpt"}],
        )
        banned = ("message", "history", "transcript", "conversation", "turns", "trace")

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    lowered = str(key).lower()
                    assert not any(
                        word in lowered for word in banned
                    ), f"envelope key {key!r} is conversation-history shaped"
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(envelope.to_dict())

    def test_the_builder_has_no_parameter_that_could_carry_history(self) -> None:
        """Assert on ABSENCE at the API surface: there is no seam through which
        a caller could hand the evaluator the worker's transcript."""
        banned = ("message", "history", "transcript", "conversation", "turns", "trace")
        params = inspect.signature(build_evaluation_envelope).parameters
        for name in params:
            lowered = name.lower()
            assert not any(
                word in lowered for word in banned
            ), f"build_evaluation_envelope({name}=...) would be a history seam"

    def test_long_text_is_truncated_and_the_truncation_is_recorded(self) -> None:
        long_intent = "x" * (MAX_ENVELOPE_TEXT_CHARS * 3)
        envelope = build_evaluation_envelope(make_thought(intent=long_intent), FakeActionProposal())
        rendered = envelope.to_dict()["thought"]["intent"]
        assert len(rendered) <= MAX_ENVELOPE_TEXT_CHARS
        assert "intent" in " ".join(envelope.truncated)

    def test_lists_and_evidence_are_capped(self) -> None:
        many = [f"constraint-{i}" for i in range(MAX_ENVELOPE_LIST_ITEMS * 4)]
        evidence = [
            {"ref": f"obs-{i}", "text": "excerpt"} for i in range(MAX_ENVELOPE_EVIDENCE_ITEMS * 4)
        ]
        envelope = build_evaluation_envelope(
            make_thought(constraints=many), FakeActionProposal(), evidence=evidence
        )
        data = envelope.to_dict()
        assert len(data["thought"]["constraints"]) == MAX_ENVELOPE_LIST_ITEMS
        assert len(data["evidence"]) == MAX_ENVELOPE_EVIDENCE_ITEMS
        assert envelope.truncated

    def test_envelope_is_json_serializable_and_stable(self) -> None:
        envelope = build_evaluation_envelope(make_thought(), FakeActionProposal())
        once = json.dumps(envelope.to_dict(), sort_keys=True)
        twice = json.dumps(envelope.to_dict(), sort_keys=True)
        assert once == twice

    def test_builder_tolerates_a_mapping_shaped_action(self) -> None:
        """t9's ActionProposal is being built in a parallel worktree; the
        builder reads FIELD NAMES structurally, so a plain dict works too."""
        envelope = build_evaluation_envelope(
            make_thought(),
            {
                "action_id": "action-9",
                "thought_id": "thought-1",
                "proposed_action": "edit senses_moves.py",
                "expected_effect": "no raise",
                "evidence_refs": ["obs-1"],
                "messages": [{"role": "assistant", "content": WORKER_HISTORY_SENTINELS[0]}],
            },
        )
        data = envelope.to_dict()
        assert data["action"]["action_id"] == "action-9"
        assert WORKER_HISTORY_SENTINELS[0] not in json.dumps(data)

    def test_envelope_records_a_thought_action_binding_mismatch(self) -> None:
        """The envelope never silently retargets: an action naming a different
        thought is surfaced, not repaired."""
        envelope = build_evaluation_envelope(
            make_thought(), FakeActionProposal(thought_id="thought-99")
        )
        data = envelope.to_dict()
        assert data["thought"]["thought_id"] == "thought-1"
        assert data["action"]["thought_id"] == "thought-99"


# ---------------------------------------------------------------------------
# The tools-off wire discipline (senses_moves.py's precedent)
# ---------------------------------------------------------------------------


class TestToolsOffStructuralBoundary:
    SOURCE = Path(__file__).resolve().parents[1] / "colleague" / "evaluation.py"

    def test_module_never_imports_subprocess(self) -> None:
        tree = ast.parse(self.SOURCE.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        assert "subprocess" not in names

    def test_module_never_imports_the_tool_executor(self) -> None:
        tree = ast.parse(self.SOURCE.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert "colleague.tools" not in imported
        assert "ToolExecutor" not in imported

    def test_module_is_not_a_sanctioned_subprocess_consumer(self) -> None:
        from tests.test_boundary import _SUBPROCESS_ALLOWED

        assert "colleague/evaluation.py" not in _SUBPROCESS_ALLOWED

    def test_module_never_constructs_a_tool_schema(self) -> None:
        """Nothing tool-shaped on the wire: no ``tools`` / ``tool_choice`` /
        ``function`` key is ever built here."""
        tree = ast.parse(self.SOURCE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        assert key.value not in {
                            "tools",
                            "tool_choice",
                            "function",
                            "function_call",
                            "tool_calls",
                        }

    def test_instruction_names_every_verdict_and_route(self) -> None:
        instruction = build_evaluation_instruction()
        for token in sorted(VERDICTS) + sorted(ROUTES):
            assert token in instruction
        assert "faithfully realize" in instruction

    def test_prompt_embeds_the_envelope_and_the_instruction(self) -> None:
        envelope = build_evaluation_envelope(make_thought(), FakeActionProposal())
        prompt = build_evaluation_prompt(envelope)
        assert "thought-1" in prompt
        assert ROUTE_BLOCK in prompt

    def test_instruction_states_that_alignment_is_not_permission(self) -> None:
        instruction = build_evaluation_instruction()
        lowered = instruction.lower()
        assert "permission" in lowered

    def test_check_is_a_distinct_type_from_the_evaluation(self) -> None:
        check = validate_evaluation(make_evaluation())
        assert isinstance(check, EvaluationCheck)
        assert not isinstance(check, Evaluation)
