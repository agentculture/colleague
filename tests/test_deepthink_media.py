"""Tests for the deepthink digest's media-flattening seam (plan task t7).

Wave 1 landed ``colleague/media.py`` (``flatten_parts(content) -> str``): a
parts-list ``content`` value becomes plain text with ``[image attachment]`` /
``[audio attachment]`` placeholders, and a plain string passes through
unchanged. A later task makes the loop's message history carry content-parts
LISTS in some user messages (media attachments). The deepthink escalation
(``colleague/deepthink.py``) sends a digest of history-shaped messages to a
SECOND model that may be TEXT-ONLY today (the served 27B) — a list-typed
``content`` field must structurally never reach that wire.

``window_messages`` is the ONE point every deepthink message-list digest
funnels through — directly (plan-mode's proposal routing) or via
``_window_question`` from ``run_deepthink`` — so that is where
``colleague.deepthink._flatten_history`` now runs first. These tests pin:

1. A history-shaped message list carrying parts-list content is flattened to
   string-only content before it ever reaches the completion seam
   (``Engine.make_complete``'s product) — captured with a fake engine exactly
   like ``tests/test_deepthink.py``'s ``_FakeEngine`` does — with the media
   placeholders present in the flattened text.
2. A string-only history is byte-identical to today: ``flatten_parts`` is the
   identity for a ``str``, and ``window_messages`` returns the very same list
   object (no copy) when nothing needs flattening.
3. A media-bearing dual-model run still escalates successfully through
   ``run_deepthink`` against a fake completion seam — no crash, and the
   returned ``DeepthinkCall`` records ``degraded=False``.
"""

from __future__ import annotations

from colleague import media
from colleague.config import DeepthinkConfig, EngineConfig
from colleague.deepthink import _flatten_history, _needs_flattening, run_deepthink, window_messages
from colleague.loop import ModelResponse


def _dual_config(**dt_overrides) -> EngineConfig:
    dt_defaults = dict(
        model="deepthink-model",
        base_url="http://localhost:8002/v1",
        api_key="dt-key",
        context_budget=100000,
    )
    dt_defaults.update(dt_overrides)
    return EngineConfig(deepthink=DeepthinkConfig(**dt_defaults))


class _FakeEngine:
    """Records make_complete()/complete() calls; no network, fully scripted.

    Mirrors ``tests/test_deepthink.py``'s ``_FakeEngine`` — the same shape
    ``run_deepthink`` drives via ``engine.make_complete(dt_config,
    tools=[])(messages)``.
    """

    name = "fake"

    def __init__(self, response: ModelResponse | None = None) -> None:
        self.make_complete_calls: list[list[dict] | None] = []
        self.captured_messages: list[dict] | None = None
        self._response = response or ModelResponse(
            content="the answer", prompt_tokens=5, completion_tokens=7
        )

    def make_count_tokens(self, config: EngineConfig):
        def counter(messages: list[dict]) -> int:
            return sum(len(str(m.get("content") or "")) for m in messages)

        return counter

    def make_complete(self, config: EngineConfig, tools=None):
        self.make_complete_calls.append(tools)

        def complete(messages: list[dict]) -> ModelResponse:
            self.captured_messages = messages
            return self._response

        return complete


def _counter(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


# ---------------------------------------------------------------------------
# 1. A parts-list user message flattens to string-only content on the wire
# ---------------------------------------------------------------------------


class TestHistoryWithMediaPartsFlattensToStringOnly:
    def _media_history(self) -> list[dict]:
        return [
            {"role": "system", "content": "You are grading a work item."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Here is the diagram: "},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAAA"},
                    },
                    {"type": "text", "text": " and the recording: "},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": "BBBB", "format": "wav"},
                    },
                ],
            },
        ]

    def test_window_messages_flattens_parts_list_to_string(self) -> None:
        history = self._media_history()

        out = window_messages(history, budget=100000, count_tokens=_counter)

        # No list-typed content survives anywhere in the outgoing messages.
        for m in out:
            assert isinstance(m["content"], str), f"non-string content leaked: {m!r}"

        digest_text = out[1]["content"]
        assert "Here is the diagram:" in digest_text
        assert "[image attachment]" in digest_text
        assert "and the recording:" in digest_text
        assert "[audio attachment]" in digest_text

        # The original history is never mutated.
        assert isinstance(history[1]["content"], list)

    def test_flattened_digest_reaches_the_completion_seam_as_strings_only(self) -> None:
        """Capture what the ``Engine.make_complete`` product actually receives.

        This is the exact call shape ``run_deepthink`` drives
        (``engine.make_complete(dt_config, tools=[])(messages)``) and the
        shape plan-mode's proposal routing drives directly with
        ``window_messages``' output — proving a list-typed content field
        never reaches the wire, regardless of which enumerated caller
        composed the digest.
        """
        history = self._media_history()
        fake = _FakeEngine()
        dt_config = _dual_config()

        windowed = window_messages(
            history, budget=dt_config.deepthink.context_budget, count_tokens=_counter
        )
        complete = fake.make_complete(dt_config, tools=[])
        complete(windowed)

        sent = fake.captured_messages
        assert sent is not None
        assert fake.make_complete_calls == [[]]  # tools-off invariant untouched
        for m in sent:
            assert isinstance(m["content"], str)
            assert not isinstance(m["content"], list)
        assert "[image attachment]" in sent[1]["content"]
        assert "[audio attachment]" in sent[1]["content"]

    def test_needs_flattening_detects_parts_list_content(self) -> None:
        assert _needs_flattening(self._media_history()) is True

    def test_flatten_history_matches_media_flatten_parts_per_message(self) -> None:
        history = self._media_history()
        out = _flatten_history(history)
        assert out[0]["content"] == media.flatten_parts(history[0]["content"])
        assert out[1]["content"] == media.flatten_parts(history[1]["content"])


