"""Tests for :mod:`colleague.frontdoor` :func:`run_frontdoor` +
:class:`FrontDoorOutcome` (talking-to-one-teammate arc, task t5).

Surfaces under test: the ONE shared front-agnostic front-door entry that
composes the deterministic classifier (:func:`colleague.frontdoor.
classify_frontdoor`) with the senses front-door answer
(:func:`colleague.senses.run_senses_frontdoor`) so both the interactive
session and the mesh resident can decide-and-answer through one call.

1. unarmed (``senses_config=None``) never classifies, never consults senses.
2. a cortex-routed message never consults senses either (only a
   ``senses_direct`` route reaches the wire).
3. a clean senses-direct answer sets ``answered_directly``/``dispatch``
   correctly and builds the "talk" chat entry.
4. a degraded senses-direct attempt falls back to dispatching to cortex.
5. omitting ``facts`` defaults to the real curated architecture fact-set.

No network: every ``make_complete`` under test is a fake recording what it
was called with, mirroring the ``_FakeMakeComplete`` pattern in
``tests/test_senses_frontdoor.py``.
"""

from __future__ import annotations

import json

from colleague.config import EngineConfig
from colleague.frontdoor import CORTEX, SENSES_DIRECT, FrontDoorOutcome, run_frontdoor
from colleague.loop import ModelResponse

_FRONTDOOR_JSON = json.dumps({"answer": "I am senses, the front lobe."})


def _senses_config(**overrides) -> EngineConfig:
    """A plain EngineConfig standing in for the already-built senses config.

    A big budget means the prompt passes through untouched unless a test
    lowers it (mirrors ``tests/test_senses_frontdoor.py``'s helper).
    """
    defaults = dict(model="senses-model", context_budget_tokens=100000)
    defaults.update(overrides)
    return EngineConfig(**defaults)


class _FakeMakeComplete:
    """A recording stand-in for ``engine.make_complete`` (bound method shape).

    Mirrors ``tests/test_senses_frontdoor.py``'s ``_FakeMakeComplete``: models
    the ``(config, tools=...) -> CompleteFn`` call shape and records the
    ``tools`` it was offered + the messages the returned ``CompleteFn`` was
    called with.
    """

    def __init__(self, response: ModelResponse | None = None, raise_on_complete=None) -> None:
        self.tools_calls: list[list | None] = []
        self.complete_call_count = 0
        self.captured_messages: list[dict] | None = None
        self._response = response or ModelResponse(
            content=_FRONTDOOR_JSON, prompt_tokens=5, completion_tokens=7
        )
        self._raise_on_complete = raise_on_complete

    def __call__(self, config: EngineConfig, tools=None):
        self.tools_calls.append(tools)

        def complete(messages: list[dict]):
            self.complete_call_count += 1
            self.captured_messages = messages
            if self._raise_on_complete is not None:
                raise self._raise_on_complete
            return self._response

        return complete


class _RaisingMakeComplete:
    """A ``make_complete`` stand-in that fails the test if it is ever invoked.

    Used to prove senses is NEVER consulted on the unarmed or cortex-routed
    paths.
    """

    def __call__(self, config: EngineConfig, tools=None):
        raise AssertionError("make_complete must not be called on this path")


def _char_counter(messages: list[dict]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


# ---------------------------------------------------------------------------
# (1) unarmed -> dispatch to cortex, senses never consulted
# ---------------------------------------------------------------------------


class TestUnarmed:
    def test_none_senses_config_dispatches_to_cortex_without_consulting_senses(self) -> None:
        fake = _RaisingMakeComplete()

        outcome = run_frontdoor(
            "hi",
            senses_config=None,
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert isinstance(outcome, FrontDoorOutcome)
        assert outcome.route == CORTEX
        assert outcome.dispatch is True
        assert outcome.answered_directly is False
        assert outcome.answer is None
        assert outcome.degraded is False
        assert outcome.record is None
        assert outcome.chat_entry is None


# ---------------------------------------------------------------------------
# (2) cortex route -> dispatch, senses never consulted
# ---------------------------------------------------------------------------


class TestCortexRoute:
    def test_repo_touching_message_dispatches_without_consulting_senses(self) -> None:
        fake = _RaisingMakeComplete()

        outcome = run_frontdoor(
            "fix the bug in loop.py",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert outcome.route == CORTEX
        assert outcome.dispatch is True
        assert outcome.answered_directly is False
        assert outcome.record is not None
        assert outcome.record.point.endswith(":cortex")
        assert outcome.chat_entry is None


# ---------------------------------------------------------------------------
# (3) senses_direct clean -> answered directly, no dispatch
# ---------------------------------------------------------------------------


class TestSensesDirectClean:
    def test_clean_answer_is_returned_without_dispatch(self) -> None:
        fake = _FakeMakeComplete()

        outcome = run_frontdoor(
            "what are you?",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert outcome.route == SENSES_DIRECT
        assert outcome.dispatch is False
        assert outcome.answered_directly is True
        assert outcome.answer == "I am senses, the front lobe."
        assert outcome.degraded is False
        assert outcome.record is not None
        assert outcome.record.point.endswith(":senses_direct")
        assert outcome.record.degraded is False
        assert outcome.chat_entry is not None
        assert outcome.chat_entry["kind"] == "talk"
        assert outcome.chat_entry["message"] == "what are you?"
        assert outcome.chat_entry["answer"] == "I am senses, the front lobe."
        assert isinstance(outcome.chat_entry["at"], float)
        assert fake.complete_call_count == 1


# ---------------------------------------------------------------------------
# (4) senses_direct degraded -> falls back to dispatching to cortex
# ---------------------------------------------------------------------------


class TestSensesDirectDegraded:
    def test_degraded_answer_falls_back_to_cortex_dispatch(self) -> None:
        fake = _FakeMakeComplete(raise_on_complete=ConnectionError("connection refused"))

        outcome = run_frontdoor(
            "what are you?",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert outcome.route == SENSES_DIRECT
        assert outcome.dispatch is True
        assert outcome.answered_directly is False
        assert outcome.degraded is True
        assert outcome.answer is not None  # the safe degraded-fallback text
        assert outcome.record is not None
        assert outcome.record.point.endswith(":senses_direct")
        assert outcome.record.degraded is True
        assert outcome.chat_entry is None


# ---------------------------------------------------------------------------
# (5) facts default -> the real curated architecture fact-set reaches senses
# ---------------------------------------------------------------------------


class TestFactsDefault:
    def test_omitted_facts_defaults_to_real_architecture_facts(self) -> None:
        fake = _FakeMakeComplete()

        outcome = run_frontdoor(
            "tell me about yourself",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert outcome.answered_directly is True
        assert fake.captured_messages is not None
        user_content = fake.captured_messages[-1]["content"]
        # A real fact from colleague.architecture_facts.load_architecture_facts()
        # reached the senses prompt (e.g. the "cortex" lobe fact).
        assert "cortex" in user_content.lower()
