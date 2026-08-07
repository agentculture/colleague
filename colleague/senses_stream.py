"""Fence-tolerant incremental JSON-envelope extractor (plan task t1).

Senses replies ride a prompted-JSON move envelope — live-probed 2026-08-06 as
a ```` ```json ```` fence around ``{"move": …, "text": …}`` with chunk
boundaries splitting mid-key. :class:`EnvelopeStream` is a small character
state machine that extracts the ``"text"`` field's value incrementally as
chunks arrive, so the session can render a senses reply while it generates.

Contract (the t1 acceptance criteria):

* the display stream carries exactly the decoded text-field characters —
  fence markers, braces, keys, and the closing quote/brace/fence are
  withheld;
* malformed / unfenced-non-JSON / non-envelope input raises
  :class:`EnvelopeError` carrying ``.accumulated`` (every raw character fed)
  so the caller can fall back to a whole-reply render;
* a plain unfenced envelope extracts identically.

Leniencies, chosen for the live wire (not speculation):

* keys other than ``"text"`` are skipped with full JSON awareness (strings,
  numbers, ``true``/``false``/``null``, nested objects/arrays — senses moves
  carry ``confidence`` floats and ``omissions`` lists);
* a COMPLETE envelope whose closing fence never arrives is fine — models
  stop at ``}`` on max-tokens/EOS routinely, and erroring would force the
  caller to re-render text it already streamed.

:meth:`EnvelopeStream.feed` never raises — a hopeless stream flips the
:attr:`EnvelopeStream.failed` flag (so a live caller can bail to raw
rendering immediately) and :meth:`EnvelopeStream.finish` raises the typed
error. Stdlib only; no third-party imports.
"""

from __future__ import annotations

__all__ = ["EnvelopeError", "EnvelopeStream"]

#: Parser states, in stream order. Module-private ints (not enum: stdlib enum
#: is fine but ints keep the hot per-character loop cheap).
_PRE = 0  #: leading whitespace; deciding fence vs bare JSON
_FENCE_OPEN = 1  #: inside the opening ``` marker / language tag, to EOL
_JSON_START = 2  #: expecting the envelope's opening ``{``
_SCAN = 3  #: inside the object, outside any string
_KEY = 4  #: inside a key string (depth 1 keys are captured)
_POST_KEY = 5  #: after a key string, expecting ``:``
_VALUE_START = 6  #: after ``:``, expecting the value's first character
_STRING = 7  #: inside a non-target string value
_TEXT = 8  #: inside the target ``"text"`` string value — emitting
_SCALAR = 9  #: inside a number / true / false / null
_DONE = 10  #: top-level object closed; only ws / closing fence may follow
_POST_FENCE = 11  #: closing fence seen; only whitespace may follow
_FAILED = 12  #: unrecoverable; accumulate raw and wait for finish()

#: JSON single-character escapes (``\u`` handled separately).
_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

_WS = " \t\r\n"


class EnvelopeError(Exception):
    """The stream was not a well-formed move envelope.

    ``accumulated`` preserves every raw character fed, so the caller can
    degrade to a whole-reply render without losing anything.
    """

    def __init__(self, message: str, accumulated: str = "") -> None:
        super().__init__(message)
        self.accumulated = accumulated


