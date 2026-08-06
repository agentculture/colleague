"""Cortex narration — senses-authored higher-self lines at boundaries (ssv t6,
covers c12/c14/c23/h9/h11/h19).

The narration lane: cortex's live streamed output is captured (buffered, never
completed on — c23) in the ``on_delta`` callback, windowed, and handed to the
senses boundary beat as ``BoundaryContext.delta_tail``; senses may then author
a ``narrate`` move describing IN ITS OWN WORDS what cortex is doing (h9), and
the engine renders it verbatim-labeled ``<<higher self thought>>`` through the
SAME feed-line surface presence lines use (c12).

The HARD boundary (c14/h11): narration is user-display ONLY. It never enters
any model's context (not senses' own history, not cortex's), never lands in
the run artifact, and never becomes a chat entry / injection — presentation,
never feedback. Tests here machine-check all of that:

1. narration lines appear at tool-call/phase boundaries ONLY — one senses
   completion per boundary beat, ZERO completions issued between boundaries
   (delta buffering is pure state, c23);
2. h11 — a narrated run's artifact JSON, every model-bound messages array, and
   senses' own loop history/chat contain zero narration lines;
3. windowing — a huge cortex delta stream reaches the beat as a bounded
   excerpt (session-side char cap + loop-side budget windowing);
4. senses unarmed renders byte-identical (h19);
5. the narrate move is display-only in the loop core (no chat entry, no
   injection, record-only without a live excerpt).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from colleague.artifact import artifact_dir
from colleague.artifact import write as write_artifact
from colleague.cli._commands._presence_sink import fold_presence_snapshot
from colleague.cli._commands.session import (
    _NARRATION_DELTA_CHARS,
    SensesSessionOptions,
    SessionIO,
    _Session,
    _WorkSink,
)
from colleague.cockpit_run import DeltaTail, fold_delta
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import (
    OK,
    SENSES_LOOP_POINT_PREFIX,
    ContextPacket,
    SensesRecord,
    TaskResult,
)
from colleague.presence import UpdateCadence
from colleague.presence_engine import PresenceEngine, PresenceIO, build_presence_executor
from colleague.senses_loop import (
    BOUNDARY_CADENCE_TICK,
    NARRATION_LABEL,
    BoundaryContext,
    SensesLoopDriver,
)

_NARRATE_TEXT = "cortex is combing the failing tests and drafting a fix"
_NARRATE_REPLY = json.dumps({"move": "narrate", "text": _NARRATE_TEXT})


# ── fakes (mirroring tests/test_presence_engine.py / test_senses_loop.py) ────
class _FakeResp:
    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning = ""
        self.prompt_tokens = 3
        self.completion_tokens = 5


def _make_complete(replies, *, default=None, prompts=None, calls=None):
    seq = list(replies)
    idx = {"i": 0}
    default = default if default is not None else json.dumps({"move": "wait"})

    def make_complete(config, *, tools):  # noqa: ANN001
        assert tools == [], "senses loop must always issue tools=[] (tools-off)"

        def complete(messages):  # noqa: ANN001
            if prompts is not None:
                prompts.append(messages)
            if calls is not None:
                calls.append(1)
            i = idx["i"]
            idx["i"] += 1
            return _FakeResp(seq[i] if i < len(seq) else default)

        return complete

    return make_complete


class _NarrationIO:
    """Recording PresenceIO with a session-shaped windowed cortex-delta buffer.

    ``feed_delta`` is the on_delta-side capture: PURE folding into a windowed
    tail (the session's ``_fold_cortex_delta`` pattern) — never a completion.
    """

    def __init__(self) -> None:
        self.rendered: "list[str]" = []
        self._tail = DeltaTail()

    def feed_delta(self, chunk: str) -> None:
        self._tail = fold_delta(self._tail, chunk, width=_NARRATION_DELTA_CHARS)

    def excerpt(self) -> str:
        return self._tail.text

    def io(self) -> PresenceIO:
        return PresenceIO(
            render=self.rendered.append,
            feed_tail=lambda: "step 3/40 · editing foo.py",
            task_state=lambda: "step 3/40",
            delta_tail=self.excerpt,
        )


def _config(budget: int = 24000):
    return SimpleNamespace(context_budget_tokens=budget)


def _presence(
    replies=(),
    *,
    default=_NARRATE_REPLY,
    cadence=None,
    senses_config="__armed__",
    prompts=None,
    calls=None,
    history_provider=None,
):
    io = _NarrationIO()
    cfg = _config() if senses_config == "__armed__" else senses_config
    driver = SensesLoopDriver(
        senses_config=cfg,
        make_complete=_make_complete(replies, default=default, prompts=prompts, calls=calls),
        executor=build_presence_executor(io.io()),
    )
    engine = PresenceEngine(
        driver=driver,
        io=io.io(),
        cadence=cadence if cadence is not None else UpdateCadence(every_steps=2, max_updates=8),
        history_provider=history_provider,
    )
    return engine, io


def _narration_lines(rendered) -> "list[str]":
    return [line for line in rendered if line.startswith(f"{NARRATION_LABEL} ")]


# ── 1. boundaries only: completions == beats, zero between (c12/c23) ─────────
def test_narration_renders_at_boundaries_only_and_never_completes_between() -> None:
    calls: list = []
    engine, io = _presence(calls=calls)

    # Cortex streams BETWEEN boundaries: the callback only buffers (c23) —
    # no senses completion may be issued by delta traffic.
    for _ in range(300):
        io.feed_delta("cortex writes a line of code here ")
    assert calls == [], "buffering a cortex delta must never issue a senses completion"
    assert _narration_lines(io.rendered) == []

    # Two tool-call boundaries → two beats → two completions → two narrations.
    engine.on_progress_boundary(step_count=2)
    engine.on_progress_boundary(step_count=4)
    narrations = _narration_lines(io.rendered)
    assert len(narrations) == 2
    assert len(calls) == 2, "exactly one senses completion per boundary beat"

    # More deltas after the boundaries: still zero additional completions.
    for _ in range(100):
        io.feed_delta("more streamed cortex output ")
    assert len(calls) == 2


def test_narration_label_is_verbatim_and_distinct_from_senses_lines() -> None:
    """h9: the operator can always tell narration from senses' own replies —
    the label is the verbatim '<<higher self thought>>', never 'senses:'."""
    engine, io = _presence()
    io.feed_delta("def solve(): ...")
    engine.on_progress_boundary(step_count=2)
    narrations = _narration_lines(io.rendered)
    assert narrations == [f"<<higher self thought>> {_NARRATE_TEXT}"]
    assert not any(line.startswith("senses:") and _NARRATE_TEXT in line for line in io.rendered)


def test_narration_is_senses_authored_from_the_excerpt_not_a_relabel() -> None:
    """h9: the narration text is what the senses completion AUTHORED — the raw
    cortex delta text is never relabeled into a narration line by colleague."""
    engine, io = _presence()
    raw = "RAW-CORTEX-DELTA-TOKENS xyzzy"
    io.feed_delta(raw)
    engine.on_progress_boundary(step_count=2)
    narrations = _narration_lines(io.rendered)
    assert narrations and raw not in narrations[0]
    assert _NARRATE_TEXT in narrations[0]


# ── 2. h11 — zero narration lines anywhere model- or artifact-bound ──────────
def test_h11_narrated_run_artifact_messages_and_history_are_narration_free(
    tmp_path: Path,
) -> None:
    calls: list = []
    prompts: list = []
    history = [{"role": "operator", "text": "build the feature"}]
    engine, io = _presence(calls=calls, prompts=prompts, history_provider=lambda: list(history))

    io.feed_delta("cortex output: refactoring the parser now")
    engine.acknowledge(ContextPacket(original="build the feature"))
    engine.on_progress_boundary(step_count=2)
    engine.on_progress_boundary(step_count=4)
    assert _narration_lines(io.rendered), "the run must actually have narrated (not vacuous)"

    # Every model-bound messages array is narration-free (c14).
    assert prompts, "senses completions were issued"
    for messages in prompts:
        assert NARRATION_LABEL not in json.dumps(messages)
        assert _NARRATE_TEXT not in json.dumps(messages)

    # Senses' own loop history / chat / injections carry no narration line.
    assert history == [{"role": "operator", "text": "build the feature"}]
    snap = engine.snapshot()
    assert NARRATION_LABEL not in json.dumps(snap["chat"])
    assert NARRATION_LABEL not in json.dumps(snap["injections"])
    # The beats are still artifact FACTS (record-only, no text).
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}narrate" for r in snap["records"])

    # The run artifact JSON contains zero narration lines.
    result = TaskResult(task_id="t-narrated", status=OK, summary="did the thing")
    fold_presence_snapshot(result, engine, fold_chat=True)
    path = write_artifact(result, artifact_dir(tmp_path))
    artifact_text = path.read_text()
    assert NARRATION_LABEL not in artifact_text
    assert _NARRATE_TEXT not in artifact_text


# ── 3. windowing — a huge delta stream reaches the beat bounded ──────────────
def test_huge_delta_stream_reaches_the_beat_as_a_bounded_excerpt() -> None:
    engine, io = _presence()
    for _ in range(1000):
        io.feed_delta("x" * 100)  # 100k chars of cortex output
    assert len(io.excerpt()) <= _NARRATION_DELTA_CHARS
    prompts: list = []
    engine2, io2 = _presence(prompts=prompts)
    for _ in range(1000):
        io2.feed_delta("y" * 100)
    engine2.on_progress_boundary(step_count=2)
    sent_user = prompts[0][1]["content"]
    assert len(sent_user) < 10_000  # the beat never sees the raw 100k stream


def test_delta_excerpt_is_windowed_against_senses_own_budget_in_the_loop() -> None:
    """Even a caller that hands a raw huge excerpt is bounded by the senses
    budget windowing in ``_build_prompt`` (spec assumption: a long cortex turn
    never blows senses' context)."""
    prompts: list = []
    driver = SensesLoopDriver(
        senses_config=_config(budget=40),
        make_complete=_make_complete([_NARRATE_REPLY], prompts=prompts),
        executor=build_presence_executor(PresenceIO()),
    )
    huge = "z" * 100_000
    driver.process_boundary(BoundaryContext(kind=BOUNDARY_CADENCE_TICK, delta_tail=huge))
    sent_user = prompts[0][1]["content"]
    assert len(sent_user) < len(huge) / 5


# ── 5. loop-core display-only semantics ──────────────────────────────────────
def test_narrate_turn_is_display_only_no_chat_no_injection_record_kept() -> None:
    driver = SensesLoopDriver(
        senses_config=_config(),
        make_complete=_make_complete([_NARRATE_REPLY]),
        executor=build_presence_executor(PresenceIO()),
    )
    turns = driver.process_boundary(
        BoundaryContext(kind=BOUNDARY_CADENCE_TICK, delta_tail="live cortex output here")
    )
    assert len(turns) == 1
    assert turns[0].narration == _NARRATE_TEXT
    assert turns[0].chat_entry is None and turns[0].injection is None
    assert driver.chat == [] and driver.injections == []
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}narrate" for r in driver.records)


def test_narrate_is_terminal_one_completion_per_boundary() -> None:
    calls: list = []
    driver = SensesLoopDriver(
        senses_config=_config(),
        make_complete=_make_complete([_NARRATE_REPLY] * 5, calls=calls),
        executor=build_presence_executor(PresenceIO()),
        per_boundary_cap=2,
    )
    driver.process_boundary(BoundaryContext(kind=BOUNDARY_CADENCE_TICK, delta_tail="output"))
    assert len(calls) == 1  # narrate concludes the boundary — never a second completion


def test_narrate_without_a_live_excerpt_degrades_to_record_only() -> None:
    """Without a cortex-delta excerpt there is nothing to describe — a narrate
    move renders NOTHING (a narration then would be invention, h9) and leaves
    only the record. This also structurally protects fronts whose render
    surface persists (e.g. the watched run's flight chat) from ever writing a
    narration line into an artifact-bound channel (h11)."""
    rendered: list = []
    driver = SensesLoopDriver(
        senses_config=_config(),
        make_complete=_make_complete([_NARRATE_REPLY]),
        executor=build_presence_executor(PresenceIO(render=rendered.append)),
    )
    turns = driver.process_boundary(BoundaryContext(kind=BOUNDARY_CADENCE_TICK, feed_tail="…"))
    assert turns[0].narration is None
    assert rendered == []
    assert driver.chat == [] and driver.injections == []
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}narrate" for r in driver.records)


