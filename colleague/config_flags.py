"""Boolean / enum knob resolution: the gates, the modes, the ladders.

Every ``env > config.json > builtin default`` gate resolver colleague carries —
lint, watch, coherence, memory (+ distillation), until-done, three-tier,
thought→action→evaluation, model-bound agents, hire, test-integrity,
affected-tests — plus the engine-selection and presence-rung resolvers and the
test-integrity reviewer backfill. Split out of ``config.py`` (hard 1000-line
file limit, plan ``hard-1000-line-file-limit`` t14) — a pure move, no default
flipped. Every name is re-exported from :mod:`colleague.config`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Optional

from colleague.config_defaults import (
    _DEFAULT_AFFECTED_TESTS_ENABLED,
    _DEFAULT_AGENTS_ENABLED,
    _DEFAULT_COHERENCE_ENABLED,
    _DEFAULT_ENGINE,
    _DEFAULT_LINT_ENABLED,
    _DEFAULT_MEMORY_DISTILL,
    _DEFAULT_MEMORY_ENABLED,
    _DEFAULT_TESTINTEGRITY_ENABLED,
    _DEFAULT_THOUGHT_ACTION_EVALUATION,
    _DEFAULT_THREE_TIER_ENABLED,
    _DEFAULT_UNTIL_DONE,
    _DEFAULT_WATCH_ENABLED,
)
from colleague.config_files import _load_presence_override, _pick
from colleague.config_types import DeepthinkConfig

if TYPE_CHECKING:
    from colleague.config import EngineConfig


def _parse_bool(value: str) -> bool:
    """Parse a config/env boolean: ``0``/``false``/``no``/``off``/empty → False, else True.

    Case-insensitive and whitespace-tolerant so ``COLLEAGUE_LINT=0``,
    ``COLLEAGUE_LINT=false`` and a JSON ``"lint": false`` (which stringifies to
    ``"False"``) all disable the gate.
    """
    return value.strip().lower() not in ("", "0", "false", "no", "off")


def _resolve_lint_enabled(file_value: str | None) -> bool:
    """Resolve the lint-gate enabled flag: env ``COLLEAGUE_LINT`` > config.json > default-on.

    The ``--no-lint`` CLI flag is applied by the work path *after* ``resolve()``
    (it sets ``config.lint = False``), so this stays off the ``resolve()`` signature
    and the S107 parameter ceiling is held (the synthesis-reserve precedent).
    """
    for env_key in ("COLLEAGUE_LINT", "CONVERTIBLE_LINT"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_LINT_ENABLED


def _resolve_watch_enabled(file_value: str | None) -> bool:
    """Resolve the flight-plane armed flag: env ``COLLEAGUE_WATCH`` > config.json >
    default-on (#307).

    The ``--watch`` / ``--no-watch`` CLI flags override this post-resolve (the work
    path resolves the effective value against ``config.watch``), so this stays off
    the ``resolve()`` signature — the ``_resolve_lint_enabled`` precedent.
    """
    for env_key in ("COLLEAGUE_WATCH", "CONVERTIBLE_WATCH"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_WATCH_ENABLED


def _resolve_until_done_enabled(file_value: str | None) -> bool:
    """Resolve the chain-arming flag: env ``COLLEAGUE_UNTIL_DONE`` > config.json >
    default-OFF (indefinite-run decision c21 — armed, never ambient).

    The ``--until-done`` CLI flag is applied by the work path *after*
    ``resolve()`` (t5), so this stays off the ``resolve()`` signature — the
    ``_resolve_lint_enabled`` precedent (S107 parameter ceiling).
    """
    for env_key in ("COLLEAGUE_UNTIL_DONE", "CONVERTIBLE_UNTIL_DONE"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_UNTIL_DONE


def _resolve_coherence_enabled(file_value: str | None) -> bool:
    """Resolve the coherence-gate flag: env ``COLLEAGUE_COHERENCE`` > config.json > default-on.

    The ``--no-coherence`` CLI flag is applied by the work path *after*
    ``resolve()`` (it sets ``config.coherence = False``) — the exact --no-lint
    precedent (#294; operator decision on colleague#291: default-ON warn-only).
    """
    for env_key in ("COLLEAGUE_COHERENCE", "CONVERTIBLE_COHERENCE"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_COHERENCE_ENABLED


def _resolve_memory_distill(file_value: str | None) -> bool:
    """Resolve the rung-2 distillation knob (t9): env ``COLLEAGUE_MEMORY_DISTILL``
    > config.json ``{"memory_distill": ...}`` > default-on.

    Independent of the memory gate by design (spec c29): disarming distillation
    must never cost the rung-1 record or recall-before.
    """
    env = os.environ.get("COLLEAGUE_MEMORY_DISTILL")
    if env is not None and env.strip() != "":
        return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_MEMORY_DISTILL


def _resolve_memory_enabled(file_value: str | None) -> bool:
    """Resolve memory-informed-runtime enablement (spec R1 / plan t2):
    env ``COLLEAGUE_MEMORY`` > config.json ``{"memory": ...}`` > default-on.

    Default-ON is safe because the loop additionally arms only when the repo
    contains a ``.eidetic/`` store AND the eidetic CLI is installed — a repo
    without a store (every tmp test repo) is a strict no-op regardless.
    """
    for env_key in ("COLLEAGUE_MEMORY", "CONVERTIBLE_MEMORY"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_MEMORY_ENABLED


def _resolve_three_tier_enabled(file_value: str | None) -> bool:
    """Resolve the three-tier execution arming flag: env ``COLLEAGUE_THREE_TIER``
    > config.json ``three_tier`` > default-OFF (three-tier-execution arc,
    plan task t3).

    Default-OFF, never ambient — the ``until_done`` precedent (decision c21):
    an execution-mode change needs explicit operator intent. No CLI flag in
    this task (kept off the ``resolve()`` signature, the ``_resolve_lint_enabled``
    S107-ceiling precedent) — a later task may add one.
    """
    env = os.environ.get("COLLEAGUE_THREE_TIER")
    if env is not None and env.strip() != "":
        return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_THREE_TIER_ENABLED


def _resolve_thought_action_evaluation_enabled(file_value: str | None) -> bool:
    """Resolve the thought→action→evaluation arming flag: env
    ``COLLEAGUE_THOUGHT_ACTION_EVALUATION`` > config.json
    ``thought_action_evaluation`` > default-OFF (plan task t12; issue #397).

    The exact precedence shape of :func:`_resolve_three_tier_enabled` over a
    DELIBERATELY DISTINCT key: arming this mode never arms three-tier, and
    arming three-tier never arms this mode (acceptance criterion 1). Default-OFF,
    never ambient — an execution-mode change needs explicit operator intent
    (decision c21's stance), never an accident of an armed lobes gateway alone.
    """
    env = os.environ.get("COLLEAGUE_THOUGHT_ACTION_EVALUATION")
    if env is not None and env.strip() != "":
        return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_THOUGHT_ACTION_EVALUATION


def _resolve_agents_enabled(file_value: str | None) -> bool:
    """Resolve the model-bound-agents arming flag: env ``COLLEAGUE_AGENTS`` >
    config.json ``agents`` > default-OFF (#411, plan task t7).

    The exact precedence shape of the two sibling modes over a DELIBERATELY
    DISTINCT key: arming this mode never arms three-tier or
    thought→action→evaluation, and vice versa. Default-OFF, never ambient.
    """
    env = os.environ.get("COLLEAGUE_AGENTS")
    if env is not None and env.strip() != "":
        return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_AGENTS_ENABLED


_DEFAULT_HIRE_ENABLED = False


def _resolve_hire_enabled(file_value: str | None) -> bool:
    """Resolve the hire_colleague arming flag: env ``COLLEAGUE_HIRE`` >
    config.json ``hire`` > default-OFF (delegation-follow-ups t4, spec c17/D5).

    RESOLUTION ONLY: this flag arms nothing by itself — the hire tools read
    it in later tasks. Default-OFF, never ambient; independent of every
    execution mode (it refuses nothing and is refused by nothing).
    """
    env = os.environ.get("COLLEAGUE_HIRE")
    if env is not None and env.strip() != "":
        return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_HIRE_ENABLED


def _resolve_acting_add_tools() -> tuple[str, ...]:
    """The acting seat's ADD-set as resolved for attestation (t4): the same
    comma-separated, whitespace-tolerant, order-preserving, de-duplicated
    reading :func:`colleague.actingsurface.acting_add_set` applies (t1);
    imported when present so the two can never disagree, else parsed here
    identically. Unset/blank = ``()`` (omitted from the snapshot)."""
    from colleague import actingsurface

    reader = getattr(actingsurface, "acting_add_set", None)
    if callable(reader):
        return tuple(reader())
    raw = os.environ.get("COLLEAGUE_ACTING_ADD_TOOLS", "")
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


def _resolve_distiller_checkpoint(file_value: str | None) -> str | None:
    """Resolve the DECLARED distiller checkpoint id: env
    ``COLLEAGUE_DISTILLER_MODEL`` > config.json ``distiller`` > absent
    (plan task t12; spec c38/h30).

    Evaluation and distillation are DISTINCT authority contracts even when they
    share a checkpoint: the evaluator does closed-world thought↔action judgment
    and cannot write durable memory, while the distiller runs post-outcome and
    only when evidence exists. ``colleague/distill.py``'s
    ``_refuses_evaluator_as_distiller`` guard refuses to let the evaluator seat
    author lessons UNLESS a distinct distiller authority is declared — this is
    that declaration.

    Deliberately a bare CHECKPOINT ID, not a dial: it asserts *who the
    distillation authority is*, and distill.py's own precedence already owns
    where that author is dialed. Resolved independently of the mode's arming
    (an authority declaration is meaningful on its own); ``None`` when absent
    or blank, which leaves the guard exactly as inert as it is today.
    """
    declared = _pick(None, "COLLEAGUE_DISTILLER_MODEL", default=file_value or "")
    return declared.strip() or None


def _resolve_testintegrity_enabled(file_value: str | None) -> bool:
    """Resolve the test-integrity gate flag: env ``COLLEAGUE_TESTINTEGRITY`` > config > default-on.

    Kept off the ``resolve()`` signature (no CLI flag in v0), mirroring
    :func:`_resolve_lint_enabled` so the S107 parameter ceiling holds.
    """
    for env_key in ("COLLEAGUE_TESTINTEGRITY", "CONVERTIBLE_TESTINTEGRITY"):
        env = os.environ.get(env_key)
        if env is not None and env.strip() != "":
            return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_TESTINTEGRITY_ENABLED


def _resolve_affected_tests_enabled(file_value: str | None) -> bool:
    """Resolve the affected-tests gate flag: env ``COLLEAGUE_AFFECTED_TESTS`` > config > default-on.

    Mirrors :func:`_resolve_lint_enabled` so the S107 parameter ceiling holds.
    ``0``/``false`` disables; any truthy value enables.
    """
    env = os.environ.get("COLLEAGUE_AFFECTED_TESTS")
    if env is not None and env.strip() != "":
        return _parse_bool(env)
    if file_value is not None:
        return _parse_bool(file_value)
    return _DEFAULT_AFFECTED_TESTS_ENABLED


def _resolve_testintegrity_reviewer_model(
    explicit: str,
    deepthink: "DeepthinkConfig | None",
    main_base_url: str,
) -> str:
    """Default the test-integrity diverse-model reviewer to the deepthink model.

    Spec c10(d) (task t7): when dual-model deepthink (t1) is configured and the
    operator has NOT set an explicit ``COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL``
    (or its ``CONVERTIBLE_*`` fallback), the deepthink model becomes the
    reviewer default — the strong reasoner is the natural diverse reviewer for
    a mirrored-test finding (#203).

    *explicit* is the value already resolved from env (empty/whitespace means
    unconfigured, matching this module's convention throughout). An
    explicit value — even whitespace-only-vs-non-whitespace aside, ANY
    non-blank explicit value — always wins over the default; this function
    only ever fills in the ELSE branch.

    The default is guarded to the SAME endpoint: the reviewer subagent switch
    (``colleague/subagents.py``'s ``dataclasses.replace(parent_config,
    model=..., role=...)``) carries only a model name — the spawned child
    inherits the parent's ``base_url``/``api_key`` unchanged. Defaulting to a
    deepthink model served on a DIFFERENT endpoint would point the reviewer
    subagent at a model name the main endpoint likely doesn't serve, so when
    ``deepthink.base_url`` differs from *main_base_url* the reviewer model is
    left exactly as *explicit* (empty, or a caller-provided whitespace value
    from an already-empty resolution). Honest v1 limit: a cross-endpoint
    reviewer default is a documented follow-up that needs the subagent switch
    to carry an endpoint of its own — not built here.
    """
    if explicit.strip():
        return explicit
    if deepthink is not None and deepthink.base_url == main_base_url:
        return deepthink.model
    return explicit


def resolve_engine(explicit: str | None) -> str:
    """Resolve the backend plugin name to drive.

    Precedence, highest first: an explicit value (the ``--engine`` flag), the
    ``COLLEAGUE_ENGINE`` environment variable (legacy ``CONVERTIBLE_ENGINE`` is
    honored as a deprecated fallback), then the built-in default
    (:data:`_DEFAULT_ENGINE`). Engine selection is config too, so it mirrors the
    provider-field precedence — but it is a separate concern (the ``mock`` engine
    never reads provider config).

    An empty or whitespace-only candidate is treated as *absent*, not as a valid
    override: ``--engine ''`` (or ``--engine "$VAR"`` with ``VAR`` unset, or a
    blank ``COLLEAGUE_ENGINE``) falls through to the next source rather than
    resolving to an invalid engine name that would later raise ``UnknownEngine``.
    A non-blank value is returned stripped of surrounding whitespace.
    """
    for candidate in (
        explicit,
        os.environ.get("COLLEAGUE_ENGINE"),
        os.environ.get("CONVERTIBLE_ENGINE"),
    ):
        if candidate and candidate.strip():
            return candidate.strip()
    return _DEFAULT_ENGINE


def resolve_session_engine(explicit: str | None) -> str:
    """Resolve the backend for the *interactive session* (``colleague session``).

    The session is colleague-driving-colleague, so it defaults to colleague's own
    served backend exactly like :func:`resolve_engine`. This adds ONE session-scoped
    override slotted ahead of the global default: an explicit ``--engine`` flag wins,
    then ``COLLEAGUE_SESSION_ENGINE`` (a session-only override, so an operator can
    point the conversational session at a different backend than a bare
    ``colleague work`` without changing the global default), then the normal
    :func:`resolve_engine` chain (``COLLEAGUE_ENGINE`` → built-in default).

    An empty or whitespace-only candidate is treated as *absent* (not a valid
    override), matching :func:`resolve_engine`.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    session_env = os.environ.get("COLLEAGUE_SESSION_ENGINE")
    if session_env and session_env.strip():
        return session_env.strip()
    return resolve_engine(None)


# ---------------------------------------------------------------------------
# Presence-lane ladder rung resolution (presence-default-everywhere arc,
# spec docs/specs/2026-07-08-colleague-s-middle-manager-presence-is-now-its-def.md,
# plan task t4).
# ---------------------------------------------------------------------------

# The presence lane's bounded degradation ladder, highest-fidelity rung first:
# "loop" is the senses agentic loop (t5, the DEFAULT rung whenever senses is
# armed); "beats" is today's fixed-beat lane (intake/ack/updates/talk, an
# explicit operator opt-down); "off" is cortex-only — no middle-manager
# presence at all, either because no senses model is resolved (nothing to
# talk to) or because the operator disarmed the lane. Downstream front tasks
# (t7-t11) consult :func:`resolve_presence_rung` to learn which rung to drive;
# this module only decides the rung, it never wires a front.
PRESENCE_RUNGS = ("loop", "beats", "off")

# Values that normalize to the "off" rung for COLLEAGUE_PRESENCE / the
# top-level "presence" config.json key — mirrors ``_parse_bool``'s falsy
# vocabulary so ``COLLEAGUE_PRESENCE=0`` behaves the same way every other
# boolean-shaped knob in this module does.
_PRESENCE_OFF_VALUES = frozenset({"off", "0", "false", "no"})


def _normalize_presence_value(value: str) -> str | None:
    """Map a raw ``presence`` string to a canonical rung name, or ``None``.

    Case-insensitive and whitespace-tolerant, matching every other knob's
    parsing style in this module. ``"off"``/``"0"``/``"false"``/``"no"`` all
    normalize to ``"off"``; ``"beats"``/``"loop"`` pass straight through. A
    blank or unrecognised value (a typo, e.g. ``"loops"``) returns ``None`` so
    the caller falls through to the NEXT precedence rung instead of silently
    trusting a malformed value — never raises.
    """
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in _PRESENCE_OFF_VALUES:
        return "off"
    if normalized in ("beats", "loop"):
        return normalized
    return None


def resolve_presence_rung(
    config: "EngineConfig",
    *,
    cortex_only: bool = False,
    env: Optional[Mapping[str, str]] = None,
    repo_path: str | Path | None = None,
) -> str:
    """Resolve which presence-lane ladder rung is active for this work item.

    Returns one of :data:`PRESENCE_RUNGS` (``"loop"`` | ``"beats"`` | ``"off"``).
    *config* is an already-resolved :class:`EngineConfig` (any front — session,
    talk, background, resident, or a one-shot ``work`` item — resolves through
    the SAME ``EngineConfig``, so this one function serves every front).

    Precedence, highest first:

    1. *cortex_only* — the front's own ``--cortex-only`` bypass (a session-wide
       flag in ``colleague session``, a per-run flag in ``colleague work``,
       etc.) always forces ``"off"``, regardless of anything else below.
    2. ``config.senses is None`` — senses was never resolved at all (no
       operator-declared model, no lobes discovery). There is nothing to talk
       to, so the rung is ``"off"`` — byte-identical to pre-arc behaviour
       (honesty h1: an install with no senses resolved stays byte-identical on
       every front).
    3. ``COLLEAGUE_PRESENCE`` env var (``CONVERTIBLE_PRESENCE`` honored as a
       deprecated fallback, matching every other knob in this module) —
       ``"loop"``, ``"beats"``, or an off-shaped value (``"off"``/``"0"``/
       ``"false"``/``"no"``).
    4. a top-level ``presence`` key in ``.colleague/config.json`` (only
       consulted when *repo_path* is given) — same three values.
    5. the built-in default: ``"loop"`` — the senses agentic loop is the
       DEFAULT rung whenever senses is armed and not disarmed (the arc's
       "default state" requirement).

    Never raises: a malformed or unrecognised env/config value (a typo) is
    treated as absent and falls through to the next precedence rung, exactly
    like every other knob resolved in this module — it never silently wins
    with a nonsensical value, but it also never blocks resolution.

    This is a PURE function over its arguments (no I/O beyond the optional
    config-file read) — it does not mutate *config*, and it is not baked into
    :meth:`EngineConfig.resolve` or ``to_dict()``: a field would have to be
    included/omitted from the artifact snapshot, and *cortex_only* is a
    per-front, post-resolve decision (fronts apply it by nulling
    ``config.senses`` today) rather than a value known at ``resolve()`` time.
    Keeping this a standalone resolver keeps a senses-less or cortex-only
    config's ``to_dict()`` untouched (byte-identical, sacred per this repo's
    conventions) while still giving downstream tasks (the artifact/debug
    surface, t5-t11) one authoritative call to learn the active rung.
    """
    if env is None:
        env = os.environ

    if cortex_only:
        return "off"

    if config.senses is None:
        return "off"

    for env_key in ("COLLEAGUE_PRESENCE", "CONVERTIBLE_PRESENCE"):
        raw = env.get(env_key)
        if raw is not None:
            normalized = _normalize_presence_value(raw)
            if normalized is not None:
                return normalized

    if repo_path is not None:
        file_value = _load_presence_override(repo_path)
        if file_value is not None:
            normalized = _normalize_presence_value(file_value)
            if normalized is not None:
                return normalized

    return "loop"
