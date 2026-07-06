"""Tests for the cortex/senses "senses" invocation layer (task t5).

Surfaces under test (:mod:`colleague.senses`):

1. tools-off on the wire — every senses completion is issued with an EMPTY
   offered-tools list; a senses request NEVER carries a tool schema.
2. the verbatim-original invariant — ``ContextPacket.original`` is the caller's
   input byte-for-byte, NEVER derived from the model output (even when the model
   emits a bogus ``original`` of its own).
3. degrade-never-raise — an unreachable endpoint, bad/lossy JSON, empty content,
   and the ``mock`` engine's ``NotImplementedError`` all yield ``(None, degraded
   record)`` so the caller keeps the raw request/summary.
4. runtime-fact records — each :class:`SensesRecord` carries latency/tokens/
   degraded per point, and asserts NOTHING about answer quality.

No network: every engine is a fake exposing ``make_complete`` /
``make_count_tokens`` (recording what it was called with), or the real ``mock``
engine (whose ``make_complete`` raises ``NotImplementedError``).
"""

from __future__ import annotations

from colleague.config import EngineConfig, SensesConfig
from colleague.contract import ContextPacket, SensesRecord
from colleague.loop import ModelResponse
from colleague.registry import load
from colleague.senses import (
    INTAKE_POINT,
    SPEAKBACK_POINT,
    run_senses_intake,
    run_senses_speakback,
    run_senses_talk,
    run_senses_update,
    senses_engine_config,
)

_INTAKE_JSON = (
    '{"interpretation": "add a retry to the uploader", "confidence": 0.8, '
    '"task_type": "feature", "omissions": ["which backoff", "max attempts"]}'
)


def _senses_config(**overrides) -> EngineConfig:
    """A plain EngineConfig standing in for the already-built senses config.

    ``run_senses_*`` take the senses-pointed EngineConfig directly (t6 builds it
    via ``senses_engine_config``); a big budget means ``_window_text`` passes the
    prompt through untouched unless a test lowers it.
    """
    defaults = dict(model="senses-model", context_budget_tokens=100000)
    defaults.update(overrides)
    return EngineConfig(**defaults)


class _FakeEngine:
    """Records make_complete()/complete() calls; no network, fully scripted.

    Mirrors the fake used by ``tests/test_deepthink.py``: it captures the
    ``tools`` argument handed to ``make_complete`` (so a test can assert
    tools-off on the wire) and the messages handed to ``complete``.
    """

    name = "fake"

    def __init__(self, response: ModelResponse | None = None, raise_on_complete=None) -> None:
        self.make_complete_calls: list[list[dict] | None] = []
        self.complete_call_count = 0
        self.captured_messages: list[dict] | None = None
        self._response = response or ModelResponse(
            content=_INTAKE_JSON, prompt_tokens=5, completion_tokens=7
        )
        self._raise_on_complete = raise_on_complete

    def make_count_tokens(self, config: EngineConfig):
        def counter(messages: list[dict]) -> int:
            return sum(len(m.get("content") or "") for m in messages)

        return counter

    def make_complete(self, config: EngineConfig, tools=None):
        self.make_complete_calls.append(tools)

        def complete(messages: list[dict]) -> ModelResponse:
            self.complete_call_count += 1
            self.captured_messages = messages
            if self._raise_on_complete is not None:
                raise self._raise_on_complete
            return self._response

        return complete


# ---------------------------------------------------------------------------
# senses_engine_config — the config builder t6 uses
# ---------------------------------------------------------------------------


class TestSensesEngineConfig:
    def test_none_without_senses_declaration(self) -> None:
        assert senses_engine_config(EngineConfig()) is None

    def test_maps_replaced_fields_and_inherits_the_rest(self) -> None:
        config = EngineConfig(
            model="main-model",
            base_url="http://main:8001/v1",
            api_key="main-key",
            max_steps=99,
            timeout=42.0,
            senses=SensesConfig(
                model="senses-model",
                base_url="http://senses:8003/v1",
                api_key="senses-key",
                context_budget=32768,
            ),
        )

        sc = senses_engine_config(config)

        assert sc is not None
        assert sc.model == "senses-model"
        assert sc.base_url == "http://senses:8003/v1"
        assert sc.api_key == "senses-key"
        # windowed to the senses model's OWN budget, never the main model's.
        assert sc.context_budget_tokens == 32768
        # unrelated knobs inherit unchanged from the main config.
        assert sc.max_steps == 99
        assert sc.timeout == 42.0


