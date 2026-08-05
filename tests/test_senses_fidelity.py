"""Tests for structural senses relay fidelity (three-tier-execution arc, t2).

Colleague drives with two lobes: an ACTING mind (today cortex; the loop
speaks of it generically) that does the repo work, and senses — a tools-off
front door that perceives/presents. A real embodiment live session exposed a
fidelity gap in the existing senses relay lane: across a run, senses recited
its background "knowledge" block on 6 out of 6 turns instead of relaying the
CURRENT answer the acting mind had actually produced for the CURRENT
message. Prompt wording alone ("please answer the question") is hope, not a
guarantee — a served model can still ignore it.

This module pins the structural fix, entirely at the code level, across the
two "live conversational answer relay" surfaces that can carry a worker
answer today: :func:`colleague.senses.run_senses_talk` and the senses
coordination loop's ``reply_to_operator`` move
(:class:`colleague.senses_loop.SensesLoopDriver`). Three acceptance criteria:

1. Structural containment — with a worker answer present, the FINAL displayed
   text always CONTAINS it verbatim (a substring check in code, never prompt
   hope alone).
2. A fidelity failure (the model's raw reply omits the worker answer) falls
   back to presenting the raw worker answer and records a degradation; four
   additive counters land on the :class:`~colleague.contract.SensesRecord`
   surface: ``verbatim_presence``, ``knowledge_repetition``, ``fallback``,
   ``truncated``.
3. The embodiment 6/6 domain-mismatch failure shape is pinned as a committed
   regression test — and the existing ``ContextPacket.original``
   never-touched / ``tools=[]``-always pins survive untouched.

No network: every completion is a fake recording what it was called with.
"""

from __future__ import annotations

import json

from colleague.config import EngineConfig
from colleague.contract import ContextPacket, SensesRecord
from colleague.loop import ModelResponse
from colleague.senses import (
    _FRONTDOOR_SYSTEM_PROMPT,
    _INTAKE_SYSTEM_PROMPT,
    _SPEAKBACK_SYSTEM_PROMPT,
    _TALK_SYSTEM_PROMPT,
    _UPDATE_SYSTEM_PROMPT,
    _enforce_fidelity,
    _fold_history,
    _repeats_background,
    run_senses_talk,
)
from colleague.senses_loop import (
    _LOOP_SYSTEM_PROMPT,
    BOUNDARY_OPERATOR_INPUT,
    BoundaryContext,
    SensesLoopDriver,
)
from colleague.senses_moves import MOVE_REPLY_TO_OPERATOR, MOVE_SCHEMA, SensesMoveExecutor

# ---------------------------------------------------------------------------
# fakes (mirrors tests/test_senses_talk.py's _FakeMakeComplete pattern)
# ---------------------------------------------------------------------------


def _senses_config(**overrides) -> EngineConfig:
    defaults = dict(model="senses-model", context_budget_tokens=100000)
    defaults.update(overrides)
    return EngineConfig(**defaults)


class _FakeMakeComplete:
    """A recording stand-in for ``engine.make_complete`` (bound method shape)."""

    def __init__(self, response: "ModelResponse | None" = None, raise_on_complete=None) -> None:
        self.tools_calls: "list[list | None]" = []
        self.complete_call_count = 0
        self.captured_messages: "list[dict] | None" = None
        self._response = response or ModelResponse(
            content=json.dumps({"answer": "stub", "relay": False, "relay_text": ""}),
            prompt_tokens=5,
            completion_tokens=7,
        )
        self._raise_on_complete = raise_on_complete

    def __call__(self, config: EngineConfig, tools=None):
        self.tools_calls.append(tools)

        def complete(messages: "list[dict]"):
            self.complete_call_count += 1
            self.captured_messages = messages
            if self._raise_on_complete is not None:
                raise self._raise_on_complete
            return self._response

        return complete


def _char_counter(messages: "list[dict]") -> int:
    return sum(len(m.get("content") or "") for m in messages)


def _talk_json(answer: str) -> str:
    return json.dumps({"answer": answer, "relay": False, "relay_text": ""})


# ---------------------------------------------------------------------------
# senses_loop fakes (mirrors tests/test_senses_loop.py)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning = ""
        self.prompt_tokens = 3
        self.completion_tokens = 5


def _scripted_make_complete(replies):
    seq = list(replies)
    idx = {"i": 0}

    def make_complete(config, *, tools):
        assert tools == [], "senses loop must always issue tools=[] (tools-off)"

        def complete(messages):
            i = idx["i"]
            idx["i"] += 1
            reply = seq[i] if i < len(seq) else json.dumps({"move": "wait"})
            return _FakeResp(reply)

        return complete

    return make_complete


