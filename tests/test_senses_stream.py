"""Tests for the fence-tolerant incremental JSON-envelope extractor.

Surfaces under test (:mod:`colleague.senses_stream`):

1. ``EnvelopeStream`` — a state machine over streamed text chunks that
   extracts the ``"text"`` field value from a JSON move envelope, emitting
   display-able deltas as chunks arrive.
2. ``EnvelopeError`` — raised on malformed / unfenced-non-JSON /
   non-envelope input; exposes ``.accumulated`` for fallback rendering.

The extractor handles:
- An optional markdown code fence (`````json ... ``````) around the envelope.
- JSON keys arriving split across chunk boundaries.
- JSON string escapes (``\\\"`` ``\\\\`` ``\\n`` ``\\uXXXX``) inside the
  text value.
- Keys before ``"text"`` skipped.
- The closing quote, closing brace, and closing fence WITHHELD from display.
"""

from __future__ import annotations

import pytest

from colleague.senses_stream import EnvelopeError, EnvelopeStream

# ---------------------------------------------------------------------------
# Live-probed chunk sequence (2026-08-06) — fence-wrapped envelope
# ---------------------------------------------------------------------------

#: The exact chunk sequence from the live probe, in order.
_LIVE_CHUNKS = [
    "",
    "```",
    "json\n",
    '{"move',
    '": "',
    "direct_",
    'answer",',
    ' "text',
    '": "',
    "A rainbow",
    " is a meteorological phenomenon caused by",
    " the reflection of light.",
    '"}',
    "\n```",
]

#: The expected concatenated display output — the rainbow sentence only.
_EXPECTED_RAINBOW = "A rainbow is a meteorological phenomenon caused by the reflection of light."


class TestLiveProbeChunks:
    """Given the live-probed chunk sequence the extractor emits exactly the
    text-field characters and withholds the closing quote/brace/fence."""

    def test_fenced_envelope_emits_text_field(self) -> None:
        stream = EnvelopeStream()
        deltas: list[str] = []
        for chunk in _LIVE_CHUNKS:
            delta = stream.feed(chunk)
            deltas.append(delta)
        remainder = stream.finish()
        deltas.append(remainder)

        output = "".join(deltas)
        assert output == _EXPECTED_RAINBOW

    def test_fenced_envelope_withholds_closing_quote_brace_fence(self) -> None:
        """The closing quote, closing brace, and closing fence are NOT in output."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        for chunk in _LIVE_CHUNKS:
            deltas.append(stream.feed(chunk))
        deltas.append(stream.finish())

        output = "".join(deltas)
        # No fence markers, no JSON braces, no surrounding quotes.
        assert "```" not in output
        assert "{" not in output
        assert "}" not in output
        assert '"' not in output

    def test_fenced_envelope_delta_sequence(self) -> None:
        """Verify the per-chunk delta sequence: early chunks yield '', text
        chunks yield their content, fence/brace chunks yield ''."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        for chunk in _LIVE_CHUNKS:
            deltas.append(stream.feed(chunk))
        deltas.append(stream.finish())

        # First three chunks (empty, fence open, lang+newline) produce no text.
        assert deltas[0] == ""  # empty chunk
        assert deltas[1] == ""  # "```"
        assert deltas[2] == ""  # "json\n"

        # Chunks 3-7 are before the "text" key — no display output.
        assert deltas[3] == ""  # '{"move'
        assert deltas[4] == ""  # '": "'
        assert deltas[5] == ""  # "direct_"
        assert deltas[6] == ""  # 'answer",'
        assert deltas[7] == ""  # ' "text'

        # Chunk 8 is '": "' — still no text (key-value separator).
        assert deltas[8] == ""  # '": "'

        # Chunks 9-12 carry the actual text value.
        assert deltas[9] == "A rainbow"
        assert deltas[10] == " is a meteorological phenomenon caused by"
        assert deltas[11] == " the reflection of light."

        # Chunk 12 is '"}' — closing quote and brace withheld.
        assert deltas[12] == ""

        # Chunk 13 is "\n```" — closing fence withheld.
        assert deltas[13] == ""

        # finish() returns any remainder (none in this case).
        assert deltas[14] == ""