# ---------------------------------------------------------------------------
# (1) tools-off on the wire + (2) verbatim original
# ---------------------------------------------------------------------------


class TestIntakeToolsOffAndVerbatimOriginal:
    def test_make_complete_called_with_empty_tools(self) -> None:
        """A senses request NEVER carries a tool schema — make_complete gets []."""
        fake = _FakeEngine()
        packet, record = run_senses_intake("do the thing", _senses_config(), fake)

        # tools-off ALWAYS: exactly one make_complete, offered an EMPTY tool list.
        assert fake.make_complete_calls == [[]]
        assert fake.complete_call_count == 1
        assert record.degraded is False
        assert isinstance(packet, ContextPacket)

    def test_original_is_verbatim_input_not_model_output(self) -> None:
        """packet.original is the exact input, even when the model emits its own."""
        text = "  Fix the flaky test in tests/test_widget.py — it times out.\n"
        # The model tries to supply a DIFFERENT original; it must be ignored.
        bogus = (
            '{"original": "MODEL REWROTE THIS", "interpretation": "deflake a test", '
            '"confidence": 0.6, "task_type": "bugfix", "omissions": ["root cause"]}'
        )
        fake = _FakeEngine(ModelResponse(content=bogus, prompt_tokens=3, completion_tokens=4))

        packet, record = run_senses_intake(text, _senses_config(), fake)

        assert packet is not None
        # The core invariant: original survives byte-for-byte (whitespace,
        # trailing newline, everything) — sourced from the input, NOT the model.
        assert packet.original == text
        assert packet.original != "MODEL REWROTE THIS"
        # The derived fields DO come from the model.
        assert packet.interpretation == "deflake a test"
        assert packet.confidence == 0.6
        assert packet.task_type == "bugfix"
        assert packet.omissions == ["root cause"]
        assert record.degraded is False

    def test_structured_fields_parsed_from_model_json(self) -> None:
        fake = _FakeEngine()
        packet, _ = run_senses_intake("add a retry to the uploader", _senses_config(), fake)

        assert packet is not None
        assert packet.interpretation == "add a retry to the uploader"
        assert packet.confidence == 0.8
        assert packet.task_type == "feature"
        assert packet.omissions == ["which backoff", "max attempts"]

    def test_intake_windows_prompt_to_senses_budget(self) -> None:
        """A huge request is truncated under the senses send budget before sending.

        The verbatim original is STILL the full input — only the prompt SENT to
        the senses model is windowed.
        """
        fake = _FakeEngine()
        huge = "x" * 5000
        budget = 2000
        config = _senses_config(context_budget_tokens=budget)
        send_budget = budget - budget // 4  # the reserve arithmetic in _window_text

        packet, record = run_senses_intake(huge, config, fake)

        sent = fake.captured_messages
        assert sent is not None
        # The full [system, user] prompt is windowed under the senses send budget
        # (the fixed system prompt is the floor; only the user text is truncated).
        total_chars = sum(len(m.get("content") or "") for m in sent)
        assert total_chars <= send_budget
        assert len(sent[-1]["content"]) < len(huge)  # the user text was truncated
        assert "[senses digest truncated to fit budget]" in sent[-1]["content"]
        # original is the FULL input despite the windowed prompt.
        assert packet is not None
        assert packet.original == huge
        assert record.degraded is False


# ---------------------------------------------------------------------------
# ack rides the SAME intake completion (talking-to-one arc, task t1)
# ---------------------------------------------------------------------------