class EnvelopeStream:
    """Incremental ``"text"``-field extractor over streamed envelope chunks.

    ``feed(chunk)`` returns the decoded display delta for *chunk* (often
    ``""``); ``finish()`` validates completeness and returns any withheld
    remainder that proved to be text (``""`` under the strict rules).
    """

    def __init__(self, field: str = "text") -> None:
        #: The envelope key whose string value is the display text. Senses
        #: surfaces are key-inconsistent (d4/#374): coordination moves carry
        #: ``"text"``, the talk lane carries ``"answer"`` — the consumer names
        #: its surface's key; the default stays the probed coordination shape.
        self._field = field
        self._raw: list[str] = []  #: every character fed, for .accumulated
        self._state = _PRE
        self._reason = ""  #: first failure reason, for the finish() error
        self._depth = 0  #: object/array nesting depth (1 = envelope body)
        self._key: list[str] = []  #: current depth-1 key being read
        self._in_key_escape = False
        self._container: list[str] = []  #: nested container stack in skips
        self._escape: list[str] = []  #: pending escape chars in _TEXT/_STRING
        self._backtick_run = 0  #: consecutive backticks toward a fence marker
        self._saw_text_key = False
        self._text_done = False

    # -- public surface ----------------------------------------------------

    @property
    def failed(self) -> bool:
        """Whether the stream is already known hopeless (finish() will raise).

        Live callers may poll this after each ``feed`` to bail out to raw
        rendering immediately instead of waiting for the terminal ``finish``.
        """
        return self._state == _FAILED

    def feed(self, chunk: str) -> str:
        """Consume *chunk*, returning the decoded text delta it produced."""
        self._raw.append(chunk)
        out: list[str] = []
        for ch in chunk:
            self._step(ch, out)
        return "".join(out)

    def finish(self) -> str:
        """Validate completeness; raise :class:`EnvelopeError` if the stream
        never became a complete envelope carrying a ``"text"`` key."""
        if self._state in (_DONE, _POST_FENCE) and self._saw_text_key:
            return ""
        accumulated = "".join(self._raw)
        if self._state == _FAILED:
            raise EnvelopeError(self._reason, accumulated)
        if not accumulated:
            raise EnvelopeError("empty stream", accumulated)
        if self._state in (_DONE, _POST_FENCE):
            raise EnvelopeError(f"envelope carried no {self._field!r} key", accumulated)
        raise EnvelopeError("envelope incomplete at end of stream", accumulated)

    # -- state machine -----------------------------------------------------

    def _fail(self, reason: str) -> None:
        self._state = _FAILED
        if not self._reason:
            self._reason = reason

    def _step(self, ch: str, out: list[str]) -> None:
        """Dispatch one character to the current state's handler.

        The per-state handlers keep each state's logic small (SonarCloud
        S3776); ``_TEXT``/``_VALUE_START`` need the *out* sink, the rest
        take only the character.
        """
        state = self._state
        if state == _FAILED:
            return
        if state == _TEXT:
            self._read_text(ch, out)
        else:
            self._HANDLERS[state](self, ch)

    def _st_pre(self, ch: str) -> None:
        if ch in _WS:
            return
        if ch == "`":
            self._backtick_run = 1
            self._state = _FENCE_OPEN
            return
        if ch == "{":
            self._enter_object()
            return
        self._fail(f"expected an envelope, got {ch!r}")

    def _st_fence_open(self, ch: str) -> None:
        # Consume the rest of the ``` marker + language tag up to EOL.
        if ch == "\n":
            self._backtick_run = 0
            self._state = _JSON_START

    def _st_json_start(self, ch: str) -> None:
        if ch in _WS:
            return
        if ch == "{":
            self._enter_object()
            return
        self._fail(f"expected '{{' after the fence, got {ch!r}")

    def _st_post_key(self, ch: str) -> None:
        if ch in _WS:
            return
        if ch == ":":
            self._state = _VALUE_START
            return
        self._fail(f"expected ':' after a key, got {ch!r}")

    def _st_done(self, ch: str) -> None:
        if ch in _WS:
            return
        if ch == "`":
            self._backtick_run += 1
            if self._backtick_run >= 3:
                self._backtick_run = 0
                self._state = _POST_FENCE
            return
        self._fail(f"trailing content after the envelope: {ch!r}")

    def _st_post_fence(self, ch: str) -> None:
        if ch in _WS:
            return
        self._fail(f"trailing content after the closing fence: {ch!r}")

    def _enter_object(self) -> None:
        self._depth = 1
        self._state = _SCAN

    def _scan(self, ch: str) -> None:
        """Inside the envelope object (or a skipped nested container),
        outside any string."""
        if ch in _WS or ch == ",":
            return
        if self._depth == 1 and not self._container:
            self._scan_envelope_body(ch)
        else:
            self._scan_skipped_container(ch)

    def _scan_envelope_body(self, ch: str) -> None:
        """Depth-1 scanning: keys and the envelope's closing brace."""
        if ch == '"':
            self._key = []
            self._in_key_escape = False
            self._state = _KEY
            return
        if ch == "}":
            self._depth = 0
            self._state = _DONE
            return
        self._fail(f"expected a key or '}}', got {ch!r}")

    def _scan_skipped_container(self, ch: str) -> None:
        """Skipping a nested container's content with structure awareness."""
        if ch == '"':
            self._state = _STRING
            return
        if ch in "{[":
            self._container.append(ch)
            return
        if ch in "}]":
            opener = self._container.pop() if self._container else ""
            if (opener, ch) not in (("{", "}"), ("[", "]")):
                self._fail(f"mismatched container close {ch!r}")
        # ':' separators and scalar characters inside the container are
        # consumed as skip.

    def _read_key(self, ch: str) -> None:
        if self._in_key_escape:
            self._in_key_escape = False
            self._key.append(ch)
            return
        if ch == "\\":
            self._in_key_escape = True
            return
        if ch == '"':
            self._state = _POST_KEY
            return
        self._key.append(ch)

    def _begin_value(self, ch: str) -> None:
        if ch in _WS:
            return
        is_text = "".join(self._key) == self._field and not self._text_done
        if ch == '"':
            if is_text:
                self._saw_text_key = True
                self._escape = []
                self._state = _TEXT
            else:
                self._state = _STRING
            return
        if ch in "{[":
            self._container.append(ch)
            self._state = _SCAN
            return
        if ch in "}]":
            self._fail(f"expected a value, got {ch!r}")
            return
        # Number / true / false / null.
        self._state = _SCALAR

    def _read_text(self, ch: str, out: list[str]) -> None:
        """Inside the target string value — decode and emit."""
        if self._escape:
            self._escape.append(ch)
            self._flush_escape(out)
            return
        if ch == "\\":
            self._escape = ["\\"]
            return
        if ch == '"':
            self._text_done = True
            self._state = _SCAN
            return
        if ch == "\n":
            self._fail("raw newline inside the text value (unescaped)")
            return
        out.append(ch)

    def _flush_escape(self, out: list[str]) -> None:
        esc = self._escape
        kind = esc[1]
        if kind == "u":
            if len(esc) < 6:
                return  # \uXXXX still accumulating (chunk boundaries)
            try:
                out.append(chr(int("".join(esc[2:6]), 16)))
            except ValueError:
                self._fail("invalid \\u escape in the text value")
                return
            self._escape = []
            return
        decoded = _ESCAPES.get(kind)
        if decoded is None:
            self._fail(f"invalid escape \\{kind} in the text value")
            return
        out.append(decoded)
        self._escape = []

    def _read_string(self, ch: str) -> None:
        """Inside a non-target string (key's value, or nested content)."""
        if self._escape:
            self._escape = []
            return
        if ch == "\\":
            self._escape = ["\\"]
            return
        if ch == '"':
            self._state = _SCAN

    def _read_scalar(self, ch: str) -> None:
        if ch in _WS or ch == ",":
            self._state = _SCAN
            return
        if ch == "}":
            if self._container:
                self._scan(ch)
                return
            self._depth = 0
            self._state = _DONE
            return
        if ch == "]":
            self._scan(ch)

    #: State-dispatch table (S3776): every no-sink state's handler.
    _HANDLERS = {
        _PRE: _st_pre,
        _FENCE_OPEN: _st_fence_open,
        _JSON_START: _st_json_start,
        _SCAN: _scan,
        _KEY: _read_key,
        _VALUE_START: _begin_value,
        _POST_KEY: _st_post_key,
        _STRING: _read_string,
        _SCALAR: _read_scalar,
        _DONE: _st_done,
        _POST_FENCE: _st_post_fence,
    }
