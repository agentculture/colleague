"""``colleague talk <task-id>`` — attach to a running work item's flight plane.

The senses live-presence + voice arc's flight-attach verb (task t6). While
cortex drives a running work item (armed via ``colleague work --watch``), an
operator or agent caller can attach a REPL that holds a *live, tools-off*
conversation with senses — each typed message is answered (labeled
``senses:``), and an instruction can be relayed into the running cortex loop
via the flight guidance channel (echoed as a visible ``-> cortex:`` line so the
relay is never silent). ``--audio FILE`` (or the mid-REPL ``/say FILE``)
transcribes a spoken message via :func:`colleague.voice.transcribe`; a reply is
synthesized to a ``.wav`` beside the flight files when text-to-speech is
configured (``config.voice.tts_model``) — additive only, a failed synthesis
never blocks the text reply.

The REPL core (:func:`run_talk_repl`) is dependency-injected — ``input_fn`` /
``out`` / ``err`` / ``talk_fn`` / ``resolve_engine_seam`` all have test seams,
mirroring :mod:`colleague.cli._commands.session`'s ``run`` — so it is
unit-testable without a live model or a live flight, and t7 (the session's
concurrent lane) can reuse the same turn-processing helper.

Degradation: when senses is unarmed (:func:`colleague.senses.run_senses_talk`
returns ``None``), the REPL degrades to a **watch + raw-guide** mode — one
notice is printed, and every subsequent typed line is relayed directly into
the running loop via :func:`colleague.flight.append_guidance` with the same
``-> cortex:`` echo (no senses answer). The REPL never raises on a bad turn;
the only hard failure is an unsafe/invalid flight task id (a clean
:class:`~colleague.cli._errors.CliError`, never a traceback).

**Middle-manager parity (presence-default-everywhere, task t8):** attaching to
an ARMED run (:func:`colleague.config.resolve_presence_rung` != ``"off"``)
gets two beats on top of the reactive lane above, both pumped through the SAME
:class:`~colleague.presence_engine.PresenceEngine` every other front uses —
never a bespoke reimplementation:

1. **Attach context.** Before the first prompt, the REPL renders whatever the
   flight plane already recorded — the most recent ``kind="ack"`` chat entry
   (:func:`colleague.flight.read_chat`) and a one-line factual snapshot of
   cortex's last recorded step/tool (:func:`_last_task_state`) — so an
   attaching operator sees context immediately instead of a cold prompt. This
   is a pure READ of already-recorded state (no model call), so it degrades
   silently to nothing when the flight has recorded nothing yet (never a
   fabricated status line).
2. **Proactive updates.** At each REPL loop iteration (after a message is
   handled, a ``/say`` transcription, or even a blank line — "between operator
   turns"), :meth:`~colleague.presence_engine.PresenceEngine.on_progress_boundary`
   is polled with the flight's current step/tool; the cadence policy
   (:mod:`colleague.presence`) decides whether a proactive update actually
   fires. A boundary where nothing fired renders NOTHING.

The reactive per-message answer (``talk_fn``/:func:`_handle_talk_message`,
including the guaranteed ``cortex:`` relay-prefix override) is UNCHANGED by
this — the presence engine is additive, not a replacement, so the reactive
lane's existing tests keep holding. Senses-unarmed (``config.senses is None``,
which also always yields ``rung == "off"``) is BYTE-IDENTICAL to before this
task: no presence engine is built, so nothing new renders or is written.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from colleague import flight, registry, voice
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP
from colleague.config import EngineConfig, resolve_engine, resolve_presence_rung
from colleague.presence import cadence_from_env
from colleague.presence_engine import PresenceEngine, PresenceIO, build_presence_executor
from colleague.senses import run_senses_talk, senses_engine_config
from colleague.senses_loop import SensesLoopDriver

_TASK_ID_HELP = "Task id of the running flight (printed by 'colleague work --watch')."
_RELAY_PREFIX = "cortex:"
_FEED_TAIL_LINES = 40
_UNARMED_NOTICE = (
    "colleague: senses not armed — relaying raw instructions to cortex, no senses answers"
)
_NO_TRANSCRIPT_NOTICE = "colleague: could not transcribe that audio — try again or type a message"
_VOICE_UNCONFIGURED_NOTICE = "colleague: stt is not configured — type a message instead"

TalkFn = Callable[..., "Optional[dict[str, Any]]"]
# (senses_config, make_complete, make_count_tokens) or None (senses unarmed / engine
# unloadable — the caller degrades to watch + raw-guide).
EngineSeam = "Optional[tuple[EngineConfig, Any, Any]]"


def _eprint(*args: object, **kwargs: object) -> None:
    """Default diagnostics sink — writes to stderr (kept off stdout)."""
    print(*args, file=sys.stderr, **kwargs)  # type: ignore[arg-type]


def _read_line(input_fn: "Optional[Iterator[str]]") -> "Optional[str]":
    """Return the next input line, or ``None`` on EOF / ``StopIteration``.

    Mirrors :mod:`colleague.cli._commands.session`'s ``_read_line``: with
    ``input_fn`` (the test seam) the next item is pulled from the iterator;
    otherwise the real :func:`input` builtin reads from stdin.
    """
    if input_fn is not None:
        try:
            return next(input_fn)  # type: ignore[call-overload]
        except StopIteration:
            return None
    try:
        return input()
    except EOFError:
        return None


def _tail_feed(repo: "Path | str", task_id: str, lines: int = _FEED_TAIL_LINES) -> str:
    """Return the last *lines* lines of the flight feed, or ``""`` when absent."""
    fp = flight.feed_path(repo, task_id)
    if not fp.exists():
        return ""
    content = fp.read_text().splitlines()
    return "\n".join(content[-lines:])


def _last_task_state(repo: "Path | str", task_id: str) -> "Optional[dict[str, Any]]":
    """Return a short ``{step_index, tool}`` snapshot from the last parseable feed
    record, or ``None`` when the feed is absent/empty/unparseable throughout."""
    fp = flight.feed_path(repo, task_id)
    if not fp.exists():
        return None
    for line in reversed(fp.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            continue
        if isinstance(record, dict):
            return {"step_index": record.get("step_index"), "tool": record.get("tool")}
    return None


def _last_ack_text(repo: "Path | str", task_id: str) -> "Optional[str]":
    """Return the most recent ``kind="ack"`` flight chat entry's text, or ``None``.

    A pure read of :func:`colleague.flight.read_chat` — no model call, so it
    works even when senses itself is currently unreachable. ``None`` when no
    ack has been recorded (yet, or ever) for this run.
    """
    for record in reversed(flight.read_chat(repo, task_id)):
        if record.get("kind") == "ack":
            text = str(record.get("text") or "").strip()
            if text:
                return text
    return None


def _render_attach_context(repo: "Path | str", task_id: str, out: "Callable[..., None]") -> None:
    """Render the run's ack + a factual state snapshot before the first prompt.

    So an attaching operator sees what senses has already acknowledged and
    where cortex currently stands, instead of a cold prompt (t8, bullet 1).
    Purely reads already-recorded flight-plane state — never a model call, and
    never a fabrication: a run with nothing recorded yet renders nothing.
    """
    ack_text = _last_ack_text(repo, task_id)
    if ack_text:
        out(f"senses: {ack_text}")
    state = _last_task_state(repo, task_id)
    if state and (state.get("tool") is not None or state.get("step_index") is not None):
        out(f"[flight] cortex last recorded: step {state.get('step_index')} - {state.get('tool')}")


def _seed_presence_state(repo: "Path | str", task_id: str, state: "dict[str, object]") -> None:
    """Seed the boundary-tracking state from the flight's CURRENT snapshot.

    Called once at attach, before the first REPL turn, so the first
    cadence-gated update is driven by genuine cadence (step deltas / a phase
    change AFTER attach) rather than a "free" phase-change fire from a
    None -> <current tool> comparison.
    """
    current = _last_task_state(repo, task_id)
    state["presence_last_tool"] = current.get("tool") if current else None
    step = current.get("step_index") if current else None
    state["presence_last_step"] = step if isinstance(step, int) else 0


def _persist_presence_turns(repo: "Path | str", task_id: str, turns: "list[Any]") -> None:
    """Persist each turn's chat entry to the flight chat log (the artifact fold-in seam).

    The work-loop's own finish-time fold-in reads this log and extends the
    result's senses chat with whatever it finds — this is how a beat generated
    in TALK's own process (a separate process from the one that will write the
    final result) survives into the record. Rendering already happened inside
    :meth:`~colleague.presence_engine.PresenceEngine`'s turn dispatch; this
    only makes the fact durable. Never raises.
    """
    for turn in turns:
        entry = getattr(turn, "chat_entry", None)
        if entry is not None:
            with contextlib.suppress(OSError, ValueError):
                flight.append_chat(repo, task_id, entry)


def _build_presence_engine_for_talk(
    repo: Path,
    task_id: str,
    config: EngineConfig,
    senses_config: Any,
    make_complete: Any,
    make_count_tokens: Any,
    out: "Callable[..., None]",
) -> "Optional[PresenceEngine]":
    """Construct talk's own :class:`PresenceEngine` when the presence lane is armed.

    Returns ``None`` when the resolved seam has no senses config, OR
    :func:`colleague.config.resolve_presence_rung` resolves ``"off"`` (senses
    unarmed, ``COLLEAGUE_PRESENCE=off``, or a repo-config disarm) — the caller
    then behaves exactly as before this task (byte-identical, t8 bullet 3).

    Talk cannot START cortex (a run it attaches to is already driving in
    another process) — it can only RELAY, so both ``dispatch_to_cortex`` and
    ``guide_cortex`` bind to the SAME :func:`colleague.flight.append_guidance`
    sink, echoed visibly with the existing ``-> cortex:`` convention (mirroring
    :func:`_handle_talk_message`'s relay echo). ``poll_operator_input`` always
    returns ``None`` here: a typed line is already fully handled by the
    existing reactive lane in the SAME REPL iteration before the boundary
    check runs, so there is never a separately-pending message for the engine
    to discover.
    """
    if senses_config is None or make_complete is None:
        return None
    rung = resolve_presence_rung(config, repo_path=repo)
    if rung == "off":
        return None

    def _relay(text: str) -> None:
        with contextlib.suppress(OSError, ValueError):
            flight.append_guidance(repo, task_id, text)
        out(f"-> cortex: {text}")

    io = PresenceIO(
        dispatch_to_cortex=_relay,
        append_guidance=_relay,
        read_flight=lambda: _tail_feed(repo, task_id),
        render=out,
        poll_operator_input=lambda: None,
        feed_tail=lambda: _tail_feed(repo, task_id),
        task_state=lambda: _last_task_state(repo, task_id),
    )
    driver = SensesLoopDriver(
        senses_config=senses_config,
        make_complete=make_complete,
        executor=build_presence_executor(io),
        make_count_tokens=make_count_tokens,
        initial_rung=rung,
    )
    return PresenceEngine(
        driver=driver,
        io=io,
        cadence=cadence_from_env(os.environ),
        three_tier=getattr(config, "three_tier", False),
    )


def _make_progress_boundary(
    presence_engine: PresenceEngine,
    repo: "Path | str",
    task_id: str,
    state: "dict[str, object]",
) -> "Callable[[], None]":
    """Build the per-REPL-iteration boundary check (t8 bullet 2).

    Reads the flight's current step/tool, computes a ``phase_changed`` flag
    relative to what was true at the LAST boundary (seeded at attach by
    :func:`_seed_presence_state`), fires ``on_progress_boundary``, and persists
    any resulting chat entries. A boundary with nothing to say renders and
    persists NOTHING — :meth:`PresenceEngine.on_progress_boundary` already
    guarantees that.
    """

    def boundary() -> None:
        current = _last_task_state(repo, task_id)
        tool = current.get("tool") if current else None
        step = current.get("step_index") if current else None
        step_count = step if isinstance(step, int) else state.get("presence_last_step", 0)
        # A talk attach reads the flight feed, which records only REAL steps
        # (step_index/tool) — NOT the loop's empty-tool phase notices (#206). A
        # tool-name change is therefore not a reliable phase-change proxy (Qodo):
        # firing the phase-change path off it would skew the cadence and burn the
        # update cap early. Talk boundaries rely solely on the step cadence
        # (every_steps); phase_changed is always False here. presence_last_tool
        # is still tracked for context but no longer drives the cadence.
        state["presence_last_tool"] = tool
        state["presence_last_step"] = step_count
        turns = presence_engine.on_progress_boundary(step_count=step_count, phase_changed=False)
        _persist_presence_turns(repo, task_id, turns)

    return boundary


def default_engine_seam(config: EngineConfig, engine_name: str) -> "EngineSeam":
    """Resolve ``(senses_config, make_complete, make_count_tokens)`` for a live talk turn.

    Returns ``None`` when no senses model is resolved (``config.senses is None``)
    or the named engine cannot be loaded — the caller degrades to a watch +
    raw-guide REPL. Never raises.
    """
    senses_config = senses_engine_config(config)
    if senses_config is None:
        return None
    try:
        engine = registry.load(engine_name)
        return senses_config, engine.make_complete, engine.make_count_tokens(senses_config)
    except Exception:  # noqa: BLE001
        return None


def _maybe_transcribe(
    path: str, config: EngineConfig, err: "Callable[..., None]"
) -> "Optional[str]":
    """Transcribe *path* via the configured stt model; ``None`` + a notice on failure."""
    voice_cfg = config.voice
    if voice_cfg is None or not voice_cfg.stt_model:
        err(_VOICE_UNCONFIGURED_NOTICE)
        return None
    transcript = voice.transcribe(
        path,
        stt_model=voice_cfg.stt_model,
        base_url=voice_cfg.stt_base_url,
        api_key=voice_cfg.api_key or "",
    )
    if not transcript:
        err(_NO_TRANSCRIPT_NOTICE)
    return transcript


def _maybe_synthesize(
    answer: str, config: EngineConfig, repo: Path, task_id: str, out: "Callable[..., None]"
) -> None:
    """Synthesize *answer* to a WAV when TTS is configured. Additive only."""
    voice_cfg = config.voice
    if voice_cfg is None or not voice_cfg.tts_model:
        return
    wav_path = flight.flight_dir(repo) / f"{task_id}.talk-{int(time.time() * 1000)}.wav"
    written = voice.synthesize(
        answer,
        tts_model=voice_cfg.tts_model,
        base_url=voice_cfg.tts_base_url,
        out_path=wav_path,
        api_key=voice_cfg.api_key or "",
    )
    if written is not None:
        out(f"[voice] {written}")


def _handle_talk_message(
    message: str,
    *,
    repo: Path,
    task_id: str,
    config: EngineConfig,
    senses_config: Any,
    make_complete: Any,
    make_count_tokens: Any,
    talk_fn: TalkFn,
    out: "Callable[..., None]",
    err: "Callable[..., None]",
    state: dict[str, object],
) -> None:
    """Process one talk message: senses answer, relay, chat-log, TTS."""
    record = talk_fn(
        message,
        feed_tail=_tail_feed(repo, task_id),
        packet=None,
        task_state=_last_task_state(repo, task_id),
        senses_config=senses_config,
        make_complete=make_complete,
        make_count_tokens=make_count_tokens,
        relay_prefix=_RELAY_PREFIX,
    )
    if record is None:
        if not state["unarmed_notice_shown"]:
            err(_UNARMED_NOTICE)
            state["unarmed_notice_shown"] = True
        with contextlib.suppress(OSError, ValueError):
            flight.append_guidance(repo, task_id, message)
        out(f"-> cortex: {message}")
        return

    answer = record.get("answer", "")
    out(f"senses: {answer}")
    if record.get("relay"):
        relay_text = record.get("relay_text") or message
        with contextlib.suppress(OSError, ValueError):
            flight.append_guidance(repo, task_id, relay_text)
        out(f"-> cortex: {relay_text}")
    with contextlib.suppress(OSError, ValueError):
        flight.append_chat(
            repo,
            task_id,
            {
                "message": message,
                "answer": answer,
                "relay": bool(record.get("relay", False)),
                "relay_text": record.get("relay_text", ""),
                "latency": record.get("latency"),
                "degraded": bool(record.get("degraded", False)),
                "at": time.time(),
            },
        )
    _maybe_synthesize(answer, config, repo, task_id, out)


def _fire_boundary(on_boundary: "Optional[Callable[[], None]]") -> None:
    """Call *on_boundary*, if given — the shared post-iteration presence pump.

    Extracted so ``_repl_loop`` states the "fire the boundary" intent once
    instead of repeating the same guard at each of its three exit points
    (pure refactor for cognitive complexity, no behaviour change)."""
    if on_boundary is not None:
        on_boundary()


def _handle_say_line(
    stripped: str,
    config: EngineConfig,
    err: "Callable[..., None]",
    dispatch: "Callable[[str], None]",
) -> None:
    """Transcribe a ``/say <path>`` line and dispatch the transcript, if any.

    A failed/empty transcription dispatches nothing — mirrors the inline
    behaviour this replaces in ``_repl_loop`` exactly."""
    transcript = _maybe_transcribe(stripped[len("/say ") :].strip(), config, err)
    if transcript:
        dispatch(transcript)


def _repl_loop(
    input_fn: "Optional[Iterator[str]]",
    config: EngineConfig,
    err: "Callable[..., None]",
    dispatch: "Callable[[str], None]",
    *,
    on_boundary: "Optional[Callable[[], None]]" = None,
) -> None:
    """Read lines until /quit /exit / EOF; dispatch each message.

    *on_boundary*, when given, is called once per iteration AFTER the line is
    fully handled (dispatch, ``/say`` transcription, or a blank line) — "each
    REPL loop iteration / between typed lines" (t8 bullet 2), the presence
    engine's cadence-gated proactive-update check. ``None`` (the default, and
    always the case when the presence lane is unarmed) leaves this function
    byte-identical to before task t8.
    """
    while True:
        line = _read_line(input_fn)
        if line is None:
            return
        stripped = line.strip()
        if stripped in ("/quit", "/exit"):
            return
        if not stripped:
            _fire_boundary(on_boundary)
            continue
        if stripped.startswith("/say "):
            _handle_say_line(stripped, config, err, dispatch)
            _fire_boundary(on_boundary)
            continue
        dispatch(stripped)
        _fire_boundary(on_boundary)


def run_talk_repl(
    repo: "Path | str",
    task_id: str,
    config: EngineConfig,
    *,
    engine_name: str = "vllm-openai",
    audio_path: "Optional[str]" = None,
    input_fn: "Optional[Iterator[str]]" = None,
    out: "Callable[..., None]" = print,
    err: "Optional[Callable[..., None]]" = None,
    talk_fn: TalkFn = run_senses_talk,
    resolve_engine_seam: "Callable[[EngineConfig, str], EngineSeam]" = default_engine_seam,
) -> int:
    """The REPL core for ``colleague talk`` — unit-testable via dependency injection.

    Reads operator lines from *input_fn* (an iterator; ``None`` reads real
    stdin via :func:`input`), holding one senses talk turn per line via
    *talk_fn* (default :func:`colleague.senses.run_senses_talk`). ``/quit`` /
    ``/exit`` / EOF end the REPL cleanly (return ``0``). ``/say <path>``
    transcribes an audio file as the next message; *audio_path* does the same
    once at startup, before the first prompted line.

    The engine seam (``senses_config``, ``make_complete``, ``make_count_tokens``)
    is resolved ONCE via *resolve_engine_seam* — the injected default calls
    :func:`default_engine_seam`, so a test can inject a stub instead of loading
    a real backend. *talk_fn* is called every turn regardless of the seam;
    when it returns ``None`` (senses unarmed) the REPL degrades to relaying the
    raw message via :func:`colleague.flight.append_guidance` with a visible
    ``-> cortex:`` echo — printing the unarmed notice exactly once.

    **Middle-manager parity (t8):** when the presence lane is armed
    (:func:`colleague.config.resolve_presence_rung` resolves something other
    than ``"off"`` for *config*), a :class:`~colleague.presence_engine.PresenceEngine`
    is built from the SAME resolved seam (see :func:`_build_presence_engine_for_talk`)
    and: (1) renders the run's ack/context from the flight plane once, before
    the first prompt (:func:`_render_attach_context`); (2) fires a
    cadence-gated proactive-update check after every REPL iteration
    (:func:`_make_progress_boundary`). Both are ADDITIVE to the reactive lane
    above — unarmed (``config.senses is None``, which always resolves
    ``"off"``) leaves this function's behaviour byte-identical to before task
    t8: no presence engine is built, nothing new renders or is persisted.
    """
    if err is None:
        err = _eprint
    repo = Path(repo)
    if not flight.is_safe_task_id(task_id):
        raise CliError(EXIT_USER_ERROR, f"invalid flight task id: {task_id!r}")
    seam = resolve_engine_seam(config, engine_name)
    if seam is not None:
        senses_config, make_complete, make_count_tokens = seam
    else:
        senses_config, make_complete, make_count_tokens = None, None, None
    state: dict[str, object] = {"unarmed_notice_shown": False}

    def dispatch(message: str) -> None:
        _handle_talk_message(
            message,
            repo=repo,
            task_id=task_id,
            config=config,
            senses_config=senses_config,
            make_complete=make_complete,
            make_count_tokens=make_count_tokens,
            talk_fn=talk_fn,
            out=out,
            err=err,
            state=state,
        )

    presence_engine = _build_presence_engine_for_talk(
        repo, task_id, config, senses_config, make_complete, make_count_tokens, out
    )
    on_boundary = None
    if presence_engine is not None:
        _render_attach_context(repo, task_id, out)
        _seed_presence_state(repo, task_id, state)
        on_boundary = _make_progress_boundary(presence_engine, repo, task_id, state)

    if audio_path:
        transcript = _maybe_transcribe(audio_path, config, err)
        if transcript:
            dispatch(transcript)
        if on_boundary is not None:
            on_boundary()
    _repl_loop(input_fn, config, err, dispatch, on_boundary=on_boundary)
    return 0


def cmd_talk(args: argparse.Namespace) -> int:
    """Handler for the ``colleague talk`` verb."""
    repo = Path(args.repo).expanduser()
    task_id = args.task_id
    if not flight.is_safe_task_id(task_id):
        raise CliError(EXIT_USER_ERROR, f"invalid flight task id: {task_id!r}")

    engine_name = resolve_engine(getattr(args, "engine", None))
    config = EngineConfig.resolve(
        base_url=getattr(args, "base_url", None),
        api_key=getattr(args, "api_key", None),
        model=getattr(args, "model", None),
        repo_path=repo,
    )
    return run_talk_repl(
        repo,
        task_id,
        config,
        engine_name=engine_name,
        audio_path=getattr(args, "audio", None),
    )


_TALK_HELP = "Attach a live REPL to a running work item's flight plane (talk to senses)."
_TALK_DESCRIPTION = (
    "Attach to a RUNNING work item over the file-based flight plane and converse "
    "with senses while cortex drives. Each typed message gets a senses answer "
    "(labeled 'senses:'); an instruction can be relayed into the running cortex "
    "loop ('-> cortex:'). '--audio FILE' / '/say FILE' transcribes a spoken "
    "message; replies are synthesized to a wav when voice/tts is configured. "
    "Degrades to a watch + raw-guide REPL when senses is unarmed."
)


def _configure_talk_parser(p: argparse.ArgumentParser) -> None:
    """Add ``talk``'s flags to an already-created parser.

    Shared by the legacy :func:`register` and the agentfront host-command
    ``configure`` hook (:func:`register_into`). ``talk`` is a host command (a
    blocking interactive REPL agentfront's single-return rendered tools can't
    express); ``func`` is left for the caller / agentfront to set to
    :func:`cmd_talk`.
    """
    p.description = _TALK_DESCRIPTION
    p.add_argument("task_id", help=_TASK_ID_HELP)
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help="Backend plugin used for the senses turn (default: COLLEAGUE_ENGINE, "
        "else vllm-openai).",
    )
    p.add_argument("--base-url", default=None, help="Override the engine base URL.")
    p.add_argument("--model", default=None, help="Override the engine model name.")
    p.add_argument("--api-key", default=None, help="Override the engine API key.")
    p.add_argument(
        "--audio",
        default=None,
        help="Transcribe this audio file as the first message (stt must be configured).",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("talk", help=_TALK_HELP)
    _configure_talk_parser(p)
    p.set_defaults(func=cmd_talk)


def register_into(app) -> None:
    """Register ``talk`` as an agentfront host command.

    A live REPL over stdin/stdout is a blocking interactive surface agentfront's
    rendered tools (a single return value, emitted once) structurally cannot
    express — the same carve-out as ``session``/``flight``. Reuses
    :func:`cmd_talk`'s ``(args) -> int`` handler verbatim.
    """
    app.add_command("talk", cmd_talk, help=_TALK_HELP, configure=_configure_talk_parser)
