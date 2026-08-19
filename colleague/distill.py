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

import contextlib
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


# ---------------------------------------------------------------------------
# Authority-separation guard (spec c38/h30) — forward-compatible for t12's
# armed evaluation mode.
# ---------------------------------------------------------------------------
#
# The three-tier / evaluation arc being built by later plan tasks (t10 defines
# the evaluator's closed-world thought<->action judgment contract; t12 arms
# it) introduces a seat that judges thought<->action pairs. That seat is
# resolved BY ROLE — today the SAME role (``cortex``) this module already
# falls back to for distillation. Left unguarded, the fallback below would
# silently hand a seat serving as evaluator the authority to write durable
# memory as the distiller, even though the two are distinct authority
# contracts: the evaluator judges and CANNOT write memory; the distiller
# distills post-outcome and runs only when evidence exists.
#
# Neither ``evaluator_checkpoint`` nor ``distiller_checkpoint`` is set by any
# config path today (that arming is t12's territory) — both are read via
# ``getattr`` so this guard activates the moment a later task starts
# populating them, and is an inert no-op (returns ``False`` always) until
# then. This keeps today's resolution byte-identical while pinning the split
# with a test that works now (a caller can declare both attributes on a
# stand-in config object without waiting on t12's real wiring).


def _refuses_evaluator_as_distiller(config: Any, candidate_model: str) -> bool:
    """``True`` when *candidate_model* is a declared evaluator seat with no
    distinct distiller authority declared to override it.

    Reads two forward-declared, duck-typed facts off *config*:

    - ``evaluator_checkpoint`` — the model/checkpoint id serving the
      evaluator role, when the armed evaluation mode has declared one.
    - ``distiller_checkpoint`` — a model/checkpoint id EXPLICITLY declared
      as a distinct distillation authority, distinguishing it from the
      evaluator seat even when both happen to be served from the same
      underlying checkpoint.

    A candidate is refused (this returns ``True``) only when an evaluator
    checkpoint is declared, the candidate IS that checkpoint, and no
    distiller checkpoint distinct from it has been declared. Absent any
    declaration (today, always) this returns ``False`` — byte-identical.
    """
    evaluator_checkpoint = getattr(config, "evaluator_checkpoint", None)
    if not evaluator_checkpoint or evaluator_checkpoint != candidate_model:
        return False
    distiller_checkpoint = getattr(config, "distiller_checkpoint", None)
    return not (distiller_checkpoint and distiller_checkpoint != evaluator_checkpoint)


def _deepthink_author(config: Any) -> DistillAuthor | None:
    """Rung 1, shared by both resolvers: the declared deepthink/muse target.

    ``None`` when no deepthink model is declared — the caller falls to its
    next rung.
    """
    dt = getattr(config, "deepthink", None)
    if dt is None:
        return None
    model = getattr(dt, "model", None)
    if not (model and isinstance(model, str) and model.strip()):
        return None
    return DistillAuthor(
        model=model.strip(),
        base_url=getattr(dt, "base_url", None) or getattr(config, "base_url", "") or "",
        api_key=getattr(dt, "api_key", None) or getattr(config, "api_key", "") or "",
    )