# ---------------------------------------------------------------------------
# Unfenced JSON envelope — same envelope without the code fence
# ---------------------------------------------------------------------------


class TestUnfencedEnvelope:
    """A plain unfenced JSON envelope also extracts correctly."""

    def test_unfenced_envelope_emits_text_field(self) -> None:
        """Same envelope without the fence wrapper."""
        chunks = [
            '{"move": "direct_answer", "text": "A rainbow is a meteorological',
            " phenomenon caused by the reflection of light." '"}',
        ]
        stream = EnvelopeStream()
        deltas: list[str] = []
        for chunk in chunks:
            deltas.append(stream.feed(chunk))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == _EXPECTED_RAINBOW

    def test_unfenced_envelope_withholds_braces_and_quotes(self) -> None:
        stream = EnvelopeStream()
        deltas: list[str] = []
        for chunk in [
            '{"text": "hello world"}',
        ]:
            deltas.append(stream.feed(chunk))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "hello world"
        assert "{" not in output
        assert "}" not in output
        assert '"' not in output


# ---------------------------------------------------------------------------
# JSON string escapes inside the text value
# ---------------------------------------------------------------------------


class TestJsonEscapes:
    """A text value containing \\\" and \\n escapes is decoded correctly."""

    def test_escaped_quote_decoded(self) -> None:
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "say \\"hello\\" now"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == 'say "hello" now'

    def test_escaped_newline_decoded(self) -> None:
        """\\n inside the text value is decoded to a literal newline."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "line1\\nline2"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "line1\nline2"

    def test_escaped_backslash_decoded(self) -> None:
        """\\\\ inside the text value is decoded to a single backslash."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "path\\\\to\\\\file"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "path\\to\\file"

    def test_unicode_escape_decoded(self) -> None:
        """\\uXXXX inside the text value is decoded to the Unicode character."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "\\u00e9l\\u00e8ve"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "élève"

    def test_mixed_escapes(self) -> None:
        """A mix of \\\" \\n \\\\ \\uXXXX all decoded correctly."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "quote \\" nl \\n bs \\\\ snow \\u2603"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == 'quote " nl \n bs \\ snow ☃'


# ---------------------------------------------------------------------------
# Keys before "text" are skipped
# ---------------------------------------------------------------------------


class TestSkipKeysBeforeText:
    """Keys before ``"text"`` in the envelope are skipped."""

    def test_move_key_before_text_skipped(self) -> None:
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"move": "direct_answer", "text": "result"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "result"

    def test_multiple_keys_before_text_skipped(self) -> None:
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"a": "x", "b": "y", "move": "z", "text": "value"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "value"

    def test_text_key_first(self) -> None:
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "first", "other": "ignored"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "first"


# ---------------------------------------------------------------------------
# EnvelopeError — malformed / unfenced-non-JSON / non-envelope input
# ---------------------------------------------------------------------------


