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
6. (task t10) an optional ``config`` param appends the REAL resolved
   self-facts (:func:`colleague.selfknowledge.build_self_facts`) onto the
   fact-set grounding a senses-direct answer, so "what model are you?" can
   answer with the actual resolved model ids instead of the static fact-set's
   deferral. Omitting ``config`` stays byte-identical to before this task.

No network: every ``make_complete`` under test is a fake recording what it
was called with, mirroring the ``_FakeMakeComplete`` pattern in
``tests/test_senses_frontdoor.py``.
"""

from __future__ import annotations

import json

from colleague.config import EngineConfig, SensesConfig
from colleague.frontdoor import (
    CORTEX,
    SENSES_DIRECT,
    FrontDoorOutcome,
    cortex_frontdoor_outcome,
    run_frontdoor,
)
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

    def test_cortex_frontdoor_outcome_shared_helper(self) -> None:
        # Bug 4: cortex_frontdoor_outcome() is the single source of truth for the
        # CORTEX outcome shape, shared by run_frontdoor's own CORTEX branch and the
        # session's classify-first short-circuit (which never resolves/loads the
        # senses engine for the common CORTEX case).
        outcome = cortex_frontdoor_outcome()

        assert outcome.route == CORTEX
        assert outcome.dispatch is True
        assert outcome.answered_directly is False
        assert outcome.record is not None
        assert outcome.record.point.endswith(":cortex")


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

    def test_omitting_config_never_appends_self_facts(self) -> None:
        """Byte-identical pin: no ``config`` kwarg -> no self-facts block at
        all (not even the honest 'not configured'/'not armed' lines) — the
        prompt is exactly what it was before task t10."""
        fake = _FakeMakeComplete()

        outcome = run_frontdoor(
            "what model are you?",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert outcome.answered_directly is True
        user_content = fake.captured_messages[-1]["content"]
        assert "senses: not configured" not in user_content
        assert "lobes: not armed" not in user_content
        # The self-facts gate-summary line (build_self_facts's own format,
        # e.g. "gates: lint on ..."), not the static architecture fact-set's
        # unrelated prose mentioning "pre-handoff gates: a lint gate".
        assert "gates: lint" not in user_content


# ---------------------------------------------------------------------------
# (6) task t10 -- resolved self-facts reach the senses-direct prompt
# ---------------------------------------------------------------------------


def _armed_engine_config(
    *, cortex_model: str = "cortex-sentinel-9000", senses_model: str = "senses-sentinel-42"
) -> EngineConfig:
    """The ORIGINAL/main resolved EngineConfig (not the senses-replaced
    ``senses_config`` the routing call already receives) — carries the real
    cortex model id plus the ``senses`` sub-config
    :func:`colleague.selfknowledge.build_self_facts` reads."""
    config = EngineConfig(model=cortex_model)
    config.senses = SensesConfig(
        model=senses_model, base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


class TestSelfFactsComposition:
    def test_resolved_model_ids_reach_the_senses_prompt_when_config_given(self) -> None:
        """The headline case: with a resolved ``config`` given, the exact
        cortex + senses model id strings reach the prompt verbatim — not the
        live-proven "I don't know which specific model I am using" deferral,
        which only happens because the static fact-set never names a model."""
        fake = _FakeMakeComplete()
        config = _armed_engine_config()

        outcome = run_frontdoor(
            "what model are you?",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
            config=config,
        )

        assert outcome.answered_directly is True
        assert fake.captured_messages is not None
        user_content = fake.captured_messages[-1]["content"]
        # Exact, verbatim -- no truncation/rewrite of the resolved ids.
        assert "cortex-sentinel-9000" in user_content
        assert "senses-sentinel-42" in user_content
        assert "cortex: cortex-sentinel-9000" in user_content
        assert "senses: senses-sentinel-42" in user_content

    def test_config_present_but_lobes_unarmed_says_not_armed_no_fabricated_url(self) -> None:
        """Honesty pin: ``config`` given, ``gateway_url`` omitted (lobes
        unarmed) -> the composed facts say 'not armed', never a fabricated
        URL — while the resolved model ids still appear verbatim."""
        fake = _FakeMakeComplete()
        config = _armed_engine_config()

        outcome = run_frontdoor(
            "what model are you?",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
            config=config,
        )

        assert outcome.answered_directly is True
        user_content = fake.captured_messages[-1]["content"]
        assert "lobes: not armed" in user_content
        for line in user_content.split("\n"):
            if line.startswith("lobes:"):
                assert "not armed" in line
                assert "http" not in line
        assert "cortex-sentinel-9000" in user_content
        assert "senses-sentinel-42" in user_content

    def test_gateway_url_reaches_the_prompt_when_given(self) -> None:
        """A resolved lobes gateway URL, when passed, appears verbatim too."""
        fake = _FakeMakeComplete()
        config = _armed_engine_config()

        outcome = run_frontdoor(
            "what model are you?",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
            config=config,
            gateway_url="http://lobes.local:8001",
        )

        assert outcome.answered_directly is True
        user_content = fake.captured_messages[-1]["content"]
        assert "lobes: http://lobes.local:8001" in user_content

    def test_config_with_no_senses_subconfig_says_not_configured(self) -> None:
        """A resolved ``config`` whose OWN ``.senses`` is ``None`` (e.g. senses
        armed only via a lobes rung distinct from *config*) renders the
        honest 'not configured' line rather than fabricating a senses id."""
        fake = _FakeMakeComplete()
        config = EngineConfig(model="cortex-sentinel-9000")  # config.senses stays None

        outcome = run_frontdoor(
            "what model are you?",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
            config=config,
        )

        assert outcome.answered_directly is True
        user_content = fake.captured_messages[-1]["content"]
        assert "senses: not configured" in user_content
        assert "cortex-sentinel-9000" in user_content

    def test_cortex_route_never_composes_self_facts(self) -> None:
        """A cortex-routed message never even builds the self-facts block —
        composition happens only inside the senses-direct branch, and
        ``make_complete`` is never called on this path."""
        fake = _RaisingMakeComplete()
        config = _armed_engine_config()

        outcome = run_frontdoor(
            "fix the bug in loop.py",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
            config=config,
        )

        assert outcome.route == CORTEX
        assert outcome.dispatch is True
