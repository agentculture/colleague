"""Coherence pre-finish gate — score changed docs via the coherence CLI (#294).

The fourth rack gate (sibling to :mod:`colleague.lint`,
:mod:`colleague.testintegrity`, :mod:`colleague.affectedtests`): after a
non-aborted tool loop, the work item's changed **documentation** artifacts
(``*.md``) are scored with the operator-installed ``coherence`` CLI
(``coherence meaning score <file> --json`` — the Meaning Gradient, the one
shipped scorer in coherence-cli 0.5.x) and the result is recorded on
``TaskResult.coherence_report`` (omit-when-None). Advisory + non-blocking,
always: the git handoff proceeds regardless of any score.

Frame provenance (coherence-cli#10): every score is a *model-relative,
anchor-defined* measurement, never universal meaning. The report therefore
records the embedding frame that produced it — the ``COHERENCE_EMBED_URL`` /
``COHERENCE_EMBED_MODEL`` the subprocess saw (the lobes-resolved embedder when
colleague injected one via :func:`colleague.lobes.embed_env`, the operator's
own env otherwise, or the CLI's documented default when neither is set).
Unknown keys in the CLI's payload (e.g. a future native ``frame`` block from
coherence-cli#10/#11) are passed through verbatim, never dropped.

The consumer seam is pinned by a fixture test copied verbatim from a live
``coherence meaning score --json`` run (see ``tests/test_coherence_gate.py``)
so the coherence-cli#11 domain restructure — which keeps the ``meaning`` noun
stable per its own decision — cannot silently break this gate.

Degradation (h7 — diagnosable, never silent, never fatal):

- coherence CLI not installed        -> ``status="skipped"`` with the reason;
- a per-file failure (the CLI exits non-zero — e.g. exit 2 when the embedding
  endpoint is unreachable; probed live 2026-07-06: ``--json`` emits the
  structured error on stderr and NOTHING on stdout) -> that file is recorded
  with an ``error`` field, the other files still score;
- no changed ``.md`` files           -> the gate is a strict no-op (``None``).

Allow-list: exactly ``coherence`` (this module is a sanctioned subprocess
consumer — see ``tests/test_boundary.py``). No socket, no daemon, no import
of coherence-cli; the CLI is operator-installed, same trust model as the
culture/devague/memory shell-outs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 — sanctioned consumer, see tests/test_boundary.py
from pathlib import Path
from typing import Any, Optional

from .contract import CoherenceReport

ALLOWED_CLI = "coherence"
"""The one CLI this gate may launch (allow-list of exactly one)."""

_SCORE_TIMEOUT = 60
"""Per-file timeout (seconds) for one ``coherence meaning score`` call."""

_KNOWN_PAYLOAD_KEYS = ("meaning_score", "subdimensions", "diagnostics")
"""The pinned v0.5 payload keys; anything else rides through verbatim."""


def _changed_markdown(repo_path: str | Path, changed_files: list[str]) -> list[Path]:
    """The changed files this gate scores: existing ``.md`` files in the repo."""
    root = Path(repo_path)
    out: list[Path] = []
    for rel in sorted(changed_files):
        if not rel.endswith(".md"):
            continue
        path = root / rel
        if path.is_file():
            out.append(path)
    return out


def _parse_cli_error(stderr_text: str) -> str:
    """Best-effort extraction of the CLI's structured error message."""
    try:
        payload = json.loads(stderr_text.strip().splitlines()[-1])
        message = payload.get("message") or payload.get("remediation")
        if isinstance(message, str) and message:
            return message
    except (ValueError, IndexError, AttributeError):
        pass
    return stderr_text.strip()[:500] or "coherence exited non-zero with no error output"


def _score_one(path: Path, repo_path: str | Path, env: dict[str, str]) -> dict[str, Any]:
    """Score ONE file; always returns a record, never raises."""
    rel = str(path.relative_to(Path(repo_path)))
    record: dict[str, Any] = {"path": rel}
    try:
        proc = subprocess.run(  # nosec B603 — allow-listed CLI, no shell
            [ALLOWED_CLI, "meaning", "score", str(path), "--json"],
            capture_output=True,
            text=True,
            timeout=_SCORE_TIMEOUT,
            cwd=str(repo_path),
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    if proc.returncode != 0:
        record["error"] = _parse_cli_error(proc.stderr)
        return record
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        record["error"] = "coherence emitted unparseable JSON"
        return record
    if not isinstance(payload, dict):
        record["error"] = "coherence emitted a non-object payload"
        return record
    # Known keys first (the pinned v0.5 shape), then any future keys verbatim
    # (e.g. a native `frame` provenance block, coherence-cli#10) — pass-through,
    # never dropped.
    for key in _KNOWN_PAYLOAD_KEYS:
        if key in payload:
            record[key] = payload[key]
    for key, value in payload.items():
        if key not in _KNOWN_PAYLOAD_KEYS:
            record[key] = value
    return record


def run_coherence_gate(
    repo_path: str | Path,
    changed_files: list[str],
    env_overrides: Optional[dict[str, str]] = None,
) -> Optional[CoherenceReport]:
    """Score the work item's changed ``.md`` files; advisory, degrade-never-raise.

    ``env_overrides`` carries the lobes-resolved embedder env
    (:func:`colleague.lobes.embed_env`) when armed; the operator's own
    ``os.environ`` always wins over an injected value (the same precedence as
    :mod:`colleague.memory`'s eidetic shell-out).

    Returns ``None`` (a strict no-op — byte-identical ``TaskResult``) when no
    changed ``.md`` file exists **or no embedder is configured**; a ``skipped``
    report when the CLI is absent; a ``scored`` report otherwise.

    **Configured-detection (the lint-gate precedent):** lint fires only when
    the repo *configures* a linter; the coherence analog is an embedder
    endpoint colleague actually knows about — ``COHERENCE_EMBED_URL`` in the
    operator's environment or injected from the lobes-resolved embedder
    (``env_overrides``). Without one, every ``meaning score --json`` call
    exit-2s (probed live 2026-07-06 — no payload on stdout), so an
    unconfigured machine is a strict no-op rather than a noise generator.
    ``config.coherence`` stays default-ON (the #291 operator decision); this
    is the "no linter configured" analog, not an opt-in.
    """
    files = _changed_markdown(repo_path, changed_files)
    if not files:
        return None
    env = {**(env_overrides or {}), **os.environ}
    if not env.get("COHERENCE_EMBED_URL"):
        return None
    if shutil.which(ALLOWED_CLI) is None:
        return CoherenceReport(
            status="skipped",
            reason="coherence CLI not installed (uv tool install coherence-cli)",
        )
    report = CoherenceReport(
        status="scored",
        embed_url=env.get("COHERENCE_EMBED_URL"),
        embed_model=env.get("COHERENCE_EMBED_MODEL"),
    )
    for path in files:
        report.files.append(_score_one(path, repo_path, env))
    return report


def diagnostics_lines(report: CoherenceReport) -> list[str]:
    """Human-readable stderr hint lines for a scored report (may be empty)."""
    lines: list[str] = []
    for record in report.files:
        score = record.get("meaning_score")
        codes = [d.get("code", "?") for d in record.get("diagnostics", []) if isinstance(d, dict)]
        if "error" in record:
            lines.append(f"coherence: {record['path']} — {record['error']}")
        elif codes:
            shown = f"{score:.2f}" if isinstance(score, (int, float)) else "?"
            lines.append(f"coherence: {record['path']} meaning {shown} — hints: {', '.join(codes)}")
    return lines
