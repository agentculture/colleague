"""Cockpit live generation tail (feels-alive arc, task t6; session arming
extended to every render tier by task t4/ssv, covers c19/h16).

Arms + renders the runtime's optional token-delta seam (``EngineConfig.on_delta``,
``colleague/config.py``, landed by task t3): on the standalone ``colleague work
--tui`` cockpit only when it is genuinely live-rendering, and — since t4/ssv —
on EVERY interactive ``session`` cortex turn regardless of render tier, because
arming has a second job beyond live display: it flips the engine onto its
per-read-timeout-resetting streamed request path (``vllm_openai._make_complete``,
keyed on ``config.on_delta is not None``). A session's dynamic ANSI tier still
owns the only VISIBLE redraw; a piped/``--json``/Markdown session now streams
(for the timeout reset) but still never redraws into a frame nobody looks at —
its own output stays byte-identical to before t4/ssv.

Four layers, outside-in:

* pure delta-accumulation + throttle + sanitize helpers in ``colleague.cockpit_run``
  (``DeltaTail`` / ``fold_delta`` / ``should_repaint_delta`` / ``mark_delta_rendered``
  / ``delta_status_message`` / ``sanitize_delta_chunk``);
* ``CockpitProgressSink.on_delta`` (``colleague/cli/_commands/_tui_sink.py``) —
  the standalone ``work --tui`` cockpit;
* ``_WorkSink.on_delta`` (``colleague/cli/_commands/session.py``) — the
  interactive session's own sink; ``wants_delta_stream`` is now True on every
  session view tier (t4/ssv), with the visible redraw still gated on the
  dynamic ANSI tier inside ``on_delta``/``__call__`` themselves;
* the arming site itself, ``execute_work`` (``colleague/cli/_commands/work.py``),
  which sets ``config.on_delta`` iff the cockpit sink in play wants it.

Mirrors the existing ``fold_phase``/#206 test conventions (``tests/test_tui_sink.py``,
``tests/test_session.py``) throughout: a delta must never advance
``work_item.step_count``, never append a conversation/feed line, and never reach
the structured events-replay stream — it is a STATUS-surface-only, display-only
enhancement (the same invariant ``fold_phase`` pins for a phase notice).
"""

from __future__ import annotations

import io
import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
from agentfront.taui.events import loads_events
from agentfront.taui.state import TAUIState as CockpitState
from agentfront.taui.state import WorkItem

