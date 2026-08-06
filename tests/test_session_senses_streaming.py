"""Conversation-surface incremental senses rendering (ssv task t3, covers c4/h3/h12).

A senses reply on a LIVE colour-TTY session renders as ONE growing ``senses: …``
line, repainted in place above the owned input line as display deltas arrive —
instead of appearing whole only after the completion ends. Three surfaces arm
(each with ITS OWN reply's envelope key, bound in ``colleague/senses.py`` so the
streaming field can never drift from the parsing field):

* the senses front door (``run_senses_frontdoor``, reply ``{"answer": …}``) —
  :data:`colleague.senses.FRONTDOOR_STREAM_FIELD`;
* the live talk lane (``run_senses_talk``, reply ``{"answer": …}``) —
  :data:`colleague.senses.TALK_STREAM_FIELD`;
* speak-back (``run_senses_speakback``, BARE PROSE — no envelope) — a raw
  pass-through ``on_delta`` (the raw deltas ARE the display text), never the
  extractor.

NOTE (deviation from the plan's parenthetical, recorded honestly): the plan
sketch said "text" for the front door, but ``run_senses_frontdoor`` parses its
reply with ``required_key="answer"`` (``{"answer": "..."}`` per its system
prompt) — arming ``"text"`` would structurally never stream (the extractor
withholds everything and fails at ``finish()``). The per-surface constants bind
the streaming key to the SAME key each surface's parser requires; the
coordination loop's moves keep :class:`EnvelopeStream`'s default ``"text"``.

Throttle + paint: display deltas fold through the SAME ``DeltaTail`` machinery
the cockpit status stream uses (``fold_delta`` / ``should_repaint_delta`` /
``mark_delta_rendered`` — count-based cadence, sanitized single line) but paint
the CONVERSATION surface: a transient in-place row repaint (CR + erase-line +
text, NO newline) on the row the reply's final whole-line render then
overwrites — so the final rendered line always comes from the UNCHANGED
blocking-path code, never from accumulated deltas. With the owned input line
armed the paint is its lock-protected ``stream_paint`` (all terminal writes on
the main thread through the owned-line seam); the cockpit DeltaTail status
behavior (CORTEX deltas → status line) is untouched.

Off the colour TTY — piped / ``--json`` / Markdown tier — NOTHING arms (h12):
``senses_engine_config`` sees ``on_delta=None``, the engine takes its blocking
path, and session output stays byte-identical (the golden test).

Per the fake-streams lesson the paint test runs over a REAL ``os.openpty`` pair
(and a real ``os.pipe`` for the reader) — never ``io.StringIO`` for reads — with
the senses completion streaming from a REAL local SSE server (the
``tests/test_senses_streaming.py`` harness shape).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import select as select_mod
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Optional

import pytest

from colleague import senses as senses_mod
from colleague.cli._commands import session as session_mod
from colleague.cli._commands._input_line import OwnedInputLine, transient_paint
from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session, _WorkSink
from colleague.cockpit_run import DELTA_REPAINT_THRESHOLD
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, SensesRecord, TaskResult

# ---------------------------------------------------------------------------
# Real-socket harness (mirrors tests/test_senses_streaming.py — a genuine
# http.server thread per side, never a faked/monkeypatched transport).
# ---------------------------------------------------------------------------


def _sse_frame(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def _make_streaming_handler(chunks: "list[str]", usage: dict) -> type:
    class _StreamingHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt: str, *args: object) -> None:  # silence test noise
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(_sse_frame({"choices": [{"delta": {"content": chunk}}]}))
                self.wfile.flush()
            self.wfile.write(_sse_frame({"choices": [], "usage": usage}))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    return _StreamingHandler


def _make_blocking_handler(full_text: str, usage: dict) -> type:
    class _BlockingHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt: str, *args: object) -> None:  # silence test noise
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            body = json.dumps(
                {"choices": [{"message": {"content": full_text}}], "usage": usage}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _BlockingHandler


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
# Session builders (mirror tests/test_session_frontdoor.py / _input_line.py)
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
    stream read — the fake-streams lesson) and the given output stream."""
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