def _declared_distiller_author(config: Any) -> DistillAuthor | None:
    """The EXPLICITLY declared distillation authority, or ``None``.

    Shared by both resolvers as the armed-mode rung. Declaring a distiller
    names the AUTHOR — it never merely licenses the evaluator to author (spec
    c38/h30), which is why the armed branch returns this result directly
    rather than falling through to a cortex-shaped candidate.
    """
    declared = getattr(config, "distiller_checkpoint", None)
    if not (declared and isinstance(declared, str) and declared.strip()):
        return None
    return DistillAuthor(
        model=declared.strip(),
        base_url=getattr(config, "base_url", "") or "",
        api_key=getattr(config, "api_key", "") or "",
    )


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
    2. **Armed thought→action→evaluation: the DECLARED distiller, or nothing.**
       In that mode both implicit candidates are disqualified — the cortex role
       IS the evaluator seat, and the acting dial points at the worker, which
       would make the actor author lessons about its own work. So an explicit
       ``distiller_checkpoint`` names the author, and its absence falls to the
       rung-1 floor. Declaring a distiller names the AUTHOR; it must never
       merely license the evaluator to author.
    3. **Lobes cortex** — when lobes is armed (``lobes_roles`` is not ``None``),
       the cortex role is the author — UNLESS the cortex checkpoint is a
       declared evaluator seat with no distinct distiller authority declared
       (:func:`_refuses_evaluator_as_distiller`, spec c38/h30): the evaluator
       and the distiller are distinct authority contracts even when they
       share a checkpoint, so that case falls through to the rung-1 floor
       rather than silently handing the evaluator write access to memory.
    4. **None** — when neither deepthink nor lobes is configured (or the
       guard above refuses the candidate), no author is resolved. The rung-1
       floor stands (byte-identical record, no counters — spec c16/h13).

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
    deepthink_author = _deepthink_author(config)
    if deepthink_author is not None:
        return deepthink_author

    # Rung 2 (armed thought→action→evaluation): the DECLARED distiller, or
    # nothing. In that mode both implicit candidates are disqualified (cortex
    # IS the evaluator, the worker IS the actor), so there is no safe
    # fallthrough — hence the unconditional return.
    if getattr(config, "thought_action_evaluation", False):
        return _declared_distiller_author(config)

    # Rung 3: lobes cortex (armed gateway) — guarded against silently
    # authoring as a declared evaluator seat (c38/h30).
    if lobes_roles is not None:
        cortex = lobes_roles.cortex
        if cortex is not None and not _refuses_evaluator_as_distiller(config, cortex.model):
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

    The marker is a small JSON file with ``status``
    (``pending``/``done``/``failed``/``dead``), an optional ``pid`` (for
    liveness probing), an optional ``lesson`` dict (when ``status == "done"``),
    and an optional ``reason`` (when ``status`` is ``failed`` or ``dead`` —
    see :func:`_failure_reason` for the failure vocabulary).
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
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    status = data.get("status")
    return status if isinstance(status, str) else None


def lesson_has_external_evidence(evidence: dict[str, Any]) -> bool:
    """Return ``True`` when *evidence* carries EXTERNAL grounding.

    A durable lesson must be grounded in EXTERNAL evidence — an evaluator
    verdict is a DIAGNOSIS, not ground truth.  This function returns ``True``
    only when:

    - ``external_evidence`` is a non-empty list, OR
    - ``outcome`` is a non-empty string.

    A lesson whose only evidence is an ``evaluation_id`` (evaluator verdict
    alone) returns ``False`` — the flywheel guard in the child entry uses
    this to refuse to persist such lessons.
    """
    ext = evidence.get("external_evidence")
    if isinstance(ext, list) and len(ext) > 0:
        return True
    outcome = evidence.get("outcome")
    if isinstance(outcome, str) and outcome.strip():
        return True
    return False


