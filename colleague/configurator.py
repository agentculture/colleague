"""Opt-in cortex configurator through the lattice (three-tier-execution plan
task t11 — delivery step 7, LAST of the build tasks by design).

Everything this module builds on already exists: :mod:`colleague.lattice`
(t4) is the typed change surface + refuse-whole validation,
:mod:`colleague.configlifecycle` (t6) is the episode-boundary queue that
applies ONLY at a sanctioned window, and :mod:`colleague.configevents` (t7)
is the append-only audit trail that eventually lands on
``TaskResult.config_events``. This module is the ONE new producer that turns
"cortex looked at an episode and decided something should change" into a
sequence of validated :class:`~colleague.lattice.ChangeUnit` proposals —
never anything else.

**The two structural pins (acceptance criterion 1).**

1. *Nothing cortex-authored ever reaches the worker's message history.* This
   module has no function that accepts or returns a ``list[dict]`` shaped
   like ``colleague/loop.py``'s conversation history, and ``colleague/loop.py``
   never imports this module — the dependency points the other way
   (``colleague/chain.py``'s :func:`~colleague.chain.run_configurator_window`
   calls INTO this module, BETWEEN episodes; the loop itself only ever
   consults the lifecycle it is handed, exactly as it did before this task —
   see ``colleague/configlifecycle.py``'s own docstring). Both halves are
   pinned by ``tests/test_configurator_boundary.py``.
2. *The acting completion seam is never wrapped.* This module's ONE
   completion call always drives the CORTEX dial (:func:`resolve_cortex_dial`
   — independently re-resolved from the lobes gateway's ``cortex`` role,
   since in three-tier mode ``EngineConfig.model``/``base_url``/``api_key``
   already carry the WORKER's acting dial, per t8's "the acting dial becomes
   the worker's own"), and it is always issued **tools-off**
   (``engine.make_complete(cortex_config, tools=[])``) — the same
   prompted-JSON-move-over-a-tools-off-completion pattern
   ``colleague/senses_loop.py``'s ``_one_completion`` uses (cited there, not
   duplicated: this module builds its own prompt/parse pair because the
   payload shape is a list of typed lattice units, not a senses coordination
   move). Nothing here ever wraps, decorates, or post-processes the acting
   engine's own ``make_complete`` result — pinned structurally by
   ``tests/test_configurator_boundary.py``.

**The review, end to end** (:func:`review_and_queue`, called from
``colleague/chain.py``'s :func:`~colleague.chain.run_configurator_window` —
the ONLY sanctioned call site, mirroring ``colleague/configlifecycle.py``'s
own "chain.py's between-episode window is the ONLY application point"):

1. Compose ONE prompt from a caller-assembled compact digest
   (:class:`ConfiguratorReviewInput`) plus the resolved authority ceiling
   (:class:`~colleague.lattice.CapabilityCatalog`, rendered so cortex only
   ever sees the tool ids it may actually select).
2. Issue ONE tools-off completion against the cortex dial. Any failure
   anywhere — no gateway, unreachable, a dead port, a request error — degrades
   to :class:`ConfiguratorReviewResult` ``.degraded=True``, never raises (the
   ``colleague/deepthink.py`` precedent), and appends ONE
   :data:`~colleague.configevents.EVENT_KIND_DEGRADED` event to the caller's
   :class:`~colleague.configevents.ConfigEventStream` carrying the reason —
   visible, never silent (the #363 armed-is-not-alive lesson), and distinct
   from a healthy ``{"changes": []}`` reply, which appends nothing.
3. Parse the reply as strict JSON (``{"changes": [...]}}``, tolerant of a
   markdown fence or surrounding prose via
   :func:`colleague.plan.cli_driver._extract_json_object` — the same
   JSON-recovery primitive ``colleague/senses_moves.py`` reuses). A reply
   that cannot be read this way is **refused whole**, with the reason
   recorded on the caller's :class:`~colleague.configevents.ConfigEventStream`
   — never a crash.
4. Each entry in ``changes`` becomes a :class:`~colleague.lattice.ChangeUnit`
   stamped ``origin=Origin.CORTEX`` (a model-supplied ``"origin"`` field, if
   present, is ignored — authority is never self-declared) and is proposed
   onto the caller's :class:`~colleague.configlifecycle.EpisodeConfigLifecycle`,
   which independently validates it against the lattice (the "verify" step)
   before ever queuing it. Every proposed/verified/refused outcome is
   recorded on the :class:`~colleague.configevents.ConfigEventStream` — a
   malformed entry (not a JSON object, a missing ``target``, a wrongly-typed
   ``tool_ids``/``knowledge_entries``) is refused whole with a recorded
   reason too, exactly like a lattice-level refusal, and processing continues
   with the next entry rather than aborting the whole batch.
5. **Application still happens ONLY at :func:`~colleague.chain.
   apply_config_window`** — this module never calls
   :meth:`~colleague.configlifecycle.EpisodeConfigLifecycle.apply_window`
   itself. ``colleague/chain.py``'s ``run_configurator_window`` calls
   :func:`review_and_queue` and THEN ``apply_config_window`` at the very
   same sanctioned window, and :func:`record_applied` folds the applied
   units back onto the event stream as ``"applied"`` events.

**Opt-in, off by default (acceptance criterion 2).** :func:`configurator_enabled`
resolves env ``COLLEAGUE_CONFIGURATOR`` > the nested ``three_tier.configurator``
key of ``.colleague/config.json`` > default **OFF** — a SEPARATE flag from
``three_tier.enabled`` itself: an armed three-tier run does NOT arm the
configurator (``tests/test_configurator.py`` holds the off-default even under
an armed three-tier config). ``colleague/chain.py``'s
``run_configurator_window`` takes ``armed`` as an explicit caller-resolved
bool and is a strict no-op (queues nothing, applies nothing beyond whatever
was ALREADY queued, appends no event) when it is ``False`` — so a dormant
configurator is byte-identical to a pre-t11 chain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

from colleague.config import EngineConfig, _merged_config_json
from colleague.configevents import (
    EVENT_KIND_APPLIED,
    EVENT_KIND_DEGRADED,
    EVENT_KIND_PROPOSED,
    EVENT_KIND_REFUSED,
    EVENT_KIND_VERIFIED,
    ConfigEventStream,
)
from colleague.configlifecycle import ConfigApplication, EpisodeConfigLifecycle
from colleague.lattice import CapabilityCatalog, ChangeUnit, Origin, Target
from colleague.layers import EVALUATOR_SECTION_MAX_CHARS
from colleague.plan.cli_driver import _extract_json_object, robust_simple_complete

if TYPE_CHECKING:
    from colleague.engine import Engine

# ---------------------------------------------------------------------------
# Opt-in arming — OFF by default, a SEPARATE flag from three_tier.enabled
# ---------------------------------------------------------------------------

#: The one env var that arms the configurator (mirrors ``COLLEAGUE_THREE_TIER``
#: / ``COLLEAGUE_TESTINTEGRITY`` / every other opt-in-flag precedent in
#: ``colleague/config.py``).
_CONFIGURATOR_ENV = "COLLEAGUE_CONFIGURATOR"


def _parse_bool(value: str) -> bool:
    """Parse a config/env boolean the same way ``colleague/config.py``'s own
    ``_parse_bool`` does: ``0``/``false``/``no``/``off``/empty -> ``False``,
    else ``True``. Duplicated as a one-line function rather than importing
    the private helper — this is the one opt-in flag this module owns end to
    end, so it stays self-contained."""
    return value.strip().lower() not in ("", "0", "false", "no", "off")


def _load_configurator_file_value(repo_path: "str | Path") -> Optional[bool]:
    """Read the ``configurator`` key nested under ``.colleague/config.json``'s
    ``three_tier`` OBJECT section (``{"three_tier": {"configurator": true}}``).

    Deliberately does NOT accept a bare ``three_tier`` boolean (that form has
    no sub-key to read) — only the nested-object form carries a
    ``configurator`` key. Returns ``None`` when the file/section/key is
    absent; never raises — delegates to
    :func:`colleague.config._merged_config_json` (the at-home per-key merge),
    the same reach-into-config's-private-merge-primitive precedent
    ``colleague/icons.py`` already uses for its own single-key resolution.
    """
    data = _merged_config_json(repo_path)
    section = data.get("three_tier")
    if not isinstance(section, dict) or "configurator" not in section:
        return None
    return _parse_bool(str(section["configurator"]))


def configurator_enabled(
    *, repo_path: "Optional[str | Path]" = None, env: "Optional[Mapping[str, str]]" = None
) -> bool:
    """Resolve the configurator arming flag: env > config.json > default OFF.

    Precedence: ``COLLEAGUE_CONFIGURATOR`` env var > the nested
    ``three_tier.configurator`` key of ``.colleague/config.json`` (read via
    *repo_path*, when given) > **default OFF**. This is deliberately
    independent of ``three_tier.enabled``/``COLLEAGUE_THREE_TIER`` — an armed
    three-tier run does NOT arm the configurator; both must be armed
    explicitly. Never raises.
    """
    environ = env if env is not None else os.environ
    raw = environ.get(_CONFIGURATOR_ENV)
    if raw is not None and raw.strip() != "":
        return _parse_bool(raw)
    if repo_path is not None:
        file_value = _load_configurator_file_value(repo_path)
        if file_value is not None:
            return file_value
    return False


# ---------------------------------------------------------------------------
# The cortex dial — re-resolved independently of the (possibly worker-
# overridden) acting EngineConfig fields
# ---------------------------------------------------------------------------


def resolve_cortex_dial(
    config: EngineConfig, *, gateway_url: "Optional[str]" = None
) -> "Optional[EngineConfig]":
    """Build the :class:`~colleague.config.EngineConfig` a configurator review
    should complete against — the CORTEX role, never the acting dial.

    In three-tier mode, ``config.model``/``base_url``/``api_key``/
    ``context_budget_tokens`` already carry the WORKER's own resolution (plan
    task t8: "the acting dial becomes the worker's own — cortex does not
    act") — so the cortex dial cannot be read off *config* directly. This
    re-resolves cortex BY ROLE NAME from the lobes gateway (the same
    discovery rung ``colleague/config.py``'s muse/senses/worker rungs use),
    dialing *gateway_url* (defaults to ``config.lobes_gateway_url`` — the
    ARMED gateway origin the run actually resolved with) for a live
    ``/capabilities`` GET.

    Returns ``None`` — never raises — when there is no gateway to ask, the
    gateway is unreachable, or it advertises no usable cortex model; a
    caller (:func:`review_and_queue`) degrades a review to a no-op on
    ``None``, exactly like every other lobes-fed rung's absent-config stance.
    """
    from colleague import lobes as _lobes
    from colleague.config import _DEFAULT_API_KEY, _lobes_base_url, _same_origin

    url = gateway_url if gateway_url is not None else config.lobes_gateway_url
    if not url:
        return None
    roles = _lobes.resolve_roles(url)
    if roles is None:
        return None
    cortex_role = roles.cortex
    model = str(getattr(cortex_role, "model", "") or "").strip()
    if not model:
        return None
    base_url = _lobes_base_url(_lobes.resolve_role_base_url(cortex_role, url))
    # Same-origin inherit — but never the ACTING key: in three-tier mode
    # EngineConfig.resolve() repoints config.api_key to the WORKER's key
    # (t8), and forwarding it to the cortex endpoint would ship the wrong
    # Bearer (Qodo #367 review, thread 5). Legacy (no worker) keeps the
    # main key; three-tier inherits the operator-DECLARED key (env) or
    # degrades to the withheld default — visible at the call point, the
    # same c13 ladder every other rung uses. A config.json-declared main
    # key is not reachable here (no repo_path); env is the declared source.
    if not _same_origin(base_url, url):
        api_key = _DEFAULT_API_KEY
    elif config.worker is None:
        api_key = config.api_key
    else:
        declared = os.environ.get("COLLEAGUE_API_KEY") or os.environ.get("CONVERTIBLE_API_KEY")
        api_key = declared if declared else _DEFAULT_API_KEY
    context = int(getattr(cortex_role, "context", 0) or 0)
    return replace(
        config,
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_budget_tokens=context if context > 0 else config.context_budget_tokens,
    )


# ---------------------------------------------------------------------------
# The review input — a small, caller-assembled digest (never a message list)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfiguratorReviewInput:
    """Caller-assembled facts for ONE configurator review.

    ``digest`` is a compact TEXT digest of the episode's summary/snapshot
    facts — the caller (eventually a later task's chain/session wiring)
    assembles this; this module never composes it and never accepts a
    ``list[dict]`` message-history shape here or anywhere else (structural
    pin 1 — see the module docstring). Deliberately a single, small,
    frozen dataclass: adding a field here is a visible, reviewable change,
    never an incidental history leak.
    """

    digest: str = ""


# ---------------------------------------------------------------------------
# The review outcome
# ---------------------------------------------------------------------------


@dataclass
class ConfiguratorReviewResult:
    """The outcome of ONE :func:`review_and_queue` call.

    ``proposed`` is every :class:`~colleague.lattice.ChangeUnit` successfully
    PARSED from the reply (regardless of verdict); ``verified`` is the subset
    the lattice accepted and that is now queued on the lifecycle (NOT yet
    applied — see the module docstring); ``refused`` pairs each rejected
    entry (a raw JSON dict when parsing itself failed, or the constructed
    :class:`~colleague.lattice.ChangeUnit` when lattice validation refused
    it) with its recorded reason. ``degraded`` is ``True`` only when the
    completion call itself never usefully reached the cortex model (no
    dial, a dead endpoint, a request error) — distinct from a REFUSAL, which
    means cortex answered but the answer (or one entry in it) was invalid.
    """

    proposed: "list[ChangeUnit]" = field(default_factory=list)
    verified: "list[ChangeUnit]" = field(default_factory=list)
    refused: "list[tuple[Any, str]]" = field(default_factory=list)
    degraded: bool = False
    degraded_reason: str = ""
    raw_reply: str = ""


@dataclass(frozen=True)
class ConfiguratorWindowResult:
    """The outcome of ONE ``colleague/chain.py``'s ``run_configurator_window`` call.

    ``reviewed`` is ``False`` exactly when the configurator was not armed —
    the strict-no-op path (no review ran, ``review``/``application`` stay
    ``None``). When ``reviewed`` is ``True``, ``review`` is the
    :class:`ConfiguratorReviewResult` and ``application`` is the
    :class:`~colleague.configlifecycle.ConfigApplication` the SAME sanctioned
    window produced (draining whatever the review just queued, plus
    anything else already pending).
    """

    reviewed: bool
    review: "Optional[ConfiguratorReviewResult]" = None
    application: "Optional[ConfigApplication]" = None


# ---------------------------------------------------------------------------
# Prompt composition — prompted-JSON over a tools-off completion (mirrors
# colleague/senses_loop.py's _one_completion pattern; cited, not duplicated)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are the CORTEX CONFIGURATOR for colleague's opt-in three-tier "
    "execution mode. Between worker episodes you review the episode's facts "
    "and MAY propose typed configuration changes for the WORKER seat only: "
    "narrowing its tool set, adding worker knowledge, or marking a "
    "task-local evaluator note. You never talk to the operator or the "
    "worker directly, and nothing you write here is ever shown to either of "
    "them verbatim — you communicate ONLY through ONE JSON object naming "
    "zero or more typed changes.\n\n"
    "Valid targets: worker.tools, worker.prompt.evaluator, worker.knowledge.\n"
    '- A worker.tools change carries "tool_ids": a list of tool ids drawn '
    "ONLY from the available set below.\n"
    '- A worker.knowledge change carries "knowledge_entries": a list of '
    "JSON objects (each will be stamped with your origin).\n"
    '- A worker.prompt.evaluator change carries "content": a string note '
    f"for the worker's next episode, capped at {EVALUATOR_SECTION_MAX_CHARS} "
    "characters.\n\n"
    "Respond with EXACTLY one JSON object of this shape:\n"
    '{"changes": [{"target": "worker.tools", "tool_ids": ["..."]}]}\n'
    'If you have nothing to change this window, respond with {"changes": []}. '
    "No prose outside the JSON object."
)


def _build_user_prompt(review_input: ConfiguratorReviewInput, catalog: CapabilityCatalog) -> str:
    tool_ids = ", ".join(catalog.tool_ids) if catalog.tool_ids else "(none)"
    digest = review_input.digest.strip() if review_input.digest else "(no facts supplied)"
    return (
        f"Available worker tool ids this window: {tool_ids}\n\n"
        f"Episode facts:\n{digest}\n\n"
        "Respond with your JSON object now."
    )


# ---------------------------------------------------------------------------
# Reply parsing — strict JSON shape, malformed -> refused-whole, never a crash
# ---------------------------------------------------------------------------

#: Keys :func:`_build_change_unit` reads structurally; anything else on a
#: change entry becomes an ``extra_fields`` key, which the lattice's own
#: ``validate_change`` refuses whole (never re-implemented here).
_RECOGNIZED_CHANGE_KEYS = frozenset({"target", "tool_ids", "knowledge_entries", "content"})

#: Target string -> enum member, so a recognized target string reaches the
#: lattice/lifecycle as the real :class:`~colleague.lattice.Target` it needs
#: to be (``EpisodeConfigLifecycle.propose``'s worker-scope check is a
#: frozenset-of-enum-members containment test — a bare string never matches
#: it, even when the string names a genuinely valid target).
_TARGET_BY_VALUE = {t.value: t for t in Target}


def _parse_changes(raw: str) -> "tuple[Optional[list[Any]], str]":
    """Parse *raw* completion text into a list of raw change dicts.

    Returns ``(changes, "")`` on success — ``changes`` may be an empty list
    ("nothing to propose this window" is a legitimate, non-malformed reply,
    the common case). Returns ``(None, reason)`` when the WHOLE reply could
    not be read as the expected ``{"changes": [...]}`` shape — refused
    whole, never raises. Reuses
    :func:`colleague.plan.cli_driver._extract_json_object` (required_key=
    ``"changes"``) for the same tolerant prose/fence recovery every other
    prompted-JSON parser in this codebase gets (``colleague/senses_moves.py``'s
    ``parse_move``, the plan-mode claim/honesty/item parsers).
    """
    try:
        obj = _extract_json_object(raw, required_key="changes")
    except ValueError as exc:
        return None, f"malformed configurator reply: {exc}"
    changes = obj.get("changes")
    if not isinstance(changes, list):
        return None, "malformed configurator reply: 'changes' is not a list"
    return changes, ""


def _coerce_target(raw_target: Any) -> Any:
    """Map a recognized target STRING to its :class:`Target` enum member;
    anything else (an unrecognized string, or a non-string) passes through
    UNCHANGED so :func:`colleague.lattice.validate_change` (reached via
    :meth:`~colleague.configlifecycle.EpisodeConfigLifecycle.propose`)
    produces its own "unknown target" refusal reason — never re-implemented
    here."""
    if isinstance(raw_target, str) and raw_target in _TARGET_BY_VALUE:
        return _TARGET_BY_VALUE[raw_target]
    return raw_target


def _stamp_knowledge_origin(entry: "dict[str, Any]") -> "dict[str, Any]":
    """Return a COPY of *entry* with any entry-level ``"origin"`` discarded,
    then re-stamped :data:`~colleague.lattice.Origin.CORTEX`.

    Entry-level origin is host-known, exactly like the unit-level origin
    this module already stamps: this module IS the cortex producer, so a
    model-supplied ``"origin"`` on an individual knowledge entry (whether
    absent, empty, or an attempt to self-declare a stronger origin like
    ``"host"``) is never trusted — discarded first, then stamped, never
    conditionally left alone when "already present". *entry* itself is
    never mutated.
    """
    stamped = dict(entry)
    stamped.pop("origin", None)
    stamped["origin"] = Origin.CORTEX.value
    return stamped


def _build_change_unit(raw_entry: Any) -> "tuple[Optional[ChangeUnit], str]":
    """Build ONE :class:`~colleague.lattice.ChangeUnit` from *raw_entry*.

    Returns ``(unit, "")`` on success, or ``(None, reason)`` when *raw_entry*
    cannot be read as a change entry at all (not a JSON object, missing
    ``target``, or a wrongly-typed ``tool_ids``/``knowledge_entries``/
    ``content``) — refused whole, never a crash, mirroring the lattice's own
    "refuse the whole unit, never strip-and-retain" discipline.

    ``origin`` is ALWAYS stamped :data:`~colleague.lattice.Origin.CORTEX` at
    BOTH levels this unit can carry it — the unit's own ``origin`` field
    (a model-supplied ``"origin"`` key on the entry itself is read and
    discarded, never trusted) AND, via :func:`_stamp_knowledge_origin`,
    every individual ``knowledge_entries`` dict (a host-known fact: this
    module IS the cortex producer, so authority is never self-declared,
    whichever level it is claimed at). Any OTHER unrecognized key on the
    entry becomes an ``extra_fields`` entry, which
    :func:`colleague.lattice.validate_change` refuses whole with its own
    reason — this function does not special-case unknown keys itself.
    """
    if not isinstance(raw_entry, dict):
        return None, f"refused: change entry is not a JSON object ({raw_entry!r})"
    if "target" not in raw_entry:
        return None, "refused: change entry missing required 'target' key"

    tool_ids_raw = raw_entry.get("tool_ids", [])
    if not isinstance(tool_ids_raw, list) or not all(isinstance(t, str) for t in tool_ids_raw):
        return None, "refused: 'tool_ids' must be a list of strings"

    knowledge_raw = raw_entry.get("knowledge_entries", [])
    if not isinstance(knowledge_raw, list) or not all(isinstance(k, dict) for k in knowledge_raw):
        return None, "refused: 'knowledge_entries' must be a list of objects"

    content_raw = raw_entry.get("content", "")
    if not isinstance(content_raw, str):
        return None, "refused: 'content' must be a string"

    extra = {k: v for k, v in raw_entry.items() if k not in _RECOGNIZED_CHANGE_KEYS}
    extra.pop("origin", None)  # never trusted, never treated as an extra key either

    return (
        ChangeUnit(
            target=_coerce_target(raw_entry.get("target")),
            origin=Origin.CORTEX,
            tool_ids=list(tool_ids_raw),
            knowledge_entries=[_stamp_knowledge_origin(k) for k in knowledge_raw],
            content=content_raw,
            extra_fields=extra or None,
        ),
        "",
    )


def _target_str(target: Any) -> str:
    return target.value if isinstance(target, Target) else str(target)


# ---------------------------------------------------------------------------
# The review — ONE tools-off completion against the CORTEX dial
# ---------------------------------------------------------------------------


def review_and_queue(
    review_input: ConfiguratorReviewInput,
    *,
    catalog: CapabilityCatalog,
    lifecycle: EpisodeConfigLifecycle,
    stream: ConfigEventStream,
    cortex_config: "Optional[EngineConfig]",
    engine_name: str,
    engine_loader: "Optional[Callable[[str], Engine]]" = None,
) -> ConfiguratorReviewResult:
    """Run ONE synchronous cortex review; queue every verified change; NEVER
    raise (mirrors :func:`colleague.deepthink.run_deepthink`'s
    degrade-never-raise contract).

    A degraded review is VISIBLE, never silent (the #363 armed-is-not-alive
    lesson applied here): both early-return paths below append ONE
    :data:`~colleague.configevents.EVENT_KIND_DEGRADED` event onto *stream*,
    carrying the degradation reason, before returning — distinguishable from
    a healthy ``{"changes": []}`` reply (nothing to change this window),
    which appends nothing at all and is never degraded.

    Application is NOT performed here — see the module docstring's step 5:
    the caller (``colleague/chain.py``'s ``run_configurator_window``) calls
    :func:`colleague.chain.apply_config_window` at the SAME sanctioned
    window right after this returns.
    """
    if cortex_config is None:
        reason = "no cortex dial resolvable"
        stream.append(EVENT_KIND_DEGRADED, origin=Origin.CORTEX.value, reason=reason)
        return ConfiguratorReviewResult(degraded=True, degraded_reason=reason)

    from colleague import registry

    loader = engine_loader if engine_loader is not None else registry.load
    try:
        engine = loader(engine_name)
        # Tools-off ALWAYS (spec: an explicit empty tool list, never None) —
        # this completion structurally cannot call a tool or `finish`, and it
        # drives the CORTEX dial (resolve_cortex_dial), never the acting
        # engine's own completion seam (structural pin 2).
        complete = engine.make_complete(cortex_config, tools=[])
        simple = robust_simple_complete(complete)
        raw = simple(_SYSTEM_PROMPT, _build_user_prompt(review_input, catalog))
    except Exception as exc:  # pragma: no cover - exercised via a raising fake engine
        reason = str(exc)
        stream.append(EVENT_KIND_DEGRADED, origin=Origin.CORTEX.value, reason=reason)
        return ConfiguratorReviewResult(degraded=True, degraded_reason=reason)

    changes, error = _parse_changes(raw)
    if changes is None:
        stream.append(EVENT_KIND_REFUSED, origin=Origin.CORTEX.value, reason=error)
        return ConfiguratorReviewResult(refused=[(raw, error)], raw_reply=raw)

    result = ConfiguratorReviewResult(raw_reply=raw)
    for entry in changes:
        unit, build_error = _build_change_unit(entry)
        if unit is None:
            stream.append(EVENT_KIND_REFUSED, origin=Origin.CORTEX.value, reason=build_error)
            result.refused.append((entry, build_error))
            continue

        target_str = _target_str(unit.target)
        stream.append(EVENT_KIND_PROPOSED, target=target_str, origin=Origin.CORTEX.value)
        result.proposed.append(unit)

        verdict = lifecycle.propose(unit)
        if verdict.allowed:
            stream.append(EVENT_KIND_VERIFIED, target=target_str, origin=Origin.CORTEX.value)
            result.verified.append(unit)
        else:
            stream.append(
                EVENT_KIND_REFUSED,
                target=target_str,
                origin=Origin.CORTEX.value,
                reason=verdict.reason,
            )
            result.refused.append((unit, verdict.reason))

    return result


def record_applied(
    stream: ConfigEventStream,
    review: "Optional[ConfiguratorReviewResult]",
    application: "Optional[ConfigApplication]",
) -> None:
    """Append one ``"applied"`` event per unit *review* got applied.

    Called by ``colleague/chain.py``'s ``run_configurator_window`` right
    after :func:`~colleague.chain.apply_config_window` drains the SAME
    window's queue. Assumes *review*'s verified units are exactly what
    *application* drained — true for the ONE sanctioned call sequence this
    module builds (review immediately followed by that same window's apply,
    nothing else proposing onto the lifecycle in between); a caller that
    interleaves a host-authored direct ``lifecycle.propose()`` between
    review and apply is out of this task's scope. A no-op when *review* is
    ``None`` (the configurator was not armed) or *application* applied
    nothing.
    """
    if review is None or application is None or application.applied_count == 0:
        return
    for unit in review.verified:
        stream.append(
            EVENT_KIND_APPLIED, target=_target_str(unit.target), origin=Origin.CORTEX.value
        )