def _spy_arming(monkeypatch):
    """Record every ``senses_engine_config(on_delta=...)`` arming and every
    ``make_senses_display_delta(field=...)`` adapter build the session performs,
    while delegating to the real functions."""
    calls = {"on_delta": [], "adapter_fields": []}
    real_sec = session_mod.senses_engine_config
    real_mk = session_mod.make_senses_display_delta

    def sec(config, *, on_delta=None):
        calls["on_delta"].append(on_delta)
        return real_sec(config, on_delta=on_delta)

    def mk(sink, *, field="text"):
        calls["adapter_fields"].append(field)
        return real_mk(sink, field=field)

    monkeypatch.setattr(session_mod, "senses_engine_config", sec)
    monkeypatch.setattr(session_mod, "make_senses_display_delta", mk)
    return calls


def _talk_record(answer: str = "all good in here.") -> dict:
    return {
        "answer": answer,
        "relay": False,
        "relay_text": "",
        "latency": 0.01,
        "degraded": False,
        "tokens": 3,
    }


# ---------------------------------------------------------------------------
# Per-surface envelope-key constants (d4/#374): bound to the parser's key
# ---------------------------------------------------------------------------


class TestStreamFieldConstants:
    def test_frontdoor_field_matches_the_parsers_required_key(self) -> None:
        """``run_senses_frontdoor`` extracts with ``required_key="answer"`` —
        the streaming field is bound to that same key (NOT the plan sketch's
        "text", which the front-door reply never carries)."""
        assert senses_mod.FRONTDOOR_STREAM_FIELD == "answer"

    def test_talk_field_matches_the_parsers_required_key(self) -> None:
        assert senses_mod.TALK_STREAM_FIELD == "answer"


# ---------------------------------------------------------------------------
# The arming decision (unit): who arms, with which field, and who never arms
# ---------------------------------------------------------------------------


