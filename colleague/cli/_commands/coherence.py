"""``colleague coherence`` — on-demand coherence measurement of colleague's work.

Coherence scores measure the semantic quality of documentation artifacts
(``*.md`` files) via the operator-installed ``coherence`` CLI
(``coherence meaning score <file> --json``). The measurement is **advisory**
and **never a gate**: it informs but never blocks the work item handoff.

``coherence score PATH [PATH...]`` scores arbitrary markdown files by
reusing the existing scoring machinery in :mod:`colleague.coherence`.

``coherence show TASK_ID`` (also ``last``) resolves a finished work item's
artifact, scores its recorded changed ``.md`` files if any, and reports the
artifact's existing ``coherence_report`` block when present.

Read-only: no writes to the repo, no new subprocess consumers (reuses the
sanctioned path in :mod:`colleague.coherence`).

Degradation: when the ``coherence`` CLI is not installed, every verb reports
a clean actionable message (never a traceback). ``overview`` still exits 0;
``score``/``show`` raise :class:`CliError` with a remediation hint.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from colleague.artifact import find_artifact
from colleague.cli._commands.overview import render_text
from colleague.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result, rendered
from colleague.coherence import (
    ALLOWED_CLI,
    _score_one,
    diagnostics_lines,
)
from colleague.feedback import get_last_work


def embed_env() -> dict[str, str]:
    """Embedder env overrides via the SAME resolution the runtime uses.

    Delegates to ``EngineConfig.resolve(repo_path=cwd)``, whose lobes-discovery
    rung fills ``.embed_env`` (``{}`` when unarmed / unreachable / no embedder
    role) — one path, so this verb can never drift from the #294 gate.
    ``colleague.lobes.embed_env`` itself takes ``(roles, gateway_url)``; calling
    it directly here would re-derive what ``resolve()`` already composes.
    """
    from colleague.config import EngineConfig

    return EngineConfig.resolve(repo_path=Path.cwd()).embed_env


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _coherence_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "On-demand coherence measurement of colleague's work artifacts",
                "Scores markdown files via the coherence CLI (Meaning Gradient)",
                "Advisory only — never a gate: scores inform but never block handoff",
                "Reuses the same scoring machinery as the pre-finish coherence gate",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "coherence overview — describe the coherence surface (this command)",
                "coherence score PATH [PATH...] — score markdown file(s) directly",
                "coherence show TASK_ID|last — score a work item's changed .md files "
                "and report its coherence_report block",
            ],
        },
        {
            "title": "Degradation",
            "items": [
                "When the coherence CLI is not installed, overview still exits 0",
                "score/show raise a structured CliError with a remediation hint",
            ],
        },
    ]


def _coherence_overview() -> object:
    sections = _coherence_sections()
    return rendered(
        {"subject": "colleague coherence", "sections": sections},
        render_text("colleague coherence", sections),
    )


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------


def _check_cli_installed() -> None:
    """Raise CliError when the coherence CLI is not installed."""
    if shutil.which(ALLOWED_CLI) is None:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message="coherence CLI not installed",
            remediation="install with: uv tool install coherence-cli",
        )


def _render_score_lines(records: list[dict[str, Any]]) -> list[str]:
    """Render one text line per scored record, plus its diagnostics hints.

    Extracted from ``_score_files`` (S3776): the nested for/if-else/for was
    the bulk of that function's cognitive complexity.
    """
    lines: list[str] = []
    for record in records:
        path = record.get("path", "?")
        if "error" in record:
            lines.append(f"  {path}: error — {record['error']}")
            continue
        score = record.get("meaning_score")
        score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "?"
        lines.append(f"  {path}: meaning {score_str}")
        fake_report = type("R", (), {"status": "scored", "files": [record]})()
        for hint in diagnostics_lines(fake_report):
            lines.append(f"    {hint}")
    return lines


def _score_files(paths: list[str] | str) -> object:
    """Score markdown file path(s) and return a rendered result.

    Accepts a single path string as well as a list: the agentfront-rendered
    tool surface has no variadic positionals (a ``list[str]`` annotation
    renders as ONE string argument), so the rendered ``coherence score``
    passes a lone string — iterating it raw would score per-character
    (caught live). Multi-path calls arrive as a real list via the legacy
    argparse path (``nargs="+"``); a variadic rendered surface is a
    possible agentfront upstream ask.
    """
    if isinstance(paths, str):
        paths = [paths]
    _check_cli_installed()

    # Resolve embedder env from lobes (same as the gate path)
    env_overrides = embed_env()
    env = {**(env_overrides or {}), **os.environ}

    # Require an embedder endpoint (same configured-detection as the gate)
    if not env.get("COHERENCE_EMBED_URL"):
        raise CliError(
            code=EXIT_ENV_ERROR,
            message="no coherence embedder configured",
            remediation="set COHERENCE_EMBED_URL to an embedding endpoint, "
            "or install the lobes gateway (uv tool install lobes-gateway)",
        )

    records: list[dict[str, Any]] = []
    for path_str in paths:
        # Resolve BEFORE calling: _score_one runs the CLI with cwd=repo_path,
        # so a relative path + cwd=path.parent would double the prefix
        # (docs/docs/… — caught live).
        path = Path(path_str).resolve()
        if not path.is_file():
            emit_diagnostic(f"coherence: skipping non-file {path_str}")
            continue
        record = _score_one(path, path.parent, env)
        records.append(record)

    if not records:
        return rendered(
            {"files": [], "scores": []},
            "no valid markdown files to score",
        )

    # Build structured payload with provenance
    payload: dict[str, Any] = {
        "files": records,
        "embed_url": env.get("COHERENCE_EMBED_URL"),
        "embed_model": env.get("COHERENCE_EMBED_MODEL"),
    }

    text = "coherence scores:\n" + "\n".join(_render_score_lines(records))
    return rendered(payload, text)


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------


def _resolve_task_id(ref: str, repo_path: Path) -> str:
    """Resolve ``ref`` ("last" or an explicit task-id) to a concrete task_id."""
    if ref != "last":
        return ref
    task_id = get_last_work(repo_path)
    if not task_id:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="no 'last' work item recorded for this repo",
            remediation="run a work item first, or pass an explicit task-id",
        )
    return task_id


def _load_artifact(repo_path: Path, task_id: str) -> tuple[Path, dict[str, Any]]:
    """Find and parse a work item's JSON artifact; raises CliError on failure."""
    artifact_path = find_artifact(repo_path, task_id)
    if artifact_path is None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no artifact found for task {task_id!r}",
            remediation="check the task-id, or run 'colleague feedback list' to see recorded items",
        )
    try:
        artifact_data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"cannot read artifact for {task_id}: {exc}",
            remediation="the artifact file may be corrupt",
        ) from exc
    return artifact_path, artifact_data