class TestIntakeAck:
    """``run_senses_intake`` returns a senses-authored ``ack`` alongside the
    packet, sourced from the SAME single completion (zero extra calls, zero
    extra latency — the spec's ack-shape decision)."""

    def test_ack_parsed_from_the_same_completion_zero_extra_calls(self) -> None:
        reply = (
            '{"interpretation": "add a retry to the uploader", "confidence": 0.8, '
            '"task_type": "feature", "omissions": ["which backoff"], '
            '"ack": "Got it — you want a retry added to the uploader; handing this '
            'to cortex now."}'
        )
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=5, completion_tokens=9))

        packet, record = run_senses_intake("add a retry to the uploader", _senses_config(), fake)

        # exactly ONE completion issued — the ack rides it, no second call.
        assert fake.make_complete_calls == [[]]
        assert fake.complete_call_count == 1
        assert packet is not None
        assert record.degraded is False
        assert (
            packet.ack
            == "Got it — you want a retry added to the uploader; handing this to cortex now."
        )

    def test_ack_taken_verbatim_from_the_model_reply(self) -> None:
        """h2 grounding pin: the ack is exactly the model's own wording (modulo
        strip/cap) — no code path invents ack content absent from the reply."""
        exact_wording = "Understood — deflaking the widget test; cortex is on it."
        reply = (
            '{"interpretation": "deflake a test", "confidence": 0.7, '
            f'"task_type": "bugfix", "omissions": [], "ack": "{exact_wording}"}}'
        )
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=2, completion_tokens=3))

        packet, _ = run_senses_intake("fix the flaky test", _senses_config(), fake)

        assert packet is not None
        assert packet.ack == exact_wording

    def test_ack_missing_defaults_to_none_back_compat(self) -> None:
        """A reply with no ``ack`` key (today's shape) leaves ``packet.ack``
        ``None`` — byte-identical to before this field existed."""
        fake = _FakeEngine()  # _INTAKE_JSON module fixture carries no "ack" key
        packet, record = run_senses_intake("add a retry to the uploader", _senses_config(), fake)

        assert packet is not None
        assert packet.ack is None
        assert record.degraded is False

    def test_ack_is_stripped_and_hard_capped(self) -> None:
        overlong = "x" * 800
        reply = (
            '{"interpretation": "i", "confidence": 0.5, "task_type": "feature", '
            f'"omissions": [], "ack": "   {overlong}   "}}'
        )
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=1, completion_tokens=1))

        packet, _ = run_senses_intake("do it", _senses_config(), fake)

        assert packet is not None
        assert packet.ack is not None
        assert len(packet.ack) <= 500
        assert not packet.ack.startswith(" ") and not packet.ack.endswith(" ")
        assert packet.ack == "x" * 500

    def test_non_string_ack_is_ignored(self) -> None:
        for bogus_ack in ('"ack": 3.14', '"ack": ["a", "b"]', '"ack": null'):
            reply = (
                '{"interpretation": "i", "confidence": 0.5, "task_type": "feature", '
                f'"omissions": [], {bogus_ack}}}'
            )
            fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=1, completion_tokens=1))

            packet, record = run_senses_intake("do it", _senses_config(), fake)

            assert packet is not None
            assert packet.ack is None
            assert record.degraded is False


# ---------------------------------------------------------------------------
# (3) degrade-never-raise — intake keeps the raw request
# ---------------------------------------------------------------------------


