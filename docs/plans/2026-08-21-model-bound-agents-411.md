# Build Plan — model-bound agents (#411)

slug: `model-bound-agents-411` · status: `exported` · from frame: `model-bound-agents-411`

> Colleague represents model-bound agents: a typed AgentProfile (purpose, lobes role, authority ceiling, validated tool profile) with per-invocation identity + context manifest + tool-surface digest; subagents are explicit agents that may bind a different lobes role/model; agents exchange typed attributable messages (delegate/ask/inform/challenge/handoff/return); the reference topology is Talker=senses (Gemma 4 12B), Worker=worker (Nemotron 3.5 Lightning, NOT the coder), Thinker/Coder=cortex (Qwen 3.8 27B) — and when the worker role is not ready (today), cortex carries every purpose under a RECORDED fallback, subagents still spawn; byte-identical when unarmed

## Tasks

### t1 — t1 agents/profile.py — AgentProfile + purposes + role map + fallback resolution

- instruction: New package colleague/agents/. Model on roles.Role (roles.py:27-57) and lobes.RoleInfo (lobes.py:154-171). Purpose before tools: the profile names a `tool_profile` id (string) resolved by t2, never a tool list. No imports from loop.py. Keep it under 250 lines.
- covers: c2, h6, c20, h15
- acceptance:
  - colleague/agents/`__init__.py` + colleague/agents/profile.py exist; AgentProfile is a frozen dataclass (`agent_id`, purpose, `model_role`, `resolved_model`, `tool_profile`, `authority_profile`, `parent_agent_id`, `task_id`, `fallback_from_role`, `schema_version`) with `to_dict`/`from_dict` round-trip
  - PURPOSES is the closed set {talker, worker, `thinker_coder`}; `PURPOSE_ROLE` maps talker→senses, worker→worker, `thinker_coder`→cortex; `resolve_profile`(purpose, roles) returns the role's model when ready, else the cortex model with `fallback_from_role` set — pure function, no network (tests use a RoleInfo double mirroring the 2026-08-21 advert)
  - tests/`test_agents_profile.py` passes; it includes a grep guard that no file under colleague/agents/ contains gemma|qwen|nemotron|lightning (case-insensitive)

### t2 — t2 agents/tools.py — ToolProfile records, effective-surface intersection, digest, the three purpose profiles

- instruction: Pure module, no engine imports. tools.py:112 SCHEMAS is the available set (read names from tools.`TOOL_NAMES` at import — do not duplicate schemas). The digest must be stable across processes (sorted, utf-8). Two-sided ENFORCEMENT is wired in t15, not here.
- covers: c10, h10, c11, h11
- acceptance:
  - colleague/agents/tools.py defines ToolProfile(`canonical_id`, `tool_class` in {read, write, external, destructive}, `required_approval`: bool, inheritable: bool) for every name in tools.`TOOL_NAMES` + deepthink, reconciling roles.`_WRITE_TOOLS` and `tae_loop`.`CONSEQUENTIAL_TOOLS` into the single `tool_class` field (subagent/subagents are class write; culture/devague external)
  - `effective_tools`(available, `model_supported`, `purpose_tools`, `policy_tools`, `env_tools`, `approved_tools`) returns the sorted intersection and `tool_surface_digest`(tools) = sha256 over the sorted names; an empty intersection raises EmptyToolSurface (refuse whole, lattice.py:364 precedent)
  - `WORKER_TOOLS` excludes `write_file` and `edit_file` and includes `read_file`, `view_media`, `list_dir`, `run_tests`, `run_command`, memory, subagent, subagents, finish; `TALKER_TOOLS` is empty; `THINKER_CODER_TOOLS` is the full base+chassis surface; tests/`test_agents_tools.py` proves each and that narrowing never adds a name

### t3 — t3 agents/messages.py — typed agent messages + the per-task message budget

