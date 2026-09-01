"""The vLLM OpenAI-compatible engine — the first real coder backend (R2).

It drives a local coding model (the reference rig: Qwen3-32B on a vLLM server at
``localhost:8001``) purely through the OpenAI ``/v1/chat/completions`` surface
with tool/function calling. Because it touches *only* that surface — and uses the
stdlib ``urllib`` rather than any vendor SDK — pointing :class:`EngineConfig` at
any OpenAI-compatible server (vLLM, llama.cpp, an OpenAI proxy) is a config
change, never a code change (honesty condition h2).

vLLM note: tool calling needs the server started with ``--enable-auto-tool-choice``
and a ``--tool-call-parser`` matching the model (e.g. ``hermes`` for many models,
``qwen3_coder`` for some Qwen3 builds). The engine is parser-agnostic — it only
needs the server to emit OpenAI-format tool calls.

This module keeps the :class:`~colleague.engine.Engine` entry point — the pinned
``colleague.engines.vllm_openai:VllmOpenAIEngine`` import path (``pyproject.toml``'s
``vllm-openai`` entry point) — plus ``_stream_or_blocking``,
``_tokenize_count``, ``served_max_model_len``, and ``_MAX_MODEL_LEN_BY_URL``
themselves: several existing tests monkeypatch sibling names (e.g. ``_post_json``,
``_post_json_stream``, ``_tokenize_post``) through the ``colleague.engines.vllm_openai``
alias and rely on THESE functions' bare-name calls into them staying observable to
that patch — a bare-name lookup always resolves through the __globals__ of the
module a function is textually DEFINED in, never the module it happens to be
imported through, so moving one half of such a pair without the other silently
stops the patch from intercepting anything. Every other transport/payload helper
lives in the two siblings this module imports from —
:mod:`colleague.engines.vllm_transport` (raw HTTP + SSE streaming) and
:mod:`colleague.engines.vllm_payload` (payload shaping + tokenize/retry helpers) —
plan ``hard-1000-line-file-limit``, task t9: a pure move to fit the repo's hard
1000-physical-line file ceiling, no behavior change.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from typing import Any, Callable

import colleague.turnbudget as turnbudget
from colleague import associate, associate_seats, effort, streamguards, tokenestimate
from colleague.agents.artifact_block import fold_agents_block
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult, prompt_digest_for
from colleague.deepthink import make_deepthink_run
from colleague.engine import Engine

# Re-exported (not used below): colleague/cli/_commands/work.py reads this as
# ``_vllm_openai.ladder_retry_warnings_as_dicts`` after every work item.
from colleague.engines.vllm_payload import ladder_retry_warnings_as_dicts  # noqa: F401
from colleague.engines.vllm_payload import (
    _apply_associate_profile,
    _delta_sink,
    _effort_for,
    _emit_ladder_retry_warning,
    _is_ladder_400,
    _LadderRetryWarning,
    _record_ladder_retry_warning,
    _record_transport_guarded,
    _refreshed_model_id,
    _sampling_fragment,
    _tokenize_post,
    _tokenize_url,
)

# Re-exported below (never called from this module's own code): pre-t9 callers
# imported these directly off ``colleague.engines.vllm_openai`` — a plain
# ``from colleague.engines.vllm_openai import <name>`` needs the attribute to
# exist here regardless of which sibling module now defines it, exactly like
# the monkeypatch case documented at the top of this file.
from colleague.engines.vllm_transport import (  # noqa: F401
    _CONTENT_TYPE_JSON,
    _STREAM_DISABLING_VALUES,
    _STREAM_ENV_KEY,
    _STREAM_FALLBACK_ERRORS,
    _STREAM_UNSUPPORTED_HTTP_CODES,
    _accumulate_frame_tool_calls,
    _accumulate_tool_call_fragment,
    _apply_stream_frame,
    _blocking_payload,
    _capture_frame_usage,
    _decode_tool_call_arguments,
    _emit_content_and_reasoning_deltas,
    _emit_delta,
    _emit_stream_fallback_notice,
    _finalize_tool_calls,
    _headless_streaming_enabled,
    _is_model_not_found_404,
    _is_stream_unsupported_http_error,
    _iter_sse_frames,
    _noop_delta,
    _parse_response,
    _post_json,
    _post_json_stream,
    _raise_legible_connection_error,
    _raise_legible_http_error,
    _raise_legible_timeout,
    _read_error_body,
    _same_role_call_time_refresh,
    _StreamAccumulator,
    _StreamIncomplete,
)
from colleague.loop import (
    CompleteFn,
    ContextControls,
    ModelResponse,
    curated_schemas,
    resolve_role,
    run,
)
from colleague.senses import make_senses_run
from colleague.tae_loop import make_tae_session
from colleague.tools import SCHEMAS, ToolExecutor, narrow_role_by_tool_set

#: ``/tokenize`` URL → the reply's ``max_model_len`` (t12 window discovery); filled
#: by :func:`_tokenize_count`, read by the run-start probe. A plain dict, never a
#: thread primitive: the value is per endpoint, so concurrent writers agree.
#: Keyed by ``(tokenize url, model)`` (#460): two seats behind ONE gateway (cortex
#: and the role-addressed associate) serve different windows, so a URL-only key
#: let one seat's probe clobber the other's.
#:
#: Kept textually in THIS module (not :mod:`colleague.engines.vllm_payload`,
#: where :func:`_tokenize_post` and every other tokenize helper live) because
#: several tests monkeypatch this dict (and :func:`_tokenize_post`) through the
#: ``colleague.engines.vllm_openai`` alias and rely on :func:`_tokenize_count` /
#: :func:`served_max_model_len`'s bare-name reads seeing that patch — see the
#: module docstring above.
_MAX_MODEL_LEN_BY_URL: dict[tuple[str, str], int] = {}


def served_max_model_len(url: str, model: str) -> "int | None":
    """The ``/tokenize``-reported ``max_model_len`` for *(url, model)* once probed."""
    return _MAX_MODEL_LEN_BY_URL.get((url, model))


def _tokenize_count(
    messages: list[dict[str, Any]], *, url: str, model: str, api_key: str, timeout: float
) -> int | None:
    """Return the server's exact token count for *messages*, or ``None`` on any error.

    POSTs ``{"model", "messages"}`` to the vLLM ``/tokenize`` endpoint and reads the
    integer ``"count"`` field; ``None`` for *any* failure (HTTPError incl. a 404,
    URLError, timeout, decode error, missing/non-int count) so the caller can fall
    back to the char estimate — retargeting a non-vLLM server stays a config
    change. The reply's ``max_model_len`` lands in :data:`_MAX_MODEL_LEN_BY_URL`.
    """
    try:
        data = _tokenize_post(
            url, {"model": model, "messages": messages}, api_key=api_key, timeout=timeout
        )
    except Exception:  # nosec B110 - any tokenize failure falls back to the char estimate
        return None
    if isinstance(data.get("max_model_len"), int):
        _MAX_MODEL_LEN_BY_URL[(url, model)] = data["max_model_len"]
    count = data.get("count")
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    return count


def _stream_or_blocking(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: float,
    on_delta: Callable[[str], None],
) -> ModelResponse:
    """Stream one turn, falling back to ONE blocking request on a mid-stream
    failure — so a broken stream never breaks a run (task t5).

    Tries :func:`_post_json_stream` first (the SAME *payload*, still carrying
    ``stream``/``stream_options``). Any deltas already emitted via *on_delta*
    before a failure are NOT retracted — the cockpit's live tail treats a
    later event as superseding an in-flight one (t6), so a superseded partial
    stream is harmless — this function only decides whether the TURN itself
    recovers.

    Falls back to ONE blocking (non-stream) POST for the identical turn — via
    the SAME :func:`_post_json`/:func:`_parse_response` the unarmed path
    already uses, stripped of the stream keys (:func:`_blocking_payload`) —
    on exactly the failure shapes that are a *streaming*-specific problem,
    never a genuine model/server failure a retry can't fix:

      - the stream ended with no terminal frame (``_StreamIncomplete``);
      - a malformed ``data:`` JSON frame (``json.JSONDecodeError``);
      - a connection drop mid-transfer (``http.client.IncompleteRead``, or the
        legible ``ConnectionError`` the transport module already wraps a bare
        ``URLError`` into — whether the drop happened at open or mid-transfer,
        the wrapped shape is the same);
      - a stream-refusing server: a 400/422 naming ``stream``/``stream_options``
        (:func:`_is_stream_unsupported_http_error`) — arming ``on_delta`` is
        display-only and must never make an otherwise-working server unusable.

    A read-phase TIMEOUT is deliberately NOT fallback-eligible here — it
    already has its own bounded retry at the loop level
    (``colleague.context.classify_degradable`` /
    ``colleague.loop._MAX_TIMEOUT_RETRIES``). Folding it into this fallback
    too would let a single turn silently spend THREE full ``timeout`` windows
    (the stream attempt, the blocking fallback, and the loop's own retry)
    instead of the documented worst case of two — and an unrelated HTTP
    error (any status/body not naming stream support) is left alone for the
    same "don't waste an attempt on a failure retrying can't fix" reason.

    Worst-case timing (documented, not enforced by a new retry loop): ONE
    stream attempt up to *timeout*, plus — only on a fallback-eligible
    failure — ONE blocking attempt reusing the SAME *timeout*. Bounded at
    2×timeout for a single turn, never more; this is the only retry this
    function performs.

    A failing blocking attempt propagates ITS OWN error unchanged (already
    legible via :func:`_post_json`'s own wrapping) — the loop's existing
    degradation path handles it exactly as it does today.

    The turn's :class:`streamguards.StreamGuards` (c12, #438) is built ONCE
    here and shared by BOTH paths, so a drip-feeding server on the fallback
    trips the idle/lifetime bound within the turn's own clock. The lifetime
    clock starts at the turn, not at the fallback — a turn that already spent
    time on the stream attempt gets no fresh window for the retry.
    """
    guards = streamguards.StreamGuards.from_env(base_timeout=timeout)
    try:
        return _post_json_stream(
            url, payload, api_key=api_key, timeout=timeout, on_delta=on_delta, guards=guards
        )
    except urllib.error.HTTPError as exc:
        if not _is_stream_unsupported_http_error(exc):
            raise
        _emit_stream_fallback_notice(f"server rejected streaming ({exc.code}): {exc.msg}")
    except _STREAM_FALLBACK_ERRORS as exc:
        _emit_stream_fallback_notice(f"{type(exc).__name__}: {exc}")

    data = _post_json(
        url, _blocking_payload(payload), api_key=api_key, timeout=timeout, guards=guards
    )
    return _parse_response(data)


class VllmOpenAIEngine(Engine):
    """Drives an OpenAI-compatible chat-completions endpoint with tool calling."""

    name = "vllm-openai"

    def _make_count_tokens(self, config: EngineConfig) -> Callable[[list[dict[str, Any]]], int]:
        """Build the token counter the loop windows history with (t12).

        ONE exact ``/tokenize`` count at run start (its ``max_model_len`` is
        the window-discovery rung), then ``usage``-anchored estimates — never a
        per-turn network call unless ``COLLEAGUE_EXACT_TOKENS=1``. Any probe
        failure falls back to the char estimate, so a server without
        ``/tokenize`` stays a config change (h2). ALWAYS returns an int.
        """
        url = _tokenize_url(config.base_url)

        def exact(messages: list[dict[str, Any]], reply: dict[str, Any]) -> int | None:
            count = _tokenize_count(
                messages,
                url=url,
                model=config.model,
                api_key=config.api_key,
                timeout=config.timeout,
            )
            if (url, config.model) in _MAX_MODEL_LEN_BY_URL:
                reply["max_model_len"] = _MAX_MODEL_LEN_BY_URL[(url, config.model)]
            return count

        return tokenestimate.attach(config, exact)

    @staticmethod
    def _build_chat_payload(
        config: EngineConfig,
        messages: "list[dict[str, Any]]",
        offered_tools: "list[dict[str, Any]]",
    ) -> "tuple[dict[str, Any], bool]":
        """Build one chat-completions payload (+ whether it streams).

        Extracted from ``_make_complete``'s closure (SonarCloud S3776). An
        EMPTY offered-tools list omits BOTH "tools" and "tool_choice" (the
        honest tools-off invariant the deepthink seam relies on).
        Streaming (#393) arms when a delta sink is armed **or** headless streaming
        is enabled (:func:`_headless_streaming_enabled`, default on; ``COLLEAGUE_STREAM=0``
        opts out) — the SINGLE arming decision in the driver, engine-uniform by
        construction (every seat's completion is built here via ``_make_complete``).
        Opted out, the body carries NEITHER SSE key (the pre-streaming payload).
        ``max_tokens`` (t16) is :func:`colleague.turnbudget.max_tokens_for`'s
        window clamp; absent under ``COLLEAGUE_MAX_OUTPUT_TOKENS=0``.
        """
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
        }
        if offered_tools:
            payload["tools"] = offered_tools
            payload["tool_choice"] = "auto"
        # Per-seat thinking effort (#416 t3, c2/h2/c7/h6): the fragment is ABSENT
        # when nothing should be sent (kill-switched, or a rung/seat resolving to
        # None) — a vLLM/OpenAI-only extension key (CLAUDE.md's documented "vLLM
        # adapter only touches the OpenAI surface" carve-out), so a non-vLLM server
        # ignoring unknown keys behaves as today; nothing set = pre-#416 body.
        profile = associate.seat_profile(config)  # t23: an associate seat's measured contract
        limit = turnbudget.max_tokens_for(config, messages)  # t16 clamp; None = omit
        if profile is not None:
            limit = _apply_associate_profile(payload, profile, limit)
        else:
            rung = _effort_for(config)
            effort_fragment = effort.to_chat_template_kwargs(rung)
            if effort_fragment:
                payload["chat_template_kwargs"] = effort_fragment
            # Per-model sampling profile (#479 t5, c1/c2/c8/c37/c56): the SINGLE
            # write site for temperature/top_p/top_k/min_p/penalty keys. Empty —
            # byte-identical to pre-#479 — under COLLEAGUE_SAMPLING=0, for a rung
            # with no half, or for a model no row claims. It consumes the rung
            # ``_effort_for`` already resolved (never re-deriving thinking-ness)
            # and merges AFTER "temperature" is written, so a row's temperature
            # replaces the config default. No retry path when a server refuses
            # these keys (c34) — a 400 surfaces exactly as today.
            payload.update(_sampling_fragment(config, rung))
        if limit is not None:
            payload["max_tokens"] = limit
        streaming = config.on_delta is not None or _headless_streaming_enabled()
        if streaming:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        if os.environ.get("COLLEAGUE_DUMP_REQUEST"):
            # Best-effort: a diagnostic dump must NEVER break a work item (#184).
            try:
                sys.stderr.write(
                    "colleague: outgoing request payload:\n" + json.dumps(payload, indent=2) + "\n"
                )
            except OSError:  # nosec B110 - diagnostic only; never mask the real work
                pass
        return payload, streaming

    @staticmethod
    def _dispatch_once(
        url: str,
        payload: "dict[str, Any]",
        config: EngineConfig,
        streaming: bool,
    ) -> ModelResponse:
        """Send ``payload`` exactly once, streaming or blocking per *streaming*.

        Extracted from ``_make_complete``'s ``complete`` closure (SonarCloud
        S3776). A mid-stream failure degrades to ONE blocking request for
        THIS SAME turn (task t5) — the loop never sees the transport hiccup,
        only a normal ``ModelResponse``. ``_noop_delta`` is the headless case
        (#393): streaming is armed for the TRANSPORT (incremental bytes, so
        the read timeout measures silence rather than generation time) with
        no display surface to feed. Both a ladder-400 retry and the 404
        stale-pin refresh just re-call this same helper, so the streaming
        path (``_stream_or_blocking``) and the blocking one share one
        convergence point, never duplicated logic in either transport
        function itself.
        """
        _record_transport_guarded(config, streaming)
        if streaming:
            return _stream_or_blocking(
                url,
                payload,
                api_key=config.api_key,
                timeout=config.timeout,
                on_delta=_delta_sink(config.on_delta),
            )
        data = _post_json(url, payload, api_key=config.api_key, timeout=config.timeout)
        return _parse_response(data)

    @staticmethod
    def _maybe_retry_ladder_400(
        exc: urllib.error.HTTPError,
        payload: "dict[str, Any]",
        role_name: str,
        sent_effort: "str | None",
        config: EngineConfig,
        dispatch: "Callable[[], ModelResponse]",
    ) -> "ModelResponse | None":
        """Ladder-400 retry (#416 t3, c2/h2/c27/h18/c33/h23): if *exc* is a
        rejection of the ``chat_template_kwargs`` fragment, drop it, record
        ONE warning, and retry ONCE via *dispatch* — returning the retried
        response. Returns ``None`` when *exc* is not a ladder-400 (the caller
        re-raises). A second ladder-400 (the caller's own re-raise) propagates
        unguarded — never a second catch, mirroring the 404 refresh's own
        single-shot rule.
        """
        if "chat_template_kwargs" not in payload or not _is_ladder_400(exc):
            return None
        payload.pop("chat_template_kwargs", None)
        warning = _LadderRetryWarning(seat=role_name, effort=sent_effort, detail=str(exc))
        _emit_ladder_retry_warning(warning)
        _record_ladder_retry_warning(config, warning)
        return dispatch()

    @staticmethod
    def _maybe_refresh_on_404(
        exc: urllib.error.HTTPError,
        config: EngineConfig,
        role_name: str,
    ) -> "str | None":
        """Same-role stale-pin refresh AT CALL TIME (plan task t9, spec
        c10/c11, honesty h7/h8): exactly a 404 model_not_found, ONE retry.
        Returns the refreshed model id, or ``None`` when *exc* isn't a
        refreshable 404 (the caller re-raises unguarded — legible via
        ``_raise_legible_http_error``'s existing body-folding).
        """
        return _refreshed_model_id(config, role_name, exc)

    def _recover_http_error(
        self,
        exc: urllib.error.HTTPError,
        payload: "dict[str, Any]",
        role_name: str,
        sent_effort: "str | None",
        config: EngineConfig,
        dispatch: "Callable[[], ModelResponse]",
    ) -> ModelResponse:
        """The single-shot recovery ladder for one completion's HTTPError.

        Ladder-400 (#416 t3) and the 404 stale-pin refresh (plan task t9) are
        DISJOINT by status code — a 404 is never a 400 — so checking one first
        never shadows the other. Each fires at most once; a 404→400 sequence
        (c33) therefore yields exactly one refresh and one ladder retry. Anything
        unrecoverable re-raises unchanged (legible via
        ``_raise_legible_http_error``'s body-folding at the dispatch site).
        Extracted from ``_make_complete``'s closure (SonarCloud S3776).
        """
        retried = self._maybe_retry_ladder_400(
            exc, payload, role_name, sent_effort, config, dispatch
        )
        if retried is not None:
            return retried
        aliased = associate.retry_role_alias(exc, payload, config, dispatch)  # t18/c49
        if aliased is not None:
            return aliased
        refreshed_id = self._maybe_refresh_on_404(exc, config, role_name)
        if refreshed_id is None:
            raise exc
        # Persist the refresh (Qodo review, PR #381): later completions rebuild
        # their payload from ``config.model`` — leaving the stale id there would
        # re-404 + re-refresh on EVERY subsequent turn.
        config.model = refreshed_id
        payload["model"] = refreshed_id
        try:
            return dispatch()
        except urllib.error.HTTPError as retry_exc:
            # A 404→400 sequence (c33): the SAME payload the refresh just re-sent
            # can still be rejected on the ladder — the ladder retry is disjoint
            # from (and stacks on top of) the refresh that already happened once.
            retried_again = self._maybe_retry_ladder_400(
                retry_exc, payload, role_name, sent_effort, config, dispatch
            )
            if retried_again is not None:
                return retried_again
            raise

    def _make_complete(
        self, config: EngineConfig, tools: list[dict[str, Any]] | None = None
    ) -> CompleteFn:
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        # The offered tool schema: full SCHEMAS by default, or the role-curated
        # subset (#t4); captured once per config. plan mode passes none → SCHEMAS.
        offered_tools = tools if tools is not None else SCHEMAS
        # The acting seat this completion drives (same-role stale-pin refresh, plan
        # task t9): mirrors work()'s seat computation — "worker" in three-tier mode,
        # "cortex" otherwise — so a call-time refresh queries the SAME role.
        role_name = "worker" if config.worker is not None else "cortex"

        def complete(messages: list[dict[str, Any]]) -> ModelResponse:
            payload, streaming = self._build_chat_payload(config, messages, offered_tools)
            # The rung THIS payload's (possibly already-dropped) fragment was
            # built from — captured once, before a ladder-400 retry pops the
            # key below, so the warning can still name it (#416 t3).
            sent_effort = _effort_for(config)

            def dispatch() -> ModelResponse:
                return self._dispatch_once(url, payload, config, streaming)

            try:
                resp = dispatch()
            except urllib.error.HTTPError as exc:
                resp = self._recover_http_error(
                    exc, payload, role_name, sent_effort, config, dispatch
                )
            if turnbudget.escalate_on_length(payload, config, resp):  # t16: once
                resp = dispatch()
            tokenestimate.observe(config, messages, resp.prompt_tokens)  # t12 anchor
            return resp

        return complete

    def make_complete(
        self, config: EngineConfig, tools: list[dict[str, Any]] | None = None
    ) -> CompleteFn:
        """Public one-shot completion seam (see :meth:`Engine.make_complete`).

        Returns the same ``complete`` the work loop uses, so non-work-loop
        features (``colleague plan``, the deepthink escalation seam) can drive
        a live model directly. ``tools=None`` (the default) sends the full
        SCHEMAS — byte-identical to today, the plan-mode pin; ``tools=[]`` is
        the tools-off invariant the deepthink seam relies on (see
        :meth:`Engine.make_complete`).
        """
        return self._make_complete(config, tools=tools)

    def make_count_tokens(self, config: EngineConfig) -> Callable[[list[dict[str, Any]]], int]:
        """Public one-shot token-counter seam (see :meth:`Engine.make_count_tokens`).

        Returns the same exact-or-estimate counter the work loop uses
        internally — the server's ``/tokenize`` endpoint, degrading to the
        char-heuristic estimate on any error — so a feature calling
        :meth:`make_complete` outside the loop (the deepthink seam, task t2)
        windows its prompt with the loop's own precision.
        """
        return self._make_count_tokens(config)

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        """Work the task through the shared bounded tool-loop.

        Each model turn is completed via the server's OpenAI-compatible
        ``/v1/chat/completions`` endpoint. Returns a :class:`TaskResult`.
        """
        # Typed-subagent role (#t4): resolve config.role once → curated schema +
        # role-aware executor (None → full surface, byte-identical to pre-role);
        # the role PROMPT is composed by the role-aware self.system_prompt below.
        role = resolve_role(config, task.repo_path)
        # Dual-model deepthink (t5): ONE binding per work item, injected into BOTH
        # the executor (the model-facing tool) and the ContextControls (the
        # runtime escalation points) — None for a single-model config, which also
        # keeps the deepthink tool schema un-offered (byte-identical run).
        dt_run = make_deepthink_run(config, self.name)
        # Cortex/senses media bridge (t6): the SAME binding every backend passes to
        # ContextControls (all-engines rule); ``None`` for a config without senses
        # keeps the senses bridge dormant (byte-identical).
        senses_run = make_senses_run(config, self.name)
        # Change-content consumption lane (t3, spec c8/h8): an applied
        # worker.tools narrowing on the attached config-lifecycle intersects the
        # role-curated surface. Read the attachment's snapshot DEFENSIVELY — the
        # real EpisodeConfigLifecycle exposes ``snapshot`` as a read-only
        # property (already-evaluated, not callable), while a future frozen
        # child view (r2/t10) may expose a ``snapshot()`` METHOD instead — so
        # this neither assumes nor requires either shape. No lifecycle, or a
        # snapshot with the default/empty ``tool_set`` (c26: () means
        # not-narrowed), leaves ``role`` untouched: byte-identical to today.
        lifecycle = getattr(config, "config_lifecycle", None)
        tool_set: tuple[str, ...] = ()
        if lifecycle is not None:
            snapshot_attr = getattr(lifecycle, "snapshot", None)
            snapshot = snapshot_attr() if callable(snapshot_attr) else snapshot_attr
            tool_set = getattr(snapshot, "tool_set", ()) or ()
        role = narrow_role_by_tool_set(role, tool_set)
        offered_tools = curated_schemas(role, config, deepthink=dt_run is not None)
        # Acting-seat label for the flight run-start marker (t2,
        # change-content-consumption-lane spec, covers c9/h9): mirrors the
        # mock engine's identical wiring (all-engines rule) — a resolved
        # ``config.worker`` is the front's own armed signal for three-tier
        # execution, so its presence, not a separate flag, names the acting
        # seat. ``None`` (unarmed, the default) keeps the legacy "cortex"
        # label, byte-identical to every prior release.
        # The thought->action->evaluation mode (t13) names the SAME acting
        # seat for the same reason: with the mode armed, config.resolve()
        # repointed the acting dial at the worker seat, so the worker — not
        # the evaluator/cortex — is what drives this tool loop.
        seat = (
            "worker"
            if config.worker is not None or getattr(config, "thought_action_evaluation", False)
            else "cortex"
        )
        # Prompt digest (plan task t7, covers c49/h36): hoist the composed
        # prompt into a local so the artifact can attest to the string that
        # ACTUALLY went on the wire — including any operator overlay — rather
        # than a re-derivation. Byte-identical to the previous inline call.
        composed_system_prompt = self.system_prompt(task, config)
        result = run(
            self._make_complete(config, tools=offered_tools),
            task,
            max_steps=config.max_steps,
            system_prompt=composed_system_prompt,
            model=config.model,
            progress=config.progress,
            seat=seat,
            # The engine builds the repo-confined executor so the config-derived
            # output cap (and subagent spawn) ride the existing ``executor`` seam
            # — keeps ``run()`` from growing another parameter (all-engines rule).
            # ``allowlist=role`` makes the executor REFUSE any tool the role
            # withholds — ``role`` here is already tool_set-narrowed above, so
            # this is the SAME single allowlist seam a narrowed-away tool is
            # refused through, never a second refusal mechanism.
            executor=ToolExecutor(
                task.repo_path,
                spawn=config.subagent_spawn,
                batch_spawn=config.subagent_batch_spawn,
                max_output_chars=config.max_output_chars,
                allowlist=role,
                deepthink=dt_run,
            ),
            # Context-window management (windowing + reactive auto-split #151),
            # forwarded identically by every backend (all-engines rule); dormant
            # unless a trigger fires.
            # ``from_config`` is the single source for the config→controls forwarding
            # both backends share (all-engines rule); the vLLM backend's one
            # per-backend variation is its exact ``/tokenize`` counter.
            context=ContextControls.from_config(
                config,
                count_tokens=self._make_count_tokens(config),
                deepthink_run=dt_run,
                senses_run=senses_run,
                tae_session=make_tae_session(config, self.name),
                associate_complete=associate_seats.make_associate_complete(config, self.name),
            ),
        )
        # Prompt digest (t7): the loop stamps this the moment its TaskResult
        # exists (so an aborted / salvaged run still attests to its arm); this
        # line is the floor for a caller that swapped ``run()`` out — it FILLS
        # a still-unset field on EVERY backend (all-engines rule), never
        # clobbers the loop's stamp, and omits the key when no prompt was
        # composed (byte-identical).
        if result.prompt_digest is None:
            result.prompt_digest = prompt_digest_for(composed_system_prompt)
        # offered_tools (delegation-follow-ups t2, c34/h18): the depth-0 curated
        # surface that ACTUALLY went on the wire, in schema order — same
        # fill-only-when-None discipline as prompt_digest (all-engines rule).
        # An empty surface stays ``None`` (key absent) — byte-identical to the
        # pre-field artifact, same as the mock (review finding 2026-08-30).
        if result.offered_tools is None:
            result.offered_tools = [s["function"]["name"] for s in offered_tools] or None
        # Model-bound agents (#411, t13): an ARMED config always returns the
        # versioned ``agents`` block with the SAME shape on every backend
        # (all-engines rule) — the fold only fills a still-``None`` field, so
        # the loop-authored block (when the loop wired it) wins; unarmed is a
        # strict no-op (key absent, byte-identical artifact).
        return fold_agents_block(result, config)
