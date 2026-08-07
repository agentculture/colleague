"""Streaming containment: partial render + marker, reply never lost (ssv task
t5, covers c25/h20).

Builds on ``tests/test_session_senses_streaming.py`` (t3)'s conversation-
surface streaming: a senses reply on a live colour-TTY session paints a
growing ``senses: …`` row in place while it generates, and the FINAL rendered
line normally comes from the unchanged whole-reply blocking path, which
supersedes the last transient paint. This module pins the two cases where the
completion itself does NOT produce a clean final render:

* **Mid-stream death** — the completion raises (a killed connection, no
  ``[DONE]``, no ``finish_reason``) AFTER the painter already painted at
  least one transient row. The senses run function's own try/except (see
  ``colleague/senses.py``) already degrades this to a fixed canned answer
  ("senses is unavailable right now.") — but rendering that verbatim would
  silently replace whatever the operator already watched stream in. The
  session's turn seam (:meth:`_Session._finalize_cut_stream`) instead
  finalizes the partial text as a real line plus the ONE
  ``error: senses stream cut mid-reply — showing partial text`` marker line
  (the session's existing ``error:`` seam, reused verbatim) — never a
  traceback, never the reply silently discarded.
* **Extraction failure with prior partial emission** — the DISPLAY-only
  incremental extractor (:class:`~colleague.senses_stream.EnvelopeStream`)
  can flag ``.failed`` (e.g. trailing content after the envelope closes)
  while the COMPLETION itself succeeded and the full raw text still parses
  cleanly via the separate, independent ``_extract_json_object`` the run
  function uses for its own final parse. That half of the containment
  already existed before this task (the whole-reply render simply
  supersedes the shorter transient row) — pinned here as a regression guard.

A turn that never streamed (painter unarmed, or armed but nothing painted
before a degrade) takes the byte-identical pre-t5 fallback path — pinned as
the golden regression test.

Per the fake-streams lesson and the sibling t3 module, transport is always a
REAL local ``http.server`` (never a scripted/faked stream) and terminal
writes go through the SAME owned-line-over-a-real-``os.pipe`` harness t3
uses; ``io.StringIO`` is fine as an OUTPUT sink (no blocking read involved),
matching every non-PTY test in the sibling module.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Optional

from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, TaskResult
from colleague.frontdoor import SENSES_DIRECT, FrontDoorOutcome

# ---------------------------------------------------------------------------
# Real-socket harness (mirrors tests/test_session_senses_streaming.py)
# ---------------------------------------------------------------------------


def _sse_frame(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def _make_mid_stream_death_handler(chunks: "list[str]") -> type:
    """A server that streams *chunks* then dies mid-reply on the FIRST
    ``/chat/completions`` request (no ``[DONE]``, no ``finish_reason`` —
    the AC1 trigger), and refuses every subsequent completions request
    outright (an empty response — a dead connection) so the engine's own
    one-shot blocking fallback (``colleague.engines.vllm_openai
    ._stream_or_blocking``, a DIFFERENT, earlier-landed task also numbered
    t5) also fails and the degrade genuinely reaches the senses run
    function's ``except Exception`` — never silently "fixed" underneath us.

    A ``/tokenize`` probe (the real per-turn windowing call every senses
    invocation makes) is answered with a plain 404 regardless of request
    count, so it never competes with the ``/chat/completions`` counter for
    the "first request" slot — the token counter gracefully falls back to
    the char estimate, exactly as it does against any server with no
    ``/tokenize`` route.
    """

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        _count = 0
        _lock = threading.Lock()

        def log_message(self, fmt: str, *args: object) -> None:  # silence test noise
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            if "tokenize" in self.path:
                self.send_response(404)
                self.end_headers()
                return
            with type(self)._lock:
                type(self)._count += 1
                n = type(self)._count
            if n == 1:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(_sse_frame({"choices": [{"delta": {"content": chunk}}]}))
                    self.wfile.flush()
                return  # abrupt death: no [DONE], no finish_reason frame
            # Any retry (the engine's own blocking fallback attempt): refuse
            # outright — an empty response, simulating the endpoint staying down.
            self.close_connection = True

    return _Handler


def _make_trailing_garbage_handler(chunks: "list[str]", usage: dict) -> type:
    """A server that streams *chunks* (a complete envelope PLUS trailing
    garbage the model appended after it) and terminates the stream cleanly
    with ``[DONE]`` — a genuine completion, not a connection death. The
    DISPLAY-only incremental extractor chokes on the trailing garbage
    (``EnvelopeStream.failed``); the completion's OWN final parse
    (``_extract_json_object``, entirely independent machinery) still finds
    the well-formed object and succeeds."""

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt: str, *args: object) -> None:  # silence test noise
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            if "tokenize" in self.path:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(_sse_frame({"choices": [{"delta": {"content": chunk}}]}))
                self.wfile.flush()
            self.wfile.write(_sse_frame({"choices": [], "usage": usage}))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    return _Handler


@contextmanager
def _serve(handler_cls: type) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Session builder (mirrors tests/test_session_senses_streaming.py)
# ---------------------------------------------------------------------------


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _senses_config(base_url: str = "http://senses") -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url=base_url, api_key="k", context_budget=24000
    )
    return config


def _session(
    tmp_path: Path,
    *,
    view: str = "ansi",
    config: Optional[EngineConfig] = None,
    engine_name: str = "mock",
    json_mode: bool = False,
):
    out, err = _CollectingOut(), _CollectingOut()
    result = TaskResult(task_id="t", status=OK, summary="s")

    def _fake_work(**kwargs: object):
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    sess = _Session(
        repo=tmp_path,
        engine_name=engine_name,
        open_pr=False,
        base="main",
        config=config if config is not None else _senses_config(),
        json_mode=json_mode,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=SensesSessionOptions(),
    )
    return sess, out, err


def _arm_owned_line_over_pipe(sess, stream_out):
    """Arm the owned line with a REAL os.pipe reader end (never StringIO for a
    stream READ — the fake-streams lesson) and the given output stream."""
    r_fd, w_fd = os.pipe()
    stream_in = os.fdopen(r_fd, "rb", buffering=0)
    sess._owned_line_streams = (stream_in, stream_out)
    sess._arm_owned_line()
    assert sess._owned_line is not None

    def _cleanup():
        sess._disarm_owned_line()
        with contextlib.suppress(Exception):
            os.close(w_fd)
        with contextlib.suppress(Exception):
            stream_in.close()

    return _cleanup


def _conv_lines(sess) -> "list[str]":
    return [entry.text for entry in sess.state.conversation]


def _assert_no_traceback(*texts: str) -> None:
    for text in texts:
        assert "Traceback (most recent call last)" not in text, text


# ---------------------------------------------------------------------------
# AC1 — mid-stream death: partial text finalized + marker, no traceback
# ---------------------------------------------------------------------------

_PARTIAL_PREFIX = (
    '{"answer": "the analysis is progressing nicely and stays well above the paint '
    "threshold so multiple in-place repaints occur before the reply ever closes"
)


class TestMidStreamDeathTalkLane:
    def test_finalizes_partial_text_and_marker_no_traceback(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("COLUMNS", "400")
        chunks = [_PARTIAL_PREFIX[i : i + 9] for i in range(0, len(_PARTIAL_PREFIX), 9)]
        with _serve(_make_mid_stream_death_handler(chunks)) as base_url:
            sess, out, err = _session(
                tmp_path, config=_senses_config(base_url), engine_name="vllm-openai"
            )
            fake_out = io.StringIO()
            cleanup = _arm_owned_line_over_pipe(sess, fake_out)
            try:
                fake_out.seek(0)
                fake_out.truncate(0)  # drop the arm-time prompt
                sess._talk_active = True
                sess._talk_task_id = "t-death"
                sess._talk_senses("status?")  # must not raise
            finally:
                cleanup()

        written = fake_out.getvalue()
        _assert_no_traceback(written, out.text(), err.text())

        lines = _conv_lines(sess)
        # The partial text rendered as a REAL senses: line — never the canned
        # "senses is unavailable right now." fallback that would silently
        # discard everything already streamed.
        senses_lines = [line for line in lines if line.startswith("senses: ")]
        assert senses_lines, lines
        assert all("unavailable right now" not in line for line in senses_lines)
        assert any(len(line) > len("senses: ") for line in senses_lines)
        # The ONE legible marker line, matching the session's existing error:
        # seam/prefix verbatim.
        assert session_mod._STREAM_CUT_MARKER in lines
        assert any(session_mod._STREAM_CUT_MARKER in ln for ln in err.lines)
        # The partial paint is superseded IN PLACE (finalized via print_above,
        # which starts with CR+erase) — no dangling half-written row.
        assert "\r\x1b[K" in written

    def test_no_streaming_paint_leaves_last_talk_reply_from_answer_field(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Sanity: the fallback ``_last_talk_reply`` reflects whichever text
        actually rendered (the partial text on the cut-stream path), so a
        voice turn speaking it back never speaks stale/unrelated content."""
        monkeypatch.setenv("COLUMNS", "400")
        chunks = [_PARTIAL_PREFIX[i : i + 9] for i in range(0, len(_PARTIAL_PREFIX), 9)]
        with _serve(_make_mid_stream_death_handler(chunks)) as base_url:
            sess, _out, _err = _session(
                tmp_path, config=_senses_config(base_url), engine_name="vllm-openai"
            )
            cleanup = _arm_owned_line_over_pipe(sess, io.StringIO())
            try:
                sess._talk_active = True
                sess._talk_task_id = "t-death"
                sess._talk_senses("status?")
            finally:
                cleanup()
        assert sess._last_talk_reply
        assert "unavailable right now" not in sess._last_talk_reply