def _reply_executor():
    def reply(text):
        return "replied"

    return SensesMoveExecutor(reply_to_operator=reply)


def _loop_driver(replies, *, budget: int = 24000):
    from types import SimpleNamespace

    return SensesLoopDriver(
        senses_config=SimpleNamespace(context_budget_tokens=budget),
        make_complete=_scripted_make_complete(replies),
        executor=_reply_executor(),
        make_count_tokens=_char_counter,
    )


def _op(text: str, **kw) -> BoundaryContext:
    return BoundaryContext(kind=BOUNDARY_OPERATOR_INPUT, operator_input=text, **kw)


# ---------------------------------------------------------------------------
# (A) clause composition — every prompt-bearing senses surface
# ---------------------------------------------------------------------------


class TestClauseComposition:
    """The grounding clause ("you can see only the status block you are
    given") and the fidelity clause ("answer the current message from the
    current result first; background knowledge never replaces it") are
    composed into every prompt-bearing senses surface — prompt-construction
    hygiene, not the structural guarantee itself (that's enforced in code,
    below)."""

    _PROMPTS = {
        "intake": _INTAKE_SYSTEM_PROMPT,
        "speakback": _SPEAKBACK_SYSTEM_PROMPT,
        "talk": _TALK_SYSTEM_PROMPT,
        "update": _UPDATE_SYSTEM_PROMPT,
        "frontdoor": _FRONTDOOR_SYSTEM_PROMPT,
        "loop": _LOOP_SYSTEM_PROMPT,
    }

    def test_grounding_clause_present_in_every_prompt(self) -> None:
        for name, prompt in self._PROMPTS.items():
            lowered = prompt.lower()
            assert "status block you are given" in lowered, f"{name} missing grounding clause"

    def test_fidelity_clause_present_in_every_prompt(self) -> None:
        for name, prompt in self._PROMPTS.items():
            lowered = prompt.lower()
            assert "current result first" in lowered, f"{name} missing fidelity clause"
            assert (
                "background knowledge never replaces it" in lowered
            ), f"{name} missing fidelity clause"


# ---------------------------------------------------------------------------
# (B) knowledge entries labeled "optional background", before current content
# ---------------------------------------------------------------------------


class TestKnowledgeLabeling:
    def test_folded_history_is_labeled_optional_background(self) -> None:
        folded = _fold_history(
            "current payload",
            [{"role": "operator", "text": "an old exchange"}],
            system_prompt="sys",
            budget=100000,
            count_tokens=_char_counter,
        )
        assert "optional background" in folded.lower()
        # still placed BEFORE the current content, as before this arc.
        assert folded.index("an old exchange") < folded.index("current payload")

    def test_no_history_is_unaffected(self) -> None:
        folded = _fold_history(
            "current payload", None, system_prompt="sys", budget=100000, count_tokens=_char_counter
        )
        assert folded == "current payload"

    def test_reply_to_operator_move_description_carries_fidelity_reminder(self) -> None:
        """senses_moves.py: the move description a served model reads is
        strengthened with the same fidelity reminder (task t2)."""
        description = MOVE_SCHEMA[MOVE_REPLY_TO_OPERATOR]["description"].lower()
        assert "current result" in description
        assert "background" in description


# ---------------------------------------------------------------------------
# (C) AC1 — structural containment: run_senses_talk
# ---------------------------------------------------------------------------


