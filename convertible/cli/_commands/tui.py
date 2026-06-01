"""``convertible tui`` — headless, agent-facing TUI inspection + scenario runner.

The TUI cockpit is a state machine with a single agent-readable mirror (TAUI).
This verb exposes that machine **headlessly** — no real terminal — so an agent
(or a test) can render a frame, read the semantic mirror, resolve and operate
selectors, replay an event log, capture/diagnose a snapshot triple, and run a
JSON scenario as an assertion. Every verb supports ``--json``, sends results to
stdout and diagnostics/errors to stderr, and raises :class:`CliError` on failure
(no traceback ever leaks).

The live TTY driver is a separate concern; this surface stays pure: it touches
no terminal and opens no socket. Scenarios are **JSON** files (NOT YAML —
convertible keeps zero runtime dependencies, so PyYAML is forbidden).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from convertible.cli._commands.overview import emit_overview
from convertible.cli._errors import EXIT_USER_ERROR, CliError
from convertible.cli._output import JSON_HELP, emit_result
from convertible.tui.diagnose import diagnose, diagnose_snapshot
from convertible.tui.events import event_from_dict, loads_events
from convertible.tui.reducer import reduce
from convertible.tui.render.ansi import render
from convertible.tui.replay import replay
from convertible.tui.selectors import SelectorError, resolve, selector_to_event, selectors
from convertible.tui.snapshot import write_snapshot
from convertible.tui.state import CockpitState
from convertible.tui.taui import serialize

# ---------------------------------------------------------------------------
# Shared loaders (every loader maps failure to a CliError — never a traceback)
# ---------------------------------------------------------------------------


def _read_text(path_str: str, *, kind: str) -> str:
    path = Path(path_str).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CliError(
            EXIT_USER_ERROR, f"{kind} file not found: {path}", "check the path and try again"
        ) from exc
    except OSError as exc:
        raise CliError(EXIT_USER_ERROR, f"cannot read {kind} file {path}: {exc}") from exc


def _load_state(path_str: Optional[str]) -> CockpitState:
    """Build a :class:`CockpitState` from ``--state`` (or a fresh default).

    ``CockpitState.from_dict`` tolerates extra keys, so either a CockpitState
    dict or a TAUI mirror (which carries ``taui_version`` / ``available_actions``)
    loads cleanly.
    """
    if not path_str:
        return CockpitState()
    raw = _read_text(path_str, kind="state")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(EXIT_USER_ERROR, f"--state is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CliError(EXIT_USER_ERROR, "--state must contain a JSON object")
    return CockpitState.from_dict(data)


def _load_events(path_str: Optional[str], *, kind: str = "events") -> list:
    if not path_str:
        return []
    raw = _read_text(path_str, kind=kind)
    try:
        return loads_events(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise CliError(EXIT_USER_ERROR, f"cannot parse {kind} JSONL: {exc}") from exc


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------


def _tui_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Headless, agent-facing inspection of the TUI cockpit state machine",
                "No real terminal, no socket — pure state -> mirror/frame transforms",
                "TAUI is the single agent-readable mirror; selectors address every node",
                "Scenarios are JSON (zero-deps: NOT YAML) and run as PASS/FAIL assertions",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "tui render --state <file> — render the ANSI frame for a state",
                "tui state [--state <file>] — print the TAUI mirror as JSON",
                "tui inspect --select <sel> [--state <file>] — resolve a selector to a node",
                "tui action --select <sel> [--state <file>] — operate the UI by selector",
                "tui replay <events.jsonl> [--state <file>] — fold events into a mirror",
                "tui snapshot --name <n> [--state/--events/--dir] — write the triple",
                "tui test --scenario <file.json> — run a scenario (exit 1 on FAIL)",
                "tui diagnose (--dir <d> --name <n> | --taui/--ansi/--events) — classify bugs",
                "tui overview — describe this surface (this command)",
            ],
        },
        {
            "title": "Scenario format (JSON)",
            "items": [
                '{"name", "initial": {state-dict}, "events": [event-dicts],',
                ' "expect": {"popup": {id/visible/blocking}, "focused", "action_available"}}',
                "initial -> CockpitState.from_dict; events folded via reduce; expect checked",
                "on the resulting TAUI mirror; action_available checks the derived selectors.",
            ],
        },
    ]


def cmd_tui_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "convertible tui",
        _tui_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


# ---------------------------------------------------------------------------
# render / state
# ---------------------------------------------------------------------------


def cmd_tui_render(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    state = _load_state(args.state)
    frame = render(state)
    emit_result({"ansi": frame} if json_mode else frame, json_mode=json_mode)
    return 0


def cmd_tui_state(args: argparse.Namespace) -> int:
    state = _load_state(args.state)
    emit_result(serialize(state), json_mode=True)
    return 0


# ---------------------------------------------------------------------------
# inspect / action
# ---------------------------------------------------------------------------


def cmd_tui_inspect(args: argparse.Namespace) -> int:
    state = _load_state(args.state)
    taui = serialize(state)
    try:
        node = resolve(taui, args.select)
    except SelectorError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            str(exc),
            "list addressable selectors with 'tui state --json' (every node carries an id)",
        ) from exc
    emit_result(node, json_mode=True)
    return 0


def cmd_tui_action(args: argparse.Namespace) -> int:
    state = _load_state(args.state)
    taui = serialize(state)
    try:
        event = selector_to_event(taui, args.select)
    except SelectorError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            str(exc),
            "an actionable selector is a popup action (e.g. 'popup.skill.boost.accept')",
        ) from exc
    new_state = reduce(state, event)
    emit_result(serialize(new_state), json_mode=True)
    return 0


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def cmd_tui_replay(args: argparse.Namespace) -> int:
    events = _load_events(args.events_file)
    initial = _load_state(args.state) if args.state else None
    final = replay(events, initial=initial)
    emit_result(serialize(final), json_mode=True)
    return 0


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


def cmd_tui_snapshot(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    state = _load_state(args.state)
    events = _load_events(args.events)
    paths = write_snapshot(args.dir or ".", args.name, state, events)
    str_paths = {key: str(value) for key, value in paths.items()}
    if json_mode:
        emit_result(str_paths, json_mode=True)
    else:
        emit_result("\n".join(str_paths[k] for k in ("taui", "ansi", "events")), json_mode=False)
    return 0


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------


def cmd_tui_diagnose(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    diag = _run_diagnose(args)
    payload = diag.to_dict()
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        emit_result(_render_diagnosis(payload), json_mode=False)
    return 0


def _run_diagnose(args: argparse.Namespace) -> Any:
    """Resolve the two mutually-exclusive diagnose modes into a Diagnosis."""
    if args.dir is not None or args.name is not None:
        if args.dir is None or args.name is None:
            raise CliError(
                EXIT_USER_ERROR,
                "snapshot-dir mode needs both --dir and --name",
                "use '--dir <d> --name <n>' or the explicit '--taui/--ansi' form",
            )
        try:
            return diagnose_snapshot(args.dir, args.name)
        except FileNotFoundError as exc:
            raise CliError(
                EXIT_USER_ERROR, f"snapshot not found: {exc}", "check --dir and --name"
            ) from exc

    if args.taui is None or args.ansi is None:
        raise CliError(
            EXIT_USER_ERROR,
            "diagnose needs either --dir/--name or both --taui and --ansi",
            "see 'convertible tui overview'",
        )
    raw_taui = _read_text(args.taui, kind="taui")
    try:
        taui = json.loads(raw_taui)
    except json.JSONDecodeError as exc:
        raise CliError(EXIT_USER_ERROR, f"--taui is not valid JSON: {exc}") from exc
    ansi = _read_text(args.ansi, kind="ansi")
    events = _load_events(args.events) if args.events else None
    return diagnose(taui, ansi, events)


def _render_diagnosis(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", [])
    if not findings:
        return "no findings — the captured triple agrees"
    lines = [f"{len(findings)} finding(s): {', '.join(payload.get('classes', []))}", ""]
    for finding in findings:
        lines.append(f"[{finding['bug_class']}] {finding['selector']}: {finding['message']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# test (JSON scenario runner)
# ---------------------------------------------------------------------------


def _run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run one scenario dict and return a report ``{name, passed, checks}``.

    Builds ``CockpitState.from_dict(initial)``, folds each event via
    ``event_from_dict`` + ``reduce``, serializes the final state, then checks
    each ``expect`` clause. ``checks`` is a list of ``{clause, ok, detail}``.
    """
    initial = scenario.get("initial") or {}
    if not isinstance(initial, dict):
        raise CliError(EXIT_USER_ERROR, "scenario 'initial' must be a JSON object")
    state = CockpitState.from_dict(initial)

    for raw_event in scenario.get("events", []) or []:
        try:
            event = event_from_dict(raw_event)
        except (ValueError, KeyError, TypeError) as exc:
            raise CliError(EXIT_USER_ERROR, f"bad scenario event {raw_event!r}: {exc}") from exc
        state = reduce(state, event)

    taui = serialize(state)
    expect = scenario.get("expect") or {}
    if not isinstance(expect, dict):
        raise CliError(EXIT_USER_ERROR, "scenario 'expect' must be a JSON object")

    checks: list[dict[str, Any]] = []
    for clause, expected in expect.items():
        checks.append(_check_clause(taui, clause, expected))

    return {
        "name": str(scenario.get("name", "")),
        "passed": all(c["ok"] for c in checks),
        "checks": checks,
    }