class TestMidStreamDeathSessionContinues:
    def test_talk_lane_survives_a_cut_stream_and_handles_the_next_turn(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """AC1(c): the session continues to the next prompt after a cut
        stream — proven at the talk-lane turn level (``_talk_senses`` is the
        SAME method the live loop's ``_poll_talk_lane``/``_handle_talk_input``
        call at each progress-sink boundary while the operator keeps typing;
        ``run()`` itself only arms the genuine live-TTY loop off a real
        terminal — see ``_live``'s own doc — so a scripted test iterator
        cannot drive that specific plumbing without a real PTY, already
        covered for AC1's paint-growth claim by the sibling t3 module's PTY
        test). A turn dying mid-stream must not corrupt the session: the
        VERY NEXT turn — against a normal, healthy server — renders cleanly,
        exactly like any other talk turn."""
        monkeypatch.setenv("COLUMNS", "400")
        chunks = [_PARTIAL_PREFIX[i : i + 9] for i in range(0, len(_PARTIAL_PREFIX), 9)]
        with _serve(_make_mid_stream_death_handler(chunks)) as base_url:
            sess, out, err = _session(
                tmp_path, config=_senses_config(base_url), engine_name="vllm-openai"
            )
            cleanup = _arm_owned_line_over_pipe(sess, io.StringIO())
            try:
                sess._talk_active = True
                sess._talk_task_id = "t-death"
                sess._talk_senses("status?")  # turn 1: cut mid-stream
            finally:
                cleanup()

        lines_after_turn1 = _conv_lines(sess)
        assert session_mod._STREAM_CUT_MARKER in lines_after_turn1

        # Turn 2: a normal, healthy server — the "next prompt" the operator
        # reaches. Must render cleanly, proving turn 1's cut stream left no
        # lingering bad state (a stuck painter, a corrupted history, …).
        next_answer = "all clear now - the stream came back and this turn finished normally."
        raw = json.dumps({"answer": next_answer, "relay": False, "relay_text": ""})
        usage = {"prompt_tokens": 5, "completion_tokens": 12}
        with _serve(_make_trailing_garbage_handler([raw], usage)) as base_url2:
            sess.config = _senses_config(base_url2)
            cleanup = _arm_owned_line_over_pipe(sess, io.StringIO())
            try:
                sess._talk_senses("anything new?")  # turn 2: the next prompt
            finally:
                cleanup()

        _assert_no_traceback(out.text(), err.text())
        lines = _conv_lines(sess)
        assert f"senses: {next_answer}" in lines
        # Turn 2 rendered its OWN clean answer, not a repeat of turn 1's
        # marker or partial text.
        assert lines.count(session_mod._STREAM_CUT_MARKER) == 1


# ---------------------------------------------------------------------------
# Front-door containment (unit-level: isolates the wiring, mirrors the t3
# arming-decision tests' style — a fake painter + a monkeypatched run_frontdoor)
# ---------------------------------------------------------------------------


class TestMidStreamDeathFrontdoor:
    def test_degraded_frontdoor_finalizes_partial_paint_before_falling_through(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A degraded front-door turn already falls through to cortex with NO
        senses-direct render at all (by design, c19) — but a partial paint
        from BEFORE the degrade must still be finalized here, or the next
        redraw (cortex's own) silently wipes it with no explanation."""
        sess, _out, err = _session(tmp_path)
        sess._live = True
        monkeypatch.setattr(session_mod, "_stdout_is_tty", lambda: True)

        class _FakePainter:
            paints = 3
            painted_text = "partial answer so f"

            def on_display_delta(self, piece: str) -> None:  # never actually called
                raise AssertionError("no completion ran — nothing should feed the painter")

        monkeypatch.setattr(_Session, "_senses_stream_sink", lambda self: _FakePainter())

        def _fake_frontdoor(text: str, **kwargs: object) -> FrontDoorOutcome:
            return FrontDoorOutcome(
                route=SENSES_DIRECT,
                dispatch=True,
                answered_directly=False,
                answer="senses can't answer that right now — cortex can.",
                degraded=True,
                record=None,
            )

        monkeypatch.setattr(session_mod, "run_frontdoor", _fake_frontdoor)
        outcome = sess._run_frontdoor("hello there")

        assert outcome.degraded is True
        assert outcome.dispatch is True  # still falls through to cortex, unchanged
        lines = _conv_lines(sess)
        assert "senses: partial answer so f" in lines
        assert session_mod._STREAM_CUT_MARKER in lines

    def test_degraded_frontdoor_with_no_paint_stays_silent(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A degraded front door that never painted anything (the byte-
        identical golden path) renders nothing new — unchanged from before
        this task."""
        sess, _out, _err = _session(tmp_path)
        sess._live = True
        monkeypatch.setattr(session_mod, "_stdout_is_tty", lambda: True)

        class _EmptyPainter:
            paints = 0
            painted_text = ""

            def on_display_delta(self, piece: str) -> None:
                pass

        monkeypatch.setattr(_Session, "_senses_stream_sink", lambda self: _EmptyPainter())

        def _fake_frontdoor(text: str, **kwargs: object) -> FrontDoorOutcome:
            return FrontDoorOutcome(
                route=SENSES_DIRECT,
                dispatch=True,
                answered_directly=False,
                answer="senses can't answer that right now — cortex can.",
                degraded=True,
                record=None,
            )

        monkeypatch.setattr(session_mod, "run_frontdoor", _fake_frontdoor)
        before = _conv_lines(sess)
        sess._run_frontdoor("hello there")
        assert _conv_lines(sess) == before  # nothing rendered — strict no-op


# ---------------------------------------------------------------------------
# AC2 — extraction failure with prior partial emission: nothing is lost
# ---------------------------------------------------------------------------


class TestExtractionFailureDegradesToWholeReply:
    def test_trailing_garbage_fails_the_extractor_but_full_reply_still_renders(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Pin the ALREADY-EXISTING half of AC2: the display-only incremental
        extractor can flag ``.failed`` (trailing content after the envelope)
        while the completion's OWN final parse succeeds — some deltas
        painted, extraction then goes quiet, and the unchanged whole-reply
        blocking render supersedes the transient row with the FULL, correct
        answer. Nothing is lost; no cut-stream marker fires (this was never
        a degraded turn)."""
        monkeypatch.setenv("COLUMNS", "400")
        answer = (
            "hello - the analysis is complete and every test in the suite is green, "
            "so this reply comfortably clears the paint threshold on its own"
        )
        # A complete, valid envelope PLUS trailing garbage the model appended
        # after it — the incremental extractor's `_DONE` state fails on the
        # first non-whitespace character after `}`; `_extract_json_object`
        # (entirely separate machinery) simply finds the balanced object and
        # ignores everything after it.
        raw = json.dumps({"answer": answer, "relay": False, "relay_text": ""})
        raw += " <|trailing_garbage_the_model_appended|>"
        chunks = [raw[i : i + 11] for i in range(0, len(raw), 11)]
        usage = {"prompt_tokens": 11, "completion_tokens": 29}
        with _serve(_make_trailing_garbage_handler(chunks, usage)) as base_url:
            sess, out, err = _session(
                tmp_path, config=_senses_config(base_url), engine_name="vllm-openai"
            )
            cleanup = _arm_owned_line_over_pipe(sess, io.StringIO())
            try:
                sess._talk_active = True
                sess._talk_task_id = "t-trailing"
                sess._talk_senses("status?")
            finally:
                cleanup()

        _assert_no_traceback(out.text(), err.text())
        lines = _conv_lines(sess)
        # The FULL, correct reply rendered — nothing truncated, nothing lost.
        assert f"senses: {answer}" in lines
        # This was a CLEAN completion (degraded=False) — the cut-stream
        # containment never fires for it.
        assert session_mod._STREAM_CUT_MARKER not in lines


# ---------------------------------------------------------------------------
# Golden — a turn that never streamed keeps today's plain fallback untouched
# ---------------------------------------------------------------------------


class TestGoldenNoStreamingDegradeUnchanged:
    def test_disarmed_painter_keeps_the_plain_canned_fallback(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Whatever the session printed for a degraded senses turn BEFORE
        this task stays byte-identical when no paints occurred (painter
        unarmed) — no marker line, the plain canned fallback text."""
        chunks = [_PARTIAL_PREFIX[i : i + 9] for i in range(0, len(_PARTIAL_PREFIX), 9)]
        with _serve(_make_mid_stream_death_handler(chunks)) as base_url:
            sess, out, err = _session(
                tmp_path, config=_senses_config(base_url), engine_name="vllm-openai"
            )
            # Disarm streaming entirely — the h12 baseline every t3 golden
            # test uses.
            monkeypatch.setattr(_Session, "_senses_stream_sink", lambda self: None)
            sess._talk_active = True
            sess._talk_task_id = "t-golden"
            sess._talk_senses("status?")  # must not raise

        _assert_no_traceback(out.text(), err.text())
        lines = _conv_lines(sess)
        assert "senses: senses is unavailable right now." in lines
        assert session_mod._STREAM_CUT_MARKER not in lines


# ---------------------------------------------------------------------------
# Unit-level seams: the painter's t5 state, and _finalize_cut_stream itself
# ---------------------------------------------------------------------------


class TestFinalizeCutStreamSeam:
    def test_painted_text_exposes_the_current_display_tail(self, tmp_path: Path) -> None:
        sess, _o, _e = _session(tmp_path)
        painter = session_mod._SensesStreamPainter(sess)
        assert painter.painted_text == ""
        painter.on_display_delta("x" * 60)  # crosses the repaint threshold
        assert painter.painted_text != ""
        assert painter.painted_text in ("x" * 60)[-len(painter.painted_text) :]

    def test_noop_when_painter_is_none(self, tmp_path: Path) -> None:
        sess, _o, _e = _session(tmp_path)
        before = _conv_lines(sess)
        assert sess._finalize_cut_stream(None) is False
        assert _conv_lines(sess) == before

    def test_noop_when_nothing_painted(self, tmp_path: Path) -> None:
        sess, _o, _e = _session(tmp_path)
        painter = session_mod._SensesStreamPainter(sess)
        assert painter.paints == 0
        before = _conv_lines(sess)
        assert sess._finalize_cut_stream(painter) is False
        assert _conv_lines(sess) == before

    def test_fires_and_renders_partial_text_plus_marker(self, tmp_path: Path) -> None:
        sess, _o, err = _session(tmp_path)
        painter = session_mod._SensesStreamPainter(sess)
        painter.on_display_delta("a partial reply that crosses the threshold" + "!" * 20)
        assert painter.paints > 0
        fired = sess._finalize_cut_stream(painter)
        assert fired is True
        lines = _conv_lines(sess)
        assert f"senses: {painter.painted_text}" in lines
        assert session_mod._STREAM_CUT_MARKER in lines
        assert any(session_mod._STREAM_CUT_MARKER in ln for ln in err.lines)

    def test_marker_matches_the_existing_error_line_style(self) -> None:
        assert session_mod._STREAM_CUT_MARKER.startswith("error: ")