class TestTalkStructuralContainment:
    def test_answer_already_containing_worker_answer_is_verbatim_presence(self) -> None:
        worker_answer = "the temperature is 21C"
        fake = _FakeMakeComplete(
            ModelResponse(
                content=_talk_json(f"Sure — {worker_answer}"), prompt_tokens=1, completion_tokens=1
            )
        )

        record = run_senses_talk(
            "what's the temperature?",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
            worker_answer=worker_answer,
        )

        assert record is not None
        assert worker_answer in record["answer"]  # structural containment holds
        assert record["verbatim_presence"] is True
        assert record["fallback"] is False
        assert record["knowledge_repetition"] is False
        assert record["degraded"] is False

    def test_answer_omitting_worker_answer_falls_back_and_degrades(self) -> None:
        worker_answer = "the temperature is 21C"
        fake = _FakeMakeComplete(
            ModelResponse(
                content=_talk_json("I'm not sure, ask again later."),
                prompt_tokens=1,
                completion_tokens=1,
            )
        )

        record = run_senses_talk(
            "what's the temperature?",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
            worker_answer=worker_answer,
        )

        assert record is not None
        # structural containment test, not prompt hope: the DISPLAYED text
        # contains the worker answer verbatim regardless of what the model said.
        assert worker_answer in record["answer"]
        assert record["answer"] == worker_answer  # the raw-answer fallback
        assert record["fallback"] is True
        assert record["degraded"] is True  # a fidelity failure records a degradation

    def test_no_worker_answer_is_byte_identical_to_before_this_parameter(self) -> None:
        fake = _FakeMakeComplete()
        record = run_senses_talk(
            "status?",
            feed_tail="[edit_file] x.py",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )
        assert record is not None
        # the pinned advisory dict shape (tests/test_senses_talk.py) is
        # unaffected when no worker_answer is given at all.
        assert set(record.keys()) == {
            "answer",
            "relay",
            "relay_text",
            "latency",
            "degraded",
            "tokens",
        }

    def test_truncated_prompt_sets_the_truncation_counter(self) -> None:
        worker_answer = "21C"
        fake = _FakeMakeComplete(
            ModelResponse(content=_talk_json(worker_answer), prompt_tokens=1, completion_tokens=1)
        )
        huge_feed = "line\n" * 5000

        record = run_senses_talk(
            "status?",
            feed_tail=huge_feed,
            packet=None,
            task_state=None,
            senses_config=_senses_config(context_budget_tokens=500),
            make_complete=fake,
            make_count_tokens=_char_counter,
            worker_answer=worker_answer,
        )

        assert record is not None
        assert record["truncated"] is True


# ---------------------------------------------------------------------------
# (D) AC1 — structural containment: senses_loop reply_to_operator
# ---------------------------------------------------------------------------


class TestLoopStructuralContainment:
    def test_reply_containing_worker_answer_is_verbatim_presence(self) -> None:
        worker_answer = "cortex finished writing uploader.py"
        d = _loop_driver(
            [json.dumps({"move": "reply_to_operator", "text": f"Update: {worker_answer}"})]
        )

        d.process_boundary(_op("status?", worker_answer=worker_answer))

        rec = d.records[-1]
        assert isinstance(rec, SensesRecord)
        assert rec.verbatim_presence is True
        assert rec.fallback is False
        talk = [c for c in d.chat if "kind" not in c][0]
        assert worker_answer in talk["answer"]

    def test_reply_omitting_worker_answer_falls_back_and_degrades(self) -> None:
        worker_answer = "cortex finished writing uploader.py"
        d = _loop_driver([json.dumps({"move": "reply_to_operator", "text": "still working on it"})])

        d.process_boundary(_op("status?", worker_answer=worker_answer))

        rec = d.records[-1]
        assert rec.fallback is True
        assert rec.degraded is True
        talk = [c for c in d.chat if "kind" not in c][0]
        assert talk["answer"] == worker_answer  # structural containment: verbatim fallback

    def test_no_worker_answer_is_byte_identical(self) -> None:
        d = _loop_driver([json.dumps({"move": "reply_to_operator", "text": "cortex is on step 3"})])
        d.process_boundary(_op("status?"))
        rec = d.records[-1]
        assert rec.verbatim_presence is False
        assert rec.fallback is False
        assert rec.knowledge_repetition is False
        # the pre-existing pinned to_dict shape survives unchanged.
        assert set(rec.to_dict().keys()) == {"point", "latency", "tokens", "degraded"}

    def test_truncated_completion_sets_the_truncation_counter(self) -> None:
        huge_feed = "line\n" * 5000
        d = _loop_driver(
            [json.dumps({"move": "reply_to_operator", "text": "ok"})],
            budget=500,
        )
        d.process_boundary(BoundaryContext(kind=BOUNDARY_OPERATOR_INPUT, feed_tail=huge_feed))
        assert d.records[-1].truncated is True


# ---------------------------------------------------------------------------
# (E) fidelity helper unit tests
# ---------------------------------------------------------------------------


