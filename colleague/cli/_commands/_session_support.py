"""Pure helpers, the injectable-seam types, and the senses stream painter.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17). Everything here is either a free
function with no ``_Session`` coupling (``_goal_text``, ``_read_line``,
``_resolve_selection``, ``_default_plan`` …) or :class:`_SensesStreamPainter`,
which holds only a back-reference to the session it paints for. ``session.py``
re-exports all of them, so ``from colleague.cli._commands.session import
_goal_text`` still resolves.

``_stdout_is_tty`` deliberately did NOT move: the suite patches it as
``session_mod._stdout_is_tty``, so it stays defined in ``session.py`` and the
senses lane reaches it through a lazy module-attribute lookup.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator, Optional, TypeVar

from agentfront.taui.render.layout import detect_width

from colleague.attribution import senses_line
from colleague.cli._commands._input_line import transient_paint
from colleague.cli._commands._session_const import _GOAL_MAX_CHARS
from colleague.cockpit_run import DeltaTail, fold_delta, mark_delta_rendered, should_repaint_delta
from colleague.commands import CommandError, expand_command
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.session_modes import ModeFacts

if TYPE_CHECKING:  # pragma: no cover - annotation-only
    from colleague.cli._commands.session import _Session

# ---------------------------------------------------------------------------
# Types for the injectable seams
# ---------------------------------------------------------------------------

_WorkFn = Callable[..., tuple[TaskResult, Path]]
#: A session "plan" runner: takes a free-text request and returns a summary
#: string to fold into the feed. Injectable as a test seam (mirrors ``_WorkFn``).
_PlanFn = Callable[..., str]
#: The session's chain runner (indefinite-run t9): the shape of
#: :func:`colleague.cli._commands.work.execute_work_chain` — the SAME chain
#: loop ``work --until-done`` drives. Injectable test seam (mirrors ``_WorkFn``).
_ChainFn = Callable[..., tuple[TaskResult, Path]]

#: Return type of a tracked dispatch thunk (a work-fn pair or a plan summary).
_T = TypeVar("_T")


def _reply_text_from_turns(turns: object) -> str:
    """Join the operator-facing text of a senses agentic loop's returned turns.

    Voice needs senses' rendered answer to speak it back; the ``loop`` rung's
    :meth:`PresenceEngine.on_operator_message` returns the
    :class:`~colleague.senses_loop.LoopTurn` list it just rendered, each turn's
    ``chat_entry`` carrying ``text`` (ack/clarify) or ``answer`` (a talk reply).
    Mirrors :meth:`PresenceEngine._render_turn`'s own extraction so the spoken
    text is exactly what was displayed. Tolerant of ``None`` / a bare list.

    Replies-only scope (task t8, risk r1 / open q4): a ``MOVE_NARRATE`` turn
    (the '<<higher self thought>>' narration) carries NO ``chat_entry`` at all
    — see :meth:`~colleague.senses_loop.SensesLoopDriver._build_turn`, where
    narration rides ``LoopTurn.narration`` instead, deliberately never stored
    as a chat entry — so it is already excluded here structurally, never
    spoken. Widening speech to include narration later is a ONE-LINE change:
    also join ``getattr(turn, "narration", None)`` in the loop below.
    """
    parts: list[str] = []
    for turn in turns or []:
        entry = getattr(turn, "chat_entry", None)
        if entry is None:
            continue
        text = str(entry.get("text") or entry.get("answer") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _goal_text(instruction: str) -> str:
    """The goal line: *instruction*'s first line, truncated to ``_GOAL_MAX_CHARS``.

    Returns ``""`` for blank/whitespace-only instructions (e.g. a synthetic plan
    task) so the caller can treat an empty result as "no goal to show".
    """
    first_line = instruction.strip().splitlines()[0] if instruction.strip() else ""
    if len(first_line) > _GOAL_MAX_CHARS:
        return first_line[: _GOAL_MAX_CHARS - 1].rstrip() + "…"
    return first_line


def _mode_status_text(facts: ModeFacts) -> str:
    """One-line disambiguated 'behavior (source)' fact (#285 t6) — e.g.
    ``explore (pinned)`` or ``auto→work (auto)`` — kept separate from the
    execution-profile text below so an operator can tell WHICH behavior is
    active from WHETHER it was auto-classified or pinned, without either fact
    being blurred into the other."""
    if facts.resolved_from:
        return f"{facts.behavior}→{facts.resolved_from} ({facts.source})"
    return f"{facts.behavior} ({facts.source})"


def _mode_profile_text(facts: ModeFacts) -> str:
    """One-line execution-profile fact (steps/timeout/budget/fill-line/
    synthesis-reserve), or an honest 'no fixed profile' note when the mode has
    none (``auto`` with no sample input) — never a crash or a stale-looking
    blank row."""
    if not facts.profile_rows:
        return "no fixed profile (resolves per input)"
    return " · ".join(f"{label} {value}" for label, value in facts.profile_rows)


def _coerce_strs(value: object) -> list[str]:
    """Coerce a policy config value to a list of strings, tolerating bad shapes.

    Mirrors :func:`colleague.policy._str_list` so the cockpit presents exactly
    what the gate enforces: a non-list (or a list with non-string members)
    degrades to the surviving string members, never raising on a malformed
    ``approvals.json``.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _eprint(*args: object, **kwargs: object) -> None:
    """Default diagnostics sink — writes to stderr (kept off stdout)."""
    print(*args, file=sys.stderr, **kwargs)  # type: ignore[arg-type]


def _read_line(input_fn: Optional[Iterator[str]]) -> Optional[str]:
    """Return the next input line, or None on EOF / StopIteration.

    With ``input_fn`` (test seam) the next item is pulled from the iterator;
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


def _resolve_selection(
    line: str,
    palette: list[tuple[str, str]],
    discovered: dict[str, Path],
    repo: Path,
    engine_name: str,
    note: Callable[[str], None],
    model: str | None = None,
) -> Optional[tuple[Task, Optional[str]]]:
    """Resolve a palette input line to a ``(task, command_name)`` pair.

    A bare number selects a palette entry; an exact name selects a command
    template; anything else is a free-text ad-hoc instruction (``command_name``
    is ``None``). Returns ``None`` when the line cannot be resolved (out-of-range
    number, or an unknown/erroring command) — the reason is passed to *note* and
    the caller should simply prompt again.
    """
    command_name: Optional[str] = None

    if line.isdigit():
        idx = int(line)
        if not 1 <= idx <= len(palette):
            note(f"no entry {idx} in the palette; type a number 1–{len(palette)}")
            return None
        command_name = palette[idx - 1][0]
    elif line in discovered:
        command_name = line
    else:
        # Free-text ad-hoc instruction — no originating command.
        return Task.new(str(repo), line, engine=engine_name), None

    try:
        task = expand_command(repo, command_name, [], engine_default=engine_name, model=model)
    except CommandError as exc:
        note(f"error: {exc}")
        return None
    return task, command_name


class _SensesStreamPainter:
    """Throttled in-place painter for ONE growing ``senses: …`` line (ssv t3).

    The conversation-surface twin of the cockpit's status DeltaTail: display
    deltas (decoded by :func:`colleague.senses.make_senses_display_delta`, or
    fed raw for speak-back's bare-prose replies) fold through the SAME pure
    machinery — :func:`fold_delta` / :func:`should_repaint_delta` /
    :func:`mark_delta_rendered`, the count-based cadence, the sanitized
    single-line window — but paint the CONVERSATION surface instead of the
    status line: a transient row repaint (:func:`transient_paint` — CR +
    erase-line + text, NO newline) sized to the terminal row, on exactly the
    row the reply's final whole-line render will overwrite. The FINAL rendered
    line never comes from here — the existing blocking-path code prints it
    (``_log`` + ``print_above`` / the full-frame redraw), erasing the last
    transient paint in place — so a declined extractor or a mid-stream failure
    simply means fewer (or zero) paints and the turn renders whole at the end
    exactly as today (full containment is task t5).

    All writes are MAIN-THREAD (``on_delta`` fires inside the blocking senses
    completion's streamed read loop) and go through the owned-line seam: with
    the owned input line armed, the paint is its lock-protected
    :meth:`OwnedInputLine.stream_paint` (never interleaves with the reader
    thread's echo); otherwise (a front-door / speak-back turn on the genuine
    live colour TTY, where no work line owns the bottom row) the same
    :func:`transient_paint` sequence writes to stdout directly. Build a FRESH
    painter per senses turn (per :meth:`_Session._senses_stream_sink` call) —
    the fold state is per-reply, exactly like the extractor it feeds from.

    Never raises into the engine's read loop: the paint body is suppressed
    (mirroring ``_emit_delta``'s raising-sink convention), and the fold path
    is pure computation. Never touches ``sess.state`` — no status fold, no
    conversation line, no step count (the #206 invariant; the cockpit
    DeltaTail's CORTEX-delta → STATUS behavior is untouched by construction).
    """

    def __init__(self, session: "_Session") -> None:
        self._session = session
        self._tail = DeltaTail()
        #: Paints performed — the AC1 measurement seam (>= 2 on a real PTY).
        #: Doubles as the t5 "did I paint anything this turn" signal: a
        #: caller degrading this turn checks ``paints > 0`` before finalizing
        #: partial text, rather than a fresh flag re-deriving the same fact.
        self.paints = 0

    @property
    def painted_text(self) -> str:
        """The current display tail — task t5's smallest seam.

        Whatever text this painter has folded so far (:func:`fold_delta`'s
        trailing window), whether or not a repaint has actually reached the
        screen yet (the cadence throttles WRITES, not the fold — see
        :meth:`on_display_delta`). The session's mid-stream-death
        containment reads this to finalize the partial reply as a real line
        when the completion degrades after painting occurred — the ONE
        piece of painter state that wasn't already exposed (``paints`` above
        already answers "did I paint anything").
        """
        return self._tail.text

    def on_display_delta(self, piece: str) -> None:
        """Fold ONE display delta; repaint at the cockpit's own cadence."""
        # Size the trailing window to the terminal row (label + margin off),
        # so the line genuinely GROWS until the row fills, then keeps the
        # freshest tail — the same trailing-window rule as the status stream,
        # sized to this surface. Floor of 16 keeps a degenerate width sane.
        width = max(16, detect_width() - len(senses_line("")) - 2)
        self._tail = fold_delta(self._tail, piece, width=width)
        if not should_repaint_delta(self._tail):
            return
        self._tail = mark_delta_rendered(self._tail)
        self._paint(senses_line(self._tail.text))

    def _paint(self, text: str) -> None:
        with contextlib.suppress(Exception):  # a raising sink never breaks the run
            line = self._session._owned_line
            if line is not None:
                line.stream_paint(text)
            else:
                sys.stdout.write(transient_paint(text))
                sys.stdout.flush()
            self.paints += 1


def _default_plan(*, repo: Path, engine_name: str, request: str, config: EngineConfig) -> str:
    """Default session ``plan`` runner: a quick, non-interactive spec→plan.

    Runs colleague plan mode in *quick* + *no-workforce* + auto-confirm mode so a
    conversational session yields a plan without an interactive per-item gate or a
    subagent fan-out (use ``colleague plan run`` for the full gated arc). Reuses the
    engine seams via :func:`~colleague.cli._commands.plan.run_plan_request`; raises
    :class:`CliError` (handled by the caller) on a non-live backend such as ``mock``.
    Imported lazily so a session that never plans doesn't load the plan package.
    """
    from colleague.cli._commands.plan import _auto_decide, _render_run, run_plan_request

    result = run_plan_request(
        repo=repo,
        request=request,
        engine_name=engine_name,
        config=config,
        decide=_auto_decide,
        quick=True,
        workforce=False,
    )
    return _render_run(result)