from colleague.cli._commands import _tui_sink
from colleague.cli._commands import session as session_mod
from colleague.cli._commands._tui_sink import CockpitProgressSink
from colleague.cli._commands.session import _WorkSink, run_session
from colleague.cli._commands.work import DisplayOptions, execute_work
from colleague.cockpit_run import (
    DELTA_REPAINT_THRESHOLD,
    DELTA_TAIL_CHARS,
    DeltaTail,
    delta_status_message,
    fold_delta,
    mark_delta_rendered,
    sanitize_delta_chunk,
    should_repaint_delta,
)
from colleague.config import EngineConfig
from colleague.contract import Task
from colleague.loop_deltaheartbeat import pre_armed_sink

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _make_args(tmp_path: Path) -> "object":
    import argparse

    return argparse.Namespace(
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _scripted(lines: list[str]) -> Iterator[str]:
    yield from lines


# ---------------------------------------------------------------------------
# Pure helpers (colleague.cockpit_run) — no I/O, no rendering
# ---------------------------------------------------------------------------


class TestSanitizeDeltaChunk:
    def test_strips_ansi_and_collapses_newlines(self) -> None:
        raw = "hello\nworld\r\nfoo\x1b[31mred\x1b[0m"
        sanitized = sanitize_delta_chunk(raw)
        assert "\n" not in sanitized
        assert "\r" not in sanitized
        assert "\x1b" not in sanitized
        assert sanitized == "hello world foored"

    def test_plain_text_is_unchanged(self) -> None:
        assert sanitize_delta_chunk("plain word-chunk ") == "plain word-chunk "

    def test_empty_chunk_stays_empty(self) -> None:
        assert sanitize_delta_chunk("") == ""


class TestFoldDelta:
    def test_reconstructs_short_text_exactly(self) -> None:
        tail = DeltaTail()
        for chunk in ["writing ", "the ", "marker ", "file"]:
            tail = fold_delta(tail, chunk)
        assert tail.text == "writing the marker file"

    def test_keeps_only_the_trailing_window(self) -> None:
        tail = DeltaTail()
        tail = fold_delta(tail, "x" * 200, width=DELTA_TAIL_CHARS)
        assert len(tail.text) == DELTA_TAIL_CHARS

    def test_trailing_window_is_the_most_recent_characters(self) -> None:
        tail = DeltaTail()
        tail = fold_delta(tail, "a" * 50, width=10)
        tail = fold_delta(tail, "b" * 5, width=10)
        assert tail.text == "aaaaabbbbb"

    def test_does_not_mutate_input(self) -> None:
        original = DeltaTail(text="hi", pending_chars=2)
        fold_delta(original, "there")
        assert original.text == "hi"
        assert original.pending_chars == 2

    def test_accumulates_pending_chars(self) -> None:
        tail = fold_delta(DeltaTail(), "abc")
        tail = fold_delta(tail, "de")
        assert tail.pending_chars == 5

    def test_sanitizes_each_chunk(self) -> None:
        tail = fold_delta(DeltaTail(), "line one\nline two")
        assert "\n" not in tail.text


class TestDeltaTailImmutable:
    def test_frozen(self) -> None:
        tail = DeltaTail()
        with pytest.raises(AttributeError):
            tail.text = "x"  # type: ignore[misc]


class TestShouldRepaintDelta:
    def test_below_threshold_is_false(self) -> None:
        tail = DeltaTail(pending_chars=DELTA_REPAINT_THRESHOLD - 1)
        assert should_repaint_delta(tail) is False

    def test_at_threshold_is_true(self) -> None:
        tail = DeltaTail(pending_chars=DELTA_REPAINT_THRESHOLD)
        assert should_repaint_delta(tail) is True

    def test_custom_threshold(self) -> None:
        tail = DeltaTail(pending_chars=5)
        assert should_repaint_delta(tail, threshold=5) is True
        assert should_repaint_delta(tail, threshold=6) is False


class TestMarkDeltaRendered:
    def test_resets_pending_chars_but_keeps_text(self) -> None:
        tail = DeltaTail(text="hello", pending_chars=99)
        rendered = mark_delta_rendered(tail)
        assert rendered.text == "hello"
        assert rendered.pending_chars == 0


class TestDeltaStatusMessage:
    def test_composes_generating_prefix_with_tail(self) -> None:
        msg = delta_status_message(DeltaTail(text="writing the marker file"))
        assert msg == "generating… writing the marker file"

    def test_empty_tail_has_bare_prefix(self) -> None:
        assert delta_status_message(DeltaTail()) == "generating…"


class TestRepaintThrottleBound:
    """Invariant (d): never a per-token full-screen repaint — a spy render
    counter under M deltas of K chars repaints a bounded number of times."""

    @pytest.mark.parametrize(
        "chunks, chunk_size",
        [
            (200, 1),  # many tiny chunks (per-character streaming)
            (40, 5),  # small word-sized chunks
            (10, 100),  # a few large chunks (each alone can cross the threshold)
        ],
    )
    def test_repaint_count_is_bounded(self, chunks: int, chunk_size: int) -> None:
        tail = DeltaTail()
        repaints = 0
        for _ in range(chunks):
            tail = fold_delta(tail, "x" * chunk_size)
            if should_repaint_delta(tail):
                repaints += 1
                tail = mark_delta_rendered(tail)
        total_chars = chunks * chunk_size
        bound = math.ceil(total_chars / DELTA_REPAINT_THRESHOLD) + 2
        assert repaints <= bound
        if total_chars >= DELTA_REPAINT_THRESHOLD:
            assert repaints >= 1  # real accumulation really does trigger a repaint

    def test_never_repaints_below_threshold(self) -> None:
        tail = DeltaTail()
        for _ in range(DELTA_REPAINT_THRESHOLD - 1):
            tail = fold_delta(tail, "x")
            assert should_repaint_delta(tail) is False


# ---------------------------------------------------------------------------
# CockpitProgressSink.on_delta — the standalone `work --tui` cockpit
# ---------------------------------------------------------------------------


class TestCockpitProgressSinkOnDelta:
    def test_wants_delta_stream_is_true(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=io.StringIO())
        assert sink.wants_delta_stream is True

    def test_no_repaint_before_threshold(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=io.StringIO())
        base = sink._state.status
        sink.on_delta("short")
        assert sink._state.status == base  # unchanged — no repaint yet

    def test_repaints_generating_tail_once_threshold_crossed(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=io.StringIO())
        sink.on_delta("x" * (DELTA_REPAINT_THRESHOLD + 5))
        assert sink._state.status.message.startswith("generating…")
        assert "x" in sink._state.status.message

    def test_on_delta_never_advances_step_count_or_conversation(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=io.StringIO())
        sink(0, "read_file", "a.py", True)  # one real step
        before_steps = sink._state.work_item.step_count
        before_conv = sink._state.conversation
        sink.on_delta("y" * 500)
        assert sink._state.work_item.step_count == before_steps
        assert sink._state.conversation == before_conv

    def test_tail_clears_after_next_real_step(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=io.StringIO())
        sink.on_delta("x" * (DELTA_REPAINT_THRESHOLD + 1))
        assert "generating" in sink._state.status.message
        sink(0, "read_file", "a.py", True)
        msg = sink._state.status.message
        assert "generating" not in msg
        assert "step 1" in msg  # work_item.step_count after ONE real step

    def test_tail_clears_after_next_phase_notice(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=io.StringIO())
        sink.on_delta("x" * (DELTA_REPAINT_THRESHOLD + 1))
        assert "generating" in sink._state.status.message
        sink(0, "", "thinking…", True)
        assert sink._state.status.message == "thinking…"

    def test_fresh_completion_starts_a_fresh_tail(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=io.StringIO())
        sink.on_delta("Q" * (DELTA_REPAINT_THRESHOLD + 1))
        assert "QQQQ" in sink._state.status.message
        sink(0, "write_file", "x.py", True)  # ends the first turn
        sink.on_delta("Z" * (DELTA_REPAINT_THRESHOLD + 1))
        msg = sink._state.status.message
        assert "QQQQ" not in msg  # the old turn's text is gone
        assert "ZZZZ" in msg


# ---------------------------------------------------------------------------
# _WorkSink.on_delta — the interactive session's own sink
# ---------------------------------------------------------------------------


def _session_like(view: str) -> SimpleNamespace:
    state = CockpitState(work_item=WorkItem(task_id="t", engine="mock", step_count=0, running=True))
    # `emit` is a no-op stub — the real `_Session.emit()` redraws a frame, but
    # `_WorkSink` only needs SOMETHING callable there when `view == "ansi"`
    # (mirrors how a bare holder in the existing `_poll_talk_lane`/
    # `_maybe_proactive_update`/`_update_active_run` tests never needs those
    # either, since `_WorkSink` reaches them via `getattr(..., None)`).
    return SimpleNamespace(state=state, view=view, emit=lambda: None)


class TestWorkSinkOnDelta:
    def test_wants_delta_stream_true_on_every_session_view_tier(self) -> None:
        """Task t4 (ssv, c19/h16): a session cortex turn arms ``on_delta``
        regardless of its render tier — the seam's SECOND job (flipping the
        engine onto its per-chunk-read, timeout-resetting streamed path,
        ``colleague/engines/vllm_openai.py``'s ``_make_complete``) matters
        just as much off the dynamic ANSI tier as on it. The VISIBLE redraw
        stays ANSI-only inside ``on_delta``/``__call__`` (unchanged) — this
        property only decides whether the seam is armed at all."""
        assert _WorkSink(_session_like("ansi")).wants_delta_stream is True
        assert _WorkSink(_session_like("markdown")).wants_delta_stream is True

    def test_wants_delta_stream_false_for_a_bare_holder(self) -> None:
        """A holder with no ``view`` attribute at all degrades to False — never
        armed by accident (the documented ``_WorkSink`` contract, matching the
        existing ``getattr`` guards for ``_poll_talk_lane``/``_maybe_proactive_update``)."""
        holder = SimpleNamespace(state=CockpitState())
        assert _WorkSink(holder).wants_delta_stream is False

    def test_on_delta_folds_into_status_on_ansi_tier(self) -> None:
        sess = _session_like("ansi")
        sink = _WorkSink(sess)
        sink.on_delta("z" * (DELTA_REPAINT_THRESHOLD + 1))
        assert "generating" in sess.state.status.message

    def test_on_delta_never_advances_step_count_or_conversation(self) -> None:
        sess = _session_like("ansi")
        sink = _WorkSink(sess)
        sink(0, "read_file", "a.py", True)
        before_steps = sess.state.work_item.step_count
        before_conv = sess.state.conversation
        sink.on_delta("q" * 500)
        assert sess.state.work_item.step_count == before_steps
        assert sess.state.conversation == before_conv

    def test_tail_clears_after_next_real_step(self) -> None:
        sess = _session_like("ansi")
        sink = _WorkSink(sess)
        sink.on_delta("x" * (DELTA_REPAINT_THRESHOLD + 1))
        assert "generating" in sess.state.status.message
        sink(0, "read_file", "a.py", True)
        msg = sess.state.status.message
        assert "generating" not in msg
        assert "step 1" in msg or "[read_file] a.py" in msg


# ---------------------------------------------------------------------------
# Arming site: execute_work sets config.on_delta on the two live paths ONLY
# ---------------------------------------------------------------------------


class TestExecuteWorkArmsOnDelta:
    """The CLI arming site's contract, asked through ``pre_armed_sink`` (#483).

    Since #483 the LOOP also composes ``config.on_delta`` — it chains the
    in-flight delta heartbeat onto whatever the work path armed
    (``colleague/loop_deltaheartbeat.py``) — so after a run a bare
    ``config.on_delta is None`` no longer answers "did execute_work arm a
    display sink?". :func:`~colleague.loop_deltaheartbeat.pre_armed_sink`
    unwraps that chain and answers exactly the question these tests have always
    asked; the contract itself is unchanged — the two live paths arm a sink,
    nothing else does, and the loop's wrapper never invents one.
    """

    def test_explicit_tui_arms_it(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        repo = _git_repo(tmp_path)
        config = EngineConfig.resolve()
        assert pre_armed_sink(config.on_delta) is None
        task = Task.new(str(repo), "do a small thing")
        execute_work(
            repo=repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            display=DisplayOptions(tui=True),
        )
        assert pre_armed_sink(config.on_delta) is not None

    def test_no_tui_never_arms_it(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        repo = _git_repo(tmp_path)
        config = EngineConfig.resolve()
        task = Task.new(str(repo), "do a small thing")
        execute_work(
            repo=repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            display=DisplayOptions(tui=False),
        )
        assert pre_armed_sink(config.on_delta) is None

    def test_plain_work_off_tty_never_arms_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The default `colleague work` invocation (no --tui flag) in the
        non-interactive context every test runs in (captured, non-TTY stderr)."""
        repo = _git_repo(tmp_path)
        config = EngineConfig.resolve()
        task = Task.new(str(repo), "do a small thing")
        execute_work(
            repo=repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            display=DisplayOptions(tui=None),
        )
        assert pre_armed_sink(config.on_delta) is None

    def test_tui_events_alone_never_arms_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _git_repo(tmp_path)
        config = EngineConfig.resolve()
        task = Task.new(str(repo), "do a small thing")
        execute_work(
            repo=repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            display=DisplayOptions(tui=False, tui_events=str(tmp_path / "ev.jsonl")),
        )
        assert pre_armed_sink(config.on_delta) is None

    def test_session_ansi_sink_arms_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _git_repo(tmp_path)
        config = EngineConfig.resolve()
        task = Task.new(str(repo), "do a small thing")
        sink = _WorkSink(_session_like("ansi"))
        execute_work(
            repo=repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            display=DisplayOptions(sink=sink),
        )
        assert pre_armed_sink(config.on_delta) == sink.on_delta

    def test_session_markdown_sink_also_arms_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Task t4 (ssv): a session's Markdown/piped tier now arms on_delta
        too (the per-read timeout reset), superseding the pre-t4 contract —
        only the VISIBLE redraw stays ANSI-gated, inside on_delta itself."""
        repo = _git_repo(tmp_path)
        config = EngineConfig.resolve()
        task = Task.new(str(repo), "do a small thing")
        sink = _WorkSink(_session_like("markdown"))
        execute_work(
            repo=repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            display=DisplayOptions(sink=sink),
        )
        assert pre_armed_sink(config.on_delta) == sink.on_delta

    def test_deltas_never_appear_in_tui_events_stream(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Invariant (b): deltas ride an entirely separate seam from the
        structured `WorkStep` replay stream — arming on_delta must not leak
        anything into `--tui-events`' JSONL (still step-only, byte-identical
        to before this task)."""
        repo = _git_repo(tmp_path)
        events_path = tmp_path / "ev.jsonl"
        config = EngineConfig.resolve()
        task = Task.new(str(repo), "do a small thing")
        execute_work(
            repo=repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            display=DisplayOptions(tui=True, tui_events=str(events_path)),
        )
        events = loads_events(events_path.read_text())
        labels = [e.label for e in events]
        assert labels == ["[write_file] colleague-mock.md", "[finish] mock wrote colleague-mock.md"]


# ---------------------------------------------------------------------------
# End-to-end-ish: the mock engine's REAL synthetic deltas driving the REAL
# armed sink through the REAL execute_work orchestration (requirement 5).
# ---------------------------------------------------------------------------


class TestEndToEndMockDeltasThroughRealSinks:
    def test_work_tui_streams_mock_deltas_through_the_real_cockpit_sink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _git_repo(tmp_path)
        calls: list[str] = []
        original_on_delta = _tui_sink.CockpitProgressSink.on_delta

        def _spy(self: CockpitProgressSink, chunk: str) -> None:
            calls.append(chunk)
            original_on_delta(self, chunk)

        monkeypatch.setattr(_tui_sink.CockpitProgressSink, "on_delta", _spy)

        config = EngineConfig.resolve()
        task = Task.new(str(repo), "do a small thing")
        result, _artifact = execute_work(
            repo=repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            display=DisplayOptions(tui=True),
        )
        assert calls  # deltas really flowed end to end through the real sink
        assert "".join(calls) == "writing the marker filedone"
        assert result.status == "ok"
        # Streaming never changed the TaskResult (mirrors test_delta_seam.py's
        # own "armed run == unarmed run" invariant, at the cockpit-sink layer).
        assert result.stats.step_count == 2

    def test_session_ansi_tier_streams_mock_deltas_through_the_real_worksink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _git_repo(tmp_path)
        calls: list[str] = []
        original_on_delta = session_mod._WorkSink.on_delta

        def _spy(self: _WorkSink, chunk: str) -> None:
            calls.append(chunk)
            original_on_delta(self, chunk)

        monkeypatch.setattr(session_mod._WorkSink, "on_delta", _spy)

        rc = run_session(
            _make_args(repo),
            input_fn=_scripted(["do a small thing", "q"]),
            out=_CollectingOut(),
            _color=True,
        )
        assert rc == 0
        assert calls
        assert "".join(calls) == "writing the marker filedone"

    def test_session_markdown_tier_now_arms_deltas_but_never_redraws_them(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Task t4 (ssv): the Markdown/piped session tier ARMS on_delta now
        (the engine really does take the streamed, timeout-resetting path —
        superseding the old "never streams" contract), but the seam is still
        display-only there: the frame nobody redraws mid-run stays byte-
        identical, proven below by diffing against the pre-t4 (never-armed)
        output for the SAME scripted instruction run against a FRESH,
        otherwise-identical repo (a repo run twice would itself diverge —
        the second run sees an already-graded feedback record, an extra
        commit, etc. — so the control needs its own clean repo, not a
        replay of the first one — same basename both times, since the
        rendered frame's repo line names the directory — AND a fixed task id
        monkeypatched onto ``uuid.uuid4``, since the rendered branch name
        embeds it too)."""
        import uuid as _uuid_mod

        fixed_id = _uuid_mod.UUID("12345678-1234-5678-1234-567812345678")
        monkeypatch.setattr(_uuid_mod, "uuid4", lambda: fixed_id)

        repo = _git_repo(tmp_path / "armed" / "repo")
        calls: list[str] = []
        original_on_delta = session_mod._WorkSink.on_delta

        def _spy(self: _WorkSink, chunk: str) -> None:
            calls.append(chunk)
            original_on_delta(self, chunk)

        monkeypatch.setattr(session_mod._WorkSink, "on_delta", _spy)

        out = _CollectingOut()
        rc = run_session(
            _make_args(repo),
            input_fn=_scripted(["do a small thing", "q"]),
            out=out,
            _color=False,
        )
        assert rc == 0
        # The seam really did arm and stream (the new behavior) ...
        assert calls  # sanity: the seam really armed
        assert "".join(calls) == "writing the marker filedone"
        # ... yet the Markdown tier's own output is untouched: re-run the
        # IDENTICAL scripted session with wants_delta_stream forced back to
        # its pre-t4 value (False) and diff the two transcripts byte for
        # byte — this is the "bare non-TTY work output unchanged" pin at the
        # session layer.
        baseline_repo = _git_repo(tmp_path / "baseline" / "repo")
        with monkeypatch.context() as m:
            m.setattr(
                session_mod._WorkSink,
                "wants_delta_stream",
                property(lambda self: False),
            )
            baseline_out = _CollectingOut()
            rc_baseline = run_session(
                _make_args(baseline_repo),
                input_fn=_scripted(["do a small thing", "q"]),
                out=baseline_out,
                _color=False,
            )
        assert rc_baseline == 0
        assert out.text() == baseline_out.text()

    def test_session_task_result_identical_streamed_ansi_vs_streamed_markdown(
        self, tmp_path: Path
    ) -> None:
        """Task t4 acceptance (2): extends ``test_delta_seam.py``'s "armed run
        == unarmed run" equivalence invariant to the session layer — now that
        BOTH session tiers arm ``on_delta`` (ansi visibly, markdown only for
        the timeout reset), the resulting ``TaskResult`` must still be
        byte-identical (mod wall-clock fields) between them, and identical to
        a bare (non-session) ``execute_work`` call over the SAME instruction —
        streaming stays a display/transport-only concern end to end."""
        from colleague.contract import TaskResult

        def _normalized(data: dict) -> dict:
            data = json.loads(json.dumps(data))  # deep copy via round-trip
            data["stats"]["started_at"] = ""
            data["stats"]["duration_seconds"] = 0.0
            # Path/id-derived fields legitimately differ: each capture dispatches
            # to its OWN repo (a fresh task id + artifact path + branch name),
            # not the SAME work item run twice.
            data["task_id"] = ""
            data["artifacts_path"] = ""
            data["branch"] = ""
            # tip_sha (t5, self-learning arc) hashes the per-run commit —
            # volatile for exactly the same reason as branch above.
            data.pop("tip_sha", None)
            return data

        def _capture(view: str) -> TaskResult:
            repo = _git_repo(tmp_path / view)
            captured: list[TaskResult] = []

            def _capturing_work(
                *,
                repo: Path,
                engine_name: str,
                task: Task,
                open_pr: bool,
                base: str,
                config: EngineConfig,
                allow_dirty: bool = False,
                command_name: str | None = None,
                tui: bool | None = None,
                tui_events: str | None = None,
                display: object = None,
                mode: str | None = None,
            ) -> tuple[TaskResult, Path]:
                result, art_path = execute_work(
                    repo=repo,
                    engine_name=engine_name,
                    task=task,
                    open_pr=open_pr,
                    base=base,
                    config=config,
                    allow_dirty=allow_dirty,
                    command_name=command_name,
                    display=display or DisplayOptions(tui=tui, tui_events=tui_events),
                    mode=mode,
                )
                captured.append(result)
                return result, art_path

            rc = run_session(
                _make_args(repo),
                input_fn=_scripted(["do a small thing", "q"]),
                out=_CollectingOut(),
                _work_fn=_capturing_work,
                _color=(view == "ansi"),
            )
            assert rc == 0
            assert len(captured) == 1
            return captured[0]

        ansi_result = _capture("ansi")
        markdown_result = _capture("markdown")

        assert _normalized(ansi_result.to_dict()) == _normalized(markdown_result.to_dict())
        assert ansi_result.stats.step_count == markdown_result.stats.step_count
        # Usage travels verbatim from the mock engine either way — never
        # estimated, never affected by which tier armed the seam.
        assert ansi_result.usage.prompt_tokens == markdown_result.usage.prompt_tokens
        assert ansi_result.usage.completion_tokens == markdown_result.usage.completion_tokens


# ---------------------------------------------------------------------------
# Module boundary: cockpit_run.py stays pure (mirrors TestModuleBoundary in
# tests/test_cockpit_run.py — no agentfront import, no I/O-ish stdlib).
# ---------------------------------------------------------------------------


def test_cockpit_run_still_has_no_agentfront_import() -> None:
    import inspect

    import colleague.cockpit_run as mod

    source = inspect.getsource(mod)
    assert "import agentfront" not in source
    assert "from agentfront" not in source


class TestSanitizeEscapeFamilies:
    """Non-CSI escape families must never reach the terminal (Qodo 3560546638)."""

    def test_osc_clipboard_write_is_stripped(self) -> None:
        from colleague.cockpit_run import sanitize_delta_chunk

        assert sanitize_delta_chunk("\x1b]52;c;aGVsbG8=\x07steal") == "steal"

    def test_osc_title_with_st_terminator_is_stripped(self) -> None:
        from colleague.cockpit_run import sanitize_delta_chunk

        assert sanitize_delta_chunk("\x1b]0;evil title\x1b\\ok") == "ok"

    def test_dangling_unterminated_osc_leaves_no_escape_byte(self) -> None:
        # A sequence split across two delta chunks leaves a dangling ESC] with
        # no terminator — nothing control-ish may survive.
        from colleague.cockpit_run import sanitize_delta_chunk

        out = sanitize_delta_chunk("before\x1b]52;c;aGVs")
        assert "\x1b" not in out and out.startswith("before")

    def test_single_char_fe_escape_and_8bit_csi_are_stripped(self) -> None:
        from colleague.cockpit_run import sanitize_delta_chunk

        assert sanitize_delta_chunk("a\x1bMb") == "ab"
        assert sanitize_delta_chunk("a\x9b31mb") == "ab"

    def test_residual_c0_controls_are_dropped(self) -> None:
        from colleague.cockpit_run import sanitize_delta_chunk

        assert sanitize_delta_chunk("a\x07b\x00c\x1bd") == "abcd"


class TestArmDeltaStreamReset:
    """A reused EngineConfig never carries a stale sink (Qodo 3560546632)."""

    def test_second_run_without_sink_clears_previous_arming(self) -> None:
        from colleague.cli._commands.work import _arm_delta_stream
        from colleague.config import EngineConfig

        class _Sink:
            wants_delta_stream = True

            def on_delta(self, text: str) -> None:  # pragma: no cover - spy
                pass

        config = EngineConfig(base_url="http://x", api_key="k", model="m")
        sink = _Sink()
        _arm_delta_stream(config, sink)
        assert config.on_delta is not None
        _arm_delta_stream(config, None)
        assert config.on_delta is None

    def test_second_run_with_declining_sink_clears_previous_arming(self) -> None:
        from colleague.cli._commands.work import _arm_delta_stream
        from colleague.config import EngineConfig

        class _Wants:
            wants_delta_stream = True

            def on_delta(self, text: str) -> None:  # pragma: no cover - spy
                pass

        class _Declines:
            wants_delta_stream = False

            def on_delta(self, text: str) -> None:  # pragma: no cover - spy
                pass

        config = EngineConfig(base_url="http://x", api_key="k", model="m")
        _arm_delta_stream(config, _Wants())
        _arm_delta_stream(config, _Declines())
        assert config.on_delta is None
