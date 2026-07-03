"""Tests for the senses live-presence talk lane (senses live presence, task t4).

Surfaces under test (:mod:`colleague.senses` :func:`run_senses_talk`):

1. tools-off on the wire — the completion is issued with an EMPTY tools list;
   the talk lane structurally cannot carry a tool schema.
2. windowed to senses' OWN budget — a huge flight-feed tail is trimmed to fit
   ``senses_config.context_budget_tokens`` before it is sent.
3. grounded — the prompt sent to the model explicitly carries the feed tail and
   instructs "answer only from this context / say you don't know" (a
   prompt-construction contract; a full hallucination-catch is a model-behavior
   concern, out of scope for a unit test).
4. the explicit ``relay_prefix`` (default ``"cortex:"``) ALWAYS wins over the
   model's own relay judgment — the guaranteed, deterministic relay path.
5. unarmed (``senses_config=None``) returns ``None`` cleanly.
6. degrade-never-raise — any completion failure returns an advisory record with
   ``degraded=True``, never propagates an exception.

No network: every ``make_complete`` under test is a fake recording what it was
called with (mirrors the ``_FakeEngine`` pattern in ``tests/test_senses.py``,
adapted since :func:`run_senses_talk` takes ``make_complete`` directly rather
than a full engine).
"""

from __future__ import annotations

import json

from colleague.config import EngineConfig
from colleague.contract import ContextPacket
from colleague.loop import ModelResponse
from colleague.senses import TALK_POINT, run_senses_talk

_TALK_JSON = json.dumps(
    {
        "answer": "cortex is currently editing colleague/config.py.",
        "relay": False,
        "relay_text": "",
    }
)


def _senses_config(**overrides) -> EngineConfig:
    """A plain EngineConfig standing in for the already-built senses config.

    A big budget means the feed tail passes through untouched unless a test
    lowers it (mirrors ``tests/test_senses.py``'s ``_senses_config`` helper).
    """
    defaults = dict(model="senses-model", context_budget_tokens=100000)
    defaults.update(overrides)
    return EngineConfig(**defaults)