def _check_clause(taui: dict[str, Any], clause: str, expected: Any) -> dict[str, Any]:
    if clause == "popup":
        return _check_popup(taui, expected)
    if clause == "focused":
        actual = taui.get("focused")
        return {
            "clause": "focused",
            "ok": actual == expected,
            "detail": f"focused={actual!r} expected={expected!r}",
        }
    if clause == "action_available":
        available = set(selectors(taui)) | {
            a.get("selector") for a in taui.get("available_actions", [])
        }
        ok = expected in available
        return {
            "clause": "action_available",
            "ok": ok,
            "detail": f"{expected!r} {'is' if ok else 'is NOT'} an available action",
        }
    return {
        "clause": clause,
        "ok": False,
        "detail": f"unknown expect clause {clause!r}",
    }


def _check_popup(taui: dict[str, Any], expected: Any) -> dict[str, Any]:
    if not isinstance(expected, dict):
        return {"clause": "popup", "ok": False, "detail": "popup clause must be an object"}
    popup_id = expected.get("id")
    popup = next((p for p in taui.get("popups", []) if p.get("id") == popup_id), None)
    if popup is None:
        return {
            "clause": "popup",
            "ok": False,
            "detail": f"no popup with id {popup_id!r}",
        }
    mismatches = [
        f"{key}={popup.get(key)!r} expected={value!r}"
        for key, value in expected.items()
        if key != "id" and popup.get(key) != value
    ]
    return {
        "clause": "popup",
        "ok": not mismatches,
        "detail": f"popup {popup_id!r} ok" if not mismatches else "; ".join(mismatches),
    }


