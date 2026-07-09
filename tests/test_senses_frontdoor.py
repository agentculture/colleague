"""Tests for the senses front-door lane (talking-to-one-teammate arc, task t3).

Surfaces under test (:mod:`colleague.senses` :func:`run_senses_frontdoor`): ONE
tools-off, grounded answer for a senses-direct turn (a greeting or a question
about colleague itself), so the senses front lobe can answer WITHOUT waking
cortex.

1. unarmed (``senses_config=None``) returns ``None`` cleanly, never reaching
   the wire.
2. a clean stub response comes back verbatim with ``degraded=False`` and exact
   summed tokens.
3. grounding — the system prompt forbids fabrication and instructs deferral
   to cortex, and the ``facts`` string given by the caller reaches the user
   prompt verbatim (grounded, not free-form) — pinned with the REAL curated
   fact-set from :func:`colleague.architecture_facts.load_architecture_facts`.
4. degrade-never-raise — any completion failure (unreachable endpoint, bad
   JSON, empty content, empty answer field) degrades to a safe fallback
   answer, never propagates an exception.
5. the returned dict shape is pinned exactly.

No network: every ``make_complete`` under test is a fake recording what it
was called with (mirrors the ``_FakeMakeComplete`` pattern in
``tests/test_senses_talk.py``).
"""

from __future__ import annotations

import json

from colleague.architecture_facts import load_architecture_facts
from colleague.config import EngineConfig
from colleague.loop import ModelResponse
from colleague.senses import run_senses_frontdoor

_FRONTDOOR_JSON = json.dumps({"answer": "I am senses, the front lobe."})


def _senses_config(**overrides) -> EngineConfig:
    """A plain EngineConfig standing in for the already-built senses config.

    A big budget means the prompt passes through untouched unless a test
    lowers it (mirrors ``tests/test_senses_talk.py``'s ``_senses_config``
    helper).
    """
    defaults = dict(model="senses-model", context_budget_tokens=100000)
    defaults.update(overrides)
    return EngineConfig(**defaults)