class TestArmingDecision:
    def test_talk_turn_on_owned_line_arms_answer_field(self, tmp_path: Path, monkeypatch) -> None:
        sess, _o, _e = _session(tmp_path)
        cleanup = _arm_owned_line_over_pipe(sess, io.StringIO())
        try:
            calls = _spy_arming(monkeypatch)
            seen: dict = {}

            def _fake_talk(message, **kwargs):
                seen["on_delta"] = kwargs["senses_config"].on_delta
                return _talk_record()

            monkeypatch.setattr(session_mod, "run_senses_talk", _fake_talk)
            sess._talk_active = True
            sess._talk_task_id = "t-1"
            sess._talk_senses("how is it going in there")
            assert seen["on_delta"] is not None  # the completion itself is armed
            assert calls["adapter_fields"] == [senses_mod.TALK_STREAM_FIELD]
        finally:
            cleanup()

    def test_frontdoor_turn_on_live_tty_arms_answer_field(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sess, _o, _e = _session(tmp_path)
        sess._live = True
        monkeypatch.setattr(session_mod, "_stdout_is_tty", lambda: True)
        calls = _spy_arming(monkeypatch)
        seen: dict = {}

        def _fake_frontdoor(text, **kwargs):
            seen["on_delta"] = kwargs["senses_config"].on_delta
            return session_mod.cortex_frontdoor_outcome()

        monkeypatch.setattr(session_mod, "run_frontdoor", _fake_frontdoor)
        sess._run_frontdoor("hello")
        assert seen["on_delta"] is not None
        assert calls["adapter_fields"] == [senses_mod.FRONTDOOR_STREAM_FIELD]

    def test_speakback_arms_raw_passthrough_not_the_extractor(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Speak-back replies are BARE PROSE — no envelope — so the armed
        ``on_delta`` is the painter's raw display sink itself, never a
        ``make_senses_display_delta`` extractor."""
        sess, _o, _e = _session(tmp_path)
        sess._live = True
        monkeypatch.setattr(session_mod, "_stdout_is_tty", lambda: True)
        calls = _spy_arming(monkeypatch)
        seen: dict = {}

        def _fake_speak(summary, senses_config, engine, **kwargs):
            seen["on_delta"] = senses_config.on_delta
            return "shaped", SensesRecord(point="senses-speakback", latency=0.01)

        monkeypatch.setattr(session_mod, "run_senses_speakback", _fake_speak)
        result = TaskResult(task_id="t", status=OK, summary="raw summary")
        sess._finalize_split_run(result, None)
        assert seen["on_delta"] is not None
        assert calls["adapter_fields"] == []  # no extractor for bare prose
        painter = getattr(seen["on_delta"], "__self__", None)
        assert isinstance(painter, session_mod._SensesStreamPainter)

    @pytest.mark.parametrize("view,json_mode", [("markdown", False), ("markdown", True)])
    def test_piped_json_markdown_session_arms_nothing(
        self, tmp_path: Path, monkeypatch, view: str, json_mode: bool
    ) -> None:
        """h12: off the colour TTY the senses completions stay UNARMED —
        ``senses_engine_config`` only ever sees ``on_delta=None``."""
        sess, _o, _e = _session(tmp_path, view=view, json_mode=json_mode)
        calls = _spy_arming(monkeypatch)
        monkeypatch.setattr(session_mod, "run_senses_talk", lambda m, **k: _talk_record())
        monkeypatch.setattr(
            session_mod, "run_frontdoor", lambda t, **k: session_mod.cortex_frontdoor_outcome()
        )
        monkeypatch.setattr(
            session_mod,
            "run_senses_speakback",
            lambda s, c, e, **k: (None, SensesRecord(point="senses-speakback")),
        )
        sess._talk_active = True
        sess._talk_senses("anything new")
        sess._run_frontdoor("hello")
        sess._finalize_split_run(TaskResult(task_id="t", status=OK, summary="s"), None)
        assert calls["adapter_fields"] == []
        assert all(cb is None for cb in calls["on_delta"])

    def test_ansi_but_not_live_and_no_owned_line_arms_nothing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A direct-construction / scripted ANSI session (not the genuine live
        loop, no owned line) stays byte-identical — nothing arms."""
        sess, _o, _e = _session(tmp_path)
        assert sess._live is False and sess._owned_line is None
        calls = _spy_arming(monkeypatch)
        monkeypatch.setattr(session_mod, "run_senses_talk", lambda m, **k: _talk_record())
        sess._talk_active = True
        sess._talk_senses("anything new")
        assert calls["adapter_fields"] == []
        assert all(cb is None for cb in calls["on_delta"])

    def test_bare_senses_engine_stays_unarmed_for_intake_and_updates(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Intake / clarify / proactive updates go through the bare
        ``_senses_engine()`` — even on a live TTY their completions stay
        unarmed (only the three display-reply surfaces stream)."""
        sess, _o, _e = _session(tmp_path)
        sess._live = True
        monkeypatch.setattr(session_mod, "_stdout_is_tty", lambda: True)
        pair = sess._senses_engine()
        assert pair is not None
        senses_config, _engine = pair
        assert senses_config.on_delta is None


# ---------------------------------------------------------------------------
# The transient-paint seam (owned-line writes stay main-thread + lock-guarded)
# ---------------------------------------------------------------------------


class TestStreamPaintSeam:
    def test_transient_paint_is_cr_erase_text_without_newline(self) -> None:
        assert transient_paint("senses: hi") == "\r\x1b[Ksenses: hi"

    def test_stream_paint_writes_transient_paint_when_armed(self, tmp_path: Path) -> None:
        sess, _o, _e = _session(tmp_path)
        fake_out = io.StringIO()
        cleanup = _arm_owned_line_over_pipe(sess, fake_out)
        try:
            fake_out.seek(0)
            fake_out.truncate(0)  # drop the arm-time prompt
            sess._owned_line.stream_paint("senses: gro")
            sess._owned_line.stream_paint("senses: growing")
            assert fake_out.getvalue() == "\r\x1b[Ksenses: gro\r\x1b[Ksenses: growing"
        finally:
            cleanup()

    def test_stream_paint_disarmed_is_a_strict_noop(self, tmp_path: Path) -> None:
        out = io.StringIO()
        line = OwnedInputLine(io.BytesIO(b""), out)  # never started → disarmed
        line.stream_paint("senses: nope")
        assert out.getvalue() == ""

    def test_painter_throttles_via_should_repaint_delta_cadence(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Paint cadence is the cockpit's own count-based throttle — no paint
        below DELTA_REPAINT_THRESHOLD accumulated chars, one right after."""
        monkeypatch.setenv("COLUMNS", "400")
        sess, _o, _e = _session(tmp_path)
        fake_out = io.StringIO()
        cleanup = _arm_owned_line_over_pipe(sess, fake_out)
        try:
            painter = sess._senses_stream_sink()
            assert painter is not None
            fake_out.seek(0)
            fake_out.truncate(0)
            painter.on_display_delta("x" * (DELTA_REPAINT_THRESHOLD - 1))
            assert fake_out.getvalue() == ""  # below threshold — no paint
            painter.on_display_delta("yz")
            painted = fake_out.getvalue()
            assert painted.startswith("\r\x1b[Ksenses: ")
            assert "x" * (DELTA_REPAINT_THRESHOLD - 1) + "yz" in painted
            assert painter.paints == 1
        finally:
            cleanup()

    def test_painter_never_touches_status_conversation_or_steps(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sess, _o, _e = _session(tmp_path)
        cleanup = _arm_owned_line_over_pipe(sess, io.StringIO())
        try:
            painter = sess._senses_stream_sink()
            assert painter is not None
            before_status = sess.state.status
            before_conv = sess.state.conversation
            painter.on_display_delta("q" * 500)
            assert sess.state.status == before_status
            assert sess.state.conversation == before_conv
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# Cockpit DeltaTail (CORTEX deltas → STATUS line) is untouched
# ---------------------------------------------------------------------------


class TestCockpitDeltaTailUntouched:
    def test_worksink_delta_status_behavior_unchanged_with_senses_painter_armed(
        self, tmp_path: Path
    ) -> None:
        """Extends tests/test_cockpit_delta_tail.py's _WorkSink pins: with a
        senses painter armed on the same session, a CORTEX delta still folds
        onto the STATUS line at the same cadence, never the conversation."""
        sess, _o, _e = _session(tmp_path)
        cleanup = _arm_owned_line_over_pipe(sess, io.StringIO())
        try:
            painter = sess._senses_stream_sink()
            assert painter is not None
            sink = _WorkSink(sess)
            sink.on_delta("z" * (DELTA_REPAINT_THRESHOLD - 1))
            assert "generating" not in sess.state.status.message  # throttle intact
            sink.on_delta("zz")
            assert "generating" in sess.state.status.message  # folds onto STATUS
            assert list(sess.state.conversation) == []  # never the conversation feed
            # And the senses painter never wrote the status surface.
            status_before = sess.state.status
            painter.on_display_delta("senses side " * 10)
            assert sess.state.status == status_before
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# AC1 — real PTY: >= 2 paints of a growing senses: line above the owned line
# ---------------------------------------------------------------------------


_ANSWER = (
    "Cortex is on step three of the refactor - tests are green so far and I am "
    "watching the loop fold the next change in now."
)


def _drain_pty(master: int, *, quiet: float = 0.25, total: float = 5.0) -> bytes:
    """Read everything currently flowing out of *master*, stopping after
    *quiet* seconds of silence (bounded by *total*)."""
    data = b""
    deadline = time.monotonic() + total
    last = time.monotonic()
    while time.monotonic() < deadline:
        ready, _, _ = select_mod.select([master], [], [], 0.05)
        if ready:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            data += chunk
            last = time.monotonic()
        elif time.monotonic() - last > quiet:
            break
    return data


def _paint_segments(data: str) -> "list[str]":
    """Split raw terminal output on the transient-paint marker, returning the
    painted segments (everything after each CR+erase-line)."""
    return data.split("\r\x1b[K")[1:]


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs POSIX openpty")
def test_pty_talk_reply_streams_growing_senses_line_and_final_matches_blocking(
    tmp_path: Path, monkeypatch
) -> None:
    """AC1 on a REAL PTY: a talk-lane senses reply streamed from a real SSE
    server produces >= 2 in-place paints of a growing ``senses:`` line above
    the owned input line, and the FINAL rendered line equals byte-for-byte
    what the blocking path renders for the same reply. Bounded retry (2) for
    PTY flake (risk r4)."""
    monkeypatch.setenv("COLUMNS", "400")  # keep the whole reply on one row
    raw_reply = json.dumps({"answer": _ANSWER, "relay": False, "relay_text": ""})
    chunks = [raw_reply[i : i + 7] for i in range(0, len(raw_reply), 7)]
    usage = {"prompt_tokens": 11, "completion_tokens": 29}

    last_error: Optional[BaseException] = None
    for _attempt in range(2):  # bounded PTY-flake retry (risk r4)
        try:
            _run_pty_talk_attempt(tmp_path, chunks, usage)
            break
        except AssertionError as exc:  # pragma: no cover - flake path
            last_error = exc
    else:  # pragma: no cover - flake path
        raise AssertionError(f"PTY paint assertions failed twice: {last_error}")

    # The blocking baseline on the SAME reply: the rendered senses line is
    # byte-identical to what the streamed path rendered as its final line.
    with _serve(_make_blocking_handler(raw_reply, usage)) as base_url:
        sess, _o, _e = _session(
            tmp_path, config=_senses_config(base_url), engine_name="vllm-openai"
        )
        monkeypatch.setattr(_Session, "_senses_stream_sink", lambda self: None)
        sess._talk_active = True
        sess._talk_task_id = "t-blocking"
        sess._talk_senses("status?")
        blocking_lines = [line.text for line in sess.state.conversation]
    assert f"senses: {_ANSWER}" in blocking_lines


def _run_pty_talk_attempt(tmp_path: Path, chunks: "list[str]", usage: dict) -> None:
    master, slave = os.openpty()
    stream_out = os.fdopen(os.dup(slave), "w")
    os.close(slave)
    try:
        with _serve(_make_streaming_handler(chunks, usage)) as base_url:
            sess, _o, _e = _session(
                tmp_path, config=_senses_config(base_url), engine_name="vllm-openai"
            )
            cleanup = _arm_owned_line_over_pipe(sess, stream_out)
            try:
                status_before = sess.state.status
                sess._talk_active = True
                sess._talk_task_id = "t-stream"
                sess._talk_senses("status?")
                assert sess.state.status == status_before  # DeltaTail status untouched
            finally:
                cleanup()
        stream_out.flush()
        data = _drain_pty(master).decode("utf-8", errors="replace")
    finally:
        with contextlib.suppress(Exception):
            stream_out.close()
        with contextlib.suppress(Exception):
            os.close(master)

    segments = _paint_segments(data)
    paints = [s for s in segments if s.startswith("senses: ") and "\n" not in s]
    assert len(paints) >= 2, f"expected >= 2 in-place paints, got {len(paints)}: {data!r}"
    # Growing: each successive paint extends the previous one (COLUMNS is wide
    # enough that the row window never scrolls) and stays within the reply.
    for earlier, later in zip(paints, paints[1:]):
        assert later.startswith(earlier)
        assert len(later) > len(earlier)
    full_line = f"senses: {_ANSWER}"
    for paint in paints:
        assert full_line.startswith(paint)
    # The FINAL rendered line is the whole reply — printed by the unchanged
    # whole-line path (print_above), erasing the last transient paint.
    final_segments = [s for s in segments if s.split("\r\n")[0] == full_line]
    assert final_segments, f"final senses line missing from PTY output: {data!r}"


# ---------------------------------------------------------------------------
# AC2 — golden piped test: byte-identical to the streaming-disarmed baseline
# ---------------------------------------------------------------------------


class TestGoldenPiped:
    def _run_piped_flow(
        self, tmp_path: Path, base_url: str, *, json_mode: bool, disarm: bool, monkeypatch
    ) -> "tuple[list[str], list[str]]":
        if disarm:
            # The baseline: streaming monkeypatched off — MUST be output-identical.
            monkeypatch.setattr(_Session, "_senses_stream_sink", lambda self: None)
        sess, out, err = _session(
            tmp_path,
            view="markdown",
            config=_senses_config(base_url),
            engine_name="vllm-openai",
            json_mode=json_mode,
        )
        rc = sess.run(iter(["hello there"]))
        assert rc == 0
        if disarm:
            monkeypatch.undo()
        return list(out.lines), list(err.lines)

    @pytest.mark.parametrize("json_mode", [False, True])
    def test_piped_session_output_byte_identical_to_disarmed_baseline(
        self, tmp_path: Path, monkeypatch, json_mode: bool
    ) -> None:
        """A piped / --json session's senses turn (a real front-door completion
        against a real local server) produces byte-identical stdout+stderr
        whether or not the t3 streaming code exists — because off the colour
        TTY it never arms (h12)."""
        raw_reply = json.dumps({"answer": "hi - I'm colleague's senses lobe."})
        usage = {"prompt_tokens": 5, "completion_tokens": 9}
        with _serve(_make_blocking_handler(raw_reply, usage)) as base_url:
            streamed_out, streamed_err = self._run_piped_flow(
                tmp_path, base_url, json_mode=json_mode, disarm=False, monkeypatch=monkeypatch
            )
            baseline_out, baseline_err = self._run_piped_flow(
                tmp_path, base_url, json_mode=json_mode, disarm=True, monkeypatch=monkeypatch
            )
        assert streamed_out == baseline_out
        assert streamed_err == baseline_err
        # The senses answer really rendered on both (the flow was live, not a
        # vacuous comparison of two empty transcripts).
        chrome = streamed_err if json_mode else streamed_out
        assert any("senses: hi - I'm colleague's senses lobe." in ln for ln in chrome)