def cmd_tui_test(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    raw = _read_text(args.scenario, kind="scenario")
    try:
        scenario = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            f"--scenario is not valid JSON: {exc}",
            "scenarios are JSON, not YAML (convertible keeps zero runtime deps)",
        ) from exc
    if not isinstance(scenario, dict):
        raise CliError(EXIT_USER_ERROR, "scenario must be a JSON object")

    report = _run_scenario(scenario)
    emit_result(report if json_mode else _render_report(report), json_mode=json_mode)
    # FAIL is an assertion failure, surfaced as a non-zero exit (exit 1).
    return 0 if report["passed"] else 1


def _render_report(report: dict[str, Any]) -> str:
    verdict = "PASS" if report["passed"] else "FAIL"
    lines = [f"{verdict}: {report['name']}"]
    for check in report["checks"]:
        mark = "ok  " if check["ok"] else "FAIL"
        lines.append(f"  [{mark}] {check['clause']}: {check['detail']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_tui_overview(args)


def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help=JSON_HELP)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "tui",
        help="Headless TUI inspection + JSON scenario runner (see 'convertible tui overview').",
    )
    _add_json(p)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="tui_command", parser_class=type(p))

    rnd = noun_sub.add_parser("render", help="Render the ANSI frame for a state.")
    rnd.add_argument("--state", required=True, help="Path to a CockpitState/TAUI JSON file.")
    _add_json(rnd)
    rnd.set_defaults(func=cmd_tui_render)

    st = noun_sub.add_parser("state", help="Print the TAUI mirror as JSON.")
    st.add_argument("--state", default=None, help="Path to a state JSON file (default: empty).")
    _add_json(st)
    st.set_defaults(func=cmd_tui_state)

    ins = noun_sub.add_parser("inspect", help="Resolve a selector to a node (JSON).")
    ins.add_argument("--select", required=True, help="Dotted selector into the TAUI tree.")
    ins.add_argument("--state", default=None, help="Path to a state JSON file (default: empty).")
    _add_json(ins)
    ins.set_defaults(func=cmd_tui_inspect)

    act = noun_sub.add_parser("action", help="Operate the UI by selector; print the new mirror.")
    act.add_argument("--select", required=True, help="Actionable popup-action selector.")
    act.add_argument("--state", default=None, help="Path to a state JSON file (default: empty).")
    _add_json(act)
    act.set_defaults(func=cmd_tui_action)

    rep = noun_sub.add_parser("replay", help="Fold an events JSONL log into a TAUI mirror.")
    rep.add_argument("events_file", help="Path to a JSONL event log.")
    rep.add_argument("--state", default=None, help="Initial state JSON file (default: empty).")
    _add_json(rep)
    rep.set_defaults(func=cmd_tui_replay)

    snap = noun_sub.add_parser("snapshot", help="Write a snapshot triple (taui/ansi/events).")
    snap.add_argument("--name", required=True, help="Base name for the three files.")
    snap.add_argument("--state", default=None, help="State JSON file (default: empty).")
    snap.add_argument("--events", default=None, help="Events JSONL file (default: empty).")
    snap.add_argument("--dir", default=None, help="Target directory (default: cwd).")
    _add_json(snap)
    snap.set_defaults(func=cmd_tui_snapshot)

    tst = noun_sub.add_parser("test", help="Run a JSON scenario (exit 1 on FAIL).")
    tst.add_argument("--scenario", required=True, help="Path to a JSON scenario file.")
    _add_json(tst)
    tst.set_defaults(func=cmd_tui_test)

    dia = noun_sub.add_parser("diagnose", help="Classify cross-mirror bugs in a triple.")
    dia.add_argument("--dir", default=None, help="Snapshot directory (with --name).")
    dia.add_argument("--name", default=None, help="Snapshot base name (with --dir).")
    dia.add_argument("--taui", default=None, help="TAUI mirror JSON file (with --ansi).")
    dia.add_argument("--ansi", default=None, help="ANSI frame file (with --taui).")
    dia.add_argument("--events", default=None, help="Optional events JSONL file.")
    _add_json(dia)
    dia.set_defaults(func=cmd_tui_diagnose)

    ov = noun_sub.add_parser("overview", help="Describe the tui surface.")
    _add_json(ov)
    ov.set_defaults(func=cmd_tui_overview)