def _score_changed_docs(
    md_files: list[str], repo_path: Path
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Score a work item's changed ``.md`` files; degrades to an empty result.

    Returns ``(scored_records, embed_url, embed_model)``. With no changed
    markdown files, or no embedder configured, returns ``([], None, None)`` —
    the caller renders "no scores" / "no changed .md files" from that, the
    same degradation the inline version used.
    """
    if not md_files:
        return [], None, None
    _check_cli_installed()
    env_overrides = embed_env()
    env = {**(env_overrides or {}), **os.environ}
    if not env.get("COHERENCE_EMBED_URL"):
        # If no embedder, still show the existing report if present.
        emit_diagnostic(
            "coherence: no embedder configured, skipping live scoring. "
            "Set COHERENCE_EMBED_URL to score files."
        )
        return [], None, None
    scored: list[dict[str, Any]] = []
    for rel_path in md_files:
        full_path = repo_path / rel_path
        if full_path.is_file():
            scored.append(_score_one(full_path, repo_path, env))
    return scored, env.get("COHERENCE_EMBED_URL"), env.get("COHERENCE_EMBED_MODEL")


def _format_score_record(record: dict[str, Any]) -> str:
    """Render one scored-file record for text output, including an error case."""
    path = record.get("path", "?")
    if "error" in record:
        return f"  {path}: error — {record['error']}"
    score = record.get("meaning_score")
    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "?"
    return f"  {path}: meaning {score_str}"


def _format_report_entry(entry: dict[str, Any]) -> str:
    """Render one existing ``coherence_report`` file entry (no error case)."""
    path = entry.get("path", "?")
    score = entry.get("meaning_score")
    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "?"
    return f"  {path}: meaning {score_str}"


def _render_show_text(
    task_id: str,
    artifact_path: Path,
    scored_files: list[dict[str, Any]],
    md_files: list[str],
    existing_report: dict[str, Any] | None,
) -> str:
    """Render the ``coherence show`` text block from its already-resolved parts."""
    lines: list[str] = [f"task: {task_id}", f"artifact: {artifact_path}"]

    if scored_files:
        lines.append("scores:")
        lines.extend(_format_score_record(record) for record in scored_files)
    elif md_files:
        lines.append("no scores (no embedder configured or files not found)")
    else:
        lines.append("no changed .md files in this work item")

    if existing_report is not None:
        lines.append("existing coherence_report:")
        lines.append(f"  status: {existing_report.get('status', '?')}")
        lines.extend(_format_report_entry(f) for f in existing_report.get("files") or [])
    else:
        lines.append("no existing coherence_report in artifact")

    return "\n".join(lines)


def _show_task(ref: str, repo: str = ".") -> object:
    """Show coherence for a work item: score its changed .md files + report block."""
    repo_path = Path(repo).expanduser()
    task_id = _resolve_task_id(ref, repo_path)
    artifact_path, artifact_data = _load_artifact(repo_path, task_id)

    existing_report = artifact_data.get("coherence_report")
    stats = artifact_data.get("stats") or {}
    changed_files: list[str] = stats.get("changed_files") or []
    md_files = [f for f in changed_files if f.endswith(".md")]

    scored_files, embed_url, embed_model = _score_changed_docs(md_files, repo_path)

    result: dict[str, Any] = {"task_id": task_id, "artifact": str(artifact_path)}
    if scored_files:
        result["scores"] = scored_files
        result["embed_url"] = embed_url
        result["embed_model"] = embed_model
    result["existing_report"] = existing_report

    text = _render_show_text(task_id, artifact_path, scored_files, md_files, existing_report)
    return rendered(result, text)


# ---------------------------------------------------------------------------
# Registry registration (agentfront App)
# ---------------------------------------------------------------------------


def register_into(app) -> None:
    """Register the coherence noun group onto the agentfront App registry."""
    g = app.group("coherence")
    g.tool(
        _coherence_overview,
        name="overview",
        description="Describe the coherence measurement surface.",
        doc="# coherence overview\n"
        "Describe the coherence measurement surface: what it is, "
        "that it is advisory and never a gate, and the available verbs.",
    )
    g.tool(
        _score_files,
        name="score",
        description="Score markdown file(s) via the coherence CLI.",
        doc="# coherence score PATH [PATH...]\n"
        "Score one or more markdown files using the coherence CLI "
        "(Meaning Gradient). Reuses the same scoring machinery as "
        "the pre-finish coherence gate. Supports --json.",
    )
    g.tool(
        _show_task,
        name="show",
        description="Show coherence for a work item (score its .md files + report block).",
        doc="# coherence show TASK_ID|last [--repo P]\n"
        "Resolve a finished work item's artifact, score its changed .md files, "
        "and report the artifact's existing coherence_report block when present. "
        "Accepts 'last' for the most recent work item.",
    )


# ---------------------------------------------------------------------------
# Legacy argparse path (pre-flip)
# ---------------------------------------------------------------------------


def cmd_coherence_overview(args: argparse.Namespace) -> int:
    emit_result(_coherence_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_coherence_score(args: argparse.Namespace) -> int:
    emit_result(
        _score_files(args.paths),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_coherence_show(args: argparse.Namespace) -> int:
    emit_result(
        _show_task(args.ref, getattr(args, "repo", ".")),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_coherence_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    """Register the coherence noun on the legacy argparse sub-parser."""
    p = sub.add_parser(
        "coherence",
        help="On-demand coherence measurement (see 'colleague coherence overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="coherence_command", parser_class=type(p))

    # score PATH [PATH...]
    sc = noun_sub.add_parser(
        "score",
        help="Score markdown file(s) via the coherence CLI.",
    )
    sc.add_argument(
        "paths",
        nargs="+",
        help="Paths to markdown files to score.",
    )
    sc.add_argument("--json", action="store_true", help=JSON_HELP)
    sc.set_defaults(func=cmd_coherence_score)

    # show TASK_ID|last
    sh = noun_sub.add_parser(
        "show",
        help="Show coherence for a work item.",
    )
    sh.add_argument(
        "ref",
        help="Work-item task-id, or 'last' for the most recent work item.",
    )
    sh.add_argument(
        "--repo",
        default=".",
        help="Path to the target repository (default: cwd).",
    )
    sh.add_argument("--json", action="store_true", help=JSON_HELP)
    sh.set_defaults(func=cmd_coherence_show)

    # overview
    ov = noun_sub.add_parser(
        "overview",
        help="Describe the coherence measurement surface.",
    )
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_coherence_overview)