# ---------------------------------------------------------------------------
# 2. String-only histories stay byte-identical
# ---------------------------------------------------------------------------


class TestStringOnlyHistoryIsByteIdentical:
    def _string_history(self) -> list[dict]:
        return [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "plain question"},
        ]

    def test_flatten_parts_is_the_identity_for_the_strings_used(self) -> None:
        for content in ("sys prompt", "plain question"):
            assert media.flatten_parts(content) is content

    def test_needs_flattening_is_false_for_an_all_string_history(self) -> None:
        assert _needs_flattening(self._string_history()) is False

    def test_flatten_history_returns_the_same_object_for_string_only_history(self) -> None:
        history = self._string_history()
        assert _flatten_history(history) is history

    def test_window_messages_digest_equals_the_manually_composed_expectation(self) -> None:
        history = self._string_history()
        expected = [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "plain question"},
        ]

        out = window_messages(history, budget=100000, count_tokens=_counter)

        assert out == expected
        # No flattening needed -> window_messages' existing byte-identical
        # pass-through guarantee holds all the way down to object identity.
        assert out is history

    def test_run_deepthink_question_composition_untouched_by_string_history(self) -> None:
        """A plain-string ``question``/``system_prompt`` question composition
        (``run_deepthink``'s own path, via ``_window_question``) is
        unaffected — flattening a string is the identity, so the sent
        messages equal today's pre-t7 shape exactly."""
        fake = _FakeEngine()
        config = _dual_config()

        run_deepthink(
            "a plain text question",
            config=config,
            point="tool",
            engine_name="fake",
            engine_loader=lambda name: fake,
            system_prompt="a plain system prompt",
        )

        sent = fake.captured_messages
        assert sent == [
            {"role": "system", "content": "a plain system prompt"},
            {"role": "user", "content": "a plain text question"},
        ]


# ---------------------------------------------------------------------------
# 3. A media-bearing dual-model run still escalates successfully
# ---------------------------------------------------------------------------


class TestMediaBearingRunStillEscalates:
    def test_run_deepthink_with_a_flattened_media_digest_does_not_crash(self) -> None:
        """``run_deepthink``'s public seam takes a ``question: str`` — the one
        enumerated escalation points compose today (the model-authored
        ``deepthink`` tool context, the acceptance self-check digest,
        plan-mode's claim text). A future caller that threads real message
        history through this seam is expected to flatten it first (as
        ``window_messages``/``_flatten_history`` now guarantee for any
        message-list digest) — this pins that the resulting flattened text
        escalates through ``run_deepthink`` with no crash and a clean,
        non-degraded record, exactly like any other digest text.
        """
        history_message_content = [
            {"type": "text", "text": "what does this diagram mean? "},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            {"type": "input_audio", "input_audio": {"data": "BBBB", "format": "wav"}},
        ]
        digest = media.flatten_parts(history_message_content)
        assert "[image attachment]" in digest
        assert "[audio attachment]" in digest

        fake = _FakeEngine()
        config = _dual_config()

        result = run_deepthink(
            digest,
            config=config,
            point="tool",
            engine_name="fake",
            engine_loader=lambda name: fake,
        )

        assert result.call.degraded is False
        assert result.text == "the answer"
        sent = fake.captured_messages
        assert sent is not None
        assert all(isinstance(m["content"], str) for m in sent)

    def test_window_messages_then_completion_on_a_media_history_yields_no_crash(self) -> None:
        """The plan-mode-shaped integration path: compose a history with a
        media-bearing turn, window it for the deepthink budget, and drive it
        straight through a fake ``Engine.make_complete`` product — the exact
        shape a dual-model run takes end to end."""
        history = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "an answer"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look at this: "},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,CCCC"},
                    },
                ],
            },
        ]
        fake = _FakeEngine()
        dt_config = _dual_config()

        windowed = window_messages(
            history, budget=dt_config.deepthink.context_budget, count_tokens=_counter
        )
        complete = fake.make_complete(dt_config, tools=[])
        response = complete(windowed)

        assert response.content == "the answer"
        assert fake.captured_messages is not None
        assert all(isinstance(m["content"], str) for m in fake.captured_messages)