- instruction: Model the refuse/degrade shape on `senses_moves`.MoveResult (`senses_moves.py`:186-210). Messages are in-process records destined for the ledger (t4) — no transport, no socket, no thread. Only touch config.py for the one constant line.
- covers: c9, h9, c21, h16, c53, h39
- acceptance:
  - AgentMessage(`message_id`, `task_id`, `from_agent`, `to_agent`, type, subject, content, `evidence_refs`, `requested_response`, seq) with `MESSAGE_TYPES` = frozenset({delegate, ask, inform, challenge, handoff, return}); `validate_message` refuses an unknown type or a missing from/to whole (MessageVerdict(allowed, reason)); the dataclass has no rationale/chain-of-thought field and `to_dict` emits none
  - MessageBudget(limit=`MAX_AGENT_MESSAGES`) charges atomically and refuses at the cap with reason 'message budget exhausted' (mirror subagents.`_AgentBudget` :246-289); `MAX_AGENT_MESSAGES` is a constant in colleague/config.py next to `MAX_SUBAGENT_TOTAL` (config.py:339-341)
  - tests/`test_agents_messages.py` passes: closed vocabulary, refuse-whole, budget exhaustion, `to_dict` round-trip, and a test that message content containing tool-call markup stays inert data (`senses_moves` `test_senses_cannot_act.py` shape)

### t4 — t4 agents/state/ledger.py — append-only task ledger, snapshot, digests, locked append, fail-closed reader

- instruction: Reuse ledger.`ledger_digest`'s sha256-over-replayed-sequence idea (ledger.py:277) but for the task ledger; keep the evaluation ledger + `config_events` as REFERENCED streams (store their digests on the snapshot), never duplicated. Events carry refs to evidence (artifact step index, file path, message id), never large payloads. fcntl import must be guarded like worktrees.py:46.
- covers: c34, h17, c52, h38, c54
- acceptance:
  - colleague/agents/state/`__init__.py` + ledger.py: TaskLedger(path) appends JSONL events with a closed `EVENT_KINDS` vocabulary (`operator_request`, `operator_input`, constraint, acceptance, `plan_node`, decision, `open_loop`, evidence, `working_set`, `changed_path`, verification, message, delegate, return, invocation, snapshot) and a ledger-owned seq; `LEDGER_SCHEMA_VERSION` header line first; no rewrite path exists
  - `derive_snapshot`(events) -> TaskSnapshot(`task_id`, `original_request_ref`, `active_thought`, constraints, acceptance, plan, decisions, `open_loops`, `working_set`, `changed_paths`, verification, messages, delegations, episode, `authority_digest`, `state_digest`) is replay-deterministic: same events → equal snapshot and digests (property test over shuffled-but-seq-ordered inputs)
  - append takes an fcntl advisory exclusive lock when available (worktrees.py:46,138-169 pattern; non-POSIX degrades to unlocked append + a recorded warning); tests/`test_agents_ledger.py` runs N threads × M appends on a real tmp file and asserts N×M intact lines
  - `read_ledger` refuses an unknown schema version, a torn/non-JSON tail, or a `state_digest` mismatch by raising LedgerUnreadable(reason) — never a traceback past it, never a partial snapshot
  - `ledger_path`(`repo_root`, `task_id`) = <`repo_root`>/.colleague/ledger/<`task_id`>.jsonl; tests/`test_boundary.py` passes unchanged (no subprocess, no thread consumer added)

### t5 — t5 #410 — SIGTERM writes the partial artifact unconditionally (before/independent of the wedged request)

