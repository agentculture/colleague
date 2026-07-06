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
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from colleague import flight, registry, voice
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP
from colleague.config import EngineConfig, resolve_engine
from colleague.senses import run_senses_talk, senses_engine_config

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


def _repl_loop(
    input_fn: "Optional[Iterator[str]]",
    config: EngineConfig,
    err: "Callable[..., None]",
    dispatch: "Callable[[str], None]",
) -> None:
    """Read lines until /quit /exit / EOF; dispatch each message."""
    while True:
        line = _read_line(input_fn)
        if line is None:
            return
        stripped = line.strip()
        if stripped in ("/quit", "/exit"):
            return
        if not stripped:
            continue
        if stripped.startswith("/say "):
            transcript = _maybe_transcribe(stripped[len("/say ") :].strip(), config, err)
            if transcript:
                dispatch(transcript)
            continue
        dispatch(stripped)


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

    if audio_path:
        transcript = _maybe_transcribe(audio_path, config, err)
        if transcript:
            dispatch(transcript)
    _repl_loop(input_fn, config, err, dispatch)
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