class TestIntakeDegrades:
    def test_unreachable_endpoint_degrades_to_none(self) -> None:
        fake = _FakeEngine(raise_on_complete=ConnectionError("connection refused"))
        packet, record = run_senses_intake("do it", _senses_config(), fake)

        assert packet is None  # caller passes the RAW text through untouched
        assert record.degraded is True
        assert record.point == INTAKE_POINT
        assert record.tokens is None
        assert record.latency is not None and record.latency >= 0

    def test_bad_json_degrades_to_none(self) -> None:
        fake = _FakeEngine(
            ModelResponse(content="I think this is a bugfix, no JSON here.", prompt_tokens=1)
        )
        packet, record = run_senses_intake("do it", _senses_config(), fake)

        assert packet is None
        assert record.degraded is True

    def test_empty_content_degrades_to_none(self) -> None:
        fake = _FakeEngine(ModelResponse(content="", reasoning=""))
        packet, record = run_senses_intake("do it", _senses_config(), fake)

        assert packet is None
        assert record.degraded is True

    def test_mock_engine_not_implemented_degrades_never_raises(self) -> None:
        """mock.make_complete raises NotImplementedError → degraded no-op.

        This is how a senses-armed ``mock`` run records a degraded no-op — the
        all-engines contract: the degrade-never-raise wrapping catches it.
        """
        engine = load("mock")
        packet, record = run_senses_intake("do it", _senses_config(), engine)

        assert packet is None
        assert record.degraded is True
        assert record.point == INTAKE_POINT
        assert record.latency is not None and record.latency >= 0

    def test_degraded_intake_never_carries_an_ack(self) -> None:
        """No ack from anywhere on a degraded intake (talking-to-one, task t1).

        The packet is None on every degradation path, so there is structurally
        no ``packet.ack`` to inspect — senses.py never synthesizes a fallback
        ack itself; a caller-side fixed dispatch notice is a LATER task's job
        (t6), not this module's.
        """
        for fake in (
            _FakeEngine(raise_on_complete=ConnectionError("refused")),
            _FakeEngine(ModelResponse(content="no JSON here at all", prompt_tokens=1)),
            _FakeEngine(ModelResponse(content="", reasoning="")),
        ):
            packet, record = run_senses_intake("do it", _senses_config(), fake)
            assert packet is None
            assert record.degraded is True

    def test_ack_present_but_interpretation_missing_degrades_exactly_as_today(self) -> None:
        """An ``ack`` alongside a reply with no ``interpretation`` key behaves
        exactly like today's no-``ack`` case: no required-key is enforced on
        ``interpretation`` (unchanged by this task), so the packet still comes
        back clean with an empty interpretation — ``ack`` parsing is additive,
        never a new failure mode."""
        reply = (
            '{"confidence": 0.4, "task_type": "docs", "omissions": [], '
            '"ack": "Got it, handing this to cortex now."}'
        )
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=1, completion_tokens=1))

        packet, record = run_senses_intake("do it", _senses_config(), fake)

        assert packet is not None
        assert record.degraded is False
        assert packet.interpretation == ""  # unchanged from today's default
        assert packet.ack == "Got it, handing this to cortex now."


# ---------------------------------------------------------------------------
# speakback — shapes the raw summary; degrades to the raw summary
# ---------------------------------------------------------------------------


class TestSpeakback:
    def test_tools_off_and_returns_display_string(self) -> None:
        fake = _FakeEngine(
            ModelResponse(
                content="Done! I added a retry with backoff.", prompt_tokens=2, completion_tokens=6
            )
        )
        display, record = run_senses_speakback(
            "wrote uploader.py; added retry", _senses_config(), fake
        )

        assert fake.make_complete_calls == [[]]  # tools-off on the wire
        assert display == "Done! I added a retry with backoff."
        assert record.degraded is False
        assert record.point == SPEAKBACK_POINT
        assert record.tokens == 8  # 2 + 6, exact — never estimated

    def test_unreachable_degrades_to_none(self) -> None:
        fake = _FakeEngine(raise_on_complete=ConnectionError("refused"))
        display, record = run_senses_speakback("raw cortex summary", _senses_config(), fake)

        assert display is None  # caller falls back to the raw summary
        assert record.degraded is True
        assert record.point == SPEAKBACK_POINT

    def test_empty_content_degrades_to_none(self) -> None:
        fake = _FakeEngine(ModelResponse(content="   ", reasoning=""))
        display, record = run_senses_speakback("raw cortex summary", _senses_config(), fake)

        assert display is None
        assert record.degraded is True

    def test_mock_engine_not_implemented_degrades(self) -> None:
        engine = load("mock")
        display, record = run_senses_speakback("raw cortex summary", _senses_config(), engine)

        assert display is None
        assert record.degraded is True


# ---------------------------------------------------------------------------
# (4) runtime-fact records — latency/tokens/degraded, no quality field
# ---------------------------------------------------------------------------