class _FakeMakeComplete:
    """A recording stand-in for ``engine.make_complete`` (bound method shape).

    :func:`run_senses_frontdoor` takes ``make_complete`` directly (not a full
    engine), so this fake models the ``(config, tools=...) -> CompleteFn`` call
    shape and records the ``tools`` it was offered + the messages the returned
    ``CompleteFn`` was called with.
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


def _char_counter(messages: list[dict]) -> int:
    """A trivial exact-char counter (mirrors ``tests/test_senses_talk.py``'s fake)."""
    return sum(len(m.get("content") or "") for m in messages)


# ---------------------------------------------------------------------------
# (1) unarmed -> None
# ---------------------------------------------------------------------------


class TestUnarmed:
    def test_none_senses_config_returns_none(self) -> None:
        fake = _FakeMakeComplete()

        result = run_senses_frontdoor(
            "hi",
            facts="F",
            senses_config=None,
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is None
        assert fake.complete_call_count == 0  # never even reached the wire


# ---------------------------------------------------------------------------
# (2) clean answer
# ---------------------------------------------------------------------------


class TestCleanAnswer:
    def test_stub_response_is_returned_clean_and_tools_off(self) -> None:
        fake = _FakeMakeComplete()

        result = run_senses_frontdoor(
            "hi, what are you?",
            facts="F",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None
        assert result["answer"] == "I am senses, the front lobe."
        assert result["degraded"] is False
        assert result["tokens"] is not None
        assert fake.tools_calls == [[]]  # tools-off ALWAYS: an empty list, never None
        assert fake.complete_call_count == 1

    def test_success_record_carries_exact_summed_tokens(self) -> None:
        fake = _FakeMakeComplete(
            ModelResponse(content=_FRONTDOOR_JSON, prompt_tokens=11, completion_tokens=13)
        )

        result = run_senses_frontdoor(
            "hi",
            facts="F",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None
        assert result["tokens"] == 24  # 11 + 13, exact -- never estimated


# ---------------------------------------------------------------------------
# (3) grounding
# ---------------------------------------------------------------------------


class TestGrounding:
    def test_system_prompt_forbids_fabrication_and_facts_reach_user_prompt(self) -> None:
        fake = _FakeMakeComplete()
        facts = load_architecture_facts()

        result = run_senses_frontdoor(
            "what is cortex?",
            facts=facts,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None
        sent = fake.captured_messages
        assert sent is not None
        system_content = sent[0]["content"]
        user_content = sent[-1]["content"]

        # System prompt forbids fabrication and instructs deferral to cortex.
        lowered = system_content.lower()
        assert "invent" in lowered or "fabricat" in lowered
        assert "cortex" in lowered
        assert "don't know" in lowered or "do not know" in lowered

        # The caller's facts string is grounded VERBATIM in the user prompt
        # (not paraphrased/free-form), and a key real fact substring reaches it.
        assert facts in user_content
        assert "cortex" in user_content.lower()
        assert "what is cortex?" in user_content

    def test_huge_prompt_is_windowed_to_the_senses_budget(self) -> None:
        fake = _FakeMakeComplete()
        huge_facts = "- some fact about colleague\n" * 2000
        config = _senses_config(context_budget_tokens=500)

        result = run_senses_frontdoor(
            "tell me about yourself",
            facts=huge_facts,
            senses_config=config,
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None
        sent = fake.captured_messages
        assert sent is not None
        user_content = sent[-1]["content"]
        assert len(user_content) < len(huge_facts)

    def test_no_make_count_tokens_falls_back_to_char_heuristic(self) -> None:
        """Omitting ``make_count_tokens`` still windows correctly (char fallback)."""
        fake = _FakeMakeComplete()
        huge_facts = "x" * 5000
        config = _senses_config(context_budget_tokens=200)

        result = run_senses_frontdoor(
            "status?",
            facts=huge_facts,
            senses_config=config,
            make_complete=fake,
            # make_count_tokens omitted -> colleague.context.count_tokens_chars
        )

        assert result is not None
        sent = fake.captured_messages
        assert sent is not None
        assert len(sent[-1]["content"]) < len(huge_facts)


# ---------------------------------------------------------------------------
# (4) degrade-never-raise
# ---------------------------------------------------------------------------


class TestDegrades:
    def test_unreachable_endpoint_degrades_never_raises(self) -> None:
        fake = _FakeMakeComplete(raise_on_complete=ConnectionError("connection refused"))

        result = run_senses_frontdoor(
            "hi",
            facts="F",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None
        assert result["degraded"] is True
        assert result["tokens"] is None
        assert isinstance(result["latency"], float) and result["latency"] >= 0
        assert result["answer"] == "senses can't answer that right now — cortex can."

    def test_bad_json_degrades_never_raises(self) -> None:
        fake = _FakeMakeComplete(
            ModelResponse(content="I think colleague is fine, no JSON here.", prompt_tokens=1)
        )

        result = run_senses_frontdoor(
            "hi",
            facts="F",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None
        assert result["degraded"] is True
        assert result["answer"] == "senses can't answer that right now — cortex can."

    def test_empty_content_degrades_never_raises(self) -> None:
        fake = _FakeMakeComplete(ModelResponse(content="", reasoning=""))

        result = run_senses_frontdoor(
            "hi",
            facts="F",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None
        assert result["degraded"] is True

    def test_empty_answer_field_degrades_never_raises(self) -> None:
        empty_answer = json.dumps({"answer": "   "})
        fake = _FakeMakeComplete(ModelResponse(content=empty_answer, prompt_tokens=1))

        result = run_senses_frontdoor(
            "hi",
            facts="F",
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None
        assert result["degraded"] is True


# ---------------------------------------------------------------------------
# record shape
# ---------------------------------------------------------------------------


def test_record_shape_is_the_pinned_advisory_dict() -> None:
    fake = _FakeMakeComplete()

    result = run_senses_frontdoor(
        "hi",
        facts="F",
        senses_config=_senses_config(),
        make_complete=fake,
        make_count_tokens=_char_counter,
    )

    assert result is not None
    assert set(result.keys()) == {"answer", "latency", "degraded", "tokens"}
    assert isinstance(result["answer"], str)
    assert isinstance(result["latency"], float) and result["latency"] >= 0
    assert isinstance(result["degraded"], bool)
    assert result["tokens"] is None or isinstance(result["tokens"], int)
