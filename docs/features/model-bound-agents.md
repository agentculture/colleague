# Model-bound agents — identity, ledger, typed delegation, reference topology

> The **eleventh sanctioned increment** at colleague's router-exclusion line:
> explicit, attributable agents bound to lobes roles — **never** an automatic
> task→model routing policy.

colleague can run in an **agents execution mode** (`agents` in
`.colleague/config.json` or `COLLEAGUE_AGENTS=1`) where every model invocation
is an attributable **agent instance**: a typed `AgentProfile` (purpose, the
lobes role it resolved to, the served model as trace data, a validated tool
profile, an authority ceiling, lineage) with a per-invocation **context
manifest** and **tool-surface digest**; subagents are explicit agents that may
bind a **different lobes role** than their parent; agents exchange **typed,
attributable messages**; continuity lives on an **append-only task ledger** at
the operator repo, from which continuation **rehydrates** and per-agent
contexts are **reconstructed**. Absent config is **byte-identical** to legacy
colleague (the `TaskResult` key set is pinned by `tests/test_e2e_mock.py`).

Issue: [#411](https://github.com/agentculture/colleague/issues/411). Spec:
`docs/specs/2026-08-21-model-bound-agents-411.md`. Plan:
`docs/plans/2026-08-21-model-bound-agents-411.md`. Companions landed in the
same arc: #410 (SIGTERM writes the partial artifact unconditionally) and #400
(the step-stall watchdog).

## The reference topology (by lobes role, never by model family)

| agent (purpose) | lobes role | what it may do | tool profile |
|---|---|---|---|
| **Talker** (`talker`) | `senses` | converse, perceive, present, relay — the structurally tools-off senses | empty |
| **Worker** (`worker`) | `worker` | inspect, run authorized tests/commands, recall, delegate — **dormant** (see d3) | no `write_file` / `edit_file` |
| **Thinker/Coder** (`thinker_coder`) | `cortex` | reason, plan, author and edit code, review, final synthesis | the full base + chassis surface |
| **Associate** (`associate`) | `associate` | the reserved **fast coder** (deviation d3) — coder-class surface, authority ≤ thinker/coder | = thinker/coder |

Role names live in code; Gemma / Lightning / Qwen are the **rig's** answers
(the live `/capabilities` advert) and appear only as `resolved_model` trace
data — a grep guard keeps vendor names out of `colleague/agents/`.

**Deviation d3 (operator, 2026-08-21).** A worker that cannot author code is a
conflict for this repo, so the non-coding `worker` purpose stays **dormant**:
its profile exists (write tools excluded, proven by test) but the role is
never bound; a worker-purpose request resolves to cortex under the recorded
fallback. The fast-coder agent is the new role/purpose **`associate`**,
reserved by name now and absent on the gateway today (same recorded
fallback). Guidance routes routine coding to `associate` when present, else
`thinker_coder` — never to `worker`.

**Worker-absent is a recorded fallback, never a refusal** (operator decision
q1): with the Lightning worker advertised `ready:false` (today's Spark rig),
every purpose runs on cortex and the identity record says so
(`fallback_from_role`), on the artifact (`TaskResult.agents.fallbacks`) and in
`doctor --probe` (`agents_role_<role>: … → cortex fallback`). Subagents still
spawn.

## Landed pieces

| module | what it owns |
|---|---|
| `colleague/agents/profile.py` | `AgentProfile` (schema-versioned, frozen), `PURPOSES`, `PURPOSE_ROLE`, `DORMANT_PURPOSES`, pure `resolve_profile` with the recorded cortex fallback, `validate_profile_tools` |
| `colleague/agents/tools.py` | `ToolProfile` per canonical tool (one `tool_class` reconciling `roles._WRITE_TOOLS` and `tae_loop.CONSEQUENTIAL_TOOLS`), the purpose surfaces, `effective_tools` (the six-way intersection; empty refuses whole), `tool_surface_digest`, `assert_purpose_surface` |
| `colleague/agents/messages.py` | `AgentMessage` over the closed `delegate / ask / inform / challenge / handoff / return`, refuse-whole validation, **no chain-of-thought field**, `MessageBudget` (`config.MAX_AGENT_MESSAGES`) |
| `colleague/agents/delegation.py` | `DelegationRequest` envelope, ordered authority ceilings, child ⊆ parent validation, `open_delegation` / `close_delegation` / `handoff` ledger events |
| `colleague/agents/guidance.py` | the enumerated purpose→role **guidance table** rendered as prompt text — no function takes task text and returns a model |
| `colleague/agents/runtime.py` | `InvocationRecord` (identity + manifest; `token_estimate` labelled by source and never written into `Usage`), `agent_engine_config` (the ONE seat builder: role dial, own context window, #348 same-origin key rule, `refresh_seat=None`), `AgentsRun` (the loop's seam target) |
| `colleague/agents/artifact_block.py` | `build_agents_block` / `fold_agents_block` — the `TaskResult.agents` schema (one source) |
| `colleague/agents/talker.py` | talker invocation records at every senses call site; `guide_cortex` → `operator_input` |
| `colleague/agents/state/ledger.py` | the append-only task ledger (`.colleague/ledger/<task_id>.jsonl` at the **operator** repo), closed event kinds, `fcntl`-locked append, replay-deterministic `TaskSnapshot` + `state_digest` / `authority_digest`, fail-closed reader |
| `colleague/agents/state/context.py` | per-agent reconstruction: pinned **nucleus**, `context_mode` `inherit` / `clear`, handover summary, explicit provenance rank (operator input > repo/tool evidence > accepted facts > peer claims > recalled memory), labelled peer text |
| `colleague/continuation.py` | `resolve_continuation(..., agents_armed=, warnings=)` rehydrates the seed from the ledger (fails closed and loud to the prose recap) |
| `colleague/subagents.py` | `ChildSpec.profile` / `context_mode`; a child may bind a different lobes role; `delegate` / `return` events bracket the spawn; `SubResult.agent_id` / `resolved_model` / `fallback_from_role` |
| `colleague/loop.py` | **seam calls only** — `_agents_begin` / `_agents_record` / `_agents_end`, `operator_input` on applied guidance, purpose narrowing in `resolve_role` |
| `colleague/config.py`, `colleague/oilcheck/agents.py` | the `agents` opt-in (env > config.json > OFF; arming two modes refuses naming both), `doctor` `agents` group + `--probe` role lines, `config show` `agents: armed` or `off` |
| `colleague/salvage.py` (#410) | the live-partial registry the SIGTERM handler writes the artifact from |
| `colleague/stallguard.py` (#400) | the step-stall watchdog: `COLLEAGUE_MAX_STEP_STALL`; default `max(5400 s, 6× mean turn latency)` |

## Configuration

```json
{ "lobes": "http://localhost:8001", "agents": true }
```

or `COLLEAGUE_AGENTS=1`. A THIRD independent opt-in: arming it together with
`three_tier` or `thought_action_evaluation` refuses, naming both modes.
`three_tier` is **superseded by this increment** (its worker-acts dial is
exactly the "worker is the coder" topology #411 replaces) and kept only as the
benchmark baseline. Deepthink is unaffected.

## Context policy (operator decision q7)

The acting agent keeps its **windowed transcript** (prefix caching stays
effective) with the **guidance table + the static nucleus appended ONCE to the
system prompt**; the seat's window follows its lobes advert (cortex
1,048,576 since the 2026-08-21 re-probe; the worker's own when it is ready).
Per-agent **reconstruction** is used for delegated agents (`context_mode`
`clear` — the reviewer's *clear mind*: handover summary, not the parent
transcript) and for rehydration. Subagents default to `inherit`.

## Evaluation in agents mode (operator decision q9)

Quality = deterministic host gates + **explicit review/challenge delegation**
to a thinker-profile reviewer (clear mind + handover summary). The
five-boundary evaluator seat stays TAE's; alignment is still not permission.

## Load-bearing invariants

- **Model switching only by explicit, ledgered delegation** — the runtime never
  picks a model per turn (the v1 no-router line; pinned by the AST guard in
  `tests/test_agents_boundary.py`).
- **Delegation only narrows** — child effective tools ⊆ parent's, child
  ceiling ≤ parent's, regardless of the child's model. **Enforced on the spawn
  path**: `subagents._enforce_delegation_bounds` calls
  `delegation.validate_delegation` before the `delegate` event and before the
  child engine runs — and **before the global budget charge**, so a refusal
  costs nothing. The check is gated on ARMING, never on a declared profile: a
  spawn that omits `profile` inherits the parent's purpose and is validated
  like any other (gating on the profile would let a caller skip the check by
  omitting one argument). A widening delegation refuses whole (`SubagentError`)
  and records nothing; the batch path ranks every item before the first
  worktree exists, so one widening item never aborts a batch midway. The
  `delegate` event records the `requested_tools` + `authority_ceiling` the
  decision was made on. `fanout`/`total` stay with the shared agent budget, and
  nested delegation is still permitted.
- **An empty purpose surface means NO tools** — the tools-off `talker` seat is
  narrowed to the empty set in `loop.resolve_role` (an empty `tool_set` is the
  lattice's not-narrowed sentinel, so it needs its own tools-off role), and the
  invocation manifest is derived from the executor's real allow-list.
- **Tokens are exact** — `token_estimate` is manifest data, never `Usage`.
- **Peer claims rank below evidence** and render as labelled peer text, never
  as system/operator text; both sides of a challenge stay on the ledger.
- **The ledger is local-only** (gitignored), single-writer per file, fail-closed
  on read; continuation rehydrates from it only when armed.
- **Unarmed = byte-identical** — every record is omit-when-unarmed and
  mock-implemented (all-engines parity).

## Traceability (after-state → requirement → test)

| after-state clause | requirement | test |
|---|---|---|
| every invocation attributed | c13 | `tests/test_agents_runtime.py`, `tests/test_loop_agents_wiring.py` |
| cross-role child, surface ⊆ parent | c7, c8 | `tests/test_subagents_cross_role.py`, `tests/test_agents_delegation.py`, `tests/test_agents_delegation_bounds.py` |
| typed messages | c9 | `tests/test_agents_messages.py` |
| worker profile without write tools | c11 | `tests/test_agents_tools.py`, `tests/test_loop_agents_wiring.py` |
| talker = tools-off senses | c19 | `tests/test_senses_talker_records.py`, `tests/test_senses_cannot_act.py` |
| recorded fallback | c4 / c28 | `tests/test_agents_profile.py`, `tests/test_doctor_agents.py`, `tests/test_agents_fallback.py` |
| rehydrate from the ledger | c35 | `tests/test_continuation_ledger.py`, `tests/test_agents_continuity.py` |
| per-agent reconstruction | c36 | `tests/test_agents_context.py` |
| unarmed byte-identical | c41 | `tests/test_e2e_mock.py`, `tests/test_agents_block_parity.py` |

## Honest limits

- **Opt-in only** until the matched experiment (solo cortex vs agents mode, same
  brief, pre-registered bars — success signal c45) is recorded in
  `docs/live-testing.md`.
- **The worker is dormant and the associate is reserved** — neither is served on
  the reference rig today; the fallback path is what is live-proven.
- **Three seat builders remain** (`tae_loop.seat_engine_config`,
  `deepthink_engine_config`, `senses_engine_config`) alongside
  `agent_engine_config`; the fold is a follow-up (#412).
- **loop.py grew** during the arc (the #400 / #410 / t8 policies) — tracked in
  #412 / #413; the file-length ratchet (`tests/test_file_length_ratchet.py`)
  guards further growth.
- **The `repo_patch_no_publish` ceiling rung is unreachable today** —
  `seat_ceiling` reads `no_pr`, but `--no-pr` becomes `open_pr` on the CLI args
  and is never set on an `EngineConfig`, so the enum collapses to `read_only`
  vs `repo_patch_publish`. Carrying publish intent onto the seat is a follow-up.
- **A cross-origin child dial sends no key** (same-origin hygiene) — a per-role
  key source is the follow-up.
- `drift` beyond the evaluator: cross-model disagreement is recorded as
  `challenge` messages; no synthesis/voting exists (non-goal).
