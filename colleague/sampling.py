"""Per-model sampling profiles — the FIXED builtin table + resolution ladder (#479).

Why this exists: colleague sends no sampling parameters at all today, so a rig
serving Qwen3.8 runs the model at whatever the server defaults to. On the pinned
rig that is effectively greedy decoding in thinking mode, and greedy thinking
spirals (a 271k-char single turn, #479). The model card publishes the sampling
values the checkpoint was tuned for, per *half* — thinking and non-thinking — and
this module is the leaf that holds them.

Shape (modelled on :mod:`colleague.associate_config`, the shipped precedent):

* :class:`SamplingProfile` — a frozen dataclass of OPTIONAL fields. ``None``
  means **not set** and is distinguishable from a value that happens to equal
  the server default (``min_p=0.0``, ``repetition_penalty=1.0`` are card values
  the rows set EXPLICITLY). :func:`sampling_payload` renders only the keys a
  row actually set, so an un-set key is never sent.
* :class:`SamplingRow` — one table row: the normalised model ids it claims
  (empty = any model), the seat/role it claims (``None`` = any role), the half
  it applies to, and the profile.
* :data:`BUILTIN_SAMPLING_ROWS` — the FIXED builtin table (Qwen3.8 card values).
* :func:`normalize_model_id` — the match rule.
* :func:`resolve_sampling` — the ladder.

Import direction: pure stdlib plus :mod:`colleague.effort` (for the ladder
vocabulary and the kill-switch sentinel). This module imports NOTHING from
:mod:`colleague.config` or :mod:`colleague.loop` — it is a leaf, exactly the way
``effort`` is, so the adapter and the operator-table loader can both consume it
without an import cycle.

**The half is derived from the rung, never resolved here.** Under the #416
effort ladder the rung ``"off"`` IS the model's non-thinking mode and every
other rung is the thinking half; the caller passes the rung
``vllm_payload._effort_for`` already computed. ``None`` and the
:data:`~colleague.effort.DEFAULT_SENTINEL` kill-switch resolve to NO half and
therefore to NO sampling keys at all — the byte-identical off-state.

**Enumerated ids, never a loose prefix.** A row lists the normalised ids it
claims. ``Qwen3.8-4B`` is not ``Qwen3.8-27B`` and must not inherit the 27B
card just because the names share a prefix; a checkpoint colleague has no card
for gets no sampling keys, which is the honest degrade.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional, Sequence

from colleague.effort import DEFAULT_SENTINEL, LADDER

__all__ = [
    "BUILTIN_SAMPLING_ROWS",
    "DEFAULT_SENTINEL",
    "NON_THINKING",
    "THINKING",
    "SamplingProfile",
    "SamplingRow",
    "half_for_rung",
    "normalize_model_id",
    "resolve_sampling",
    "sampling_payload",
]

#: The two halves a row can claim. Under the #416 ladder these are derived from
#: the rung (``"off"`` is the model's non-thinking mode), never resolved here.
THINKING = "thinking"
NON_THINKING = "non_thinking"

#: Quantisation / packaging suffixes stripped from a served id before matching.
#: A served checkpoint is the same MODEL as its card at a different precision,
#: so ``unsloth/Qwen3.8-27B-NVFP4`` and ``Qwen/Qwen3.8-27B`` must land on one
#: row. Stripped repeatedly (``-W8A8-INT8``), longest first, case-insensitively.
_QUANT_SUFFIXES = (
    "-bnb-4bit",
    "-nvfp4",
    "-gptq",
    "-gguf",
    "-w8a8",
    "-int8",
    "-int4",
    "-fp16",
    "-bf16",
    "-awq",
    "-fp8",
)


@dataclass(frozen=True)
class SamplingProfile:
    """The sampling keys one row sets. ``None`` = **not set** (key omitted).

    Every field is optional on purpose: a row may set only ``temperature``, and
    a row may set ``min_p=0.0`` — the card's value, which happens to equal the
    server default. Those two cases must stay distinguishable, because only the
    second one is a deliberate, card-sourced instruction to the server.
    """

    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    repetition_penalty: Optional[float] = None


@dataclass(frozen=True)
class SamplingRow:
    """One table row.

    ``models`` are NORMALISED ids (see :func:`normalize_model_id`), ENUMERATED —
    an empty tuple claims any model. ``role`` is the seat/role name the row
    claims, ``None`` claiming any. ``half`` is :data:`THINKING` or
    :data:`NON_THINKING`.
    """

    models: tuple = ()
    role: Optional[str] = None
    half: str = THINKING
    profile: SamplingProfile = SamplingProfile()


#: The FIXED builtin table. Qwen3.8 27B, both halves, verbatim from the model
#: card recorded in issue #479. ``role`` is ``None``: the card is a property of
#: the checkpoint, not of the seat that dials it — a per-seat row is an operator
#: override (t3), never a builtin.
BUILTIN_SAMPLING_ROWS: tuple = (
    SamplingRow(
        models=("qwen3.8-27b",),
        role=None,
        half=THINKING,
        profile=SamplingProfile(
            temperature=1.0,
            top_p=0.95,
            top_k=20,
            min_p=0.0,
            presence_penalty=0.0,
            repetition_penalty=1.0,
        ),
    ),
    SamplingRow(
        models=("qwen3.8-27b",),
        role=None,
        half=NON_THINKING,
        profile=SamplingProfile(
            temperature=0.7,
            top_p=0.80,
            top_k=20,
            presence_penalty=1.5,
        ),
    ),
)


def normalize_model_id(model: object) -> str:
    """Normalise a model id for matching: drop the organisation prefix, strip
    the quantisation suffix, lowercase.

    ``unsloth/Qwen3.8-27B-NVFP4`` and ``Qwen/Qwen3.8-27B`` both become
    ``qwen3.8-27b``; ``Qwen/Qwen3.8-4B`` becomes ``qwen3.8-4b`` and matches
    nothing the 27B row claims. Anything unparseable (a non-string, a blank)
    normalises to ``""`` — which matches no enumerated row — rather than
    raising, mirroring ``associate_config``'s tolerant resolution.
    """
    if not isinstance(model, str):
        return ""
    text = model.strip().rsplit("/", 1)[-1].strip().lower()
    changed = True
    while changed and text:
        changed = False
        for suffix in _QUANT_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return text


def half_for_rung(rung: object) -> Optional[str]:
    """The half a resolved effort rung selects, or ``None`` for "no keys".

    ``"off"`` is the model's NON-thinking mode; every other ladder rung is the
    thinking half. ``None``, the :data:`~colleague.effort.DEFAULT_SENTINEL`
    kill-switch and any value not on the ladder each return ``None`` — the
    caller then sends no sampling keys at all. The rung is CONSUMED here, never
    resolved: :func:`colleague.effort.resolve_effort` (via
    ``vllm_payload._effort_for``) owns that.
    """
    if not isinstance(rung, str):
        return None
    value = rung.strip()
    if not value or value == DEFAULT_SENTINEL or value not in LADDER:
        return None
    return NON_THINKING if value == "off" else THINKING


def _specificity(row: SamplingRow, model_key: str, role: Optional[str]) -> Optional[int]:
    """How specifically *row* matches, or ``None`` when it does not match.

    3 = model + role, 2 = model only, 1 = role only, 0 = the half-only
    default. The half itself is a precondition, not a score: a row for the
    other half never matches at any specificity.
    """
    score = 0
    if row.models:
        if not model_key or model_key not in row.models:
            return None
        score += 2
    if row.role is not None:
        if role is None or row.role != role:
            return None
        score += 1
    return score


def resolve_sampling(
    model: object,
    role: Optional[str] = None,
    rung: object = None,
    rows: Optional[Sequence[SamplingRow]] = None,
) -> Optional[SamplingProfile]:
    """Resolve the sampling profile for *model* / *role* / *rung*.

    Most-specific-wins over ``model+role+half > model+half > role+half >
    half``; at EQUAL specificity the LAST matching row wins, so an operator
    table layered after :data:`BUILTIN_SAMPLING_ROWS` (t3) overrides a builtin
    row rather than being shadowed by it.

    Returns ``None`` — meaning **no sampling keys at all** — when the rung
    yields no half (unset / kill-switch / unparseable) or when no row matches
    the model. A checkpoint colleague holds no card for is left at the server's
    own defaults, which is the honest degrade.
    """
    half = half_for_rung(rung)
    if half is None:
        return None
    model_key = normalize_model_id(model)
    table = BUILTIN_SAMPLING_ROWS if rows is None else rows
    best: Optional[SamplingProfile] = None
    best_score = -1
    for row in table:
        if row.half != half:
            continue
        score = _specificity(row, model_key, role)
        if score is not None and score >= best_score:
            best_score = score
            best = row.profile
    return best


def sampling_payload(profile: Optional[SamplingProfile]) -> dict:
    """Render a profile into the payload fragment a completion merges in.

    ONLY the keys the row explicitly set — an un-set (``None``) field is
    omitted, so colleague never asserts a value it has no card for. ``None``
    (no matching row / no half) renders ``{}``: byte-identical to today.
    """
    if profile is None:
        return {}
    payload: dict = {}
    for field in fields(profile):
        value = getattr(profile, field.name)
        if value is not None:
            payload[field.name] = value
    return payload
