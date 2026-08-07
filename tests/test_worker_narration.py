"""Worker narration — subconscious lines in three-tier mode (ssv t7, covers
c13/h10).

Three-tier mode is worker acts / senses relays / cortex configures. The relay
lane that carries worker activity to senses is the SAME t6 narration lane —
``EngineConfig.on_delta`` → ``_WorkSink.on_delta`` → ``_fold_cortex_delta`` →
``PresenceIO.delta_tail`` → ``BoundaryContext.delta_tail`` → the boundary
beat's ``narrate`` move → ``LoopTurn.narration`` → the render-time label seam
in :meth:`colleague.presence_engine.PresenceEngine._render_turn`. In
three-tier mode the acting dial IS the worker (the config-level seat swap),
so the streamed excerpt the beat narrates from is the worker's live output —
no new lane exists or is needed.

This arc changes exactly ONE thing: the render-time label. A three-tier
engine labels a narrate move ``<subconscious thought/actions>`` instead of
the legacy ``<<higher self thought>>``. Everything else carries over verbatim
from t6 (c14/h11, re-pinned here):

1. the label is chosen at RENDER time only — neither label ever enters any
   model-bound prompt;
2. narration is never absorbed into history / chat / injections / the run
   artifact (h11 carry-over, parametrized over both tiers);
3. ``three_tier`` unconfigured renders the t6 higher-self label byte-for-byte
   and the subconscious label never appears anywhere (golden control);
4. the authority boundary holds — a narrate move can never dispatch or guide
   (terminal + display-only), so the label selection is presentation, never a
   routing or authority change.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.artifact import artifact_dir
from colleague.artifact import write as write_artifact
from colleague.cli._commands._presence_sink import fold_presence_snapshot
from colleague.cli._commands.session import _Session, _WorkSink
from colleague.contract import OK, SENSES_LOOP_POINT_PREFIX, ContextPacket, SensesRecord, TaskResult
from colleague.presence import UpdateCadence
from colleague.presence_engine import PresenceEngine, PresenceIO, build_presence_executor
from colleague.senses_loop import (
    _TERMINAL_MOVES,
    NARRATION_LABEL,
    WORKER_NARRATION_LABEL,
    SensesLoopDriver,
)
from colleague.senses_moves import MOVE_NARRATE, build_moves_instruction
from tests.test_cortex_narration import (
    _NARRATE_REPLY,
    _NARRATE_TEXT,
    _config,
    _FakeSensesEngine,
    _make_complete,
    _NarrationIO,
    _senses_session_config,
    _session,
)


def _labeled(rendered, label: str) -> "list[str]":
    return [line for line in rendered if line.startswith(f"{label} ")]


def _presence(
    replies=(),
    *,
    three_tier=None,
    default=_NARRATE_REPLY,
    prompts=None,
    calls=None,
    history_provider=None,
):
    """The t6 engine builder plus a three-tier knob.

    ``three_tier=None`` OMITS the kwarg entirely — the pre-t7 construction
    shape, pinning that an untouched caller stays byte-identical.
    """
    io = _NarrationIO()
    driver = SensesLoopDriver(
        senses_config=_config(),
        make_complete=_make_complete(replies, default=default, prompts=prompts, calls=calls),
        executor=build_presence_executor(io.io()),
    )
    kwargs = {} if three_tier is None else {"three_tier": three_tier}
    engine = PresenceEngine(
        driver=driver,
        io=io.io(),
        cadence=UpdateCadence(every_steps=2, max_updates=8),
        history_provider=history_provider,
        **kwargs,
    )
    return engine, io


# ── 1. three-tier: the subconscious label, verbatim, chosen over higher-self ──
def test_worker_narration_label_is_the_verbatim_subconscious_literal() -> None:
    assert WORKER_NARRATION_LABEL == "<subconscious thought/actions>"
    assert WORKER_NARRATION_LABEL != NARRATION_LABEL


def test_three_tier_worker_steps_render_subconscious_lines() -> None:
    engine, io = _presence(three_tier=True)
    io.feed_delta("worker output: editing the parser now")
    engine.on_progress_boundary(step_count=2)
    engine.on_progress_boundary(step_count=4)
    narrations = _labeled(io.rendered, WORKER_NARRATION_LABEL)
    assert narrations == [f"<subconscious thought/actions> {_NARRATE_TEXT}"] * 2
    # The higher-self label is NOT chosen in three-tier mode.
    assert _labeled(io.rendered, NARRATION_LABEL) == []
    # Still unmistakable from senses' own conversational lines (h9 carry-over).
    assert not any(line.startswith("senses:") and _NARRATE_TEXT in line for line in io.rendered)


# ── 2. unconfigured: the t6 higher-self golden, subconscious never appears ────
def test_unconfigured_engine_renders_higher_self_golden_byte_identical() -> None:
    def drive(engine, io):
        io.feed_delta("cortex output: refactoring the reader")
        engine.on_progress_boundary(step_count=2)
        engine.on_progress_boundary(step_count=4)

    # The pre-t7 construction shape (no three_tier kwarg at all) ...
    engine_a, io_a = _presence()
    drive(engine_a, io_a)
    # ... and an explicit three_tier=False render byte-identically,
    engine_b, io_b = _presence(three_tier=False)
    drive(engine_b, io_b)
    assert io_a.rendered == io_b.rendered
    # ... exactly the t6 golden — label verbatim, one line per boundary,
    assert (
        _labeled(io_a.rendered, NARRATION_LABEL) == [f"<<higher self thought>> {_NARRATE_TEXT}"] * 2
    )
    # ... and the subconscious label never appears anywhere.
    assert not any(WORKER_NARRATION_LABEL in line for line in io_a.rendered)


# ── 3. h11 carry-over: neither label anywhere model- or artifact-bound ────────
@pytest.mark.parametrize("three_tier", [True, False], ids=["three-tier", "legacy"])
def test_h11_narrated_run_is_narration_free_in_prompts_and_artifact(
    tmp_path: Path, three_tier: bool
) -> None:
    prompts: list = []
    history = [{"role": "operator", "text": "build the feature"}]
    engine, io = _presence(
        three_tier=three_tier, prompts=prompts, history_provider=lambda: list(history)
    )
    io.feed_delta("acting-seat output: rewriting the loop body")
    engine.acknowledge(ContextPacket(original="build the feature"))
    engine.on_progress_boundary(step_count=2)
    engine.on_progress_boundary(step_count=4)
    expected_label = WORKER_NARRATION_LABEL if three_tier else NARRATION_LABEL
    assert _labeled(io.rendered, expected_label), "the run must actually have narrated"

    # Every model-bound messages array is free of BOTH labels (c14/h11).
    assert prompts, "senses completions were issued"
    for messages in prompts:
        blob = json.dumps(messages)
        assert NARRATION_LABEL not in blob
        assert WORKER_NARRATION_LABEL not in blob
        assert _NARRATE_TEXT not in blob

    # Senses' own history / chat / injections carry no narration line.
    assert history == [{"role": "operator", "text": "build the feature"}]
    snap = engine.snapshot()
    for key in ("chat", "injections"):
        blob = json.dumps(snap[key])
        assert NARRATION_LABEL not in blob
        assert WORKER_NARRATION_LABEL not in blob
    # The beats stay artifact FACTS (text-free records).
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}narrate" for r in snap["records"])

    # The run artifact JSON contains zero narration lines under either label.
    result = TaskResult(task_id=f"t-narrated-{three_tier}", status=OK, summary="did the thing")
    fold_presence_snapshot(result, engine, fold_chat=True)
    artifact_text = write_artifact(result, artifact_dir(tmp_path)).read_text()
    assert NARRATION_LABEL not in artifact_text
    assert WORKER_NARRATION_LABEL not in artifact_text
    assert _NARRATE_TEXT not in artifact_text


def test_neither_label_literal_is_in_the_moves_instruction() -> None:
    """The prompt-side vocabulary (fed to every senses completion) spells
    NEITHER rendered label — both stay display-only (h11)."""
    instruction = build_moves_instruction()
    assert NARRATION_LABEL not in instruction
    assert WORKER_NARRATION_LABEL not in instruction


# ── 4. authority boundary: narrate can never dispatch or guide ────────────────
def test_narrate_stays_terminal_and_cannot_dispatch_or_guide_in_three_tier() -> None:
    dispatched: list = []
    guided: list = []
    calls: list = []
    prompts: list = []
    rendered: list = []
    tail = {"text": "worker output: running the tests"}
    io = PresenceIO(
        render=rendered.append,
        dispatch_to_cortex=dispatched.append,
        append_guidance=guided.append,
        feed_tail=lambda: "step 3/40 · editing foo.py",
        task_state=lambda: "step 3/40",
        delta_tail=lambda: tail["text"],
    )
    driver = SensesLoopDriver(
        senses_config=_config(),
        make_complete=_make_complete((), default=_NARRATE_REPLY, prompts=prompts, calls=calls),
        executor=build_presence_executor(io),
        per_boundary_cap=2,
    )
    engine = PresenceEngine(
        driver=driver,
        io=io,
        cadence=UpdateCadence(every_steps=2, max_updates=8),
        three_tier=True,
    )
    turns = engine.on_progress_boundary(step_count=2)

    # The narration rendered under the worker label ...
    assert _labeled(rendered, WORKER_NARRATION_LABEL) == [
        f"{WORKER_NARRATION_LABEL} {_NARRATE_TEXT}"
    ]
    # ... but NOTHING routing- or authority-shaped happened: no dispatch, no
    # guidance injection, no chat entry, no injection dict on the turn.
    assert dispatched == []
    assert guided == []
    assert len(turns) == 1
    assert turns[0].move == MOVE_NARRATE
    assert turns[0].chat_entry is None
    assert turns[0].injection is None
    assert driver.injections == []
    assert driver.chat == []
    # Narrate concludes the boundary — terminal, exactly one completion, so a
    # narrate turn can never chain into a dispatch/guide on the same boundary.
    assert MOVE_NARRATE in _TERMINAL_MOVES
    assert len(calls) == 1
    # And the worker label never reached the model-bound prompt (h11).
    for messages in prompts:
        assert WORKER_NARRATION_LABEL not in json.dumps(messages)


# ── session wiring: the mocked three-tier session end to end ─────────────────
def _narrated_session(tmp_path: Path, monkeypatch, *, three_tier: bool):
    """Drive the session's own wiring (t6's e2e shape) at the given tier."""
    config = _senses_session_config()
    if three_tier:
        config.three_tier = True
    sess, out, err = _session(tmp_path, config=config)
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
    sink.on_delta("acting-seat output: now rewriting the loop body")
    sess._talk_senses("what is happening in there?")
    return sess, fake


def test_three_tier_session_worker_steps_yield_subconscious_lines(
    tmp_path: Path, monkeypatch
) -> None:
    """AC1: in a mocked three-tier session, worker activity renders as
    '<subconscious thought/actions>' senses-described lines — and the h11
    discipline carries over verbatim (prompts / history / artifact clean)."""
    sess, fake = _narrated_session(tmp_path, monkeypatch, three_tier=True)

    conversation = [line.text for line in sess.state.conversation]
    assert _labeled(conversation, WORKER_NARRATION_LABEL) == [
        f"<subconscious thought/actions> {_NARRATE_TEXT}"
    ]
    assert _labeled(conversation, NARRATION_LABEL) == []
    # The excerpt WAS threaded into the beat's prompt (model-bound INPUT is
    # allowed; it is narration OUTPUT that must never be) ...
    assert any("now rewriting the loop body" in json.dumps(m) for m in fake.prompts)
    # ... while no model-bound messages array carries either label (c14/h11).
    for messages in fake.prompts:
        blob = json.dumps(messages)
        assert NARRATION_LABEL not in blob
        assert WORKER_NARRATION_LABEL not in blob
    assert WORKER_NARRATION_LABEL not in json.dumps(sess._history)

    # The folded artifact is free of both labels while the narration DID render.
    monkeypatch.setattr(
        "colleague.cli._commands.session.run_senses_speakback",
        lambda s, c, e, **k: (None, SensesRecord(point="senses-speakback")),
    )
    result = TaskResult(task_id="t-artifact-3t", status=OK, summary="done")
    sess._finalize_split_run(result, None)
    blob = json.dumps(result.to_dict())
    assert NARRATION_LABEL not in blob
    assert WORKER_NARRATION_LABEL not in blob
    written = list(artifact_dir(tmp_path).glob("*.json"))
    assert written
    for path in written:
        text = path.read_text()
        assert NARRATION_LABEL not in text
        assert WORKER_NARRATION_LABEL not in text


def test_unconfigured_session_renders_higher_self_and_never_subconscious(
    tmp_path: Path, monkeypatch
) -> None:
    """AC1 control (golden): with ``three_tier`` unconfigured the session
    renders the t6 higher-self label byte-for-byte and the subconscious label
    appears nowhere — conversation, prompts, or history."""
    sess, fake = _narrated_session(tmp_path, monkeypatch, three_tier=False)

    conversation = [line.text for line in sess.state.conversation]
    assert _labeled(conversation, NARRATION_LABEL) == [f"<<higher self thought>> {_NARRATE_TEXT}"]
    assert not any(WORKER_NARRATION_LABEL in line for line in conversation)
    for messages in fake.prompts:
        assert WORKER_NARRATION_LABEL not in json.dumps(messages)
    assert WORKER_NARRATION_LABEL not in json.dumps(sess._history)