- instruction: Companion to the 2026-08-20 worker-wedge incident (task 3d03ebcd0879). Keep the change inside the signal handler + a small helper in work.py; do not touch loop.py. Use tests/`test_work_interrupt`\*.py shapes if present; the stream double must be a real pipe.
- covers: c44
- acceptance:
  - colleague/cli/`_commands`/work.py's SIGTERM/SIGINT handler (work.py:322-367) writes the partial result artifact (status error, incompletion recorded) BEFORE the WIP commit path and independent of the request layer's state; the artifact path is the same <`task_id`>.<slug>.json the normal path writes
  - regression test: a run blocked inside a stream that never yields (real os.pipe, per the fake-streams gotcha) receives SIGTERM → the artifact exists with status error AND 'colleague work --continue <id>' accepts it (continuation.`resolve_continuation` returns a seed)
  - existing interrupt-safety tests (#222/#162) still pass; exit code stays 143/130

### t6 — t6 #400 — progress (step-stall) watchdog: bound time-since-last-completed-step, finish partial, record honestly

- instruction: Do not add 'step-stall' to chain.`CONTINUABLE_REASONS` in this task (pinned unchanged by the self-learning increment) — file it as the plan risk r-stall instead. Keep the diff to the latency seams (loop.py:1778 `_record_turn_latency`, :1999 `_account_turn`); wiring only.
- acceptance:
  - loop.py gains ONE seam: a stall bound read from `COLLEAGUE_MAX_STEP_STALL` (seconds; default = 6× the observed mean per-step latency once ≥3 steps exist, else 1800s) evaluated in `_account_turn`/`_record_turn_latency`; crossing it records {'kind': 'step-stall', 'seconds': n, '`step_index`': i} on TaskResult.warnings and ends the episode with a preserved partial (`not_finished`=True) instead of continuing
  - backpressure.py's advisory actions are unchanged; the stall is measured by `step_index` advancing, not wall-clock of a single turn; a legitimately long single generation that DOES advance the step is never cut
  - tests/`test_loop_step_stall.py`: a scripted complete() that streams forever without a tool call trips the bound and yields a partial artifact with the warning; unset knob + fast steps → no warning (byte-identical)

### t7 — t7 config: the 'agents' opt-in (env > config.json > OFF), mutual-exclusion refusal, doctor 'agents' group + config show line

- instruction: config.py is 4200 lines — scope the edit to the `three_tier`/TAE loader block (config.py:272-299, :622-660) and the refusal helpers (:1329-1343); mirror names exactly. Doctor lines live in livecheck.py near `three_tier_armed`/`three_tier_gateway`. No model names anywhere.
- depends on: t3
- covers: c56, h42
- acceptance:
  - config.py: `_load_agents_override` reads `COLLEAGUE_AGENTS` then the 'agents' key of .colleague/config.json (bool or object-presence, the `_load_three_tier_override` :622 shape); EngineConfig.agents: bool = False; arming agents with `three_tier` OR `thought_action_evaluation` refuses via the `_refuse_conflicting_execution_modes` shape (config.py:1329-1343) naming both modes; config show prints agents: armed|off
  - livecheck.py doctor gains an 'agents' group: `agents_armed`; per reference role (senses/worker/cortex) 'ready' | 'absent → cortex fallback' from the same lobes resolution the `three_tier_`\* checks use; unarmed → the group prints nothing (byte-identical doctor output, pinned by test)
  - tests/`test_config_agents.py` + tests/`test_doctor_agents.py` pass; a gateway double mirroring the 2026-08-21 advert (worker ready:false) yields the fallback line; tests/`test_doc_config_drift.py` passes

### t8 — t8 engine truth: empty content + `finish_reason`=length is a recorded truncation in the degradation lane

- instruction: Touch loop.py only at `_handle_no_tool_turn` (:2021) and the degradation classification helper; `vllm_openai.py` needs no change (`finish_reason` already carried raw :273). Serialized after t6 so the two loop.py seams never collide.
- depends on: t6
- covers: c18, h14
- acceptance:
  - a model turn with empty content, no tool calls and `finish_reason`=='length' is classified truncated at the turn (not only at run end): loop marks the turn truncated (recorded on the invocation record once t15 lands; until then on TaskResult.warnings {'kind':'truncated-turn'}) and routes into the existing degraded-retry plan (`_plan_degraded_retry` :1702 shrink-for-retry) instead of `_handle_no_tool_turn`'s nudge
  - streaming regression test on a real os.pipe: a stream ending with empty content + `finish_reason` length yields the truncation record + one shrink retry; the blocking path yields the same; finishstate.`classify_finish_state` still reports `FINISH_TRUNCATED` at run end
  - reasoning accounting unchanged: tokens exactly from usage, `reasoning_chars`/bytes as today (`vllm_openai.py`:261-263)

### t9 — t9 agents/runtime.py — InvocationRecord (identity + context manifest) and the ONE agent seat builder

- instruction: Generalize `tae_loop`.`seat_engine_config` (`tae_loop.py`:214-232). `context_budget_tokens` FOLLOWS THE ROLE ADVERT (cortex 1,048,576 per the 2026-08-21 re-probe; worker 65,536 when ready) — the bigger sliding window is intended. Token estimate: use the engine's `count_tokens` when available (`vllm_openai`.`_make_count_tokens`) else context.`count_tokens_chars`, and label the source. Invocation records are appended to the task ledger as 'invocation' events (t4).
- depends on: t1, t2, t4
- covers: c13, h12, c4
- acceptance:
  - InvocationRecord(`agent_id`, purpose, `model_role`, `resolved_model`, `fallback_from_role`, `tool_surface_digest`, `ledger_digest`, `nucleus_refs`, `working_set_refs`, `retrieved_memory_refs`, `peer_message_refs`, `token_estimate`, `token_estimate_source` in {tokenize, chars}, truncated, `parent_agent_id`, `delegation_id`, seq) with `to_dict`; `token_estimate` is NEVER written into Usage
  - `agent_engine_config`(config, profile, roles) returns dataclasses.replace(config, model=…, `base_url`=`resolve_role_base_url`(role,…), `api_key`=<per-role key or None, never the parent's when the origin differs>, `context_budget_tokens`=<role advert context>, `refresh_seat`=None, `on_delta`=None) — one builder that `tae_loop`.`seat_engine_config`, `deepthink_engine_config` and `senses_engine_config` can delegate to (they are NOT rewritten in this task; a follow-up task may fold them)
  - tests/`test_agents_runtime.py`: a worker-purpose profile against the 2026-08-21 advert double resolves to the cortex model with `fallback_from_role`='worker' and the record carries it; `refresh_seat` is None; `api_key` hygiene per #348; manifest digests match ledger.`derive_snapshot` output

### t10 — t10 agents/state/context.py — per-agent reconstruction, pinned nucleus, `context_mode`, provenance ranking

- instruction: Pure functions over TaskSnapshot (t4) + AgentMessage (t3); the retrieved-procedures layer calls the existing memory recall seam via an injected callable (do not import loop.py). The nucleus never contains tool calls or chain-of-thought.
- depends on: t4, t3
- covers: c36, h19, c37, h20, c46, h33, c55, h41
- acceptance:
  - `build_nucleus`(snapshot) returns the pinned block (active thought/mission, constraints, acceptance, authority digest, active plan node, unresolved failures) as ONE message the acting loop pins like the system prompt + first user message; reconstruct(snapshot, purpose, budget, recall=…) returns layered messages \[nucleus, working set (verbatim recent tool evidence refs resolved), retrieved procedures (top-k, token-capped), archive refs\] plus the manifest fields; two purposes over one snapshot yield different reconstructions (test)
  - `context_mode` in {inherit, clear}: inherit = parent transcript windowed as today + nucleus pinned; clear = reconstruction only + a handover summary (objective, acceptance, changed paths, evidence refs) — the reviewer's 'clear mind'
  - ranking is explicit and tested: operator input > current repo/tool evidence > accepted task facts > peer claims > recalled memory; a peer message renders as a labelled 'peer <`agent_id`>:' text block, never as system/operator text; a later `operator_input` outranks an earlier peer inform; both sides of a challenge appear
  - `token_estimate` of an ordinary reconstruction < 50% of the seat's advertised context by construction (budget parameter); unarmed code paths are untouched (context.py unchanged)

### t11 — t11 agents/delegation.py — DelegationRequest envelope, child ⊆ parent property, lifecycle events, handoff semantics

- instruction: No spawning here — t14 wires it into subagents.`run_subagent`. Authority ceilings are a small closed enum (`read_only`, `repo_patch_no_publish`, `repo_patch_publish`) ordered; host policy still gates every route.
- depends on: t1, t2, t3, t4
- covers: c8, h22, c50, h36
- acceptance:
  - DelegationRequest(`delegation_id`, `from_agent`, `requested_agent_profile`, objective, acceptance, `evidence_refs`, `context_refs`, `requested_tools`, `authority_ceiling`, `return_contract`, `context_mode`) validates: `requested_tools` ⊆ parent effective tools, `authority_ceiling` ≤ parent's, depth/fanout/total within `MAX_SUBAGENT_`\* — refuses whole otherwise (DelegationVerdict)
  - `open_delegation`(ledger, req) appends the 'delegate' event BEFORE spawn and returns a handle; `close_delegation`(handle, SubResult) appends 'return'; `derive_snapshot` lists a delegate without return as an open loop naming sub/<`child_id`>; handoff(ledger, `plan_node`, `to_agent`) changes plan-node ownership on the ledger only
  - property test (hypothesis-free, seeded random): for random parent/child profiles `child_effective` ⊆ `parent_effective` and ceiling ≤ regardless of child model; tests/`test_agents_delegation.py` passes

### t12 — t12 agents/guidance.py — the enumerated purpose→role guidance table (prompt text, never a runtime branch)

- instruction: Source the bullets from issue #411 'Routing policy' (Prefer Talker/Worker/Thinker when…) reworded as guidance to the agent; the runtime never routes — model switching only via t11 delegations.
- depends on: t1
- covers: c5
- acceptance:
  - GUIDANCE is a frozen tuple of (purpose, when-to-prefer bullets) rendered by `build_guidance_text`() into the delegating agent's system prompt fragment; the module contains no function that takes task text and returns a model/role (grep-guarded in t18)
  - tests/`test_agents_guidance.py`: rendered text names talker/worker/`thinker_coder` purposes only (no vendor names), is deterministic, and is absent from the prompt when agents is unarmed

### t13 — t13 contract + artifact + mock: TaskResult.agents block (omit-when-unarmed) and mock-engine honouring of profiles

- instruction: Additive only. Keep the block small — messages/invocations are already in the ledger; the artifact carries them for the ROI/feedback readers. Do not touch loop.py (t15) or subagents.py (t14).
- depends on: t9, t3
- covers: c17, h24
- acceptance:
  - contract.py: TaskResult.agents: Optional\[dict\] = None carrying {version, invocations\[\], messages\[\], fallbacks\[\], `ledger_path`, `ledger_digest`}; `to_dict` omits it when None (contract.py:1308-1345 convention); `from_dict` round-trips; artifact.write unchanged otherwise
  - engines/mock.py honours ChildSpec profile/`context_mode` fields identically to vllm-openai (shape parity) and emits invocation records when config.agents is armed; tests/`test_e2e_mock.py` passes unchanged; a new parity test asserts the armed key shape is identical on both engines

### t14 — t14 subagents: a child may bind a different lobes role (cross-role dial), `context_mode`, identity + lifecycle events

- instruction: subagents.py:468-489 is the seam; keep caps (config.py:339-341) untouched; the mock engine must accept the same ChildSpec fields (t13). Same-origin key hygiene per #348.
- depends on: t9, t11
- covers: c7, h8, c49
- acceptance:
  - subagents.ChildSpec gains profile (purpose or role name), `context_mode` in {inherit, clear} (default inherit); `run_subagent` builds the child EngineConfig via agents.runtime.`agent_engine_config` when config.agents is armed (role dial, own context, per-role key — never the parent `api_key` when the origin differs), else byte-identical to today's replace(model=…)
  - the child's SubResult carries `agent_id`/`resolved_model`; delegate/return events bracket the spawn (t11); a child with `context_mode`=clear receives the handover summary (t10) instead of the parent transcript
  - every `make_spawn`/`make_batch_spawn` caller (work.py:1290-1297 and any other) passes the parent profile; tests/`test_subagents.py` + `test_subagents_parallel.py` + `test_subagent_e2e.py` pass; new tests cover cross-role dial on mock and vllm-openai (gateway double)

### t15 — t15 loop.py wiring (wiring only): mode check, invocation records at the chokepoint, ledger appends, pinned nucleus, two-sided tool surface, messages

- instruction: Claude authors this task (loop.py is 4951 lines — colleague times out on it). Keep every new body in colleague/agents/runtime.py; loop.py calls runtime.`begin_task` / runtime.`record_invocation` / runtime.`end_task`. Respect the chokepoint invariant: every model turn passes `_complete_with_degradation`. When agents is armed the acting agent's window budget is its seat's advertised context (bigger sliding window for cortex now, worker when on) with the nucleus pinned; unarmed keeps `_DEFAULT_CONTEXT_BUDGET` byte-identically.
- depends on: t8, t9, t10, t11, t12, t13
- covers: c16, h13, c51, h37, c49, h35, c11
- acceptance:
  - when config.agents is armed: run() opens the task ledger at the operator repo (`flight_repo_path` precedent, loop.py:2161-2172), appends `operator_request` first, appends an invocation record around every `_complete_with_degradation` call (loop.py:1885), appends `operator_input` for flight guidance / `guide_cortex` / talk (`_fold_flight_chat` :2129), pins the nucleus (t10) ahead of `window_messages`, feeds the profile's effective tool surface to BOTH `curate_schemas` and ToolExecutor(allowlist=), injects the guidance text (t12), and folds TaskResult.agents (t13) on every exit path including abort
  - unarmed: loop.py behaviour is byte-identical (mock parity suite + the whole suite green); the loop.py diff is seam calls + one mode check — no new `_maybe_`\* logic bodies (new logic lives in colleague/agents/)
  - tests/`test_loop_agents_wiring.py`: armed run on mock yields invocation records for every turn, `operator_input` ordering, and a Worker-profile child refused by the executor on `write_file` even if offered

### t16 — t16 talker = senses: identity + invocation records at senses call sites, talker profile refuses write tools, talk/guide as `operator_input`

- instruction: Wiring only in senses.py/`senses_loop.py`; the record builder is t9's. Do not touch loop.py.
- depends on: t9, t13
- covers: c19, h25, c21
- acceptance:
  - senses.py / `senses_loop.py` call sites (senses.py:669,744,807,1104,1237,1410) record an InvocationRecord with purpose talker when agents is armed; tools=\[\] stays at every call site (tests/`test_senses_cannot_act.py` passes unchanged)
  - AgentProfile validation refuses a talker profile whose `tool_profile` contains any write-class tool (t2 classes); `guide_cortex`/talk/clarify outputs are `operator_input` or display-only events — never a delegate/handoff authority (test)
  - headless/cortex-only runs are unchanged (no senses → no talker record; byte-identical)

### t17 — t17 continuation rehydrates from the ledger (armed), fails closed to the prose recap, unarmed ignores + warns

- instruction: continuation.py:25 + escalation.`build_continuation` :187 are the seams; the artifact is still the wrong-run guard's source. Works even when the artifact write failed only after t5 lands (dep).
- depends on: t4, t5
- covers: c35, h18, c54, h40
- acceptance:
  - continuation.`resolve_continuation`: when agents is armed AND <repo>/.colleague/ledger/<id>.jsonl reads cleanly, the seed is built from `derive_snapshot` (authority flags, --no-pr, mode, role/profile, constraints, acceptance, changed paths, failed checks, open loops, open delegations, promised follow-ups) + the verbatim original request — not escalation.`build_continuation`'s prose; LedgerUnreadable → warning recorded + the existing prose path; unarmed → prose path + a warning that a ledger exists
  - tests/`test_continuation_ledger.py`: rehydrated snapshot equals the pre-cut snapshot for `changed_paths`/`open_loops`/acceptance/authority (0 lost items); truncated tail / bumped schema / digest mismatch each → warning + prose fallback, exit 0; latest `operator_input` outranks the snapshot's summaries

### t18 — t18 guards + parity tests: vendor-name grep, no-router grep, boundary allow-lists, TAE schemas unchanged, mock key-set diff 0

- instruction: Tests only; pure stdlib ast/grep. These are the c41/h28 and c22/h26 proofs.
- depends on: t15
- covers: c5, h21, c20, c22, h26, c23, h27, c41, h28, c12, h23
- acceptance:
  - tests/`test_agents_boundary.py`: (a) no gemma|qwen|nemotron|lightning under colleague/agents/; (b) no function under colleague/agents/ or loop.py reads task.instruction/context to choose a model (AST guard: no call that returns a model/role takes the instruction text) — the only model switch is a DelegationRequest; (c) tests/`test_boundary.py` `_SUBPROCESS_ALLOWED`/`_THREADS_ALLOWED` unchanged; (d) Thought/ActionProposal/Evaluation/LedgerEntry field sets unchanged or additively versioned
  - tests/`test_e2e_mock.py` passes unchanged and a new assertion diffs the unarmed `to_dict` key set against the pinned list = 0 additions; the armed key shape is identical on mock and vllm-openai

### t19 — t19 ledger location + clean/reap scope: operator-repo path on isolated runs, reap finished-task ledgers only

- instruction: Small edits in handoff.py reap helpers + cleanup docs; path resolution comes from t4's `ledger_path` + loop's `_flight_repo_path`.
- depends on: t4, t15
- covers: c47, h34
- acceptance:
  - an isolated run (work/drive worktree) writes .colleague/ledger/<id>.jsonl under the OPERATOR repo (task.`flight_repo_path`), never inside the throwaway worktree; 'git status' is clean after an armed run (gitignore /.colleague/\* at .gitignore:247)
  - handoff.py's reap (handoff.py:697 scope) and 'colleague clean' include .colleague/ledger/ for tasks whose artifact is final or orphaned; a live task's ledger is never removed (test with a running-marker double)

### t20 — t20 fallback proof on a gateway double of the 2026-08-21 advert + doctor fallback line

- instruction: Save the dump from this session's probe verbatim (re-probe at implementation time and note any diff). The double speaks only GET /capabilities; no model calls leave the process (mock engine).
- depends on: t15, t7
- covers: c43, h30, c4, h7
- acceptance:
  - tests/fixtures/capabilities-2026-08-21.json is the saved advert (cortex ready 1048576; senses ready 32768; worker Lightning ready:false 65536; hand ready; muse/stt/tts not ready) served by a stdlib http double; tests/`test_agents_fallback.py`: an armed work item with ≥1 subagent completes status ok, 0 refusals, every worker-purpose invocation recorded as cortex-backed with `fallback_from_role`='worker'; TaskResult.agents.fallbacks non-empty; doctor prints the fallback line
  - the same double with worker ready:true yields a worker-bound invocation (proves the fallback is conditional, not hardcoded)

### t21 — t21 continuity regression: SIGTERM-resume equality + compaction drops 0 plan nodes (real os.pipe)

- instruction: Build on t5's pipe fixture and t17's rehydration. The audit helper is test-side, not a new CLI verb.
- depends on: t17, t5, t15
- covers: c44, h31
- acceptance:
  - tests/`test_agents_continuity.py`: an armed run blocked in a never-yielding stream (real os.pipe) receives SIGTERM → artifact exists (t5) AND ledger exists; work --continue rehydrates a snapshot equal to the pre-cut snapshot on `changed_paths`/`open_loops`/acceptance/authority (0 lost); a fillline compaction during an armed run leaves every `plan_node` and `changed_path` on the ledger (0 dropped)
  - a manifest audit helper (tools/… or tests util) reports max `token_estimate` / advertised context over a run; asserted < 0.5 on the scripted run and used by t23 on the live run

### t22 — t22 docs + scope line + changelog + version: docs/features/model-bound-agents.md, CLAUDE.md eleventh increment, CHANGELOG, minor bump

- instruction: Match docs/features/thought-action-evaluation.md for structure and docs/specs/2026-08-09-…md:92 for the scope sentence. Honest limits must say: opt-in only until c45; acting agent keeps transcript (q7); evaluator seat is TAE's (q9).
- depends on: t15, t16, t17, t18, t19, t20, t21
- covers: c38, h2, c39, h3, c40, h5
- acceptance:
  - docs/features/model-bound-agents.md follows the feature-doc shape (what / modes / invariants / honest limits / module list / spec+plan links) and contains a traceability table mapping every after-state clause to its requirement + test (h3); it names lobes-cli#187 as the advert owner and cites the 2026-08-21 probe (h2); why-it-matters cites the benchmark numbers from their sources (h5)
  - CLAUDE.md: a new architecture bullet + the v1-scope paragraph gains '(11) the model-bound-agents increment' in the established three-part form (FIXED roles BY ROLE NAME, INDEPENDENT opt-in, byte-identical unarmed, NEVER a routing policy); three-tier bullet marked superseded-by-#411 (kept); CHANGELOG top entry in the Keep-a-Changelog form; version bumped minor via the version-bump skill; markdownlint-cli2 clean

### t23 — t23 live proof + experiment pre-registration: refusal reproduced, armed run on the Spark rig, live-testing rows, bars before arms

- instruction: Unset `three_tier` in .colleague/config.json first (the current refusal). Clean the stale `CONVERTIBLE_MODEL` export before the run so identity records carry the served cortex id. Run arm A (solo cortex legacy) and arm B (agents armed) on the same brief; record both even if B loses.
- depends on: t22
- covers: c1, h1, c3, h4, c42, h29, c43, h30, c45, h32
- acceptance:
  - docs/deliveries/2026-08-21-model-bound-agents-411.md records: the pre-fix refusal reproduced verbatim against the live gateway + the 2026-08-21 /capabilities dump; one LIVE armed 'colleague work' on the Spark rig (worker ready:false) completing end to end with the task id; the artifact audit showing 100% of invocations attributed, the negative authority test result, and the manifest audit (max `token_estimate` / advertised context) from the run
  - docs/live-testing.md gains rows for the live run and for the matched experiment; the experiment's success bars (quality, completion, latency, tokens/model, tool calls/model, escalation rate, invalid tool calls, corrections) are committed in the delivery doc BEFORE the arms run; agents mode remains opt-in in config docs until the row exists

## Risks

- [unknown_nonblocking] loop.py (4951 lines) and config.py (4200 lines) edits (t6, t8, t15, t7) exceed what colleague can edit before timing out — Claude authors t15; t6/t8/t7 dispatch only with tight line-range briefs; #399 extraction stays a separate follow-up (task t15)
- [follow_up] adding 'step-stall' to chain.`CONTINUABLE_REASONS` (#400's suggestion) would change a surface the self-learning increment pinned unchanged — left out of t6; decide in a follow-up re-spec (task t6)
- [unknown_nonblocking] the local GPU serializes requests: parallel waves of colleague dispatches cap at ~2 with `COLLEAGUE_TIMEOUT`=300; wide waves are operational only for Claude-side tasks
- [follow_up] the Lightning worker may become ready mid-arc (lobes-cli#187); t20's 'ready:true' branch is the only worker-bound proof until then — re-run t20/t23 when the role is ready (task t20)
- [follow_up] the three existing seat builders (`tae_loop`.`seat_engine_config`, `deepthink_engine_config`, `senses_engine_config`) are not folded into t9's builder in this arc (c48 assumption) — a fourth copy is avoided but the triplication remains; fold is a follow-up (task t9)
- [unknown_nonblocking] t23's live arms need rig time (hours per run on the reasoning-heavy 3.8); the matched experiment may land after the PR as a follow-up row — the mode stays opt-in until it does (c45) (task t23)
