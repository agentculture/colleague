"""vLLM/OpenAI payload-shaping + retry-classifier helpers.

Split out of ``colleague/engines/vllm_openai.py`` (plan ``hard-1000-line-file-limit``,
task t9) purely to fit the repo's hard 1000-physical-line file ceiling
(``tests/test_file_length_limit.py``) — a pure move, no behavior change. This module
owns the ladder-400 classifier + retry-warning record, the ``/tokenize`` POST
primitive, the same-role refresh id lookup, the associate-seat sampling contract,
the per-seat thinking-effort rung resolution, the headless delta-sink choice, and
the per-turn stream-guard bookkeeping. ``colleague/engines/vllm_transport.py`` owns
the raw HTTP/SSE transport. ``colleague/engines/vllm_openai.py`` keeps the
:class:`~colleague.engine.Engine` entry point (the pinned
``colleague.engines.vllm_openai:VllmOpenAIEngine`` import path) plus
``_tokenize_count``/``served_max_model_len``/``_MAX_MODEL_LEN_BY_URL`` themselves,
whose bare-name calls/reads must stay observable to a monkeypatch applied to
``colleague.engines.vllm_openai`` (several existing tests patch exactly that);
everything else the tokenize probe needs lives here, imported back in.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import Any, Callable

from colleague import associate_config, sampling, samplingfile, samplingwire, streamguards
from colleague.config import EngineConfig
from colleague.engines.vllm_transport import (
    _CONTENT_TYPE_JSON,
    _noop_delta,
    _same_role_call_time_refresh,
)

# ── ladder-400 retry (per-seat thinking effort, #416 t3, c2/h2/c7/h6/c27/h18) ─
#
# vLLM/Qwen3's chat template validates ``chat_template_kwargs.reasoning_effort``
# against its OWN ladder (low/medium/xhigh; see ``colleague/effort.py``) and
# answers an unknown rung with an HTTP 400 naming "reasoning effort" — a
# SERVER-SIDE mismatch, not a Colleague bug: drop the kwargs and retry once
# (``_make_complete``), the same "stale config, not a reason to die" posture as
# the 404 stale-pin refresh above, disjoint from it by status code.


def _is_ladder_400(exc: urllib.error.HTTPError) -> bool:
    """True for exactly the "server rejects this reasoning-effort ladder
    rung" shape: an HTTP 400 whose message names "reasoning effort"
    (case-insensitive). The real server's message: "Unexpected reasoning
    effort bogus. Supported types are xhigh (default), medium, and low."

    Reads ``str(exc)`` — mirroring :func:`_is_model_not_found_404`'s own
    convention — rather than re-reading the body directly: by the time this
    is reached, *exc* is already the RE-RAISED, body-folded exception
    :func:`_raise_legible_http_error` produces (its own re-raise carries no
    readable ``fp``, so a second :func:`_read_error_body` call on it would
    just see an empty body). Any other 400 (or any other status) is a
    genuine failure this classifier must NOT swallow — it propagates
    unguarded, exactly as before this task.
    """
    return exc.code == 400 and "reasoning effort" in str(exc).lower()


def _tokenize_url(base_url: str) -> str:
    """Derive the vLLM ``/tokenize`` URL from an OpenAI-style ``base_url``.

    ``/tokenize`` is served at the *server root*, not under ``/v1`` like the chat
    surface. Strip a trailing ``/v1`` (with or without a trailing slash) to get the
    root, then append ``/tokenize`` — so ``http://host:8001/v1`` (or
    ``…/v1/``) → ``http://host:8001/tokenize``. A base_url that does not end in
    ``/v1`` just gets ``/tokenize`` appended to its stripped form.
    """
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return f"{root.rstrip('/')}/tokenize"


def _tokenize_post(
    url: str, payload: dict[str, Any], *, api_key: str, timeout: float
) -> dict[str, Any]:
    """POST ``payload`` to the vLLM ``/tokenize`` endpoint and parse the JSON reply.

    Same wire style as :func:`_post_json` but a SEPARATE function on purpose: the
    chat-completions tests monkeypatch ``_post_json`` with a scripted mock, and the
    tokenize probe must never consume that script (tests patch :func:`_tokenize_count`).
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": _CONTENT_TYPE_JSON, "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(  # nosec B310 - configured endpoint
        request, timeout=timeout
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _delta_sink(on_delta: "Callable[[str], None] | None") -> "Callable[[str], None]":
    """The sink a streamed turn feeds: the caller's, or the headless no-op.

    An explicit ``is None`` test, NOT truthiness. The arming decision is
    ``config.on_delta is not None``, and a callable can be falsey via
    ``__bool__``/``__len__`` — a collector sink defining ``__len__`` is the
    obvious real case. ``or`` would arm streaming for such a sink and then
    silently swap it for the no-op, dropping every delta it was installed to
    receive (qodo-code-review, PR #401 comment 3746408765).
    """
    return _noop_delta if on_delta is None else on_delta


def _refreshed_model_id(
    config: EngineConfig, role_name: str, exc: "urllib.error.HTTPError"
) -> "str | None":
    """The same-role refreshed model id for a stale pin, else ``None``.

    ``None`` means the caller must re-raise unchanged: either this is a
    replaced-config seat (deepthink/senses), whose 404 belongs to that lane's
    own degrade path rather than a main-seat refresh (d5, issue 375), or the
    gateway offered no replacement.
    """
    if config.refresh_seat is None:
        return None
    return _same_role_call_time_refresh(config, role_name, exc)


def _apply_associate_profile(
    payload: "dict[str, Any]",
    profile: "associate_config.AssociateProfile",
    limit: "int | None",
) -> "int | None":
    """Write an associate seat's sampling contract (t23) onto *payload*.

    Nemotron's template takes the boolean toggle, not the Qwen ladder key;
    temperature/top_p come from the profile, never from cortex's config.
    Returns the ``max_tokens`` limit to send: DEPTH omits it (a small cap
    returned empty content under 200); a profile cap is honoured only where the
    window clamp *limit* allows it. Extracted from
    :meth:`VllmOpenAIEngine._build_chat_payload` (SonarCloud S3776/S3358);
    byte-identical payloads in every case.
    """
    payload["temperature"] = profile.temperature
    payload["top_p"] = profile.top_p
    payload["chat_template_kwargs"] = {"enable_thinking": profile.enable_thinking}
    if profile.max_tokens is None:
        return None
    if limit is None:
        return profile.max_tokens
    return min(profile.max_tokens, limit)


def _effort_for(config: EngineConfig) -> "str | None":
    """The thinking-effort rung THIS completion's payload should carry (#416 t3).

    ``config.reasoning_effort_seat`` is an OPTIONAL plain attribute — not a
    dataclass field, so it never shows up in ``to_dict()``/eq/repr — read via
    ``getattr`` and, when present and not ``None``, takes precedence over
    ``config.reasoning_effort_effective`` (the ACTING seat's resolved rung,
    :attr:`EngineConfig.reasoning_effort_effective`). Later seat-builder tasks
    (deepthink/senses/evaluator/subagent children) set it with a plain
    ``setattr`` on their OWN replaced config, exactly the way ``role``/
    ``worker`` already ride ``dataclasses.replace`` copies — a copy that never
    sets it just falls back to the acting-seat property, and
    ``dataclasses.replace`` naturally drops a plain attribute (it is not a
    field), which is the correct degrade: the copy re-resolves its own
    acting-seat rung rather than inheriting its parent's override.
    """
    # PRESENCE wins, not truthiness (Qodo #419 r2): a seat builder may set the
    # attribute to ``None`` — e.g. a per-seat/child override of the ``default``
    # kill-switch sentinel resolves to ``None`` — and that means "send nothing",
    # never "fall back to the acting seat". Absent (a fresh ``dataclasses.replace``
    # copy) is the only case that re-resolves the acting seat.
    if "reasoning_effort_seat" in getattr(config, "__dict__", {}):
        return config.__dict__["reasoning_effort_seat"]
    return config.reasoning_effort_effective


# ── per-model sampling profile on the wire (#479 t5, c1/c2/c8/c34/c37/c56) ──
#
# The ONE write site for sampling keys: :func:`_sampling_fragment` renders the
# profile :func:`colleague.sampling.resolve_sampling` resolved for THIS
# completion's model/role/rung, and ``_build_chat_payload``'s NON-associate
# branch merges it into the outgoing body. Nothing else in ``colleague/``
# writes a sampling key onto a payload (the associate seat's separate,
# pre-existing lane — :func:`_apply_associate_profile` — is deliberately
# untouched; its fold-in is a documented follow-up, not this task).

#: The per-PROCESS kill switch (c37). Deliberately NOT a file switch:
#: ``.colleague/models.json`` is TRACKED and therefore shared by every process
#: on the checkout, so only an environment variable lets two concurrent arms
#: (an A/B, or a byte-identical control) differ on one working tree. It carries
#: no value — unlike a global temperature it cannot flatten a model's two halves.
_SAMPLING_ENV_KEY = "COLLEAGUE_SAMPLING"
_SAMPLING_DISABLING_VALUES = frozenset({"0", "false", "no", "off"})


#: ``models.json`` half labels → :mod:`colleague.sampling`'s two halves. The
#: file format (t3) is intentionally uninterpreted at parse time; mapping its
#: labels is this consumer's job. An unrecognised label contributes no row.
_HALF_LABELS = {
    sampling.THINKING: sampling.THINKING,
    sampling.NON_THINKING: sampling.NON_THINKING,
    "non_thinking": sampling.NON_THINKING,
    "nonthinking": sampling.NON_THINKING,
    "instruct": sampling.NON_THINKING,
}


def _sampling_enabled() -> bool:
    """False only under the explicit ``COLLEAGUE_SAMPLING`` kill switch."""
    raw = os.environ.get(_SAMPLING_ENV_KEY)
    if raw is None:
        return True
    return raw.strip().lower() not in _SAMPLING_DISABLING_VALUES


def _operator_profile(values: "dict[str, Any]") -> "sampling.SamplingProfile | None":
    """One ``models.json`` half → a typed profile, or ``None`` for "nothing usable".

    Unrecognised keys and unparseable values are dropped individually
    (``associate_config.resolve_associate_profile``'s posture), so one typo
    never costs an operator the rest of their row — and never refuses a run.
    """
    fields: "dict[str, Any]" = {}
    for key, raw in values.items():
        cast = samplingwire.SAMPLING_COERCERS.get(key)
        if cast is None or isinstance(raw, bool):
            continue
        try:
            fields[key] = cast(raw)
        except (TypeError, ValueError):
            continue
    return sampling.SamplingProfile(**fields) if fields else None


def _operator_sampling_rows(config: EngineConfig) -> "tuple[sampling.SamplingRow, ...]":
    """The operator's ``.colleague/models.json`` rows as typed table rows (c56).

    A dispatched work item must read the same sampling table the operator repo
    declares, so the root is ``config.memory_root`` — the OPERATOR repo the CLI
    stamps on every isolated run (the ``memory_root`` precedent: an isolated
    run's throwaway worktree is not where operator state lives) — falling back
    to the process CWD when no front set it.

    KNOWN LIMITATION (t3's file shape): ``models.json`` nests model → half →
    keys, with NO role level, so every operator row resolves with
    ``role=None`` — it claims any seat. A per-seat operator row needs a file
    format change; this consumer deliberately does not invent a role nesting.
    """
    root = getattr(config, "memory_root", None) or os.getcwd()
    try:
        raw = samplingfile.load_models_file(root)
    except (OSError, ValueError):  # pragma: no cover - the loader promises not to raise
        return ()
    rows: "list[sampling.SamplingRow]" = []
    for model_id, halves in raw.items():
        model_key = sampling.normalize_model_id(model_id)
        if not model_key or not isinstance(halves, dict):
            continue
        for label, values in halves.items():
            half = _HALF_LABELS.get(str(label).strip().lower().replace("-", "_"))
            if half is None or not isinstance(values, dict):
                continue
            profile = _operator_profile(values)
            if profile is None:
                continue
            rows.append(
                sampling.SamplingRow(models=(model_key,), role=None, half=half, profile=profile)
            )
    return tuple(rows)


def _sampling_fragment(config: EngineConfig, rung: "str | None") -> "dict[str, Any]":
    """The sampling keys THIS completion should carry — the single write site.

    Empty (``{}`` — byte-identical to pre-#479) when the kill switch is set,
    when the rung yields no half, or when no row claims the served model: a
    checkpoint colleague holds no card for is left at the server's own
    defaults. Otherwise: exactly the keys the resolved row explicitly set,
    minus any whose value already equals a server default
    (:data:`colleague.samplingwire.SERVER_DEFAULT_SAMPLING`).

    Operator rows are layered AFTER :data:`~colleague.sampling.BUILTIN_SAMPLING_ROWS`
    so that :func:`~colleague.sampling.resolve_sampling`'s last-wins tie-break at
    equal specificity makes an operator row override the builtin it shadows.
    The override is ROW-level, not key-level (the ladder returns one row's whole
    profile), matching t2's resolution contract.

    No retry path exists for a server that REFUSES these keys (c34): exposure
    is already bounded — an unmatched model sends nothing — so a 400 surfaces
    exactly as it does today.
    """
    if not _sampling_enabled():
        return {}
    rows = tuple(sampling.BUILTIN_SAMPLING_ROWS) + _operator_sampling_rows(config)
    profile = sampling.resolve_sampling(
        config.model, role=getattr(config, "role", None), rung=rung, rows=rows
    )
    return samplingwire.wire_fragment(profile)


@dataclass(frozen=True)
class _LadderRetryWarning:
    """One ladder-400 retry record (#416 t3, c33/h23).

    Mirrors :class:`colleague.lobes.ModelRefreshWarning`'s shape/mechanism —
    a frozen record with a ``message()`` stderr line and a ``to_dict()`` for
    the run artifact — but lives in THIS module (this task edits only
    ``colleague/engines/vllm_openai.py``, so it cannot add a new dataclass
    field to ``EngineConfig``). It is recorded via
    :func:`_record_ladder_retry_warning` onto the plain
    ``config.reasoning_effort_warnings`` attribute (the same
    reassign-a-new-tuple convention ``config.model_refresh_warnings`` already
    uses, so a subagent child sharing this config value via
    ``dataclasses.replace`` never sees a parent's later call-time append and
    vice versa) — a later task can fold it onto ``TaskResult.warnings`` the
    same way ``colleague/cli/_commands/work.py`` already folds
    ``config.model_refresh_warnings`` (mirroring the t9→t11 split).
    """

    seat: str
    effort: "str | None"
    detail: str

    def message(self) -> str:
        return (
            f"colleague: reasoning-effort ladder retry — the {self.seat} seat's "
            f"{self.effort!r} rung was rejected by the server; retried once "
            f"without chat_template_kwargs. Server said: {self.detail}"
        )

    def to_dict(self) -> "dict[str, str]":
        return {"seat": self.seat, "effort": str(self.effort), "detail": self.detail}


def _emit_ladder_retry_warning(warning: _LadderRetryWarning) -> None:
    """Print *warning*'s message to stderr — mirrors
    :func:`colleague.lobes.emit_model_refresh_warning`'s convention. Never
    raises: a closed/broken stderr must never break the retry it announces.
    """
    with suppress(OSError):
        print(warning.message(), file=sys.stderr)


def ladder_retry_warnings_as_dicts(config: Any) -> "list[dict[str, Any]]":
    """The ladder-400 retry warnings recorded on *config* as artifact-ready dicts
    (Qodo #419 r4): the work front folds these into ``TaskResult.warnings`` before
    the artifact write, exactly like ``config.model_refresh_warnings``. Empty when
    none fired — a strict no-op on the unset path."""
    existing = getattr(config, "reasoning_effort_warnings", ()) or ()
    return [w.to_dict() if hasattr(w, "to_dict") else asdict(w) for w in existing]


def _record_ladder_retry_warning(config: EngineConfig, warning: _LadderRetryWarning) -> None:
    """Append *warning* onto ``config.reasoning_effort_warnings`` (a NEW
    tuple, never a shared-list mutation — see :class:`_LadderRetryWarning`).
    """
    existing: "tuple[_LadderRetryWarning, ...]" = getattr(config, "reasoning_effort_warnings", ())
    config.reasoning_effort_warnings = existing + (warning,)


def _record_transport_guarded(config: EngineConfig, streaming: bool) -> None:
    """Record on *config* whether THIS turn's transport is really stream-guarded.

    The loop suppresses its PROACTIVE backpressure timeout raise while the
    stream guards bound an alive-but-slow turn (#438 guidance 3). That decision
    used to read the ENVIRONMENT alone, which is default-armed — so a
    ``COLLEAGUE_STREAM=0`` run lost the guards *and* the raise (Qodo PR #450).
    Only the SSE reader (and the blocking fallback ``_stream_or_blocking``
    shares its guards with) reads its body through
    :func:`streamguards.guarded_lines`; a plain blocking POST does not, so it is
    honestly unguarded and keeps its one-time raise.

    Written as a plain attribute per turn, the ``config.base_timeout`` /
    ``config.reasoning_effort_warnings`` call-time-state convention; the loop
    reads it back through ``loop._make_transport_guard_probe``.
    """
    config.transport_stream_guarded = bool(streaming) and (
        streamguards.StreamGuards.from_env() is not None
    )
