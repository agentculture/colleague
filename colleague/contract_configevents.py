"""Config-event mapping split out of :mod:`colleague.contract` (task t13,
hard-1000-line-file-limit): :class:`ConfigEventRecord` (contract.py's own
compatible extension of :class:`~colleague.configevents.ConfigEvent`), the
``EpisodeConfigLifecycle`` → durable ``ConfigEvent`` mapper
(:func:`map_configlifecycle_events` and its helpers), and the two digest
helpers :func:`config_digest_for` / :func:`prompt_digest_for`. Re-exported
from ``colleague.contract`` so every existing ``from colleague.contract
import ...`` call site resolves unmodified.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Sequence

from colleague.configevents import (
    EVENT_KIND_APPLIED,
    EVENT_KIND_BASELINE,
    EVENT_KIND_PROPOSED,
    EVENT_KIND_REFUSED,
    ConfigEvent,
    effective_digest,
)

# ---------------------------------------------------------------------------
# Config event fold (three-tier-execution plan task t8, covers c6/h6/c36/h29)
# ---------------------------------------------------------------------------
#
# colleague.configlifecycle.EpisodeConfigLifecycle keeps its OWN small,
# in-memory event log (kind in {"proposed", "refused", "applied", "boundary"}
# — a deliberate subset of the full configevents vocabulary; see that
# module's own docstring) plus a per-window application history. Neither of
# those lifecycle-native shapes is what TaskResult.config_events carries —
# this section is the ONE mapper that turns the lifecycle's own records into
# durable configevents.ConfigEvent entries, reusing the vocabulary
# configevents.py already owns rather than inventing a parallel one here.
# configevents.py itself belongs to a sibling task (t6) this wave and is
# never touched by this mapper or by ConfigEventRecord below — both are
# contract.py's own compatible extension of ConfigEvent's shape.


#: Lifecycle kind -> the honest configevents.py kind it maps onto.
#: "proposed"/"refused"/"applied" share their literal string with
#: configevents' own EVENT_KIND_* constants (imported, not re-typed here, so
#: a rename on either side cannot silently drift the mapping out of sync).
#: "boundary" has no durable counterpart of its own in configevents.py: an
#: episode boundary marks a RESTING config STATE observed at that instant
#: (never a change action) — which is exactly what EVENT_KIND_BASELINE
#: already means in that module's vocabulary (a "starting config, seeded"
#: checkpoint the T8-trap guard requires to be explicit). Every OTHER kind in
#: EVENT_KINDS (proposed/refused/verified/applied/reverted/degraded)
#: describes a mutation, so baseline is the one honest existing kind a
#: boundary can map onto without inventing a new one.
_LIFECYCLE_KIND_TO_CONFIG_EVENT_KIND: dict[str, str] = {
    "proposed": EVENT_KIND_PROPOSED,
    "refused": EVENT_KIND_REFUSED,
    "applied": EVENT_KIND_APPLIED,
    "boundary": EVENT_KIND_BASELINE,
}

#: The one lattice target string whose APPLIED unit carries content worth
#: folding onto the artifact. Mirrors
#: ``colleague.lattice.Target.WORKER_PROMPT_EVALUATOR.value`` — duck-typed
#: here (a plain string compare) rather than importing ``colleague.lattice``,
#: so this mapper stays exactly as decoupled from the lattice's typed surface
#: as ``colleague/configevents.py`` itself already is (that module's own
#: docstring: "target/origin are free-form strings here ... so this stream
#: stays usable by any future producer").
_EVALUATOR_TARGET_VALUE = "worker.prompt.evaluator"


@dataclass
class ConfigEventRecord(ConfigEvent):
    """A :class:`~colleague.configevents.ConfigEvent` extended with the
    verbatim applied evaluator ``content`` (plan task t8, decision q5).

    ``configevents.py`` belongs to a sibling task this wave and is not
    touched here — this subclass is contract.py's own COMPATIBLE extension
    of the base dataclass's ``to_dict``/``from_dict`` shape: ``content`` is
    OMITTED (not emitted as an empty string) whenever it is empty, so an
    ordinary proposed/refused/applied-non-evaluator/baseline record
    serializes byte-identically to a plain :class:`ConfigEvent`, and an
    artifact written before this field existed loads with ``content=""``
    (falsy — round-trips right back to the same omitted shape old artifacts
    always had). Only an APPLIED ``worker.prompt.evaluator`` record ever
    carries a non-empty ``content``; refused records stay reason-only
    (acceptance 2) — nothing here special-cases that, it simply follows from
    :func:`map_configlifecycle_events` never setting ``content`` on anything
    but an applied evaluator record.

    A plain :class:`ConfigEvent` (e.g. one another producer like
    :mod:`colleague.configurator` appends directly onto a
    :class:`~colleague.configevents.ConfigEventStream`) is left completely
    alone by this subclass's existence — its own ``to_dict`` is unaffected,
    since Python dispatches on each instance's *actual* class.
    """

    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        if self.content:
            d["content"] = self.content
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfigEventRecord":
        base = ConfigEvent.from_dict(data)
        return cls(
            kind=base.kind,
            target=base.target,
            origin=base.origin,
            reason=base.reason,
            seq=base.seq,
            content=str(data.get("content", "") or ""),
        )


def map_configlifecycle_events(
    events: Sequence[Any],
    *,
    applied_units: Sequence[Any] = (),
) -> list[ConfigEvent]:
    """Map one :meth:`~colleague.configlifecycle.EpisodeConfigLifecycle.events`
    replay (append-only, kind in ``{"proposed", "refused", "applied",
    "boundary"}``) onto durable :class:`ConfigEvent` entries — the shape
    :attr:`TaskResult.config_events` carries. A mapped event that carries
    applied evaluator content (see *applied_units* below) is a
    :class:`ConfigEventRecord`; every other mapped event is a PLAIN
    :class:`ConfigEvent` — the same class-selection rule
    :func:`colleague.contract_coerce._coerce_config_events` uses reading an
    artifact back, so mapper output and a round-tripped artifact are
    indistinguishable.

    *events* is duck-typed (each item needs only ``.kind``/``.target``/
    ``.origin``/``.detail`` attributes) so this function never imports
    ``colleague.configlifecycle`` — mirroring ``colleague/configevents.py``'s
    own "free-form, usable by any future producer" stance. Kinds map
    honestly (see :data:`_LIFECYCLE_KIND_TO_CONFIG_EVENT_KIND`); an
    unrecognized kind passes through UNCHANGED rather than being invented
    into something new — unreachable today (the lifecycle emits only the
    four kinds named above), a signal that a future lifecycle kind needs its
    own deliberate mapping decision if this fallback ever actually fires.
    ``seq`` is assigned by THIS function from each event's position in
    *events* (the lifecycle's own ``ConfigEvent`` carries no ``seq`` of its
    own — only :class:`~colleague.configevents.ConfigEventStream` does).

    *applied_units* supplies the actual :class:`~colleague.lattice.ChangeUnit`
    objects that were applied — matched POSITIONALLY, one per "applied"-kind
    lifecycle event, in the same order
    :meth:`~colleague.configlifecycle.EpisodeConfigLifecycle.apply_window`
    drained its queue (a caller accumulates this across every sanctioned
    window it has run so far — e.g. ``colleague.chain.run_configurator_
    window``'s ``ConfiguratorWindowResult.review.verified`` units — since the
    applied CONTENT lives on neither the lifecycle event nor
    :class:`~colleague.configlifecycle.ConfigApplication`; only the
    originally-queued :class:`~colleague.lattice.ChangeUnit` carries it).
    Content rides the mapped record ONLY when the paired unit targets
    ``worker.prompt.evaluator`` (the lattice's only content-bearing target
    this lifecycle ever applies — ``senses.*`` proposals are refused before
    they ever queue). Every other applied unit (worker.tools/
    worker.knowledge) contributes nothing to ``content``, matching the
    "refused records stay reason-only, content only on applied evaluator
    records" acceptance (criterion 2). *applied_units* shorter than the
    number of "applied" events in *events* is tolerated (the trailing
    applied events simply get no content) — this function never raises.
    """
    applied_iter = iter(applied_units)
    mapped: list[ConfigEvent] = []
    for seq, event in enumerate(events):
        mapped.append(_map_one_lifecycle_event(seq, event, applied_iter))
    return mapped


def _applied_unit_content(applied_iter: Iterator[Any]) -> str:
    """Pull the next applied :class:`~colleague.lattice.ChangeUnit` (if any)
    off *applied_iter* and return its content when it targets the evaluator
    prompt — the "content only on applied evaluator records" rule (see
    :func:`map_configlifecycle_events`). Returns ``""`` when the iterator is
    exhausted or the applied unit carries no evaluator content.
    """
    unit = next(applied_iter, None)
    if unit is None:
        return ""
    target = getattr(unit, "target", None)
    target_value = getattr(target, "value", target)
    unit_content = str(getattr(unit, "content", "") or "")
    if target_value == _EVALUATOR_TARGET_VALUE and unit_content:
        return unit_content.strip()
    return ""


def _map_one_lifecycle_event(seq: int, event: Any, applied_iter: Iterator[Any]) -> ConfigEvent:
    """Map a single lifecycle event onto a durable :class:`ConfigEvent` (or
    :class:`ConfigEventRecord` when it carries applied evaluator content).

    Extracted from :func:`map_configlifecycle_events` to keep the caller's
    cognitive complexity under the S3776 ceiling (the ``_moded_config``
    precedent, PR #338).
    """
    kind = str(getattr(event, "kind", ""))
    mapped_kind = _LIFECYCLE_KIND_TO_CONFIG_EVENT_KIND.get(kind, kind)
    # "refused records stay reason-only" (acceptance 2): every other kind
    # keeps reason empty, matching ConfigEvent's own stated convention —
    # except "degraded" (stream-only, the #363 visibility rung), whose reason
    # IS the degradation. The source attribute differs by producer: the
    # lifecycle's internal events carry ``detail``, the configurator stream's
    # durable events carry ``reason`` — read whichever is present so this
    # mapper serves both (the fold sources the configurator CYCLE from the
    # stream precisely because pre-propose refusals exist only there).
    reason = ""
    if kind in ("refused", "degraded"):
        reason = str(getattr(event, "detail", "") or getattr(event, "reason", ""))
    content = _applied_unit_content(applied_iter) if kind == "applied" else ""
    base_kwargs: dict[str, Any] = {
        "kind": mapped_kind,
        "target": str(getattr(event, "target", "")),
        "origin": str(getattr(event, "origin", "")),
        "reason": reason,
        "seq": seq,
    }
    if content:
        return ConfigEventRecord(content=content, **base_kwargs)
    return ConfigEvent(**base_kwargs)


def config_digest_for(events: Sequence[ConfigEvent]) -> Optional[str]:
    """``TaskResult.config_digest`` for *events* — :func:`colleague.
    configevents.effective_digest` over the sequence, or ``None`` when
    *events* is empty.

    Mirrors ``config_digest``'s own omit-when-``None`` field convention, and
    exists so the "digest is a pure function of ``config_events``" invariant
    stays true from ONE call site — a caller that just changed
    ``config_events`` (the front folding a window, or
    :func:`colleague.artifact.update_config_events` rewriting an
    already-persisted artifact) recomputes ``config_digest`` from here rather
    than each re-deriving the omit-when-empty rule independently.
    """
    if not events:
        return None
    return effective_digest(list(events))


def prompt_digest_for(system_prompt: Optional[str]) -> Optional[str]:
    """``TaskResult.prompt_digest`` for *system_prompt* — a plain sha256 hex
    digest of the COMPOSED prompt string, or ``None`` when the backend
    composed no system prompt (plan task t7).

    Deliberately the narrowest possible function: it hashes exactly the bytes
    a backend hands ``loop.run`` as ``system_prompt``, so whatever the
    composition path actually produced — base family text, role prompt, an
    operator overlay from ``.colleague/agents/<role>.md`` — is inside the
    digest. It never re-derives the prompt from config, because a digest of a
    re-derivation would attest to what the prompt *should* have been rather
    than what ran (the whole point of the field).

    Mirrors ``config_digest_for``'s omit-when-``None`` shape so both digests
    on the artifact are produced by one convention. An EMPTY prompt (``""``)
    is a composed prompt and DOES get a digest; only ``None`` (no prompt at
    all) is omitted.
    """
    if system_prompt is None:
        return None
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