class TestRuntimeFactRecords:
    def test_success_record_carries_exact_tokens_and_latency(self) -> None:
        fake = _FakeEngine(
            ModelResponse(content=_INTAKE_JSON, prompt_tokens=11, completion_tokens=13)
        )
        _, record = run_senses_intake("do it", _senses_config(), fake)

        assert isinstance(record, SensesRecord)
        assert record.tokens == 24  # 11 + 13, exact — never estimated
        assert record.latency is not None and record.latency >= 0
        assert record.degraded is False

    def test_record_shape_has_no_quality_field(self) -> None:
        """A runtime-fact layer, not a quality judge: only {point, latency, tokens,
        degraded} — no field grades the answer."""
        fake = _FakeEngine()
        _, record = run_senses_intake("do it", _senses_config(), fake)

        assert set(record.to_dict().keys()) == {"point", "latency", "tokens", "degraded"}


# ---------------------------------------------------------------------------
# boundary — senses.py opens no socket / forks no daemon / shells out to nothing
# ---------------------------------------------------------------------------


def test_senses_module_has_no_io_surface() -> None:
    """senses.py is pure stdlib + the engine's own OpenAI-wire seam — no direct
    socket/daemon/thread/subprocess primitive of its own (mirrors the named
    deepthink.py boundary pin). The package-wide boundary sweep in
    tests/test_boundary.py already covers this file; this pins it by name."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "colleague" / "senses.py"
    source = src.read_text(encoding="utf-8")
    for forbidden in (
        "import socket",
        "import asyncio",
        "import threading",
        "concurrent.futures",
        "import subprocess",
    ):
        assert forbidden not in source, f"senses.py must not use {forbidden!r}"


# ---------------------------------------------------------------------------
# run_senses_update — proactive progress narration (task t3)
# ---------------------------------------------------------------------------


class TestSensesUpdate:
    """Tests for :func:`run_senses_update` — proactive progress narration."""

    def test_exactly_one_completion_no_tool_schema(self) -> None:
        """A senses update request NEVER carries a tool schema — make_complete gets []."""
        reply = '{"update": "I am currently running the test suite."}'
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=3, completion_tokens=5))

        result = run_senses_update(
            ["ran pytest: 42 tests passed"],
            None,
            _senses_config(),
            fake,
        )

        assert fake.make_complete_calls == [[]]
        assert fake.complete_call_count == 1
        assert result is not None
        assert result["degraded"] is False

    def test_prompt_contains_feed_tail_and_respects_budget(self) -> None:
        """The prompt carries the provided feed-tail lines and windowing respects
        senses' context_budget."""
        reply = '{"update": "Processing feed lines."}'
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=2, completion_tokens=4))
        budget = 2000
        config = _senses_config(context_budget_tokens=budget)

        result = run_senses_update(
            ["step 1: wrote foo.py", "step 2: ran tests"],
            None,
            config,
            fake,
        )

        assert result is not None
        assert result["degraded"] is False
        sent = fake.captured_messages
        assert sent is not None
        user_content = sent[-1]["content"]
        # The feed lines must appear in the prompt.
        assert "step 1: wrote foo.py" in user_content
        assert "step 2: ran tests" in user_content
        # Windowing respects the send budget.
        send_budget = budget - budget // 4
        total_chars = sum(len(m.get("content") or "") for m in sent)
        assert total_chars <= send_budget

    def test_prompt_carries_packet_interpretation_when_present(self) -> None:
        """With a packet, the prompt names what the run is ABOUT (integrator pin):
        the interpretation augments the feed, it never substitutes for it."""
        reply = '{"update": "Still reading the config module."}'
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=2, completion_tokens=4))
        packet = ContextPacket(
            original="tidy the config module",
            interpretation="refactor config loading for clarity",
        )

        result = run_senses_update(
            ["step 3: read config.py"],
            packet,
            _senses_config(),
            fake,
        )

        assert result is not None
        user_content = fake.captured_messages[-1]["content"]
        assert "refactor config loading for clarity" in user_content
        assert "step 3: read config.py" in user_content

    def test_stub_reply_returned_verbatim_as_update(self) -> None:
        """A stub reply is returned verbatim as 'update' (modulo strip)."""
        exact = "I just finished linting three files and all checks passed."
        reply = f'{{"update": "{exact}"}}'
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=2, completion_tokens=6))

        result = run_senses_update(
            ["linted file_a.py, file_b.py, file_c.py"],
            None,
            _senses_config(),
            fake,
        )

        assert result is not None
        assert result["update"] == exact
        assert result["degraded"] is False

    def test_error_stub_degrades_without_raising(self) -> None:
        """Error/empty-content stub degrades to {'update': None, 'degraded': True}."""
        fake = _FakeEngine(raise_on_complete=ConnectionError("connection refused"))

        result = run_senses_update(
            ["some feed line"],
            None,
            _senses_config(),
            fake,
        )

        assert result is not None
        assert result["update"] is None
        assert result["degraded"] is True
        assert result["tokens"] is None
        assert result["latency"] is not None and result["latency"] >= 0

    def test_empty_content_degrades(self) -> None:
        """Empty content from the model degrades gracefully."""
        fake = _FakeEngine(ModelResponse(content="", reasoning=""))

        result = run_senses_update(
            ["some feed line"],
            None,
            _senses_config(),
            fake,
        )

        assert result is not None
        assert result["update"] is None
        assert result["degraded"] is True

    def test_empty_feed_tail_still_completes(self) -> None:
        """Empty feed_tail still completes with the prompt instructing nothing-new honesty."""
        reply = '{"update": "There is nothing new in the feed."}'
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=2, completion_tokens=4))

        result = run_senses_update(
            [],
            None,
            _senses_config(),
            fake,
        )

        assert result is not None
        assert result["degraded"] is False
        assert result["update"] == "There is nothing new in the feed."
        sent = fake.captured_messages
        assert sent is not None
        user_content = sent[-1]["content"]
        assert "(no feed yet)" in user_content

    def test_none_senses_config_returns_none(self) -> None:
        """When senses_config is None, run_senses_update returns None cleanly."""
        result = run_senses_update(
            ["some line"],
            None,
            None,
            _FakeEngine(),
        )

        assert result is None

    def test_none_engine_returns_none(self) -> None:
        """When engine is None, run_senses_update returns None cleanly."""
        result = run_senses_update(
            ["some line"],
            None,
            _senses_config(),
            None,
        )

        assert result is None


