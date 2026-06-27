"""``colleague learn-from <source>`` — learn skills from a peer agent.

Reads another agent's skills and adapts them into colleague's own
``.colleague/skills/*.md`` format, so colleague folds them into every backend's
system prompt on the same repo/root. The first (and currently only) source is
``claude`` — Claude Code's ``.claude/skills/<name>/SKILL.md`` directory-per-skill
form; the source is a small registry, so future minds slot in without a CLI change.

Two stages:

1. **Deterministic copy** — :func:`colleague.learn_from.adapt_skills` (stdlib
   only): strip the SKILL.md YAML frontmatter, fold the description into a leading
   summary line, stamp a ``learned-from`` provenance marker, keep the body.
2. **LLM review-and-adapt** (optional; skip with ``--copy-only``) — drive the
   configured backend over each freshly written skill **in the working tree, with
   NO git handoff/branch**, to fix paths/locations and Claude-isms (the Skill
   tool, slash commands) for colleague's own tool surface, then flip the marker
   to ``adapt: claude->colleague``. It degrades to copy-only with a clear notice
   when no backend is reachable.

Honest limit: colleague *loads* skills as instructional text — it does not
execute them. A skill leaning on scripts / the Skill tool / slash commands maps
only partially (surfaced per skill as ``runnable_estimate``).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from colleague import registry
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result
from colleague.config import EngineConfig, resolve_engine
from colleague.contract import Task
from colleague.learn_from import adapt_skills, available_sources

#: Actions whose file was actually written (the stage-2 adapt candidates).
_WRITTEN = {"created", "updated"}
_PENDING_MARK = "adapt: pending"
_DONE_MARK = "adapt: claude->colleague"


def _adapt_instruction(rel_dest: str) -> str:
    """The scoped task for the stage-2 per-skill adapt work item."""
    return (
        "You are adapting a skill that was just copied verbatim from Claude into "
        "this colleague repo. Edit ONLY the file `" + rel_dest + "`.\n\n"
        "It is now a colleague skill doc — instructional text colleague folds into "
        "its model system prompt. colleague does NOT execute skills; it has the "
        "tools read_file/write_file/list_dir/run_command/culture/devague/subagent. "
        "Revise the file so it fits THIS repo and colleague's tool surface:\n"
        "- fix file paths / locations that referred to the source repo or to "
        "`.claude/`;\n"
        "- replace Claude-specific machinery (the Skill tool, slash commands like "
        "/think) with colleague's tools or plain instructions;\n"
        "- keep the skill's intent AND the leading one-line summary as the first "
        "line.\n"
        "Preserve the `<!-- learned-from: ... -->` provenance comment but change "
        "`adapt: pending` to `adapt: claude->colleague`.\n"
        "Do not touch any other file. Save with write_file, then call finish."
    )


def _mark_adapted(path: Path, skills_dir: Path) -> None:
    """Deterministically stamp that stage 2 ran for *path* (pending -> done).

    *path* derives from a skill name (untrusted input), so confine the read/write
    to *skills_dir*: the canonical (realpath) target must sit inside the canonical
    skills dir, else the operation is refused. This is the recognized path-
    traversal guard (S2083) at the read/write sink — defense in depth alongside
    the sanitized stem from :func:`colleague.learn_from._skill_dest`.
    """
    base = os.path.realpath(skills_dir)
    target = os.path.realpath(path)
    if target != base and not target.startswith(base + os.sep):
        return  # outside the skills dir — refuse (path traversal guard)
    try:
        with open(target, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return
    if _PENDING_MARK in text:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text.replace(_PENDING_MARK, _DONE_MARK, 1))


def _run_stage2(args: argparse.Namespace, repo: Path, targets: list) -> dict:
    """Drive the configured backend over each written skill, in place, no handoff.

    Best-effort and isolated: an unreachable backend (or any per-skill failure)
    degrades to copy-only — the stage-1 file stays on disk and the marker stays
    ``adapt: pending``. Returns a small status dict for the report.
    """
    try:
        engine_name = resolve_engine(getattr(args, "engine", None))
        config = EngineConfig.resolve(
            base_url=getattr(args, "base_url", None),
            model=getattr(args, "model", None),
            api_key=getattr(args, "api_key", None),
            max_steps=getattr(args, "max_steps", None),
            repo_path=repo,
        )
        engine = registry.load(engine_name)
    # Any resolution failure degrades to copy-only; it never crashes the verb.
    except Exception as exc:  # noqa: BLE001
        return {
            "ran": False,
            "engine": None,
            "adapted": [],
            "degraded": f"{type(exc).__name__}: {exc}",
        }

    skills_dir = repo / ".colleague" / "skills"
    adapted: list[str] = []
    degraded: str | None = None
    for r in targets:
        dest = Path(r.dest)
        try:
            rel = str(dest.relative_to(repo))
        except ValueError:
            rel = str(dest)
        task = Task.new(str(repo), _adapt_instruction(rel), engine=engine_name)
        try:
            engine.work(task, config)
        # Per-skill failure degrades to copy-only; stop early, keep what landed.
        except Exception as exc:  # noqa: BLE001
            degraded = f"{type(exc).__name__}: {exc}"
            emit_diagnostic(
                f"learn-from: stage-2 adapt degraded at {r.name} ({degraded}); "
                "remaining skills kept copy-only"
            )
            break
        _mark_adapted(dest, skills_dir)
        adapted.append(r.name)
    return {"ran": True, "engine": engine_name, "adapted": adapted, "degraded": degraded}


def cmd_learn_from(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        raise CliError(
            EXIT_USER_ERROR,
            f"repo path is not a directory: {args.repo}",
            "pass --repo pointing at an existing repository",
        )

    source = args.source
    json_mode = bool(getattr(args, "json", False))
    names = list(args.names) if getattr(args, "names", None) else None
    dry_run = bool(getattr(args, "dry_run", False))
    force = bool(getattr(args, "force", False))
    copy_only = bool(getattr(args, "copy_only", False))
    user = bool(getattr(args, "user", False))

    try:
        results = adapt_skills(
            repo, source=source, names=names, dry_run=dry_run, force=force, user=user
        )
    except ValueError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            str(exc),
            f"known sources: {', '.join(available_sources())}",
        ) from exc

    stage2 = {"ran": False, "engine": None, "adapted": [], "degraded": None}
    if not dry_run and not copy_only:
        targets = [r for r in results if r.action in _WRITTEN]
        if targets:
            stage2 = _run_stage2(args, repo, targets)

    payload = {
        "source": source,
        "repo": str(repo),
        "dry_run": dry_run,
        "copy_only": copy_only,
        "skills": [vars(r) for r in results],
        "stage2": stage2,
    }
    emit_result(payload if json_mode else _render(payload), json_mode=json_mode)
    return 0


def _render(payload: dict) -> str:
    head = "learn-from " + payload["source"]
    if payload["dry_run"]:
        head += " (dry-run)"
    elif payload["copy_only"]:
        head += " (copy-only)"
    lines = [f"{head} — {payload['repo']}"]

    skills = payload["skills"]
    if not skills:
        lines.append("(nothing to learn — no skills found in source)")
        return "\n".join(lines)

    for s in skills:
        note = f" — {s['note']}" if s.get("note") else ""
        lines.append(f"  {s['action']:<12} {s['name']}  [{s['runnable_estimate']}]{note}")

    st = payload["stage2"]
    if st["ran"]:
        adapted = ", ".join(st["adapted"]) or "(none)"
        lines.append(f"stage 2 (LLM adapt via {st['engine']}): adapted {adapted}")
        if st["degraded"]:
            lines.append(f"  degraded: {st['degraded']} — remaining kept copy-only")
    elif st["degraded"]:
        lines.append(f"stage 2 skipped (backend unavailable): {st['degraded']} — copy-only")
    return "\n".join(lines)


_LEARN_FROM_HELP = (
    "Learn skills from a peer agent (e.g. claude) into .colleague/skills/ "
    "(see 'colleague explain learn-from')."
)


def _configure_learn_from_parser(p: argparse.ArgumentParser) -> None:
    """Add ``learn-from``'s positional + flags to an already-created parser.

    Shared by the legacy :func:`register` and the host-command ``configure`` hook.
    ``learn-from`` is a host command: it drives the engine for the stage-2 adapt
    pass and carries hyphenated flags (``--dry-run`` / ``--copy-only`` /
    ``--base-url`` / ``--max-steps``) that don't map cleanly to signature-derived
    flags. ``func`` is left for the caller / agentfront to set to
    :func:`cmd_learn_from`.
    """
    p.add_argument("source", help="Skill source to learn from (currently: claude).")
    p.add_argument(
        "names",
        nargs="*",
        help="Optional skill names to learn (default: all discovered).",
    )
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--user",
        action="store_true",
        help="Read from ~/.claude/skills/ instead of <repo>/.claude/skills/.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions (would-create/skip/update) without writing.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing differing or hand-authored skill doc.",
    )
    p.add_argument(
        "--copy-only",
        action="store_true",
        help="Stage 1 only: deterministic copy, skip the LLM adapt pass.",
    )
    # Stage-2 backend knobs (mirror `work`; used only for the adapt pass).
    p.add_argument("--engine", default=None, help="Backend for the stage-2 adapt pass.")
    p.add_argument("--model", default=None, help="Model for the stage-2 adapt pass.")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL for stage 2.")
    p.add_argument("--api-key", default=None, help="API key for stage 2.")
    p.add_argument(
        "--max-steps", type=int, default=None, help="Max tool-loop steps per stage-2 skill."
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("learn-from", help=_LEARN_FROM_HELP)
    _configure_learn_from_parser(p)
    p.set_defaults(func=cmd_learn_from)


def register_into(app) -> None:
    """Register ``learn-from`` as an agentfront host command.

    See :func:`_configure_learn_from_parser` for why it is a host command (engine-
    driving + hyphenated flags). Reuses :func:`cmd_learn_from`'s ``(args) -> int``
    handler verbatim.
    """
    app.add_command(
        "learn-from",
        cmd_learn_from,
        help=_LEARN_FROM_HELP,
        configure=_configure_learn_from_parser,
    )