class _FakeMakeComplete:
    """A recording stand-in for ``engine.make_complete`` (bound method shape).

    :func:`run_senses_talk` takes ``make_complete`` directly (not a full
    engine), so this fake models the ``(config, tools=...) -> CompleteFn``
    call shape and records the ``tools`` it was offered + the messages the
    returned ``CompleteFn`` was called with.
    """

    def __init__(self, response: ModelResponse | None = None, raise_on_complete=None) -> None:
        self.tools_calls: list[list | None] = []
        self.complete_call_count = 0
        self.captured_messages: list[dict] | None = None
        self._response = response or ModelResponse(
            content=_TALK_JSON, prompt_tokens=5, completion_tokens=7
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
    """A trivial exact-char counter (mirrors ``tests/test_senses.py``'s fake)."""
    return sum(len(m.get("content") or "") for m in messages)


# ---------------------------------------------------------------------------
# (1) tools-off on the wire
# ---------------------------------------------------------------------------


class TestToolsOff:
    def test_make_complete_called_with_empty_tools(self) -> None:
        fake = _FakeMakeComplete()
        record = run_senses_talk(
            "what is cortex doing?",
            feed_tail="[edit_file] colleague/config.py",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert fake.tools_calls == [[]]  # tools-off ALWAYS: an empty list, never None
        assert fake.complete_call_count == 1
        assert record is not None
        assert record["degraded"] is False


# ---------------------------------------------------------------------------
# (2) windowed to senses' OWN budget
# ---------------------------------------------------------------------------


class TestFeedWindowing:
    def test_huge_feed_tail_is_trimmed_to_the_senses_budget(self) -> None:
        fake = _FakeMakeComplete()
        huge_feed = "[read_file] file.py\n" * 2000  # far larger than the budget
        config = _senses_config(context_budget_tokens=500)

        record = run_senses_talk(
            "how's it going?",
            feed_tail=huge_feed,
            packet=None,
            task_state=None,
            senses_config=config,
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        assert record["degraded"] is False
        sent = fake.captured_messages
        assert sent is not None
        # The sent prompt is well under the raw huge feed size — it was windowed.
        total_chars = sum(len(m.get("content") or "") for m in sent)
        assert total_chars < len(huge_feed)
        user_content = sent[-1]["content"]
        assert len(user_content) < len(huge_feed)
        assert "[senses digest truncated to fit budget]" in user_content
        # The operator's live message SURVIVES intact — only the feed was cut,
        # never the fixed context (packet/task_state/message).
        assert "how's it going?" in user_content

    def test_small_feed_tail_passes_through_untouched(self) -> None:
        fake = _FakeMakeComplete()
        feed = "[edit_file] colleague/config.py"

        record = run_senses_talk(
            "what's happening?",
            feed_tail=feed,
            packet=None,
            task_state=None,
            senses_config=_senses_config(),  # generous default budget
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        sent = fake.captured_messages
        assert sent is not None
        assert feed in sent[-1]["content"]
        assert "[senses digest truncated to fit budget]" not in sent[-1]["content"]

    def test_no_make_count_tokens_falls_back_to_char_heuristic(self) -> None:
        """Omitting ``make_count_tokens`` still windows correctly (char fallback)."""
        fake = _FakeMakeComplete()
        huge_feed = "x" * 5000
        config = _senses_config(context_budget_tokens=200)

        record = run_senses_talk(
            "status?",
            feed_tail=huge_feed,
            packet=None,
            task_state=None,
            senses_config=config,
            make_complete=fake,
            # make_count_tokens omitted -> colleague.context.count_tokens_chars
        )

        assert record is not None
        sent = fake.captured_messages
        assert sent is not None
        assert len(sent[-1]["content"]) < len(huge_feed)


# ---------------------------------------------------------------------------
# (3) grounded — the prompt-construction contract
# ---------------------------------------------------------------------------


class TestGrounding:
    def test_prompt_carries_the_feed_tail_and_instructs_grounded_answers(self) -> None:
        """The model answers with a fact NOT present in feed_tail — this test
        pins the DESIGN intent (the prompt explicitly carries the feed tail and
        instructs "answer only / say you don't know"), not model behavior."""
        fabricated = json.dumps(
            {
                "answer": "cortex finished 20 minutes ago and is now idle.",
                "relay": False,
                "relay_text": "",
            }
        )
        fake = _FakeMakeComplete(ModelResponse(content=fabricated, prompt_tokens=4))
        feed = "[edit_file] colleague/config.py\n[run_command] pytest -q"
        packet = ContextPacket(original="add a retry to the uploader")

        record = run_senses_talk(
            "is cortex done yet?",
            feed_tail=feed,
            packet=packet,
            task_state={"step": 3, "phase": "editing"},
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        sent = fake.captured_messages
        assert sent is not None
        system_content = sent[0]["content"]
        user_content = sent[-1]["content"]
        # The feed tail is verbatim in the prompt sent to the model.
        assert feed in user_content
        # The operator's original request + task state also ride the prompt.
        assert "add a retry to the uploader" in user_content
        assert "editing" in user_content
        # The system prompt instructs grounded, non-fabricated answers.
        assert "ONLY" in system_content
        assert "don't know" in system_content
        # (Design intent only: the fabricated answer above is NOT itself
        # asserted false here — catching a live hallucination is a model
        # behavior concern the live proof (t10) covers, not a unit test.)
        assert record["answer"] == "cortex finished 20 minutes ago and is now idle."


# ---------------------------------------------------------------------------
# (4) explicit relay prefix ALWAYS wins
# ---------------------------------------------------------------------------


class TestRelayPrefixOverride:
    def test_explicit_prefix_forces_relay_true_over_model_no(self) -> None:
        """The model says NOT to relay; the "cortex:" prefix overrides it anyway."""
        model_says_no = json.dumps(
            {"answer": "Got it, just chatting.", "relay": False, "relay_text": "irrelevant"}
        )
        fake = _FakeMakeComplete(ModelResponse(content=model_says_no, prompt_tokens=2))

        record = run_senses_talk(
            "cortex: do X",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        assert record["relay"] is True
        assert record["relay_text"] == "do X"

    def test_no_prefix_uses_the_models_own_relay_judgment(self) -> None:
        model_says_yes = json.dumps(
            {"answer": "Sure, I'll pass that along.", "relay": True, "relay_text": "focus here"}
        )
        fake = _FakeMakeComplete(ModelResponse(content=model_says_yes, prompt_tokens=2))

        record = run_senses_talk(
            "please focus on the config file",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        assert record["relay"] is True
        assert record["relay_text"] == "focus here"

    def test_prefix_override_survives_a_degraded_call(self) -> None:
        """The GUARANTEED relay path: even when senses itself fails, an explicit
        "cortex:" prefixed message still relays."""
        fake = _FakeMakeComplete(raise_on_complete=ConnectionError("refused"))

        record = run_senses_talk(
            "cortex: focus on the config file",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        assert record["degraded"] is True
        assert record["relay"] is True
        assert record["relay_text"] == "focus on the config file"

    def test_custom_relay_prefix(self) -> None:
        fake = _FakeMakeComplete()

        record = run_senses_talk(
            "colleague: stop editing that file",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
            relay_prefix="colleague:",
        )

        assert record is not None
        assert record["relay"] is True
        assert record["relay_text"] == "stop editing that file"


# ---------------------------------------------------------------------------
# (5) unarmed -> None
# ---------------------------------------------------------------------------


class TestUnarmed:
    def test_none_senses_config_returns_none(self) -> None:
        fake = _FakeMakeComplete()

        record = run_senses_talk(
            "hello?",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=None,
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is None
        assert fake.complete_call_count == 0  # never even reached the wire


# ---------------------------------------------------------------------------
# (6) degrade-never-raise
# ---------------------------------------------------------------------------


class TestDegrades:
    def test_unreachable_endpoint_degrades_never_raises(self) -> None:
        fake = _FakeMakeComplete(raise_on_complete=ConnectionError("connection refused"))

        record = run_senses_talk(
            "how's it going?",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        assert record["degraded"] is True
        assert record["tokens"] is None
        assert isinstance(record["latency"], float) and record["latency"] >= 0
        assert record["answer"]  # a safe non-empty notice, never a fabricated status
        assert record["relay"] is False  # no explicit prefix -> no relay
        assert record["relay_text"] == "how's it going?"

    def test_bad_json_degrades_never_raises(self) -> None:
        fake = _FakeMakeComplete(
            ModelResponse(content="I think cortex is fine, no JSON here.", prompt_tokens=1)
        )

        record = run_senses_talk(
            "status?",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        assert record["degraded"] is True

    def test_empty_content_degrades_never_raises(self) -> None:
        fake = _FakeMakeComplete(ModelResponse(content="", reasoning=""))

        record = run_senses_talk(
            "status?",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        assert record["degraded"] is True

    def test_empty_answer_field_degrades_never_raises(self) -> None:
        empty_answer = json.dumps({"answer": "   ", "relay": False, "relay_text": ""})
        fake = _FakeMakeComplete(ModelResponse(content=empty_answer, prompt_tokens=1))

        record = run_senses_talk(
            "status?",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=_senses_config(),
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert record is not None
        assert record["degraded"] is True


# ---------------------------------------------------------------------------
# record shape
# ---------------------------------------------------------------------------


def test_record_shape_is_the_pinned_advisory_dict() -> None:
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
    assert set(record.keys()) == {"answer", "relay", "relay_text", "latency", "degraded", "tokens"}
    assert isinstance(record["answer"], str)
    assert isinstance(record["relay"], bool)
    assert isinstance(record["relay_text"], str)
    assert isinstance(record["latency"], float) and record["latency"] >= 0
    assert isinstance(record["degraded"], bool)
    assert record["tokens"] is None or isinstance(record["tokens"], int)


def test_success_record_carries_exact_summed_tokens() -> None:
    fake = _FakeMakeComplete(
        ModelResponse(content=_TALK_JSON, prompt_tokens=11, completion_tokens=13)
    )
    record = run_senses_talk(
        "status?",
        feed_tail="",
        packet=None,
        task_state=None,
        senses_config=_senses_config(),
        make_complete=fake,
        make_count_tokens=_char_counter,
    )

    assert record is not None
    assert record["tokens"] == 24  # 11 + 13, exact -- never estimated


def test_talk_point_constant_is_stable_for_callers() -> None:
    """TALK_POINT is the label a caller (t5/t6) tags a SensesRecord with when it
    wraps this dict for the artifact — not returned inline (the dict shape above
    is deliberately flat, unlike SensesRecord)."""
    assert TALK_POINT == "senses-talk"


# ---------------------------------------------------------------------------
# boundary — no ToolExecutor / no subprocess (mirrors tests/test_senses.py)
# ---------------------------------------------------------------------------


def test_senses_module_still_has_no_io_surface_or_tool_executor() -> None:
    """senses.py stays pure stdlib + the engine's own OpenAI-wire seam — no
    ToolExecutor import, no socket/daemon/thread/subprocess primitive (the
    structural invariant a later proof test (t9) will pin package-wide)."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "colleague" / "senses.py"
    source = src.read_text(encoding="utf-8")
    for forbidden in (
        "import socket",
        "import asyncio",
        "import threading",
        "concurrent.futures",
        "import subprocess",
        "ToolExecutor",
    ):
        assert forbidden not in source, f"senses.py must not use {forbidden!r}"