def upsert_lesson(
    repo_path: str | Path,
    task_id: str,
    lesson: dict[str, str],
    *,
    evidence: dict[str, Any] | None = None,
) -> bool:
    """Validate-then-remember: upsert the SAME work-lesson id with the lesson folded.

    The lesson is validated via :func:`colleague.lessons.validate_lesson` BEFORE
    being remembered. An invalid lesson is **never** stored — no partial record.
    This is the atomic guarantee: validate-then-single-remember (h26).

    The record uses the SAME ``work-lesson-<task_id>`` id as the rung-1 record,
    so eidetic deduplication upserts in place rather than creating a duplicate.

    When *evidence* is provided, the flywheel guard checks that the lesson has
    external grounding via :func:`lesson_has_external_evidence`.  A lesson
    whose only evidence is an evaluator verdict (``evaluation_id`` present but
    no ``external_evidence`` and no ``outcome``) is refused with a
    ``no-lesson-extracted`` marker — the same style already used in this file.

    Parameters
    ----------
    repo_path:
        The repo root (for eidetic CLI cwd).
    task_id:
        The work item's task id (used to build the record id).
    lesson:
        The validated lesson dict (``pattern``, ``constant``, ``reason`` —
        the answer-shaped schema, #396).
    evidence:
        Optional evidence dict linking the chain (``thought_id``, ``action_id``,
        ``evaluation_id``, ``outcome``, ``external_evidence``).

    Returns
    -------
    bool
        ``True`` if the lesson was validated and remembered, ``False`` otherwise.
    """
    verdict = lessons.validate_lesson(lesson)
    if not verdict.allowed:
        return False

    # Flywheel guard: refuse lessons whose only evidence is an evaluator verdict.
    if evidence is not None and not lesson_has_external_evidence(evidence):
        return False

    # Build the record with the SAME work-lesson id as rung-1.
    # The text folds the structured lesson into the free-form field.
    text = (
        f" Lesson (origin=model): pattern: {lesson['pattern']} — "
        f"constant: {lesson['constant']} — reason: {lesson['reason']}."
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
) -> list[str]:
    """Build the argv for the distillation child process.

    The child re-invokes the module entry ``python -m colleague.distill``;
    author credentials ride the child env (:func:`_child_env`), never argv.
    """
    return [
        sys.executable,
        "-m",
        "colleague.distill",
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
        argv = _build_child_argv(repo_path, task_id, author_model)
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
        with contextlib.suppress(Exception):  # never block the run
            detach_distill_child(
                repo_path=repo_path,
                task_id=result.task_id,
                author_model=author_model,
                author_base_url=author_base_url or "",
                author_api_key=author_api_key or "",
            )
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
    2. **armed thought→action→evaluation mode: an EXPLICITLY declared
       ``distiller_checkpoint``, or nothing.** In that mode there is no safe
       implicit author — see the note below;
    3. otherwise the armed-lobes main model (cortex-resolved) when
       ``config.lobes_gateway_url`` is set — UNLESS that model is a declared
       evaluator seat with no distinct distiller authority declared
       (:func:`_refuses_evaluator_as_distiller`, spec c38/h30);
    4. ``None`` — the rung-1 floor (byte-identical record, no counters).

    Why rung 2 exists (t13). Rung 3's premise is that the armed-lobes main
    model is *cortex-resolved*. That held until the three-seat mode repointed
    the acting dial at the **worker** (``config.py``'s TAE branch), after
    which ``config.model`` is the actor, not the reflective seat. Falling
    through to rung 3 would then silently make the worker author lessons
    about its own work — which the evaluator/distiller separation (c38/h30)
    exists to prevent and which the operator's standing role doctrine
    assigns to the reflective seat, never the actor. In that mode both
    implicit candidates are disqualified — cortex *is* the evaluator, and the
    worker *is* the actor — so the author must be declared outright or the
    run honestly falls to the rung-1 floor.
    """
    deepthink_author = _deepthink_author(config)
    if deepthink_author is not None:
        return deepthink_author
    if getattr(config, "thought_action_evaluation", False):
        return _declared_distiller_author(config)
    if getattr(config, "lobes_gateway_url", None):
        model = getattr(config, "model", "") or ""
        if model and not _refuses_evaluator_as_distiller(config, model):
            return DistillAuthor(
                model=model,
                base_url=getattr(config, "base_url", "") or "",
                api_key=getattr(config, "api_key", "") or "",
            )
    return None


# ---------------------------------------------------------------------------
# The child entry (t17 finisher) — `python -m colleague.distill`
# ---------------------------------------------------------------------------
#
# The live probe caught the detach pointing at a CLI verb that never existed
# (the #363 armed-not-alive class, for real): the scaffolding above had no
# child main and no completion call. This is that child. It is NOT an operator
# verb — it never registers on the CLI; the only caller is
# :func:`detach_distill_child`'s one-shot detach.


# The bounded completion's token envelope, SIZED FROM LIVE MEASUREMENT (t3,
# spec h10) against unsloth/Qwen3.8-27B-NVFP4 on 2026-08-20 with realistic
# rung-2 payloads composed by :func:`_compose_child_prompt`:
#
#   payload                     max_tokens  finish_reason  reasoning  content  tok
#   A (one clear TypeError)            400  length          1854 ch     0 ch   400
#   A                                  800  stop            2530 ch   655 ch   669
#   A                                 1600  stop            2530 ch   655 ch   669
#   B (contradictory gates)           1600  stop            6346 ch   459 ch  1449
#   C (ambiguous outcome)             1600  stop            4854 ch   709 ch  1160
#
# Two facts drive the number. (1) The degradation is REAL, not theoretical:
# payload A at 400 returns a 200 with `finish_reason=length`, 1854 chars of
# reasoning and ZERO content — an empty lesson from a successful HTTP call.
# (2) The old 1600 cap left a 151-token margin over the worst realistic
# payload (1449, 90.6% of the cap), and reasoning — not the prompt — is what
# varies: `_compose_child_prompt` truncates every field, so the prompt is
# structurally capped near 1.7 KB while the reasoning spend tripled between
# an easy diagnosis and a hard one. Content itself is only ~150-200 tokens.
#
# 4096 is 2.8x the measured worst case and still a BOUNDED completion (the
# detached-and-bounded child contract holds). Raising it is free on the stop
# path: at temperature 0 the same payload emitted an identical 669/1449/1160
# tokens at caps of 800, 1600, 3200 and 6000 — vLLM bills what is generated,
# not what is reserved. The explicit `finish_reason=length` handling below
# lands regardless: a measured envelope is not a proof of an upper bound.
_DISTILL_MAX_TOKENS = 4096

#: Wall-clock ceiling for the one bounded completion. The slowest measured
#: realistic payload took 79 s at 1449 tokens, so 180 s covers the raised
#: envelope with room to spare.
_DISTILL_TIMEOUT = 180


@dataclass(frozen=True)
class DistillCompletion:
    """The result of the child's ONE bounded completion.

    Structured rather than a bare string so the truncation case is
    diagnosable: a reasoning model bills its thinking against the SAME
    ``max_tokens`` as its answer, so a completion can succeed at the HTTP
    layer and still carry no lesson (``finish_reason == "length"`` with empty
    ``content``). :attr:`text` preserves the pre-change concatenation, so
    parsing behaviour is unchanged — including servers that emit the JSON in
    ``reasoning`` with an empty ``content``.
    """

    content: str
    reasoning: str
    finish_reason: str

    @property
    def text(self) -> str:
        """Content then reasoning — the string the lesson parser sees."""
        return self.content + ("\n" + self.reasoning if self.reasoning else "")

    @property
    def truncated(self) -> bool:
        """``True`` when the server stopped because the token cap was hit."""
        return self.finish_reason == "length"


def _openai_completion(model: str, base_url: str, api_key: str, prompt: str) -> DistillCompletion:
    """ONE bounded chat completion over urllib (the vLLM-adapter convention)."""
    import urllib.request

    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _DISTILL_MAX_TOKENS,
            "temperature": 0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key or 'x'}",
        },
    )
    with urllib.request.urlopen(
        req, timeout=_DISTILL_TIMEOUT
    ) as resp:  # nosec B310 - operator-configured http(s) endpoint
        data = json.loads(resp.read().decode("utf-8"))
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    # Servers disagree on the spelling of the reasoning field (s14): vLLM's
    # OpenAI front end serves `reasoning`, others `reasoning_content`.
    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
    return DistillCompletion(
        content=msg.get("content") or "",
        reasoning=reasoning,
        finish_reason=choice.get("finish_reason") or "",
    )


def _find_artifact(repo_path: str | Path, task_id: str) -> Path | None:
    """Locate the run artifact for *task_id*, never a sidecar (Qodo #386).

    The artifact dir holds same-stem siblings — ``<id>.feedback.json``,
    ``<id>.<author>.feedback.json``, ``<id>.distill.json``,
    ``<id>-correction-capture.json``, ``<id>.*.trace.jsonl`` — so name
    exclusion alone is fragile. A candidate must also be artifact-SHAPED:
    a JSON object whose ``task_id`` matches. Ambiguity resolves to the
    lexicographically first match (deterministic).
    """
    base = Path(repo_path) / ".colleague"
    candidates = []
    for p in sorted(base.glob(f"{task_id}.*.json")):
        name = p.name
        if (
            ".trace" in name
            or "-correction-capture" in name
            or name.endswith(".distill.json")
            or ".feedback." in name
            or name.endswith(".feedback.json")
        ):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("task_id") == task_id:
            candidates.append(p)
    return candidates[0] if candidates else None


def _compose_child_prompt(artifact: dict[str, Any]) -> str:
    """Build the distillation ask from the persisted run facts alone."""
    stats = artifact.get("stats") or {}
    inc = artifact.get("incompletion") or {}
    parts = [
        "You are distilling ONE lesson from a finished coding-agent work item.",
        f"Status: {artifact.get('status')}. Steps: {stats.get('step_count')}.",
        f"Request: {str(artifact.get('request', ''))[:300]}",
    ]
    if inc:
        parts.append(
            f"Incompletion: {inc.get('reason')} — evidence: {str(inc.get('evidence'))[:300]}"
        )
    if artifact.get("error"):
        parts.append(f"Error: {str(artifact.get('error'))[:200]}")
    if artifact.get("summary"):
        parts.append(f"Final summary: {str(artifact.get('summary'))[:300]}")
    parts.append(
        "Reply with ONLY a JSON object, exactly these keys, each a non-empty "
        'string under 1000 chars: {"pattern": "the recurring shape this '
        'lesson generalizes — what class of situation it applies to", '
        '"constant": "the specific repo anchor it pins — an identifier, '
        'value, path, or invariant, not generic prose", "reason": "why the '
        'pattern holds — the causal link to the constant"}. No other keys, '
        "no prose around the JSON, no thinking out loud — start your reply "
        "with '{'."
    )
    return "\n".join(parts)


def _failure_reason(completion: DistillCompletion, verdict_reason: str) -> str:
    """Name WHY no lesson was extracted, on the existing marker channel.

    The three failures are operationally different and must not read alike
    (spec h10). A completion whose reasoning ate the token budget is a SIZING
    fault; a completion with no content at all is a SERVING fault; anything
    else is the genuine schema refusal the validator already explains.
    Reporting the first two as a schema complaint would send the operator
    hunting the prompt instead of the cap — and an empty completion must
    never pass silently as "no lesson today".

    The marker itself is the recorded-warning channel: a ``failed`` marker
    counts as an attempt-without-a-validation in the ``distillation_alive``
    check group, so doctor surfaces it as the armed-but-not-alive warning.
    """
    if completion.truncated:
        return (
            f"truncated: the distillation completion hit max_tokens="
            f"{_DISTILL_MAX_TOKENS} (finish_reason=length) with "
            f"{len(completion.reasoning)} reasoning chars and "
            f"{len(completion.content)} content chars — the reasoning consumed "
            f"the budget before a complete lesson JSON was emitted; raise "
            f"_DISTILL_MAX_TOKENS or shorten the distillation prompt"
        )
    if not completion.content.strip():
        return (
            f"no content: the distillation completion returned an empty content field "
            f"(finish_reason={completion.finish_reason or 'unset'}, "
            f"{len(completion.reasoning)} reasoning chars) — no lesson distilled; "
            f"check the author model is serving and emits content, not reasoning alone"
        )
    return verdict_reason


def child_main(argv: list[str] | None = None) -> int:
    """The detached distillation child: read artifact → ONE completion →
    validate-then-upsert → outcome marker. The exit code is informational only
    (0 done/nothing-to-do, 1 failed/dead) — outcomes ride the marker; the
    parent never waits or reads it."""
    import argparse

    parser = argparse.ArgumentParser(prog="colleague-distill-child")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args(argv)

    # The child spawns at remember time, but the parent persists the artifact
    # only after the run returns — a bounded wait (c31's window) bridges the
    # race the t17 live probe caught (round 2: child ran, found nothing,
    # exited silently). 30 tries x 2s = a 60s ceiling, then give up honestly
    # (the artifact-side attempt counter keeps doctor loud either way).
    artifact_path = None
    for _ in range(30):
        artifact_path = _find_artifact(args.repo, args.task_id)
        if artifact_path is not None:
            break
        time.sleep(2)
    marker = outcome_marker_path(artifact_path) if artifact_path else None
    if artifact_path is None or marker is None:
        return 0  # nothing to distill against; nothing to mark
    write_outcome_marker(marker, status="pending", pid=os.getpid())
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        completion = _openai_completion(
            args.model,
            os.environ.get("COLLEAGUE_DISTILL_BASE_URL", ""),
            os.environ.get("COLLEAGUE_DISTILL_API_KEY", ""),
            _compose_child_prompt(artifact),
        )
        parsed = lessons.parse_lesson_json(completion.text)
        verdict = lessons.validate_lesson(parsed if parsed is not None else completion.text)
        if parsed is not None and verdict.allowed:
            lesson = {k: str(parsed[k]) for k in ("pattern", "constant", "reason")}
            upsert_lesson(args.repo, args.task_id, lesson)
            write_outcome_marker(marker, status="done", lesson=lesson)
            return 0
        write_outcome_marker(
            marker, status="failed", reason=_failure_reason(completion, verdict.reason)
        )
        return 1
    except Exception as exc:  # the marker IS the honest failure channel
        write_outcome_marker(marker, status="dead", reason=str(exc)[:300])
        return 1


if __name__ == "__main__":  # pragma: no cover - the detached child entry
    raise SystemExit(child_main())
