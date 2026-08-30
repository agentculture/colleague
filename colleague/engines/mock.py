"""The mock engine — a deterministic, networkless coder backend (R6).

It runs the *exact same* runtime as a real backend — the shared task contract and
the bounded tool-loop — but supplies a scripted ``complete`` instead of calling a
model. That makes it the CI workhorse (h6): it proves the harness end to end with
no network and no flakiness, and it is the reference against which a live backend's
result *shape* is compared (h8).
"""

from __future__ import annotations

import re
from contextlib import suppress
from typing import Callable

from colleague import associate_seats
from colleague.agents.artifact_block import fold_agents_block
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult, prompt_digest_for
from colleague.deepthink import make_deepthink_run
from colleague.engine import Engine
from colleague.engines import mock_scenarios
from colleague.loop import (
    CompleteFn,
    ContextControls,
    ModelResponse,
    ToolCall,
    curated_schemas,
    resolve_role,
    run,
)
from colleague.senses import make_senses_run
from colleague.tae_loop import make_tae_session
from colleague.tools import ToolExecutor, narrow_role_by_tool_set

#: Where the mock writes its marker file (relative to the repo root).
OUTPUT_FILE = "colleague-mock.md"

# Splits text into ordered chunks that reconstruct it EXACTLY when
# concatenated: each match is either a run of non-whitespace plus any
# trailing whitespace, or a run of whitespace on its own (covers leading
# whitespace / repeated separators) — ``"".join(pattern.findall(s)) == s``
# always holds. Used only by :func:`_emit_synthetic_deltas` below.
_DELTA_CHUNK_RE = re.compile(r"\S+\s*|\s+")


def _emit_synthetic_deltas(content: str, on_delta: "Callable[[str], None]") -> None:
    """Stream *content* to *on_delta* as ordered chunks that reconstruct it exactly.

    The mock's network-free stand-in for a live engine's real token/SSE stream
    (feels-alive arc, task t3): word-chunked so the concatenation of every
    emitted chunk, in call order, always equals *content* — the same
    invariant a real stream upholds. A no-op on empty content. A raising sink
    must never break the run — suppressed exactly like the loop's own
    ``_emit_progress``/``_emit_phase`` observability sinks (``colleague/loop.py``).
    """
    if not content:
        return
    for chunk in _DELTA_CHUNK_RE.findall(content):
        with suppress(Exception):
            on_delta(chunk)


def _with_synthetic_deltas(complete: CompleteFn, on_delta: "Callable[[str], None]") -> CompleteFn:
    """Wrap *complete* so each returned turn's ``content`` streams to *on_delta* first.

    Kept as a wrapper around whatever ``complete`` callable :func:`_script`
    (or a test double standing in for it) returns, rather than a parameter on
    :func:`_script` itself, so :func:`_script`'s signature — and any existing
    caller/monkeypatch of it — never has to change (task t3). Only called when
    ``on_delta`` is armed; the wrapped callable's return value is otherwise
    unchanged, so this is invisible to the loop.
    """

    def _complete(messages: list[dict]) -> ModelResponse:
        resp = complete(messages)
        _emit_synthetic_deltas(resp.content, on_delta)
        return resp

    return _complete


def _script(task: Task) -> CompleteFn:
    """A deterministic script: write a marker file, then finish (or, opt-in, a batched turn)."""
    content = f"# Colleague mock engine\n\nHandled instruction:\n\n{task.instruction}\n"
    # Deterministic reasoning/answer text so WorkStats' generated-size fields are
    # non-zero and engine-agnostic (the mock is the contract reference, h5): the
    # e2e shape test compares key shape, and these give the mock the same
    # reasoning_*/answer_* fields a real reasoning model produces.
    #
    # ``finish_reason="stop"`` on every turn (plan task t1, covers c4/h4): the
    # mock never calls a real wire, so it sets a representative DELIBERATE
    # value itself — a scripted engine choosing to act/finish, never truncated
    # by a token cap — so `result.finish_states` stays populated with the same
    # shape a live backend produces (test_e2e_mock.py's shape parity).
    turns = mock_scenarios.batch_turns_or_none(task) or [
        ModelResponse(
            content="writing the marker file",
            reasoning="mock reasoning: decide to write the marker file",
            tool_calls=[
                ToolCall("mock-1", "write_file", {"path": OUTPUT_FILE, "content": content})
            ],
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        ),
        ModelResponse(
            content="done",
            reasoning="mock reasoning: nothing left to do, finish",
            tool_calls=[ToolCall("mock-2", "finish", {"summary": f"mock wrote {OUTPUT_FILE}"})],
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        ),
    ]
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