class TestFidelityHelpers:
    def test_repeats_background_true_for_a_long_verbatim_snippet(self) -> None:
        knowledge = "The reference rig serves a 128K-context cortex model on this hardware stack."
        assert _repeats_background(knowledge, [knowledge]) is True

    def test_repeats_background_false_for_a_short_coincidental_overlap(self) -> None:
        assert _repeats_background("ok, got it", ["ok"]) is False

    def test_repeats_background_false_when_no_snippets(self) -> None:
        assert _repeats_background("anything", []) is False

    def test_enforce_fidelity_passthrough_when_no_worker_answer(self) -> None:
        final, verbatim, repetition, fallback = _enforce_fidelity("anything", None, [])
        assert final == "anything"
        assert (verbatim, repetition, fallback) == (False, False, False)

    def test_enforce_fidelity_verbatim_when_contained(self) -> None:
        final, verbatim, repetition, fallback = _enforce_fidelity("the answer is 42", "42", [])
        assert final == "the answer is 42"
        assert (verbatim, repetition, fallback) == (True, False, False)

    def test_enforce_fidelity_falls_back_when_missing(self) -> None:
        final, verbatim, repetition, fallback = _enforce_fidelity("I don't know", "42", [])
        assert final == "42"
        assert (verbatim, repetition, fallback) == (False, False, True)


# ---------------------------------------------------------------------------
# (F) AC3 — the embodiment 6/6 domain-mismatch regression
# ---------------------------------------------------------------------------


class TestEmbodimentDomainMismatchRegression:
    """Mirrors a real embodiment live-session failure: senses recited its
    knowledge block 6/6 turns instead of relaying the current answer. Seeds
    background "knowledge" with repeated domain-A facts, gives a current
    answer from domain B, and asserts EVERY one of 6 turns now either relays
    domain B verbatim or structurally falls back to it — never a bare
    domain-A recitation. The existing ``ContextPacket.original`` verbatim
    pin and the tools=[] structural pin both survive untouched."""

    _DOMAIN_A_FACT = (
        "Domain A background: the unit has a 6-DOF arm, dual RGB cameras, and a "
        "48V battery bus rated for four hours of continuous operation."
    )
    _DOMAIN_B_ANSWER = "Domain B current result: the kitchen door is currently unlocked."

    def test_six_of_six_turns_relay_domain_b_never_bare_domain_a_recitation(self) -> None:
        packet = ContextPacket(
            original="is the kitchen door locked?", interpretation="check door state"
        )
        original_before = packet.original
        history = [
            {"role": "senses", "text": self._DOMAIN_A_FACT},
            {"role": "operator", "text": "no, I asked about the door"},
            {"role": "senses", "text": self._DOMAIN_A_FACT},
        ]

        for turn in range(6):
            # The served model keeps reciting the domain-A knowledge block
            # instead of the domain-B answer -- the historical failure shape.
            fake = _FakeMakeComplete(
                ModelResponse(
                    content=_talk_json(self._DOMAIN_A_FACT), prompt_tokens=1, completion_tokens=1
                )
            )

            record = run_senses_talk(
                "is the kitchen door locked?",
                feed_tail="",
                packet=packet,
                task_state=None,
                senses_config=_senses_config(),
                make_complete=fake,
                make_count_tokens=_char_counter,
                history=history,
                worker_answer=self._DOMAIN_B_ANSWER,
            )

            assert record is not None, f"turn {turn}: unarmed unexpectedly"
            assert (
                self._DOMAIN_B_ANSWER in record["answer"]
            ), f"turn {turn}: domain B answer not relayed"
            assert record["fallback"] is True, f"turn {turn}: fidelity failure did not fall back"
            assert (
                record["knowledge_repetition"] is True
            ), f"turn {turn}: knowledge recitation undetected"
            assert record["degraded"] is True, f"turn {turn}: fallback did not record a degradation"
            # tools=[] pin: never touched, every single turn.
            assert fake.tools_calls == [[]]

        # ContextPacket.original stays verbatim, untouched across all 6 turns.
        assert packet.original == original_before == "is the kitchen door locked?"

    def test_six_of_six_loop_turns_relay_domain_b_via_the_coordination_loop(self) -> None:
        """The same regression shape, exercised through the senses coordination
        loop's reply_to_operator move (senses_loop.py) rather than the plain
        talk lane."""
        history = [{"role": "senses", "text": self._DOMAIN_A_FACT}]
        for turn in range(6):
            d = _loop_driver(
                [json.dumps({"move": "reply_to_operator", "text": self._DOMAIN_A_FACT})]
            )
            d.process_boundary(
                _op("is the kitchen door locked?", worker_answer=self._DOMAIN_B_ANSWER),
                history=history,
            )

            rec = d.records[-1]
            talk = [c for c in d.chat if "kind" not in c][0]
            assert self._DOMAIN_B_ANSWER in talk["answer"], f"turn {turn}: domain B not relayed"
            assert rec.fallback is True, f"turn {turn}: no fallback recorded"
            assert rec.knowledge_repetition is True, f"turn {turn}: knowledge recitation undetected"
            assert rec.degraded is True, f"turn {turn}: fallback did not degrade"