# ---------------------------------------------------------------------------
# conversation continuity — rolling history threaded into every senses call
# (talking-to-one arc, task t4)
# ---------------------------------------------------------------------------


class TestSensesHistory:
    """All four invocation functions (:func:`run_senses_intake`,
    :func:`run_senses_speakback`, :func:`run_senses_talk`,
    :func:`run_senses_update`) accept an optional keyword-only ``history`` —
    a rolling record of prior operator/senses exchanges — folded into the
    user prompt BEFORE the function's own existing payload, windowed
    (oldest-entries-dropped-first) to the senses model's own budget. Absent
    or empty history produces a byte-identical prompt to before this
    parameter existed."""

    _HISTORY = [
        {"role": "operator", "text": "please fix the flaky test"},
        {"role": "senses", "text": "Got it, handing this to cortex."},
        {"role": "operator", "text": "also check the timeout"},
    ]

    # -- (a) history lines appear oldest-first, labeled, for all four fns --

    def test_intake_prompt_carries_history_oldest_first_before_payload(self) -> None:
        fake = _FakeEngine()

        run_senses_intake(
            "add a retry to the uploader", _senses_config(), fake, history=self._HISTORY
        )

        user_content = fake.captured_messages[-1]["content"]
        assert "operator: please fix the flaky test" in user_content
        assert "senses: Got it, handing this to cortex." in user_content
        assert "operator: also check the timeout" in user_content
        # oldest first ...
        assert user_content.index("please fix the flaky test") < user_content.index(
            "also check the timeout"
        )
        # ... and history precedes the function's own payload (the request text).
        assert user_content.index("also check the timeout") < user_content.index(
            "add a retry to the uploader"
        )

    def test_speakback_prompt_carries_history_oldest_first_before_payload(self) -> None:
        fake = _FakeEngine(
            ModelResponse(content="Done! Added a retry.", prompt_tokens=1, completion_tokens=1)
        )

        run_senses_speakback(
            "wrote uploader.py; added retry", _senses_config(), fake, history=self._HISTORY
        )

        user_content = fake.captured_messages[-1]["content"]
        assert "operator: please fix the flaky test" in user_content
        assert "operator: also check the timeout" in user_content
        assert user_content.index("please fix the flaky test") < user_content.index(
            "also check the timeout"
        )
        assert user_content.index("also check the timeout") < user_content.index(
            "wrote uploader.py"
        )

    def test_talk_prompt_carries_history_oldest_first_before_payload(self) -> None:
        reply = '{"answer": "ok", "relay": false, "relay_text": ""}'
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=1, completion_tokens=1))
        config = _senses_config()

        record = run_senses_talk(
            "how's it going?",
            feed_tail="[edit_file] uploader.py",
            packet=None,
            task_state=None,
            senses_config=config,
            make_complete=fake.make_complete,
            make_count_tokens=fake.make_count_tokens(config),
            history=self._HISTORY,
        )

        assert record is not None
        assert record["degraded"] is False
        user_content = fake.captured_messages[-1]["content"]
        assert "operator: please fix the flaky test" in user_content
        assert "operator: also check the timeout" in user_content
        assert user_content.index("please fix the flaky test") < user_content.index(
            "also check the timeout"
        )
        assert user_content.index("also check the timeout") < user_content.index("how's it going?")

    def test_update_prompt_carries_history_oldest_first_before_payload(self) -> None:
        reply = '{"update": "still working on it."}'
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=1, completion_tokens=1))

        run_senses_update(
            ["step 1: wrote foo.py"],
            None,
            _senses_config(),
            fake,
            history=self._HISTORY,
        )

        user_content = fake.captured_messages[-1]["content"]
        assert "operator: please fix the flaky test" in user_content
        assert "operator: also check the timeout" in user_content
        assert user_content.index("please fix the flaky test") < user_content.index(
            "also check the timeout"
        )
        assert user_content.index("also check the timeout") < user_content.index(
            "step 1: wrote foo.py"
        )

    # -- (b) oldest-first dropping under a tight budget ---------------------

    def test_intake_drops_oldest_history_first_under_tight_budget(self) -> None:
        """Newest entry survives; oldest dropped; the primary payload (the
        operator's request) always survives — mirrors the send-budget
        arithmetic ``_window_text`` already uses elsewhere in this module."""
        history = [
            {"role": "operator", "text": "OLDEST-MARKER-" + "a" * 200},
            {"role": "senses", "text": "MIDDLE-MARKER-" + "b" * 200},
            {"role": "operator", "text": "NEWEST-MARKER-" + "c" * 200},
        ]
        fake = _FakeEngine()
        # Room for the system prompt + "do it" comfortably, but not enough
        # left over for all three history entries.
        budget = 1800
        config = _senses_config(context_budget_tokens=budget)

        packet, record = run_senses_intake("do it", config, fake, history=history)

        assert record.degraded is False
        sent = fake.captured_messages
        user_content = sent[-1]["content"]
        assert "do it" in user_content  # the primary payload always survives
        assert "NEWEST-MARKER" in user_content  # newest entry survives
        assert "OLDEST-MARKER" not in user_content  # oldest entry dropped first
        send_budget = budget - budget // 4
        total_chars = sum(len(m.get("content") or "") for m in sent)
        assert total_chars <= send_budget

    def test_update_drops_oldest_history_first_under_tight_budget(self) -> None:
        """Same oldest-first drop contract on run_senses_update's feed-shaped
        primary payload (a list of lines, not a single text blob)."""
        history = [
            {"role": "operator", "text": "OLDEST-MARKER-" + "a" * 200},
            {"role": "senses", "text": "MIDDLE-MARKER-" + "b" * 200},
            {"role": "operator", "text": "NEWEST-MARKER-" + "c" * 200},
        ]
        reply = '{"update": "still going."}'
        fake = _FakeEngine(ModelResponse(content=reply, prompt_tokens=1, completion_tokens=1))
        budget = 1500
        config = _senses_config(context_budget_tokens=budget)

        result = run_senses_update(["step 1: wrote foo.py"], None, config, fake, history=history)

        assert result is not None
        assert result["degraded"] is False
        sent = fake.captured_messages
        user_content = sent[-1]["content"]
        assert "step 1: wrote foo.py" in user_content  # primary payload survives
        assert "NEWEST-MARKER" in user_content  # newest entry survives
        assert "OLDEST-MARKER" not in user_content  # oldest entry dropped first
        send_budget = budget - budget // 4
        total_chars = sum(len(m.get("content") or "") for m in sent)
        assert total_chars <= send_budget

    # -- (c) history=None/[] byte-identical pin, for all four functions -----

    def test_intake_history_none_or_empty_is_byte_identical(self) -> None:
        baseline = _FakeEngine()
        run_senses_intake("add a retry to the uploader", _senses_config(), baseline)

        without_kwarg = baseline.captured_messages

        for history in (None, []):
            fake = _FakeEngine()
            run_senses_intake(
                "add a retry to the uploader", _senses_config(), fake, history=history
            )
            assert fake.captured_messages == without_kwarg

    def test_speakback_history_none_or_empty_is_byte_identical(self) -> None:
        def _response():
            return ModelResponse(content="Done!", prompt_tokens=1, completion_tokens=1)

        baseline = _FakeEngine(_response())
        run_senses_speakback("wrote uploader.py; added retry", _senses_config(), baseline)
        without_kwarg = baseline.captured_messages

        for history in (None, []):
            fake = _FakeEngine(_response())
            run_senses_speakback(
                "wrote uploader.py; added retry", _senses_config(), fake, history=history
            )
            assert fake.captured_messages == without_kwarg

    def test_talk_history_none_or_empty_is_byte_identical(self) -> None:
        reply = '{"answer": "ok", "relay": false, "relay_text": ""}'
        config = _senses_config()

        def _response():
            return ModelResponse(content=reply, prompt_tokens=1, completion_tokens=1)

        baseline = _FakeEngine(_response())
        run_senses_talk(
            "how's it going?",
            feed_tail="[edit_file] uploader.py",
            packet=None,
            task_state=None,
            senses_config=config,
            make_complete=baseline.make_complete,
            make_count_tokens=baseline.make_count_tokens(config),
        )
        without_kwarg = baseline.captured_messages

        for history in (None, []):
            fake = _FakeEngine(_response())
            run_senses_talk(
                "how's it going?",
                feed_tail="[edit_file] uploader.py",
                packet=None,
                task_state=None,
                senses_config=config,
                make_complete=fake.make_complete,
                make_count_tokens=fake.make_count_tokens(config),
                history=history,
            )
            assert fake.captured_messages == without_kwarg

    def test_update_history_none_or_empty_is_byte_identical(self) -> None:
        def _response():
            return ModelResponse(content='{"update": "ok"}', prompt_tokens=1, completion_tokens=1)

        baseline = _FakeEngine(_response())
        run_senses_update(["step 1: wrote foo.py"], None, _senses_config(), baseline)
        without_kwarg = baseline.captured_messages

        for history in (None, []):
            fake = _FakeEngine(_response())
            run_senses_update(
                ["step 1: wrote foo.py"], None, _senses_config(), fake, history=history
            )
            assert fake.captured_messages == without_kwarg

    # -- (d) a malformed history entry is skipped defensively, never raises -

    def test_malformed_history_entries_are_skipped_defensively(self) -> None:
        malformed_history = [
            {"role": "operator", "text": "valid oldest entry"},
            {"role": "narrator", "text": "unknown role, must be skipped"},
            {"role": "operator"},  # missing "text"
            {"role": "senses", "text": ""},  # blank text
            {"role": "senses", "text": "   "},  # whitespace-only text
            "not-even-a-dict",
            {"role": "senses", "text": 42},  # non-string text
            {"role": "senses", "text": "valid newest entry"},
        ]
        fake = _FakeEngine()

        # Must not raise despite the garbage entries mixed in.
        packet, record = run_senses_intake(
            "do it", _senses_config(), fake, history=malformed_history
        )

        assert record.degraded is False
        user_content = fake.captured_messages[-1]["content"]
        assert "operator: valid oldest entry" in user_content
        assert "senses: valid newest entry" in user_content
        assert "unknown role, must be skipped" not in user_content
        assert "narrator:" not in user_content
