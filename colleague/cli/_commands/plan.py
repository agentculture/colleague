"""``colleague plan`` — colleague plans a complex task (the plan-mode verb).

Same arc as the ``/think`` -> ``/spec-to-plan`` -> ``/assign-to-workforce`` skills,
but with COLLEAGUE as the planning mind: it proposes spec claims, you gate each
one, it proposes a split plan, then it fans the waves out to a subagent-colleague
workforce. The orchestration lives in :mod:`colleague.plan.orchestrator` (engine-
agnostic); this verb wires the live backend and the operator's per-item gate.

Verbs: ``plan "<request>"`` (run), ``plan status`` (read the last checkpoint),
``plan overview``. Results to stdout, diagnostics to stderr; every verb supports
``--json``. The operator gates each proposed item on stdin (a TTY); ``--yes``
auto-confirms for non-interactive/agent use.

v1 scope: the cross-invocation ``plan continue`` resume is a documented follow-up
(the interactive session gates every sub-step within one invocation). Plan mode
needs a live backend (the ``mock`` engine has no model).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from colleague import registry
from colleague.cli._commands.overview import emit_overview
from colleague.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result
from colleague.config import EngineConfig, resolve_engine
from colleague.plan import checkpoint as ckpt
from colleague.plan.cli_driver import (
    make_propose_claims,
    make_propose_plan_items,
    robust_simple_complete,
)
from colleague.plan.orchestrator import run_plan_mode
from colleague.subagents import make_batch_spawn, new_agent_budget

_PLAN_ID = "plan"


def _plan_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Colleague plans a complex task: spec -> plan -> subagent workforce",
                "Same arc as think -> spec-to-plan -> workforce; colleague is the planner",
                "You gate each proposed item (a different mind proposes; you confirm)",
                "Needs a live backend (mock has no model)",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                'plan "<request>" [--repo P] [--engine E] [--yes] [--review] [--json]',
                "  [--quick/--no-spec] skip the spec stage; [--no-workforce] plan only",
                "plan status [--repo P] [--json] — read the last plan checkpoint",
                "plan overview — describe the plan surface (this command)",
            ],
        },
        {
            "title": "Gating",
            "items": [
                "Default: gate each proposed claim on stdin (a TTY)",
                "--yes: auto-confirm every gate (non-interactive / agent use)",
                "--review: run the same-model critic before each gate",
            ],
        },
    ]


def _auto_decide(_item: Any, _critique: Any) -> str:
    return "confirm"


def _stdin_decide(item: Any, critique: Any) -> str:
    if critique:
        text = getattr(critique, "text", None) or str(critique)
        emit_diagnostic(f"critic: {text}")
    kind = getattr(item, "kind", "item")
    body = getattr(item, "text", "")
    sys.stderr.write(f"confirm {kind} {item.id}: {body}\n[y/N]? ")
    sys.stderr.flush()
    answer = sys.stdin.readline().strip().lower()
    return "confirm" if answer in ("y", "yes") else "reject"


def _resolve_decide(args: argparse.Namespace):
    if getattr(args, "yes", False):
        return _auto_decide
    if not sys.stdin.isatty():
        raise CliError(
            EXIT_USER_ERROR,
            "plan mode needs an interactive terminal to gate each item",
            "re-run with --yes to auto-confirm every gate (non-interactive)",
        )
    return _stdin_decide


def _render_run(result: Any) -> str:
    lines = [f"converged: {result.converged}"]
    if not result.converged:
        conv = result.spec_result.result
        missing = conv.missing_kinds
        # #224: the gate also fails on spec-affecting claims that lack a confirmed
        # honesty condition. Surfacing only missing_kinds rendered "missing: (none)"
        # when honesty was the sole gap — a non-actionable dead end. Name both.
        missing_honesty = getattr(conv, "claims_missing_honesty", [])
        if missing:
            lines.append(f"spec gate not passed; missing: {', '.join(missing)}")
        if missing_honesty:
            lines.append(
                "claims missing a confirmed honesty condition: " + ", ".join(missing_honesty)
            )
        if not missing and not missing_honesty:
            # Defensive + unreachable: converge() only fails with a non-empty
            # missing_kinds or claims_missing_honesty, so this never fires in
            # practice. Still, never report a silent "(none)" — if it ever does,
            # it is a gate bug worth surfacing, not a clean result.
            lines.append("spec gate not passed; no reason recorded (unexpected gate bug)")
        return "\n".join(lines)
    lines.append(f"plan items: {len(result.plan_items)}")
    lines.append(f"waves: {result.waves}")
    lines.append(f"sub-results: {len(result.sub_results)}")
    lines.append(f"conflicts: {len(result.conflicts)}")
    if result.conflicts:
        lines.append("CONFLICTS surfaced (not force-merged) — resolve the sub/<id> branches:")
        for sub in result.conflicts:
            lines.append(f"  - {getattr(sub, 'summary', '(conflict)')}")
    return "\n".join(lines)


def _run_payload(result: Any) -> dict[str, Any]:
    conv = result.spec_result.result
    return {
        "converged": result.converged,
        "missing_kinds": conv.missing_kinds,
        # #224: a machine consumer needs the honesty-gap reason too, else a
        # non-converged run serialized {converged: false, missing_kinds: []}.
        "claims_missing_honesty": getattr(conv, "claims_missing_honesty", []),
        "plan_items": [i.id for i in result.plan_items],
        "waves": result.waves,
        "sub_results": len(result.sub_results),
        "conflicts": len(result.conflicts),
    }


def cmd_plan_overview(args: argparse.Namespace) -> int:
    emit_overview("colleague plan", _plan_sections(), json_mode=bool(getattr(args, "json", False)))
    return 0


def run_plan_request(
    *,
    repo: Path,
    request: str,
    engine_name: str,
    config: EngineConfig,
    decide,
    quick: bool,
    workforce: bool,
    review: bool = False,
):
    """Run colleague plan mode for a single *request* and return the result.

    Factored out of :func:`cmd_plan_run` so other surfaces (the interactive
    session's intent router, #234) can drive plan mode without rebuilding the
    engine seams. The caller resolves ``engine_name`` + ``config`` and chooses
    the ``decide`` gate (:func:`_auto_decide` for non-interactive callers).

    Raises :class:`CliError` (never a traceback) on an unknown engine, a
    non-live backend (``make_complete`` not implemented, e.g. ``mock``), or an
    unusable model proposal.
    """
    try:
        engine = registry.load(engine_name)
    except registry.UnknownEngine as exc:
        raise CliError(EXIT_USER_ERROR, str(exc), "see 'colleague backends list'") from exc

    try:
        complete = engine.make_complete(config)
    except NotImplementedError as exc:
        raise CliError(
            EXIT_ENV_ERROR,
            str(exc),
            "use a live backend, e.g. --engine vllm-openai",
        ) from exc

    simple = robust_simple_complete(complete)
    # ONE shared agent budget so the global MAX_SUBAGENT_TOTAL cap is enforced for
    # the plan workforce fan-out too (#t4 Q3 wiring fix).
    batch_spawn = make_batch_spawn(str(repo), config, engine_name, counter=new_agent_budget(config))

    try:
        return run_plan_mode(
            request,
            propose_claims=make_propose_claims(simple),
            decide=decide,
            propose_plan_items=make_propose_plan_items(simple),
            batch_spawn=batch_spawn,
            engine=engine_name,
            model=config.model,
            complete=simple,
            reviewer_enabled=review,
            repo_path=str(repo),
            plan_id=_PLAN_ID,
            quick=quick,
            workforce=workforce,
        )
    except ValueError as exc:
        # The model returned a malformed proposal (unparseable JSON, an invalid
        # plan-item set, or a cyclic/dangling dependency graph). Surface a clean
        # error, never a traceback (the agent-first no-traceback contract).
        raise CliError(
            EXIT_USER_ERROR,
            f"the backend returned an unusable plan proposal: {exc}",
            "retry, or use a stronger backend/model",
        ) from exc


def cmd_plan_run(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        raise CliError(EXIT_USER_ERROR, f"repo path is not a directory: {args.repo}", "pass --repo")

    engine_name = resolve_engine(args.engine)
    config = EngineConfig.resolve(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        repo_path=repo,
    )
    result = run_plan_request(
        repo=repo,
        request=args.request,
        engine_name=engine_name,
        config=config,
        decide=_resolve_decide(args),
        quick=bool(getattr(args, "quick", False)),
        workforce=not bool(getattr(args, "no_workforce", False)),
        review=bool(getattr(args, "review", False)),
    )

    emit_result(_run_payload(result) if json_mode else _render_run(result), json_mode=json_mode)
    return 0 if result.converged else EXIT_USER_ERROR


def cmd_plan_status(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    checkpoint = ckpt.load(_PLAN_ID, str(repo))
    if checkpoint is None:
        payload: dict[str, Any] = {"plan_id": _PLAN_ID, "checkpoint": None}
        text = f"no plan checkpoint yet for '{_PLAN_ID}'"
    else:
        payload = checkpoint.to_dict()
        text = "\n".join(
            [
                f"plan:             {checkpoint.plan_id}",
                f"recommended_move: {checkpoint.recommended_move}",
                f"resolved_gates:   {len(checkpoint.resolved_gates)}",
                f"proposed_item:    {checkpoint.proposed_item or '(none)'}",
            ]
        )
    emit_result(payload if json_mode else text, json_mode=json_mode)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_plan_overview(args)


_PLAN_HELP = "Colleague plans a complex task (see 'colleague plan overview')."


def _configure_plan_parser(p: argparse.ArgumentParser) -> None:
    """Add ``plan``'s ``--json`` + run/status/overview subcommands to an
    already-created parser.

    Shared by the legacy :func:`register` (pre-flip argparse path) and the
    agentfront host-command ``configure`` hook (:func:`register_into`) so both
    doors build a byte-identical surface. It does NOT set ``func`` on *p* itself:
    the legacy path sets ``func=_no_verb`` after calling this, and the
    host-command path lets agentfront set ``func=`` to the handler it was
    registered with (``_no_verb`` — bare ``plan`` → overview). Each subcommand
    parser sets its own ``func``, which wins when that subcommand is chosen.
    """
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(json=False)
    noun_sub = p.add_subparsers(dest="plan_command", parser_class=type(p))

    run = noun_sub.add_parser("run", help="Plan a task end to end (spec -> plan -> workforce).")
    _add_run_args(run)
    run.set_defaults(func=cmd_plan_run)

    st = noun_sub.add_parser("status", help="Read the last plan checkpoint.")
    st.add_argument("--repo", default=".", help="Target repository (default: cwd).")
    st.add_argument("--json", action="store_true", help=JSON_HELP)
    st.set_defaults(func=cmd_plan_status)

    ov = noun_sub.add_parser("overview", help="Describe the plan surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_plan_overview)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("plan", help=_PLAN_HELP)
    _configure_plan_parser(p)
    p.set_defaults(func=_no_verb)


def register_into(app) -> None:
    """Register the ``plan`` noun-group as an agentfront host command.

    ``plan run`` returns a custom exit code (``0`` when the spec converges, else
    ``EXIT_USER_ERROR``) with the result still on stdout — the same "print a
    result AND exit non-zero" semantic ``work`` has, which agentfront's rendered
    tool dispatch (return → emit, exit 0) cannot express. A noun is moreover
    *either* a tool-group *or* a host command, never both, so the whole ``plan``
    group (run/status/overview) is registered as one host command reusing the
    existing handlers verbatim via :func:`_configure_plan_parser`.
    """
    app.add_command("plan", _no_verb, help=_PLAN_HELP, configure=_configure_plan_parser)


def _add_run_args(run: argparse.ArgumentParser) -> None:
    run.add_argument("request", help="The task to plan.")
    run.add_argument("--repo", default=".", help="Target repository (default: cwd).")
    run.add_argument("--engine", default=None, help="Backend engine (default: COLLEAGUE_ENGINE).")
    run.add_argument("--model", default=None, help="Model id override.")
    run.add_argument("--base-url", default=None, help="Provider base URL override.")
    run.add_argument("--api-key", default=None, help="Provider API key override.")
    run.add_argument(
        "--yes", action="store_true", help="Auto-confirm every gate (non-interactive)."
    )
    run.add_argument(
        "--review", action="store_true", help="Run the same-model critic before each gate."
    )
    run.add_argument(
        "--quick",
        "--no-spec",
        dest="quick",
        action="store_true",
        help="Skip the spec stage; plan directly from the request (#199).",
    )
    run.add_argument(
        "--no-workforce",
        dest="no_workforce",
        action="store_true",
        help="Plan only: deliver the spec+plan, skip the workforce fan-out (#215).",
    )
    run.add_argument("--json", action="store_true", help=JSON_HELP)
