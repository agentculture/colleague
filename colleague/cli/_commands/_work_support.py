"""Presentation + knob-plumbing helpers for ``colleague work``.

Split out of ``colleague/cli/_commands/work.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t16). Nothing here is monkeypatched by the
suite and nothing here is pinned to ``work.py``'s own source text, so the move
is behaviour-preserving: the render/diagnostic sinks, the ``--no-*`` opt-out
appliers, the dirty-tree guard, the mode-profile application, the flight
announcement, the delta-stream arming, the :class:`DisplayOptions` bundle, the
presence builder, the watch arming and the outcome emitter.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NamedTuple

from colleague import flight, tasktext, web_schemas
from colleague.cli._commands._tui_sink import CockpitProgressSink, build_progress
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import emit_diagnostic, emit_result
from colleague.config import EngineConfig, apply_mode_profile
from colleague.contract import INCOMPLETE, OK, ChainView, Task, TaskResult
from colleague.engines import vllm_openai as _vllm_openai
from colleague.handoff import working_tree_dirty


class Lineage(NamedTuple):
    """Continuation lineage threaded as ONE bundle (SonarCloud S107).

    Bundles ``continued_from`` (the prior run's task id) with the propagated
    original ``task_text`` (#481/c22 — never the synthesized seed), so
    ``execute_work``/``execute_work_chain`` stay at 13 parameters. ``None``
    means an ordinary, non-continuation dispatch.
    """

    continued_from: "str | None" = None
    task_text: "str | None" = None


def _step_progress(step_index: int, tool: str, target: str, ok: bool) -> None:
    """Per-step progress line to stderr during a work item (#38).

    stdout carries only the result stream (the ``--json`` ``TaskResult``), so a
    progress line here never pollutes the parseable output — it is emitted in all
    modes. Wired onto :class:`~colleague.config.EngineConfig` by
    :func:`execute_work`, so both ``work`` and ``session`` (and every backend)
    report progress identically.

    A phase notice (colleague#206) arrives with an EMPTY ``tool`` name: render its
    detail (carried in ``target``) as a standalone line — never shaped like a
    ``step N:`` line — so a long model turn, above all the final synthesis turn, is
    visibly "working, not stalled" on a slow backend instead of going silent.
    """
    if not tool:
        if target:
            emit_diagnostic(target)
        return
    detail = f" {target}" if target else ""
    emit_diagnostic(f"step {step_index}: {tool}{detail} [{'ok' if ok else 'err'}]")


def _repo_relative(repo: Path, path_str: str) -> str | None:
    """Repo-relative POSIX path for *path_str* if it lives inside *repo*, else None.

    Used to recognise a `--tui-events` stream written into the repo so the handoff
    can treat it as baseline (telemetry) rather than work-produced output.
    """
    try:
        rel = Path(path_str).expanduser().resolve().relative_to(repo.resolve())
    except (ValueError, OSError):
        return None
    return rel.as_posix()


def _render(result: TaskResult, engine: str, artifact_path: Path) -> str:
    lines = [
        f"task: {result.task_id}",
        f"engine: {engine}",
        f"status: {result.status}",
        f"summary: {result.summary}",
        "changed files: " + (", ".join(result.changed_files) or "(none)"),
    ]
    if result.branch:
        lines.append(f"branch: {result.branch}")
    lines.append(f"PR: {result.pr_url or '(none)'}")
    lines.append(f"artifact: {artifact_path}")
    web_line = web_schemas.summary_line(result.steps)
    if web_line:
        lines.append(web_line)
    # ROI-loop nudge (text path only; `--json` bypasses `_render` so this never
    # pollutes machine output): mirror ask-colleague's `grade:` hint.
    if result.task_id:
        lines.append(f"grade: colleague feedback record {result.task_id} --rating N")
    return "\n".join(lines)


def _guard_clean_tree(repo: Path, *, allow_dirty: bool) -> None:
    """Refuse to run a work item against a dirty tree unless opted in (#149).

    A work item ends in the handoff's ``git add -u``, which would sweep the
    operator's uncommitted *tracked* edits onto the work branch and then restore
    HEAD over them — silently swallowing in-progress work. Called from the shared
    path so ``work``, ``drive``, and ``session`` are all protected (and every
    backend, since this is upstream of the loop). Untracked WIP is already
    protected by the handoff's baseline snapshot, so this checks tracked changes
    only (see :func:`~colleague.handoff.working_tree_dirty`).
    """
    if allow_dirty or not working_tree_dirty(repo):
        return
    raise CliError(
        EXIT_USER_ERROR,
        "working tree has uncommitted changes — refusing to run against a dirty repo",
        "commit or stash your changes first, or pass --allow-dirty to "
        "commit them onto the work branch",
    )


def _apply_lint_optout(args: argparse.Namespace, config: EngineConfig) -> None:
    """Apply the ``--no-lint`` opt-out — the highest-precedence lint switch (#200).

    Applied AFTER ``EngineConfig.resolve`` (which handled env > config.json >
    default-on for ``config.lint``); the flag wins last. Extracted to keep
    ``cmd_work`` under the S3776 cognitive-complexity threshold.
    """
    if getattr(args, "no_lint", False):
        config.lint = False


def _apply_coherence_optout(args: argparse.Namespace, config: EngineConfig) -> None:
    """Apply the ``--no-coherence`` opt-out — the highest-precedence switch (#294).

    Applied AFTER ``EngineConfig.resolve`` (which handled env > config.json >
    default-on for ``config.coherence``); the flag wins last — the exact
    ``--no-lint`` precedent.
    """
    if getattr(args, "no_coherence", False):
        config.coherence = False


def _apply_affected_tests_optout(args: argparse.Namespace, config: EngineConfig) -> None:
    """Apply the ``--no-affected-tests`` and ``--test`` opt-outs (#213).

    Applied AFTER ``EngineConfig.resolve`` (which handled env > config.json >
    default-on for ``config.affected_tests``); the flags win last. Extracted to
    keep ``cmd_work`` under the S3776 cognitive-complexity threshold.
    """
    if getattr(args, "no_affected_tests", False):
        config.affected_tests = False
    if getattr(args, "test", None):
        config.affected_tests_override = args.test


def _surface_lint_residual(result: TaskResult) -> None:
    """Surface lint violations the gate could not auto-fix on stderr (#200).

    A diagnostic, never the stdout result stream; the full report is in the
    artifact (``result.lint_report``). Extracted to keep ``cmd_work`` under the
    S3776 cognitive-complexity threshold.
    """
    if result.lint_report and result.lint_report.residual:
        n = len(result.lint_report.residual)
        emit_diagnostic(
            f"lint: {n} issue(s) not auto-fixed:\n" + "\n".join(result.lint_report.residual)
        )


def _surface_coherence_hints(result: TaskResult) -> None:
    """Surface coherence diagnostics/errors on stderr (#294) — advisory only.

    A diagnostic, never the stdout result stream; the full report (with frame
    provenance) is in the artifact (``result.coherence_report``).
    """
    if not result.coherence_report:
        return
    from colleague import coherence as _coherencemod

    for line in _coherencemod.diagnostics_lines(result.coherence_report):
        emit_diagnostic(line)


def _moded_config(config: EngineConfig, mode: str | None, repo: Path) -> EngineConfig:
    """Apply *mode*'s constraint profile to *config* (t3 / spec R1 / #254).

    A strict no-op without a mode (h1). The caller's explicit CLI knobs travel
    on ``config.explicit_knobs`` (a runtime-only field, the ``role`` precedent
    — keeps execute_work under the S107 parameter ceiling) and are never
    overwritten. Extracted from :func:`execute_work` (SonarCloud S3776).
    """
    if not mode:
        return config
    moded = apply_mode_profile(config, mode, explicit=config.explicit_knobs, repo_path=repo)
    # Stamp the mode beside ``role`` so the acting seat's effort resolution can
    # apply the read-only-mode rung (``effort.TOP_LEVEL_MODE_TABLE``); a
    # runtime-only field, never serialized.
    moded.mode = mode
    return moded


def _announce_flight(task: Task, repo: Path, progress_sink: "CockpitProgressSink | None") -> None:
    """Emit the flight-attach handle for a watched non-session run (#307/#310).

    Called AFTER every guard (dirty tree, unknown engine) and isolation, so a
    REFUSED run never prints a stray handle before its "error:" line
    (armed-by-default made every early error hit that ordering). Uses *repo*
    (the operator repo — the plane lives there, not the worktree, #310). Only
    fires on the non-session work path (``progress_sink is None``); the
    interactive session has its own live UI and needs no stderr handle.
    Extracted from :func:`execute_work` to keep its cognitive complexity under
    the S3776 threshold.
    """
    if task.watch and progress_sink is None:
        emit_diagnostic(
            f"flight: {task.id}\n"
            f"feed: {flight.feed_path(repo, task.id)}\n"
            f"control: {flight.control_path(repo, task.id)}"
        )


def _arm_delta_stream(config: EngineConfig, cockpit_sink: object) -> None:
    """Arm the token-delta seam on a cockpit sink that wants it (t6, extended t4/ssv).

    Live generation tail (feels-alive arc): arms the runtime's optional
    token-delta seam (`EngineConfig.on_delta`, task t3). *cockpit_sink* is
    non-None on two shapes: the standalone `work --tui`/auto-detected-colour-TTY
    cockpit (`build_progress`'s `cockpit_active` gate — a genuinely
    live-rendering surface, `CockpitProgressSink`), and the interactive
    session's own bookkeeping sink (`_WorkSink`), built for EVERY session work
    item regardless of render tier. `wants_delta_stream` is what each sink
    kind decides for itself: `CockpitProgressSink` is always True (it only
    exists when live rendering is already on); `_WorkSink` is ALSO always
    True (task t4/ssv, c19/h16) — a session cortex turn arms the seam on
    every tier, not only its dynamic ANSI one, because arming has a second
    job besides display: it flips the engine onto its per-read-timeout-
    resetting streamed request path (`config.on_delta is not None` is the
    ONLY blocking-vs-streaming decision, `vllm_openai._make_complete`), which
    a long turn on a slow model needs regardless of whether anything redraws.
    The VISIBLE redraw stays ANSI-only, decided entirely inside `_WorkSink`
    itself (`on_delta`/`__call__`'s own `sess.view == "ansi"` checks) — a
    piped/`--json`/Markdown session still never streams into a frame nobody
    redraws, it just also gets the timeout-reset benefit now. No new CLI
    flag: this is a resolution change, not an opt-in.
    The default is OPT-OUT (`getattr(..., False)`): both live cockpit sinks
    declare the property explicitly, while an EXTERNAL caller-supplied sink
    that never heard of deltas stays unarmed (an opt-in default crashed such
    callers on the missing `on_delta` attribute). Every other path — bare
    non-TTY `work`, `--no-tui`, `--tui-events` alone, i.e. `cockpit_sink is
    None` — passes ``None``, so `config.on_delta` keeps its byte-identical
    default; this path is untouched by t4/ssv. Extracted from
    :func:`execute_work` to keep its cognitive complexity under the S3776
    threshold.

    The reset is UNCONDITIONAL (mirroring how ``config.progress`` is
    overwritten every run): any long-lived caller that reuses one
    ``EngineConfig`` across work items (the session, an embedding host) must
    never carry a previous run's armed sink — a stale bound method — into a
    later run whose own sink is absent or declines (Qodo #318 review, comment
    3560546632).
    """
    config.on_delta = None
    if cockpit_sink is not None and getattr(cockpit_sink, "wants_delta_stream", False):
        config.on_delta = cockpit_sink.on_delta


@dataclass(frozen=True)
class DisplayOptions:
    """The cockpit/TUI display knobs, bundled (SonarCloud S107 — the recorded
    hot-signature pattern: rarely-passed presentation knobs ride one frozen
    options object instead of two positional-adjacent params)."""

    #: Live-cockpit activation (#74 A1): True forces on, False off, None auto.
    tui: bool | None = None
    #: Optional WorkStep-JSONL path (#74 A3) an agent can follow / `tui replay`.
    tui_events: str | None = None
    #: Optional caller-supplied cockpit sink (#74 A2): the interactive
    #: ``session`` binds one to its own ``CockpitState`` + frame-writer so a
    #: work item renders into the session's one shared screen (replacing the
    #: auto-constructed cockpit). ``None`` (the default) preserves the
    #: byte-identical ``work`` path. Rides this bundle since v1.47.0
    #: (SonarCloud S107 on ``execute_work`` — same recorded pattern).
    sink: "CockpitProgressSink | None" = None


#: The constraint-profile modes whose work items are read-only by INTENT
#: (their chains use read-only progress semantics + stay handoff-free, the
#: read-only-role treatment — t12 live-dogfood catch).
_READ_ONLY_MODES = frozenset({"explore", "review"})


def _arm_watch(args: argparse.Namespace, task, config) -> None:
    """Arm the flight control plane, armed by default (#307).

    Precedence (flag > env > config > default-on): an explicit ``--no-watch``
    disarms; an explicit ``--watch`` arms; otherwise ``config.watch`` (which
    resolved ``COLLEAGUE_WATCH`` > ``.colleague/config.json`` ``{watch}`` >
    default-on) decides. Extracted from :func:`cmd_work` to keep its cognitive
    complexity in budget (S3776).
    """
    explicit_watch = bool(getattr(args, "watch", False))
    if bool(getattr(args, "no_watch", False)):
        task.watch = False
        return
    watch = True if explicit_watch else bool(getattr(config, "watch", True))
    if not watch:
        task.watch = False
        return
    if flight.depth_exceeded():
        # Default-on watch must NEVER break a nested run: degrade to no-watch
        # silently when watch was DEFAULTED. Only an EXPLICIT --watch at depth is a
        # hard error (the operator asked for something that can't nest).
        if explicit_watch:
            raise CliError(
                EXIT_USER_ERROR,
                "flight depth cap reached — refusing to nest another sub-flight",
                "a flight may pilot a sub-flight, but not unbounded recursion",
            )
        task.watch = False
        return
    task.watch = True
    os.environ.update(flight.child_depth_env())
    # The flight-attach handle is emitted from execute_work, AFTER its guards
    # (dirty tree, unknown engine, ...), so a refused run never prints a stray
    # handle before its "error:" line (#307 armed-by-default made every early
    # error hit that ordering). See execute_work's `if task.watch and ...` block.


def _emit_work_outcome(result, engine: str, artifact_path, json_mode: bool) -> int:
    """Surface warnings + the result, and map status to the exit code (extracted
    from :func:`cmd_work` to keep its cognitive complexity in budget — S3776)."""
    # Surface the warn-only "too big for one repo" capacity warning (#156) on stderr
    # — a diagnostic, so it never pollutes the stdout result stream and reaches the
    # caller (agent or human) in both text and --json modes; it is also recorded in
    # the artifact (result.to_dict()).
    if result.capacity_warning:
        emit_diagnostic(f"capacity warning: {result.capacity_warning}")

    _surface_lint_residual(result)
    _surface_coherence_hints(result)

    if json_mode:
        emit_result(result.to_dict(), json_mode=True)
    else:
        emit_result(_render(result, engine, artifact_path), json_mode=False)
    if result.status == OK:
        return 0
    if result.status == INCOMPLETE:
        return 2
    return 1


def _arm_progress_sink(
    *,
    config: EngineConfig,
    task: Task,
    engine_name: str,
    display: "DisplayOptions",
) -> "object | None":
    """Wire the run's step-progress sink + token-delta seam; return the cockpit sink.

    Extracted from ``execute_work`` (plan t16) with the composition order
    unchanged: the progress sink is built first (so ``--tui``/``--tui-events``/
    an external session sink compose with per-sink failure isolation and the
    default path stays byte-identical :func:`_step_progress`), then the delta
    seam is armed off whatever cockpit sink that produced. The presence half
    stays in ``work.py`` — ``tests/test_work_foreground_presence.py`` is an AST
    pin over that file requiring the ``build_foreground_presence(...,
    render=emit_diagnostic)`` call to be reachable from it.
    """
    config.progress, cockpit_sink = build_progress(
        default_sink=_step_progress,
        task_id=task.id,
        engine=engine_name,
        tui=display.tui,
        tui_events=display.tui_events,
        diag=emit_diagnostic,
        external_sink=display.sink,
    )
    _arm_delta_stream(config, cockpit_sink)
    return cockpit_sink


def _stamp_lineage(
    result: TaskResult,
    command_name: str | None,
    mode: str | None,
    continued_from: str | None,
    continuation_task_text: str | None,
) -> None:
    """``command``/``mode``/``continued_from``/``task_text`` — the four fields
    every write path (success ``_stamp_run_metadata`` and the engine-failure
    handler) records identically before an artifact write. ``task_text`` is
    OVERRIDDEN with the propagated original brief on a continuation
    (:func:`colleague.tasktext.apply_continuation_task_text`, c22/h15/h3) —
    never the synthesized seed the loop's own stamp would otherwise record.
    """
    result.command = command_name
    result.mode = mode
    result.continued_from = continued_from
    tasktext.apply_continuation_task_text(
        result, continued_from=continued_from, continuation_task_text=continuation_task_text
    )


def _stamp_run_metadata(
    result: TaskResult,
    *,
    config: EngineConfig,
    command_name: str | None,
    mode: str | None,
    continued_from: str | None,
    chain: "object | None",
    continuation_task_text: str | None = None,
) -> None:
    """Record the run's origin/lineage/accounting on *result* before the write.

    Extracted from :func:`execute_work` (plan t16); every field keeps its
    omit-when-None serialization, so an ordinary run's artifact shape is
    byte-identical.

    * ``command`` — the originating template name (R5 / c12).
    * ``mode`` — the constraint profile that drove the run (t7 / R3 / #256).
    * ``continued_from`` — the one-way ``--continue`` lineage (#167).
    * ``task_text`` — on a continuation, OVERRIDDEN with the propagated
      ORIGINAL brief (:func:`colleague.tasktext.apply_continuation_task_text`,
      c22/h15/h3) — never the synthesized seed the loop's own stamp would
      otherwise record from ``task.instruction``.
    * ``chain`` — a chained episode's RUNNING :class:`ChainView`, accumulated
      before the write so every episode's artifact is self-describing (c20/h19).
    * ``warnings`` — the stale-pin refresh warnings (t11, h21), the
      ladder-400 retry warnings (#416, Qodo #419 r4), the temperature-knob
      deprecation/removal warnings (reasoning-aware-sampling arc, plan task
      t7, c9/h11), and the continuation recorded-rung mismatch warning
      (effort-v4 t8, c32/h19 — staged on ``config.continuation_warnings`` by
      the continue path and DRAINED here so a long-lived session config
      never re-stamps it), folded so background / one-shot runs surface
      them after the fact.
    """
    _stamp_lineage(result, command_name, mode, continued_from, continuation_task_text)
    if chain is not None:
        result.chain = ChainView.accumulate(chain.prior_view, result)
    if config.model_refresh_warnings:
        result.warnings.extend(asdict(w) for w in config.model_refresh_warnings)
    if config.temperature_deprecation_warnings:
        result.warnings.extend(w.to_dict() for w in config.temperature_deprecation_warnings)
    result.warnings.extend(_vllm_openai.ladder_retry_warnings_as_dicts(config))
    pending = getattr(config, "continuation_warnings", None)
    if pending:
        result.warnings.extend(pending)
        config.continuation_warnings = []