# ── 4 + session wiring ───────────────────────────────────────────────────────
class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))


def _senses_session_config() -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _session(tmp_path: Path, *, view: str = "ansi", config: Optional[EngineConfig] = None):
    out, err = _CollectingOut(), _CollectingOut()
    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config if config is not None else _senses_session_config(),
        json_mode=False,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=lambda **kwargs: (TaskResult(task_id="t", status=OK, summary="s"), None),
        senses_options=SensesSessionOptions(),
    )
    return sess, out, err


class _FakeSensesEngine:
    """A fake (senses_config, engine) pair provider for the session's presence
    build — captures every messages array any senses completion receives."""

    def __init__(self, replies, *, default=_NARRATE_REPLY) -> None:
        self.prompts: list = []
        self.calls: list = []
        self.make_complete = _make_complete(
            replies, default=default, prompts=self.prompts, calls=self.calls
        )

    def make_count_tokens(self, senses_config):  # noqa: ANN001
        return None


def test_worksink_on_delta_buffers_for_narration_and_issues_no_completion(
    tmp_path: Path, monkeypatch
) -> None:
    sess, _out, _err = _session(tmp_path)
    engine_loads: list = []
    monkeypatch.setattr(
        _Session, "_senses_engine", lambda self, **kw: engine_loads.append(1) or None
    )
    sink = _WorkSink(sess)
    # Below the repaint threshold AND regardless of tier, every chunk folds
    # into the narration buffer (capture happens before the display throttle).
    sink.on_delta("cortex is ")
    sink.on_delta("writing the fix")
    assert "cortex is writing the fix" in sess._cortex_delta_excerpt()
    assert engine_loads == []  # buffering never resolves/calls a senses engine (c23)
    # A real step boundary resets the cockpit status tail but NOT the narration
    # buffer (the beat at that boundary needs the excerpt that led up to it).
    sink(1, "read_file", "loop.py", True)
    assert "cortex is writing the fix" in sess._cortex_delta_excerpt()