class TestEnvelopeError:
    """Malformed / unfenced / non-JSON input raises a typed extraction error
    without losing accumulated text."""

    def test_plain_prose_raises_with_accumulated(self) -> None:
        """Plain prose with no JSON raises EnvelopeError with .accumulated."""
        stream = EnvelopeStream()
        stream.feed("This is just plain prose with no JSON at all.")

        with pytest.raises(EnvelopeError) as exc_info:
            stream.finish()

        assert exc_info.value.accumulated == "This is just plain prose with no JSON at all."

    def test_plain_prose_accumulated_preserves_every_character(self) -> None:
        """Every character fed is preserved in .accumulated."""
        stream = EnvelopeStream()
        stream.feed("Hello")
        stream.feed(" ")
        stream.feed("World\n")
        stream.feed("!")

        with pytest.raises(EnvelopeError) as exc_info:
            stream.finish()

        assert exc_info.value.accumulated == "Hello World\n!"

    def test_malformed_json_raises(self) -> None:
        """Malformed JSON (unclosed brace) raises EnvelopeError."""
        stream = EnvelopeStream()
        stream.feed('{"text": "hello')

        with pytest.raises(EnvelopeError) as exc_info:
            stream.finish()

        assert exc_info.value.accumulated == '{"text": "hello'

    def test_empty_input_raises(self) -> None:
        """An empty stream raises EnvelopeError on finish."""
        stream = EnvelopeStream()

        with pytest.raises(EnvelopeError) as exc_info:
            stream.finish()

        assert exc_info.value.accumulated == ""

    def test_fence_opened_never_closed_tolerated_when_envelope_complete(self) -> None:
        """A COMPLETE envelope whose closing fence never arrives extracts fine.

        A model routinely stops right after ``}`` (max-tokens, EOS) without
        emitting the closing fence; erroring here would force the caller to
        re-render text it already streamed. Only an incomplete ENVELOPE is an
        error — a missing close fence after a closed envelope is not.
        """
        stream = EnvelopeStream()
        deltas = [stream.feed("```json\n"), stream.feed('{"text": "hello"}')]
        deltas.append(stream.finish())
        assert "".join(deltas) == "hello"

    def test_fence_opened_envelope_incomplete_raises(self) -> None:
        """A fence opened with an INCOMPLETE envelope still raises."""
        stream = EnvelopeStream()
        stream.feed("```json\n")
        stream.feed('{"text": "hel')

        with pytest.raises(EnvelopeError) as exc_info:
            stream.finish()

        assert exc_info.value.accumulated == '```json\n{"text": "hel'

    def test_envelope_error_is_exception(self) -> None:
        """EnvelopeError is a proper Exception subclass."""
        assert issubclass(EnvelopeError, Exception)

    def test_envelope_error_accumulated_attribute(self) -> None:
        """EnvelopeError exposes .accumulated as a string."""
        err = EnvelopeError("test", accumulated="data")
        assert err.accumulated == "data"


# ---------------------------------------------------------------------------
# finish() returns withheld remainder
# ---------------------------------------------------------------------------


class TestFinishRemainder:
    """finish() returns any withheld remainder that proved to be text."""

    def test_finish_returns_empty_for_complete_envelope(self) -> None:
        """A complete envelope has no remainder."""
        stream = EnvelopeStream()
        stream.feed('{"text": "done"}')
        remainder = stream.finish()
        assert remainder == ""

    def test_finish_returns_empty_for_fenced_complete(self) -> None:
        stream = EnvelopeStream()
        stream.feed("```json\n")
        stream.feed('{"text": "done"}')
        stream.feed("\n```")
        remainder = stream.finish()
        assert remainder == ""


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_text_value(self) -> None:
        """An empty text value produces no output."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": ""}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == ""

    def test_text_value_with_whitespace(self) -> None:
        """Whitespace in the text value is preserved."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "  hello  world  "}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "  hello  world  "

    def test_chunk_boundary_mid_key(self) -> None:
        """A chunk boundary splitting a key name is handled."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"te'))
        deltas.append(stream.feed('xt": "value"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "value"

    def test_chunk_boundary_mid_value(self) -> None:
        """A chunk boundary splitting the text value is handled."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "hel'))
        deltas.append(stream.feed('lo"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "hello"

    def test_chunk_boundary_mid_escape(self) -> None:
        """A chunk boundary splitting an escape sequence is handled."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed('{"text": "a\\"'))
        deltas.append(stream.feed('b"}'))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == 'a"b'

    def test_no_text_key_raises(self) -> None:
        """An envelope with no "text" key raises EnvelopeError."""
        stream = EnvelopeStream()
        stream.feed('{"move": "direct_answer"}')

        with pytest.raises(EnvelopeError) as exc_info:
            stream.finish()

        assert exc_info.value.accumulated == '{"move": "direct_answer"}'

    def test_fenced_with_whitespace_before_fence(self) -> None:
        """Whitespace before the opening fence is tolerated."""
        stream = EnvelopeStream()
        deltas: list[str] = []
        deltas.append(stream.feed("  \n```json\n"))
        deltas.append(stream.feed('{"text": "ok"}'))
        deltas.append(stream.feed("\n```"))
        deltas.append(stream.finish())

        output = "".join(deltas)
        assert output == "ok"
