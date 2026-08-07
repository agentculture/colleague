"""Distillation child entry — rung-2 lesson distillation via a detached child (t10).

The loop's rung-2 distillation seam (t9) calls an injectable ``distill_fn`` after
the work item completes. This module provides that callable: it resolves the
distillation author by role (lobes cortex when armed, deepthink/muse target in
dual-model mode), detaches a one-shot child via :func:`background.spawn_background`
that re-reads the persisted artifact, distills a structured lesson, validates it
via :mod:`colleague.lessons`, and upserts the SAME work-lesson id with the lesson
folded. The outcome is written as ``distill.json`` next to the artifact.

The run's return is **never** blocked by distillation: the child is detached
(start_new_session=True, no wait/poll) and the parent returns immediately.

Role resolution mirrors deepthink/lobes precedence: env/config always win over
lobes-discovered roles. When no author is resolved the rung-1 floor stands
(byte-identical record, no counters — spec c16/h13).

Sanctioned subprocess consumer: delegates to :func:`background.spawn_background`
(the one-shot detach primitive, plan t12). This module itself never imports
``subprocess`` directly — ``tests/test_boundary.py`` extends its
sanctioned-consumer list to include this module.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from colleague import background, lessons, memory
from colleague.lobes import LobesRoles


@dataclass(frozen=True)
class DistillAuthor:
    """The resolved distillation author — model identity + dial target.

    Mirrors :class:`colleague.lobes.RoleInfo` but carries only the fields
    the distillation child needs to dial the author endpoint.
    """

    model: str
    base_url: str
    api_key: str


def resolve_distill_author(
    config: Any,
    lobes_roles: LobesRoles | None,
) -> DistillAuthor | None:
    """Resolve the distillation author by role precedence (c16, h13).

    Resolution order (highest first):

    1. **Deepthink/muse target** — when ``config.deepthink`` is present and
       carries a non-empty model id, that model is the author. This is the
       dual-model mode: the deepthink model (or lobes-discovered ``muse`` role)
       is the distillation author because it is the stronger reasoner.
    2. **Lobes cortex** — when lobes is armed (``lobes_roles`` is not ``None``),
       the cortex role is the author.
    3. **None** — when neither deepthink nor lobes is configured, no author
       is resolved. The rung-1 floor stands (byte-identical record, no
       counters — spec c16/h13).

    Env/config always win: an explicit ``config.deepthink.model`` from env var
    or config.json overrides any lobes-discovered role.

    Parameters
    ----------
    config:
        The resolved :class:`colleague.config.EngineConfig` (left untyped to
        avoid an import cycle). Read via ``getattr`` for forward compatibility.
    lobes_roles:
        The resolved :class:`colleague.lobes.LobesRoles`, or ``None`` when
        lobes is unarmed or degraded-unreachable.

    Returns
    -------
    DistillAuthor | None
        The resolved author, or ``None`` when no author is available.
    """
    # Rung 1: deepthink/muse target (dual-model mode)
    dt = getattr(config, "deepthink", None)
    if dt is not None:
        dt_model = getattr(dt, "model", None)
        if dt_model and isinstance(dt_model, str) and dt_model.strip():
            dt_base_url = getattr(dt, "base_url", None) or getattr(config, "base_url", "")
            dt_api_key = getattr(dt, "api_key", None) or getattr(config, "api_key", "")
            return DistillAuthor(
                model=dt_model.strip(),
                base_url=dt_base_url or "",
                api_key=dt_api_key or "",
            )

    # Rung 2: lobes cortex (armed gateway)
    if lobes_roles is not None:
        cortex = lobes_roles.cortex
        if cortex is not None:
            return DistillAuthor(
                model=cortex.model,
                base_url=cortex.endpoint or "",
                api_key=getattr(config, "api_key", "") or "",
            )

    # No author — rung-1 floor
    return None


def outcome_marker_path(artifact_path: Path) -> Path | None:
    """The ``distill.json`` outcome marker path next to *artifact_path*.

    Returns ``None`` when *artifact_path* is not a regular file path (e.g.
    the artifact has not been persisted yet).
    """
    if not artifact_path.is_file():
        return None
    return artifact_path.with_suffix(".distill.json")


def write_outcome_marker(
    marker_path: Path,
    *,
    status: str,
    pid: int | None = None,
    lesson: dict[str, str] | None = None,
    reason: str | None = None,
) -> None:
    """Write the outcome marker file (best-effort, never raises).

    The marker is a small JSON file with ``status`` (``pending``/``done``/``dead``),
    an optional ``pid`` (for liveness probing), an optional ``lesson`` dict
    (when ``status == "done"``), and an optional ``reason`` (when ``status == "dead"``).
    """
    try:
        payload: dict[str, Any] = {"status": status, "written_at": time.time()}
        if pid is not None:
            payload["pid"] = pid
        if lesson is not None:
            payload["lesson"] = lesson
        if reason is not None:
            payload["reason"] = reason
        marker_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError:
        pass  # best-effort bookkeeping


def read_outcome_status(marker_path: Path) -> str | None:
    """Read the outcome status from *marker_path*, or ``None`` if absent/corrupt."""
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    status = data.get("status")
    return status if isinstance(status, str) else None


def upsert_lesson(
    repo_path: str | Path,
    task_id: str,
    lesson: dict[str, str],
) -> bool:
    """Validate-then-remember: upsert the SAME work-lesson id with the lesson folded.

    The lesson is validated via :func:`colleague.lessons.validate_lesson` BEFORE
    being remembered. An invalid lesson is **never** stored — no partial record.
    This is the atomic guarantee: validate-then-single-remember (h26).

    The record uses the SAME ``work-lesson-<task_id>`` id as the rung-1 record,
    so eidetic deduplication upserts in place rather than creating a duplicate.

    Parameters
    ----------
    repo_path:
        The repo root (for eidetic CLI cwd).
    task_id:
        The work item's task id (used to build the record id).
    lesson:
        The validated lesson dict (``cause``, ``lesson``, ``next_delta``).

    Returns
    -------
    bool
        ``True`` if the lesson was validated and remembered, ``False`` otherwise.
    """
    verdict = lessons.validate_lesson(lesson)
    if not verdict.allowed:
        return False

    # Build the record with the SAME work-lesson id as rung-1.
    # The text folds the structured lesson into the free-form field.
    text = (
        f" Lesson (origin=model): cause: {lesson['cause']} — "
        f"lesson: {lesson['lesson']} — next time: {lesson['next_delta']}."
    )
    record = memory.build_lesson_record(
        task_id,
        text,
        metadata={
            "topic": "colleague-work-lesson",
            "distill": "validated",
            "lesson_origin": "model",
        },
    )
    return memory.remember(repo_path, record)


def _build_child_argv(
    repo_path: str | Path,
    task_id: str,
    author_model: str,
    author_base_url: str,
    author_api_key: str,
) -> list[str]:
    """Build the argv for the distillation child process.

    The child re-invokes the colleague CLI with a distillation subcommand,
    passing the artifact path and author credentials via env vars.
    """
    return [
        sys.executable,
        "-m",
        "colleague",
        "distill",
        "--repo",
        str(Path(repo_path).resolve()),
        "--task-id",
        task_id,
        "--model",
        author_model,
    ]


def _child_env(
    author_base_url: str,
    author_api_key: str,
) -> dict[str, str]:
    """Build the child environment with author credentials."""
    env = dict(os.environ)
    env["COLLEAGUE_DISTILL_BASE_URL"] = author_base_url
    env["COLLEAGUE_DISTILL_API_KEY"] = author_api_key
    return env


def detach_distill_child(
    repo_path: str | Path,
    task_id: str,
    author_model: str,
    author_base_url: str,
    author_api_key: str,
) -> background.BackgroundHandle | None:
    """Detach the distillation child via the sanctioned one-shot pattern.

    Uses :func:`background.spawn_background` (start_new_session=True, no
    wait/poll) — the same one-shot detach primitive as ``--background``.
    The child re-invokes the colleague CLI to perform the distillation.

    Returns the :class:`background.BackgroundHandle` on success, or ``None``
    on any failure (the parent never blocks or raises).

    Parameters
    ----------
    repo_path:
        The repo root.
    task_id:
        The work item's task id.
    author_model:
        The distillation author's model id.
    author_base_url:
        The distillation author's base URL.
    author_api_key:
        The distillation author's API key.
    """
    try:
        argv = _build_child_argv(repo_path, task_id, author_model, author_base_url, author_api_key)
        child_env = _child_env(author_base_url, author_api_key)
        return background.spawn_background(
            repo_path,
            argv,
            env=child_env,
        )
    except Exception:
        return None


def make_distill_fn(
    repo_path: str | Path,
    author_model: str | None,
    author_base_url: str | None,
    author_api_key: str | None,
) -> Any | None:
    """Build the injectable ``distill_fn`` for the loop's rung-2 seam.

    Returns a callable ``(result, request_head) -> None`` that detaches the
    distillation child and returns immediately (non-blocking). When no author
    is resolved (``author_model`` is ``None``), returns ``None`` — the rung-1
    floor (byte-identical record, no counters — spec c16/h13).

    The returned callable **never raises**: any failure is caught and the
    child is detached. The run's return is never blocked by distillation.

    Parameters
    ----------
    repo_path:
        The repo root.
    author_model:
        The distillation author's model id, or ``None`` for no author.
    author_base_url:
        The distillation author's base URL.
    author_api_key:
        The distillation author's API key.

    Returns
    -------
    callable | None
        The non-blocking distill_fn, or ``None`` when no author is resolved.
    """
    if not author_model:
        return None

    def distill_fn(result: Any, request_head: str = "") -> None:
        """Detach the distillation child and return immediately.

        This is the callable the loop injects as ``ctx.distill_fn``. It
        detaches a child process that performs the distillation and returns
        immediately — the run's return is never blocked.

        Returns ``None`` (the raw text is written by the child, not returned).
        """
        try:
            detach_distill_child(
                repo_path=repo_path,
                task_id=result.task_id,
                author_model=author_model,
                author_base_url=author_base_url or "",
                author_api_key=author_api_key or "",
            )
        except Exception:
            pass  # never block the run
        return None

    # The loop's remember seam distinguishes a detached (child-owned) outcome
    # from a sync no-lesson refusal by this marker (t16): a detached seam
    # records ``distill: detached`` — the child + outcome marker own the
    # eventual validated/failed state, and the artifact's validated count is
    # honest-at-return, never a false ``no-lesson-extracted``.
    distill_fn.detached = True  # type: ignore[attr-defined]
    return distill_fn


def resolve_distill_author_from_config(config: Any) -> DistillAuthor | None:
    """Resolve the distillation author from a resolved config ALONE (t16).

    The config-only twin of :func:`resolve_distill_author` for the
    ``ContextControls.from_config`` seam, which has no ``LobesRoles`` object —
    by resolution time the lobes rung has already collapsed into the config:
    an ARMED gateway leaves ``config.lobes_gateway_url`` set and the MAIN
    model already resolved FROM the cortex role. Precedence (c16/c32):

    1. deepthink/muse target (``config.deepthink.model``) — the stronger
       reasoner authors the lesson in dual-model mode;
    2. the armed-lobes main model (cortex-resolved) when
       ``config.lobes_gateway_url`` is set;
    3. ``None`` — the rung-1 floor (byte-identical record, no counters).
    """
    dt = getattr(config, "deepthink", None)
    if dt is not None:
        dt_model = getattr(dt, "model", None)
        if dt_model and isinstance(dt_model, str) and dt_model.strip():
            return DistillAuthor(
                model=dt_model.strip(),
                base_url=getattr(dt, "base_url", None) or getattr(config, "base_url", "") or "",
                api_key=getattr(dt, "api_key", None) or getattr(config, "api_key", "") or "",
            )
    if getattr(config, "lobes_gateway_url", None):
        model = getattr(config, "model", "") or ""
        if model:
            return DistillAuthor(
                model=model,
                base_url=getattr(config, "base_url", "") or "",
                api_key=getattr(config, "api_key", "") or "",
            )
    return None