def test_session_windowed_excerpt_is_capped(tmp_path: Path) -> None:
    sess, _out, _err = _session(tmp_path)
    sink = _WorkSink(sess)
    for _ in range(1000):
        sink.on_delta("q" * 100)  # 100k chars streamed
    assert len(sess._cortex_delta_excerpt()) <= _NARRATION_DELTA_CHARS


def test_reset_presence_lane_clears_the_narration_buffer(tmp_path: Path) -> None:
    sess, _out, _err = _session(tmp_path)
    sess._fold_cortex_delta("stale output from the previous work line")
    sess._reset_presence_lane()
    assert sess._cortex_delta_excerpt() == ""


def test_session_presence_engine_threads_excerpt_and_renders_narration(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end through the session's own wiring: _WorkSink.on_delta buffers →
    PresenceIO.delta_tail reads → the boundary beat narrates → the line renders
    into the conversation feed; nothing narration-shaped reaches history or the
    folded artifact (h11)."""
    sess, _out, _err = _session(tmp_path)
    fake = _FakeSensesEngine([_NARRATE_REPLY])
    monkeypatch.setattr(
        _Session,
        "_senses_engine",
        lambda self, **kw: (SimpleNamespace(context_budget_tokens=24000), fake),
    )
    sess._talk_active = True
    sess._talk_task_id = "t-1"
    sess._maybe_build_presence_engine()
    assert sess._presence_engine is not None

    sink = _WorkSink(sess)
    sink.on_delta("cortex output: now rewriting the loop body")
    sess._talk_senses("what is happening in there?")

    conversation = [line.text for line in sess.state.conversation]
    narrations = [ln for ln in conversation if ln.startswith(f"{NARRATION_LABEL} ")]
    assert narrations == [f"{NARRATION_LABEL} {_NARRATE_TEXT}"]
    # The excerpt WAS threaded into the beat's prompt (model-bound INPUT is
    # allowed; it is narration OUTPUT that must never be) ...
    assert any("now rewriting the loop body" in json.dumps(m) for m in fake.prompts)
    # ... and no model-bound messages array carries a narration line (c14).
    for messages in fake.prompts:
        assert NARRATION_LABEL not in json.dumps(messages)
    # Session history is narration-free (senses' own rolling context, h11).
    assert NARRATION_LABEL not in json.dumps(sess._history)

    # The folded artifact is narration-free while the narration DID render.
    monkeypatch.setattr(
        "colleague.cli._commands.session.run_senses_speakback",
        lambda s, c, e, **k: (None, SensesRecord(point="senses-speakback")),
    )
    result = TaskResult(task_id="t-artifact", status=OK, summary="done")
    sess._finalize_split_run(result, None)
    assert NARRATION_LABEL not in json.dumps(result.to_dict())
    written = list(artifact_dir(tmp_path).glob("*.json"))
    assert written and all(NARRATION_LABEL not in p.read_text() for p in written)


def test_unarmed_session_is_byte_identical_with_the_narration_seam_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    """h19: senses unarmed → the narration seam adds NOTHING. The same sink
    traffic with the capture monkeypatched away produces identical output and
    identical cockpit state."""

    def drive(sess) -> None:
        sink = _WorkSink(sess)
        sink.on_delta("streamed cortex text " * 20)
        sink(1, "read_file", "a.py", True)
        sink.on_delta("more text " * 30)
        sink(2, "edit_file", "a.py", True)

    unarmed = EngineConfig.resolve(model="cortex-model")  # no senses
    sess_a, out_a, err_a = _session(tmp_path, view="markdown", config=unarmed)
    assert sess_a._presence_engine is None
    drive(sess_a)

    unarmed_b = EngineConfig.resolve(model="cortex-model")
    sess_b, out_b, err_b = _session(tmp_path, view="markdown", config=unarmed_b)
    monkeypatch.setattr(_Session, "_fold_cortex_delta", lambda self, chunk: None)
    drive(sess_b)

    assert out_a.lines == out_b.lines
    assert err_a.lines == err_b.lines
    assert sess_a.state == sess_b.state
    assert not any(line.text.startswith(NARRATION_LABEL) for line in sess_a.state.conversation)