class MockEngine(Engine):
    """Deterministic in-process engine; never touches the network."""

    name = "mock"

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        # Typed-subagent role (#t4): resolve config.role and build a role-aware
        # executor identically to the live backend (all-engines rule). The mock's
        # scripted ``complete`` carries no tool schema, so the executor's
        # ``allowlist`` is the role-enforcement point here. None → unrestricted
        # (byte-identical to the pre-role path). Prompt via role-aware system_prompt.
        role = resolve_role(config, task.repo_path)
        # Dual-model deepthink (t5): the mock binds the SAME seam the live backend
        # does (all-engines rule). Its scripted turns never call the tool, but the
        # acceptance self-check escalation path fires identically — and degrades
        # to a recorded no-op, since the mock's make_complete raises (no live
        # model), exercising the c13 degradation ladder end-to-end.
        dt_run = make_deepthink_run(config, self.name)
        # Cortex/senses media bridge (t6): the mock forwards the senses binding
        # identically (all-engines rule); make_complete raises on the mock, so a
        # senses-armed run records a degraded no-op — the same c13 ladder as
        # deepthink-on-mock. ``None`` for a config without senses (byte-identical).
        senses_run = make_senses_run(config, self.name)
        # Change-content consumption lane (t3, spec c8/h8): an applied
        # worker.tools narrowing on the attached config-lifecycle intersects the
        # role-curated surface — identically to the live backend (all-engines
        # rule), even though the mock's scripted ``complete`` carries no wire
        # schema: the executor's ``allowlist`` stays the ONE enforcement point
        # for the mock, so narrowing must reach it the same way it reaches the
        # live backend's offered schema. Read the attachment's snapshot
        # DEFENSIVELY — the real EpisodeConfigLifecycle exposes ``snapshot`` as a
        # read-only property while a frozen child view (r2/t10) may expose a
        # ``snapshot()`` METHOD; neither shape is assumed. No lifecycle, or the
        # default/empty ``tool_set`` (c26), leaves ``role`` untouched: byte-identical.
        lifecycle = getattr(config, "config_lifecycle", None)
        tool_set: tuple[str, ...] = ()
        if lifecycle is not None:
            snapshot_attr = getattr(lifecycle, "snapshot", None)
            snapshot = snapshot_attr() if callable(snapshot_attr) else snapshot_attr
            tool_set = getattr(snapshot, "tool_set", ()) or ()
        role = narrow_role_by_tool_set(role, tool_set)
        # Token-delta seam (task t3): stream synthetic word-chunk deltas of
        # each scripted turn's content when armed. Wrapping the completed
        # `_script(task)` callable — rather than threading on_delta into
        # `_script` itself — keeps `_script`'s signature (and any existing
        # test double standing in for it) unchanged. `config.on_delta is
        # None` (the default) is a strict no-op: `complete` stays exactly
        # `_script(task)`.
        complete = _script(task)
        if config.on_delta is not None:
            complete = _with_synthetic_deltas(complete, config.on_delta)
        # Acting-seat label for the flight run-start marker (t2,
        # change-content-consumption-lane spec, covers c9/h9): a resolved
        # ``config.worker`` is the front's own armed signal for three-tier
        # execution (config.py's ``_resolve_worker`` never leaves it set
        # without a live worker role), so its presence — not a separate flag
        # — is what names the acting seat. ``None`` (unarmed, the default)
        # keeps the legacy "cortex" label, byte-identical to every prior
        # release.
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
            complete,
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
            # All-engines rule: the mock exercises the SAME loop windowing path and
            # arms reactive auto-split (#151) identically (dormant unless an
            # exhausted overflow fires it). No count_tokens → the loop uses the char
            # estimate via window_messages. ``from_config`` is the single source for
            # the config→controls forwarding both backends share.
            context=ContextControls.from_config(
                config,
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
        # offered_tools (delegation-follow-ups t2, c34/h18): the mock carries no
        # wire schema, so it stamps the SAME role-curated list the live backend
        # hands its transport (all-engines rule) — computed here, never guessed.
        if result.offered_tools is None:
            result.offered_tools = [
                s["function"]["name"]
                for s in curated_schemas(role, config, deepthink=dt_run is not None)
            ]
        # Model-bound agents (#411, t13): an ARMED config always returns the
        # versioned ``agents`` block with the SAME shape on every backend
        # (all-engines rule) — the fold only fills a still-``None`` field, so
        # the loop-authored block (when the loop wired it) wins; unarmed is a
        # strict no-op (key absent, byte-identical artifact).
        return fold_agents_block(result, config)
