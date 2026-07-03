# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What colleague is

**Colleague CLI is a swappable coder-agent harness that turns different model
backends into repo workers behind one shared task runtime.** One runtime, many minds.

The architecture, part by part:

- **Mind / backend** — the model/coder backend.
- **Adapter** — the code that invokes one backend, in `colleague/engines/` (an
  `Engine` subclass implementing `work(task, config) -> TaskResult`).
- **Task runtime** — the shared task contract (`colleague/contract.py`: `Task`,
  `TaskResult`) and lifecycle. A task MAY carry a pre-execution **goal**: optional
  `Task.goal` (a one-line statement of intent, distinct from the free-form
  `instruction`) and `Task.acceptance` (machine-readable criteria) — both
  omit-when-None (spec R6 / #259, task t14). When set, `colleague/loop.py`
  appends a distinct Goal/Acceptance-criteria block to the task prompt, and on a
  CLEAN finish runs ONE bounded, tools-off completion
  (`_maybe_run_acceptance_selfcheck`) that records per-criterion `{criterion,
  met, evidence}` outcomes onto `TaskResult.acceptance_outcomes` (task t15) —
  advisory only: `met=False` never flips the run's status, and an
  incomplete/aborted run never self-grades (operator confirmation stays the
  authority, the same convention as the `devague` destination tool). Because
  the self-check is a single bare completion with no tool schema offered, it
  structurally cannot call `finish` — a stronger invariant than the lint/
  test-integrity gates' save/restore pattern, which those need only because
  their fix-turns re-enter the full tool loop. Feature doc:
  `docs/features/task-goals.md`.
- **Tool loop** — the bounded agentic loop (`colleague/loop.py`) the backend
  works the repo through (`read_file`/`write_file`/`edit_file`/`list_dir`/
  `run_command`/`culture`/`finish`, confined to the repo by `colleague/tools.py`).
  The base six tools (`edit_file` is the partial-edit primitive added in #174 —
  cost scales with the change, not the file size, so a scoped edit to a large
  existing file no longer requires regenerating the whole file) plus one curated
  `culture` tool (allow-list: `agtag`, `devex`) — added via the mesh-member
  re-spec (spec/plan committed on this branch). Hook firing lives here — every
  backend inherits lifecycle behavior automatically. The per-step **progress sink**
  (`#38`, `ProgressFn`/`_emit_progress`) lives here too, and a **pre-completion phase
  notice** (`#206`, `_emit_phase`) fires through that same sink right *before* every
  model completion — `thinking…` before a normal turn, a louder `synthesizing…`
  before the no-tools forced-synthesis turn (#191), and `compacting…` before a
  fill-line summary turn — so a long single completion on a slow backend is visibly
  *working, not stalled* instead of going silent for minutes. A phase notice is
  encoded as a progress event with an EMPTY tool name (a reserved sentinel — a real
  tool always has a name); the plain stderr sink renders it as a standalone line, the
  structured **events** sink still skips it (so `tui replay`/`snapshot` stay
  step-only — `WorkStep` has no phase-only shape). The live cockpit
  "synthesizing" status follow-up is now **resolved** (spec R3 / #256, task t9):
  `fold_phase` (`colleague/cli/_commands/_tui_sink.py`) folds a phase notice
  onto the cockpit's STATUS surface (`state.status.message`) instead of
  dropping it — shared by both live-cockpit consumers, `CockpitProgressSink`
  (`work --tui`) and the session's `_WorkSink` — while the #206 invariant still
  holds: a phase notice never advances `work_item.step_count` or adds a
  conversation/feed line, so neither cockpit ever folds a phantom step. Runtime-owned, so
  every backend inherits it (all-engines rule); a strict no-op without a progress
  sink, and zero new deps/threads (the flight feed is untouched — the synthesis turn
  runs after the feed is reaped, so a piloting agent already reads it as ended, not
  stalled).
- **Plugins** — backends are plugins discovered via the `colleague.engines`
  Python entry-point group (`colleague/registry.py`).
- **Run report** — the JSON result artifact + step trace (`colleague/artifact.py`).
  Includes an **always-on per-work-item statistics block** (`TaskResult.stats`,
  `colleague/contract.py` `WorkStats`): request, ISO start + wall-clock
  duration, model turns, step count, per-tool counts, files changed, exact UTF-8
  `bytes_written`, and reasoning-vs-answer char/byte sizes. Tokens stay on
  `usage` (exact, verbatim from the model response — never estimated); since the
  served model reports no reasoning-token breakdown, "thought vs written" is
  measured as chars/bytes, not tokens (no tokenizer, zero deps). Populated
  runtime-side in `colleague/loop.py` (`run`/`_work_loop` + `_finalize_stats`)
  so every backend fills it identically; the vLLM backend captures
  `message.reasoning` (previously discarded).
- **Feedback** — the ROI loop (`colleague/feedback.py` + `colleague/cli/_commands/
  feedback.py`). Work stats say what a work item *cost*; a feedback record says how
  *good* it was — together they let a caller compute the ROI of delegating a task
  to colleague. A single record per work item (`<task_id>.feedback.json` beside the
  artifact, re-grade overwrites): `{task_id, rating 1-5, notes, by, at}`; a per-repo
  `last_work` pointer (written by `execute_work`) lets `feedback ... last`
  resolve the most recent work item. Stdlib JSON only; an ungraded work item reads back as
  a clean "no feedback yet" state, never an error. Surfaced as `colleague
  feedback record|show|list|overview` and as the `ask-colleague feedback` skill verb.
  **`last` is writes-only across the ask-colleague flow (#132):** `ask-colleague explore`
  / `review` run read-only in a throwaway worktree and **preserve** their artifact
  but **do not move** `last_work` (the skill's `_preserve_artifact` no longer
  writes the pointer) — so a read-only probe can never steal a grade meant for a
  consequential write. A probe is graded by its printed `task_id`; every work item
  echoes `task:` + a `grade:` hint, and resolving `last` echoes the resolved
  `task_id` + request to stderr so a mis-resolve is never silent. `feedback list`
  (`colleague/feedback.py` `list_work_items`) lists every recorded work item newest-first
  by request + status + grade — the durable way to find a work item when the order is
  forgotten; it reads the authoritative `task_id` from each artifact's contents,
  so the filename scheme doesn't matter. Artifacts and the work branch carry a
  **request slug** (`<task_id>.<slug>.json` via `colleague/artifact.py`
  `artifact_stem` + `colleague/slug.py`; `colleague/<task_id>-<slug>` via
  `handoff._branch_name`) so a work item is recognisable in an `ls` / `git branch`
  listing; `task_id` stays the key and `find_artifact`/`read_request` resolve both
  bare and slugged names (back-compat).
- **Telemetry** — opt-in OpenTelemetry traces + metrics (`colleague/telemetry/`).
  Instrumented in the loop + the shared work path so every backend emits it
  (all-engines rule), exactly like hooks. Off by default; the OpenTelemetry SDK
  is an optional `[otel]` extra, imported lazily, so the base install stays
  dep-free. Surfaced via the `telemetry` introspection noun.
- **Identity** — process-level identity resolution (`colleague/identity.py`):
  `culture.yaml` top-level `nick:` → `culture.yaml` first-agent `suffix:` (the
  canonical template shape `whoami` reads) → `.colleague/identity.json` `as` →
  None; propagated to every culture-CLI subprocess via `COLLEAGUE_IDENTITY` (no
  per-call flag). Part of the runtime; inherited by every backend (all-engines
  rule).
- **Neighbours** — operator-configured read-only neighbour clones
  (`colleague/neighbours.py`): a `.colleague/neighbours.json` allow-list of
  `{name, url}` entries; shallow-cloned on demand into
  `.colleague/neighbours/<name>/` (gitignored); refresh-on-demand, ephemeral
  (cleaned up on work finish). Defaults to empty when no config is present.
- **Culture tool** — one curated loop tool (`colleague/culture.py` +
  `colleague/tools.py`) that shells out to the allow-listed AgentCulture CLIs
  (`agtag`, `devex`) with the resolved identity injected; no socket, no daemon,
  no runtime dep. Lives in the runtime tool surface so every backend exposes it
  identically.
- **Destination** — the sibling to telemetry. Telemetry tells colleague where
  it *is*; the destination is where it's *going*. A backend MAY,
  when a task is vague/new enough to warrant a clear goal, use a curated
  **`devague` loop tool** to open/converge a devague goal-frame, work toward it,
  and declare the announcement on arrival. The destination is recorded lightweight
  in the JSON artifact (`TaskResult.destination` + `announcement`), not a per-work-item
  spec file. The `devague` tool shells out to the operator-installed `devague` CLI
  with cwd + resolved identity injected (like the culture tool); the curated
  allow-list excludes `confirm`/`reject` (user-only moves) and `export`
  (operator-only). Setting a destination is OPTIONAL and backend-judged, never a
  forced gate; convergence is ADVISORY, and only operator-confirmed claims are
  authoritative. Specification + plan: `docs/specs/2026-05-29-colleague-knows-its-destination-before-it-drives.md`
  and `docs/plans/2026-05-29-colleague-knows-its-destination-before-it-drives.md`.
- **Approval gate** — operator-declared allow-list that controls what the
  harness *executes* (`colleague/policy.py`). The policy lives in
  `.colleague/approvals.json` (repo-level, resolved via `configdir`; a
  per-model overlay at `.colleague/<sanitized-model>/approvals.json` is
  composed ahead via exact-path construction — no sibling globbing). Three
  gated categories, each opt-in via presence of its section:
  - `run_command` — gates CLI invocations by program token (`shlex` first
    token); allow/deny lists; absent section is a strict no-op.
  - `hooks` — gates lifecycle hook script files by content checksum; a
    section present but listing no entry is still a gate (allow-list
    semantics: unlisted = denied).
  - `commands` — gates command template files by content checksum at
    expansion time.
  Skills and AGENTS instructions are **never gated** — they are declarative
  and load freely. Approval values are algorithm-prefixed strings
  `"sha256:<hex>"` (default) or `"md5:<hex>"` (honored). `approve` records
  the file's current checksum; a subsequent content change voids the approval
  (checksum mismatch → denied). Absent or malformed `approvals.json` is a
  strict no-op. Spec + plan: `docs/specs/2026-05-29-colleague-only-runs-the-executables-you-ve-appro.md`
  and `docs/plans/2026-05-29-colleague-only-runs-the-executables-you-ve-appro.md`.
  **Honest limits:** this is a policy gate, not a sandbox — the token check
  is bypassable by `sh -c`, pipelines, and shell expansion; `md5` detects
  accidental drift, not a malicious editor (use `sha256` for integrity);
  v0 is checksum-only (`version` pinning is a documented follow-up, not
  built). This is the tracked "per-repo hook trust gate" from the conventions
  section, now partially landed; there is still no `--no-hooks` flag.
- **Subagents** — mid-work, a backend MAY delegate scoped sub-tasks
  via two loop tools: (1) `subagent` for a single child, or (2) `subagents`
  (plural) for a batch that runs concurrently (`colleague/subagents.py` +
  `colleague/tools.py`). Each child runs the SAME bounded tool-loop as a nested
  in-process call and is isolated in its own throwaway git worktree on a
  `sub/<id>` branch (`colleague/worktrees.py`). The parent receives each child's
  `SubResult` as the tool result; completed sub-results are folded into
  `TaskResult.sub_results` (omitted when empty). Each `SubResult` optionally
  carries `parent` (spec R6 / #259, tasks t14+t16) — the IMMEDIATE parent work
  item's `task_id`, omit-when-None — so a subagent tree spanning nested
  delegation (a child that itself spawns grandchildren) is walkable one hop at a
  time from artifacts alone; the plan workforce's `build_workforce_items` carries
  each `PlanItem`'s goal/acceptance STRUCTURALLY (dict keys, not flattened prose)
  so a workforce child's `Task` gets the same `goal`/`acceptance` treatment as
  any other subagent. A SEQUENTIAL merge-subagent
  integrates the branches afterward, surfacing (never force-merging) unresolvable
  conflicts. Concurrency is opt-in: `COLLEAGUE_SUBAGENT_CONCURRENCY` (default 1 =
  byte-identical sequential behavior); with width > 1, up to `MIN(width,
  MAX_SUBAGENT_FANOUT-1)` children run in parallel via `concurrent.futures`
  (threads confined to `subagents.py`), reserving one slot for the merge child —
  a batch whose children are ALL read-only roles frees that reservation (its
  merge is structurally a no-op over an empty diff) and may use the full
  `MAX_SUBAGENT_FANOUT` (spec R5 / #258, task t12; the same read-only check is
  duplicated in `tools.py`'s batch-cap so the model-facing limit can't drift from
  the actual fan-out width). At concurrency width > 1 each child also resolves a
  CLAMPED SHARE of the parent's context/step budget (`parent // width`, floored
  at a workable minimum, never above the parent's own value) instead of
  inheriting the parent's full budget unscaled — width 1 stays byte-identical,
  and an explicit per-child override still wins over the width-scaled share
  (task t12). Delegation is BACKEND-JUDGED and OPTIONAL (like the `devague` destination tool),
  never a forced gate. An optional `engine`/`model` switch resolves through the
  existing `registry.load` + `EngineConfig` inheritance — a config-level switch,
  no backend code change. Termination is structural: `MAX_SUBAGENT_DEPTH=2`
  (recursion cap, checked *before* any child work) and `MAX_SUBAGENT_FANOUT=4`
  (per-work-item fan-out cap, including the merge child). No per-subagent git
  handoff — only the top-level work item hands off. **Honest limit:** real wall-clock
  speedup requires the served model to handle concurrent requests; on a
  serializing server, gain is bounded by overlapped I/O wait, not model compute.
  Specification + plan: `docs/specs/2026-06-03-colleague-s-convoy-drives-subagents-in-parallel-a.md`
  and `docs/plans/2026-06-03-colleague-s-convoy-drives-subagents-in-parallel-a.md`.
  This is explicitly NOT the out-of-scope multi-backend router / routing policy: there is
  no operator-configured automatic task→backend routing policy. Runtime-owned
  (all-engines rule): the tools fire identically for every backend. Feature docs:
  `docs/features/rig-budget.md` (budget scaling + merge-slot skip),
  `docs/features/task-goals.md` (lineage).
- **Subagent roles** — a delegated subagent can be a **typed role**: a tailored
  system prompt + a **curated subset** of the tool surface + a curated skill
  subset. Built-in defaults (`colleague/roles.py` `BUILTIN_ROLES`): `explorer`/
  `planner`/`reviewer` (read-only), `validator` (read + a dedicated read-only
  `run_tests` tool, no write), `writer` (full surface = today's default). A
  **read-only role provably cannot mutate the tree**: it withholds `write_file`,
  `edit_file`, AND `run_command` (the read-only built-ins are pure-read — even
  `culture`/`devague` are excluded as write-capable shell-outs), and the
  **role-aware `ToolExecutor` refuses any withheld tool** (`allowlist=role`) even
  if the model hallucinates the call. The engine (`mock`==`vllm-openai`) resolves
  `config.role` once in `work()` via the runtime seam `colleague/loop.py`
  `resolve_role`: the offered schema = `colleague/tools.py` `curate_schemas(role)`,
  the system prompt = `colleague/layers.py` `compose_role_prompt(role,…)` (base +
  AGENTS + the role's `prompt_fragment` + its curated skills, through the ONE
  existing layered-config path), and the role-aware executor. `Engine.system_prompt`
  is itself role-aware, so every backend inherits it. The applied role is recorded
  on `TaskResult.role`/`SubResult.role` (omit-when-None → a role-less run is
  byte-identical). Recursion deepened to `MAX_SUBAGENT_DEPTH=4` (was 2) with a
  single global `MAX_SUBAGENT_TOTAL=24` agent budget (a thread-safe counter in
  `colleague/subagents.py` charged once **before any child work**, so every nesting
  shape terminates; nested batches now permitted, each child bound to its own
  depth+1 batch-spawn sharing the budget; env-tunable
  `COLLEAGUE_SUBAGENT_DEPTH`/`COLLEAGUE_SUBAGENT_TOTAL`). Selection is
  **backend-judged + optional** (a `role` param on the `subagent`/`subagents`
  tools, `colleague work --role`, `ask-colleague … --role`, and the plan workforce's
  per-child role) — never automatic routing; omitting it is byte-identical. Operator
  prompt overlays at `.colleague/agents/<name>.md` (+ per-model
  `.colleague/<model>/agents/<name>.md`, exact path, no sibling globbing) override a
  built-in role's **prompt**. Surfaced for inspection via the **`roles`** CLI noun
  (`colleague/cli/_commands/roles.py` — a DISTINCT noun from `agents`, which
  inspects the AGENTS instruction-file cascade; the plan said "agents noun" but that
  name was already taken). Runtime-owned, zero-deps (the `_AgentBudget` `threading`
  use is confined to the sanctioned `subagents.py`). **Honest limits:** writes are
  confined to the repo + the agent's worktree (`_safe_path` confines `write_file`/
  `edit_file`; the cross-repo "free-run" write mode is **parked**, out of scope —
  no code path enables an out-of-repo write); `run_command` (writer only) stays
  arbitrary shell by design (trusted-operator D2, not a sandbox); v1 operator config
  overrides the prompt only, not a role's tool-allowlist (custom-allow-list roles +
  checksum-gating of role files are documented follow-ups). Spec + plan:
  `docs/specs/2026-06-17-colleague-orchestrates-a-workforce-of-typed-subage.md` and
  `docs/plans/2026-06-17-colleague-orchestrates-a-workforce-of-typed-subage.md`;
  feature doc: `docs/features/subagent-roles.md`.
- **Rig budget** — a file-based, cooperative concurrency budget across SEPARATE
  colleague processes sharing one served endpoint (`colleague/rig.py`,
  `.colleague/rig.json` `{"concurrency": N}`; spec R5 / #258, task t13). Each
  top-level work item holds ONE atomic-`mkdir` slot (`.colleague/rig-slots/`)
  for the duration of its loop (`colleague/cli/_commands/work.py`'s
  `execute_work`, around `engine.work(task, config)`); a stale slot (holder PID
  gone) self-heals, a live holder is never stolen, and a caller that can't get a
  slot within `max_wait` (default 300s) degrades OPEN — proceeds without one —
  rather than deadlocking the run. Deliberately NOT taken per subagent child
  (a parent holding a slot while waiting on children who also need one would
  deadlock by composition); in-run fan-out is governed instead by the child
  budget scaling + read-only merge-slot skip (above) and the backpressure
  fan-out throttle. Missing/absent `rig.json` is a strict no-op — no slot files
  are ever created. No daemon, no socket, no threads (stdlib `os`/`json`/
  `pathlib`/`time`, atomicity from `mkdir` semantics alone). Feature doc:
  `docs/features/rig-budget.md`.
- **Deepthink / dual-model** — colleague drives with two minds: a fast,
  wide-window MAIN model drives every loop turn, and an operator-declared
  **deepthink** model (a stronger reasoner) is escalated to at hard-judgment
  moments; or single-model exactly as before — **absent deepthink config is
  byte-identical** (no tool schema offered, no artifact key, same resolution).
  Config: `EngineConfig.deepthink` (`colleague/config.py` `DeepthinkConfig`),
  presence keyed solely on a resolved model; `COLLEAGUE_DEEPTHINK_MODEL`/
  `_BASE_URL`/`_API_KEY`/`_CONTEXT_BUDGET` env > `.colleague/config.json`
  `deepthink` section > absent; base_url/api_key default to the main endpoint,
  `context_budget` defaults 48000 (64K-sized; the main default is 48000 too
  since the rig serves the default 27B at 64K).
  The escalation surface is **enumerated** (boundary-tested — the complete
  list): (a) the backend-judged **`deepthink` loop tool** (offered only under
  dual config, judgment-not-mechanics description, available to read-only
  roles — pure computation); (b) **plan-mode proposals**
  (`cli/_commands/plan.py`, per-call fallback to the main model + stderr
  visibility); (c) the **acceptance self-check** (graded from a self-contained
  digest, main-model fallback on degradation); (d) the **test-integrity
  reviewer default** (same-endpoint only — the subagent switch carries just a
  model name). Every invocation is ONE bounded **tools-off** completion via
  `Engine.make_complete(config, tools=[])` (nothing tool-related on the wire —
  structurally cannot call tools/`finish`), **windowed to the deepthink
  model's OWN budget** (`colleague/deepthink.py` `run_deepthink`, per-endpoint
  `/tokenize` exact counting via the public `Engine.make_count_tokens` seam,
  char fallback), and **degrades, never raises** — a dual run never fails
  because deepthink is unreachable; on `mock` it records a degraded no-op.
  Work-loop escalations are recorded on `TaskResult.deepthink`
  (`{point, tokens, duration, degraded}`, omit-when-None). ONE binding per
  work item (`make_deepthink_run(config, engine_name)`) is injected into both
  the executor and `ContextControls` by every backend (all-engines rule).
  **Forced synthesis (#191) and fill-line compaction (#156) deliberately stay
  on the main model** — their prompt IS the main model's own windowed history,
  which cannot fit the smaller deepthink window; re-windowing would discard
  context, not add judgment. **This is NOT the out-of-scope multi-model
  router**: one declared second model, a fixed enumerated surface, no
  automatic task→model routing policy, no N-model generalization. Honest
  limits: the live rig proof + wall-clock/quality benchmark are **PENDING**
  (`docs/live-testing.md` — the rig serves no tool-calling backend yet);
  plan-mode calls are stderr-visible only (no TaskResult outside the loop);
  multimodal input and mode-level model preference are parked follow-ups.
  Feature doc: `docs/features/deepthink.md`; spec + plan:
  `docs/specs/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md`
  and `docs/plans/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md`.
- **Cortex / senses** — colleague resolves its minds **by role**, from an
  operator-declared `lobes` gateway, instead of hardcoding a model id: a
  **cortex** role (the authoritative, wide-window, tool-calling mind that
  drives the bounded loop — cortex territory is otherwise untouched) and a
  **senses** role (a tools-off multimodal front door that perceives the
  operator's raw request before cortex acts and shapes cortex's raw summary
  back into a conversational reply). Absent senses/lobes config is
  **byte-identical** to pre-arc colleague (cortex-only, the default). Role
  resolution (`colleague/lobes.py` `resolve_roles`, pure `urllib` `GET
  {gateway}/capabilities`, degrade-to-`None` on any failure, never raises)
  slots into the SAME `EngineConfig.resolve()` precedence chain as one more
  rung: explicit flag > `COLLEAGUE_*` env > `.colleague/config.json` >
  **lobes discovery** (`COLLEAGUE_LOBES_URL` / config.json `lobes` section) >
  builtin default — an armed-but-unreachable gateway degrades to the next
  rung with ONE stderr notice (h7), never a hard-fail. `SensesConfig`
  (`colleague/config.py`) mirrors `DeepthinkConfig` field-for-field (`model`,
  `base_url`, `api_key`, `context_budget` default 24000 for a 32K window,
  `multimodal`); presence keyed solely on a resolved model. Senses reaches
  the wire through the SAME enumerated tools-off completion machinery as
  deepthink (`colleague/senses.py` `run_senses_intake`/`run_senses_speakback`,
  `Engine.make_complete(senses_config, tools=[])`, windowed to senses' OWN
  budget via `make_count_tokens`, degrade-never-raise) — a senses request
  structurally cannot carry a tool schema, mirroring the live lobes contract's
  own `forbidden_responsibilities = [final_decision, repo_action,
  security_decision]` for the role; a dedicated structural proof pins that
  `colleague/senses.py` imports neither `ToolExecutor` nor `subprocess`, and
  that a senses response carrying tool-call-shaped output still produces only
  an advisory record. Intake produces a `ContextPacket {original (verbatim —
  never derived from model output), interpretation, confidence, task_type,
  omissions}` that the loop injects as the operator's ORIGINAL text plus ONE
  advisory companion message (`colleague/loop.py`
  `_maybe_inject_context_packet`) — the packet augments, never replaces; a
  failed/lossy intake degrades to passing the raw text through untouched
  (intake can never lose the request). Two modes: **cortex-only** (default,
  byte-identical) and **split** (senses intake + speak-back shaping for
  DISPLAY only — the raw cortex summary is always retained in
  `TaskResult.summary`), plus a per-run **`--cortex-only`** bypass flag
  (`work`/`session`) and a **`--debug-senses`** flag that echoes the packet to
  stderr. Per q1: text intake covers the interactive surfaces only —
  `colleague session` free-text and mesh-resident inbound messages
  (`colleague/resident/appserver.py`); one-shot `colleague work` text
  deliberately bypasses text intake (it is already deliberate CLI input), but
  a media-bearing work item still gets senses MEDIA perception — a declared
  multimodal senses is PREFERRED over deepthink's media-comprehension bridge
  (`_maybe_run_senses_media_bridge` runs first; when it handles the bridge the
  deepthink path is a strict no-op). Runtime measurements land on
  omit-when-None `TaskResult.senses` (`{mode, packet, records:[{point,
  latency, tokens, degraded}]}`, the senses-side sibling of
  `TaskResult.deepthink`) so the SAME task run cortex-only and split yields
  directly comparable artifacts — runtime facts only, never a synthesized
  quality score (that stays with the feedback/ROI loop). Introspect the armed
  state via **`colleague lobes show`** (`not_configured` /
  `armed_reachable` / `armed_unreachable`). Runtime-owned under the
  all-engines rule throughout. **This is the SECOND sanctioned increment at
  the router-exclusion boundary** (after deepthink): TWO operator-declared
  roles with a FIXED responsibility boundary (cortex acts, senses
  perceives/presents), resolved by name from lobes — no automatic
  task→model routing policy, no N-role generalization, no senses-decides-
  to-answer-itself. Two follow-ups are parked, each needing its own
  router-boundary re-spec: **#276** (senses-direct-for-cheap-tasks — senses
  answering without cortex at all; a model deciding per-input whether cortex
  is needed is the start of the excluded routing policy) and **#277** (the
  voice loop — `stt`/`tts` consumption — and embedder/reranker consumption;
  both roles are discoverable in the `/capabilities` contract from day one
  but colleague consumes only `cortex`/`senses` today). Honest limits: the
  senses intake window is windowed to the senses model's own budget, but
  `ContextPacket.original` is never touched by that windowing (always
  verbatim); the lobes-reported per-role `endpoint` field is not
  client-reachable on the reference rig, so colleague dials the gateway
  origin for both roles instead (a documented workaround; a lobes-cli issue
  is a warranted follow-up, not yet filed); a lobes-discovered senses is
  `multimodal=False` (arming the media bridge needs an explicit operator
  declaration, never inferred from the wire); intake is synchronous in v1.
  Feature doc: `docs/features/cortex-senses.md`; spec + plan:
  `docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md`
  and `docs/plans/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md`.
- **Media input** — images and audio ride the task contract to a multimodal
  main model on all three surfaces (in chat: the session's `/attach` slash,
  staged one-shot for the next work line; out of chat: `colleague work
  --attach PATH`, repeatable, composes with `--command`; as a service: mesh
  `attach: <path>` line references under the c19 trust model — operator-only
  arbitrary paths, non-operator repo-confined resolve-then-contain,
  anti-exfiltration test-proven). One plumbing: optional `Task.attachments`
  (`{path, media_type}`, omit-when-None) → the loop builds the initial user
  message as standard OpenAI content parts (`colleague/media.py`, pure
  stdlib; no attachments = plain string, byte-identical) → engines pass parts
  verbatim (all-engines). A read-only **`view_media`** loop tool (the media
  sibling of `read_file`: `_safe_path`-confined, 4MB-capped, images-only,
  curated into read-only roles) folds a repo image into a follow-up user
  parts message mid-work. **Delivery is verified, never assumed** (decision
  c25): the first media-bearing completion's `prompt_tokens` vs a
  text-only baseline classifies each attachment
  delivered/dropped/unknown/bridged onto omit-when-None `TaskResult.media` —
  zero extra turns, "delivered" never claims *understood* (comprehension is
  the livecheck red-pixel proof's claim). A **media-refusing endpoint
  degrades**: a text-only model 400s on image parts (live-probed, verbatim
  fixture) → the loop flattens to placeholders, retries once, records
  dropped — never a hard-failed run. The **media-comprehension bridge**
  (operator decision c24): with a dual-model config whose second model is
  declared multimodal (`COLLEAGUE_DEEPTHINK_MULTIMODAL` / config.json
  `deepthink.multimodal` — a declaration, never a probe), a text-only main +
  attached media escalates ONE tools-off media-bearing digest to the
  multimodal endpoint (`run_media_bridge` — the deliberate inverse of the
  deepthink flatten; the declared-text-only main wire carries NO parts) and
  folds the description back as one advisory message (`TaskResult.deepthink`
  point=media-bridge, media status `bridged`). Budget accounting counts
  parts (exact counter gets a flattened copy + 260 tokens/part estimate;
  windowing/compaction drop parts whole, never sliced); deepthink digests
  always flatten (a parts list structurally never reaches a text-only wire).
  Live-proven 2026-07-02 (`docs/live-testing.md` rows 15-16): image
  end-to-end PASSED on the served Gemma4 (red-pixel through the real
  `--attach` surface, delivered + answer names red); text-only 27B
  degradation VERIFIED; audio delivery rig-dependent (dropped in the morning
  probe, consumed later the same day — the livecheck grades from evidence
  and honestly SKIPs on regression). **Honest limits:** delivery is
  aggregate per run (not per-part); Gemma4-as-main stays STAGED not flipped
  (96000@128K per-mode overlay recipe; default 27B@48000; gated on the
  external serving-side Gemma tool parser); no media output/video/OCR/URL
  fetch; no automatic task→model media routing (the bridge is ONE declared
  second model on the existing enumerated escalation surface). Runtime-owned
  (all-engines rule). Feature doc: `docs/features/media-input.md`; spec +
  plan: `docs/specs/2026-07-02-hand-colleague-a-screenshot-a-diagram-or-a-voice-n.md`
  and the matching `docs/plans/` file.
- **Memory (best-colleague arc, R1)** — colleague remembers and learns from
  every run. `colleague/memory.py` shells out to the operator-installed
  **eidetic** CLI (the SAME store + scope the operator's remember/recall
  skills use, so colleague's and Claude's lessons are mutually visible);
  allow-list exactly `recall`/`remember`, identity injected, strict no-op when
  the CLI is absent. The runtime (`colleague/loop.py`) does
  **recall-before** (a char-capped prior-lessons block injected as ONE
  advisory message at task start) and **remember-after** (a deterministic
  per-work-item lesson record — status, steps, tool counts, honesty signals —
  upserted at exit, INCOMPLETE runs included: failures are the most valuable
  lessons), recorded on omit-when-None `TaskResult.memory` `{query, recalled,
  injected_chars, lesson_recorded}` (h7: diagnosable, never silent). Arming is
  triple-gated: `config.memory` (default-ON; opt-out `COLLEAGUE_MEMORY=0` /
  config.json `{"memory": false}`) AND the repo carries a `.eidetic/` store
  (a store-less repo — every tmp test repo — is a strict no-op with zero
  subprocess) AND the CLI is installed. **Isolated runs target the OPERATOR
  repo** via `config.memory_root` (execute_work threads it; a lesson written
  to the throwaway worktree would die with it — caught live). `.eidetic/`-only
  working-tree changes do NOT trip the #149 dirty guard (store reinforcement
  is colleague's own state; it still sweeps onto the work branch — lessons
  travel with the work). A model-callable **`memory` loop tool**
  (verb=recall|remember) is offered to every backend; read-only roles get
  recall only (remember is a write-capable shell-out, refused by the
  role-aware executor). All-engines rule throughout.
- **Finish recovery + grounded reads (best-colleague arc, R2)** — a work
  item's findings always survive to the caller. The loop re-parses a finish
  the model emitted as literal tool-call markup in message content (#248 mode
  B), and fires the forced-synthesis path on a **thin** (headline-only, #248
  mode A) or **meta** (describes-a-report-it-never-contains, #231) finish
  after a read-heavy zero-write run — each recovery recorded honestly on
  omit-when-None `TaskResult.finish_recovered` (`"literal-markup"` /
  `"thin-finish-synthesis"` / `"meta-finish-synthesis"`). `read_file` output
  is **line-number grounded** (`cat -n` style, numbering before truncation so
  surviving lines still name the real file line) so cited line numbers are
  copy-derived, not re-counted from drifting context (#240); the numbering is
  display-only and never round-trips into `edit_file` matching.
- **Background one-shot + mesh residency (best-colleague arc, R4/R5,
  decision c17)** — `colleague work --background` detaches the run as a
  session-leader child (`colleague/background.py`, the sanctioned one-shot
  detach: stdio to `.colleague/background/<id>/`, machine-readable start
  payload `{id, pid, log_dir, flight}`, flight plane auto-armed so the run is
  pilotable, `colleague clean` reaps dead-pid residue and never a live run).
  **Residency (appserver mode)**: `colleague/resident/appserver.py` (opt-in
  `[resident]` extra) embeds `agent_lifecycle.runtime` as a library — the
  upstream-ratified consumption mode (`docs/colleague-embed.md` upstream):
  colleague implements the `Harness` Protocol, an inbound mesh Message becomes
  an `execute_work` work item (artifact + gates + rig budget for free), and
  the reply carries the result; supervision failures surface via
  `Supervisor.failure()`. **Trust model (decision c19)**: anyone may ask; a
  non-operator request runs read-only under the `explorer` role or is refused;
  only the operator's identity authorizes writes; in doubt the resident may
  consult peers (a documented follow-up hook). Batch semantics: a detached
  one-shot runs to completion and needs no supervisor (restart-policy `never`
  suffices — recorded for upstream's hard question). Base install stays
  byte-identical: no agent-lifecycle import, no socket, no daemon
  (`test_zero_deps.py` + `test_boundary.py` pins).
- **Auto-split** — when an assignment is too large for one context window,
  colleague recommends splitting it into up to ~4 coherent child assignments
  (via the existing `subagents` tool) instead of degrading lossily or failing.
  The reactive trigger fires at the degradation-exhaustion point (when
  `_MAX_OVERFLOW_RETRIES` are exhausted) and sequences BEFORE escalation, injecting
  one structured recommendation message that points the model at `subagents` with
  concrete per-child budget and child-count numbers; the model decides whether to
  act. A coarser up-front estimate of the task instruction text provides an early
  advisory hint. The actual fan-out + merge reuse `colleague.subagents.make_batch_spawn`
  / `batch_spawn` unchanged (isolated per-child worktrees + sequential merge-subagent).
  Capacity is tunable via `COLLEAGUE_AUTOSPLIT_TARGET` (env, default ≈1M tokens ≈ 4 children)
  and structurally clamped to `MAX_SUBAGENT_FANOUT - 1` (caps unchanged: FANOUT=4, DEPTH=2).
  The feature is runtime-owned (all-engines rule): fires identically for `mock` and
  `vllm-openai`; when no trigger fires it is a strict no-op with TaskResult shape
  unchanged. Specification + plan: `docs/specs/2026-06-05-colleague-auto-splits-a-too-large-assignment-into.md`
  and `docs/plans/2026-06-05-colleague-auto-splits-a-too-large-assignment-into.md`.
- **Handoff** — branch/commit/push + `gh pr create`, gated for offline/CI
  (`colleague/handoff.py`). **Crash-resilient (#162):** the `checkout -B` →
  commit is wrapped so a *catchable* interruption (a `HandoffError`, or a
  Ctrl-C/`KeyboardInterrupt`) before the commit lands restores the operator's
  ref and reaps the orphan `colleague/<id>` branch, then re-raises — the success
  path stays byte-identical. A SIGKILL/OOM/power-loss *inside* the commit is
  uncatchable (git/filesystem durability, not colleague's to guarantee); that
  residual wedge is what the `clean` verb recovers.
- **Write isolation (#196/#201)** — `colleague work`/`drive` (and therefore
  `ask-colleague write --apply`) run the bounded loop inside a throwaway git
  worktree created at the operator's HEAD on the `colleague/<id>` branch
  (`colleague/worktrees.py` `isolation_worktree_add`/`isolation_worktree_remove`,
  wired in `colleague/cli/_commands/work.py` `execute_work` via the `isolate`
  flag). The operator's working tree + checked-out branch are **never touched**,
  a model self-commit *during* the loop lands on `colleague/<id>` (not the
  operator's branch — `handoff.py` `head_sha`/`base_sha` + `_finish_self_committed`
  treat a clean-but-advanced HEAD as committed work, not "no changes"), and two
  concurrent runs get distinct `iso-<id>` worktrees so they can never
  cross-pollute. **Degrades to in-place** when there is no HEAD to isolate from or
  the worktree can't be created (`head_sha` is `None`) — a work item that ran
  before always still runs (h7). `session` keeps its in-place interactive path
  (it calls `execute_work` without `isolate`). The `--allow-dirty` dirty-tree
  guard (#149) is **kept** as the acknowledgement gate; because the isolated run
  works at HEAD, an operator's uncommitted edits are excluded (clean-HEAD
  isolation — commit them first to include them; the q1 decision). Runtime-owned
  (all-engines). Spec + plan:
  `docs/specs/2026-06-16-when-you-delegate-to-colleague-it-never-silently-b.md`
  and `docs/plans/2026-06-16-when-you-delegate-to-colleague-it-never-silently-b.md`.
- **Lint pre-finish gate (#200)** — `colleague work` hands back lint-clean code
  by **default**: after a non-aborted tool loop, before the git handoff, the
  runtime (`colleague/lint.py` + `colleague/loop.py` `_maybe_run_lint_gate`)
  detects the repo's configured Python linters and auto-fixes the work item's
  **changed files**, so a delegated work item no longer needs an integrator
  lint-fix pass. Detection is config-driven and stdlib-only: `[tool.black]`/
  `[tool.isort]`/`[tool.ruff]` in `pyproject.toml` (via `tomllib`) and a
  `[flake8]` section in `.flake8`/`setup.cfg`/`tox.ini` (via `configparser`).
  `run_lint_gate` runs the **fixers** (`isort`, `black`, `ruff check --fix`,
  `ruff format`) then the **reporters** (`flake8`, `ruff check`) on the changed
  `.py` files, returning a `LintReport` (`fixed`/`residual`/`skipped`) recorded
  on `TaskResult.lint_report` (omit-when-None like destination/capacity_decision,
  so a run with no lint is byte-identical). When reporter violations remain after
  a **clean finish**, the loop injects ONE bounded model fix-turn per remaining
  retry (`COLLEAGUE_LINT_FIX_RETRIES`, on `EngineConfig.lint_fix_retries`,
  default 1; 0 = deterministic fixers only) and re-runs the gate; the fix-turn
  reuses `_work_loop` and **saves/restores the work item's terminal summary/status**
  so its own `finish` can't clobber the real result. **Non-blocking** — the
  handoff always proceeds; residual is surfaced on stderr + in the artifact, never
  wedging the work item. **Default-ON with an opt-out**: `--no-lint`,
  `COLLEAGUE_LINT=0`, or `.colleague/config.json` `{"lint": false}` (precedence
  flag > env > config > default-on; the flag is applied post-`resolve()`). The
  curated allow-list is exactly `black`/`isort`/`ruff`/`flake8` — `lint.py` is the
  only new sanctioned `subprocess` consumer (the boundary test enforces this); a
  configured-but-missing binary degrades to a recorded `skipped`, never a crash.
  Runtime-owned (all-engines rule): both backends forward `config.lint` /
  `config.lint_fix_retries` via `ContextControls`; a strict no-op when lint is
  disabled, no files changed, or no linter is configured. **Honest limits:**
  Python-toolchain only (other languages a follow-up); changed-**files** scope
  (a fixer may widen the diff on a touched file in a non-conformant repo);
  standalone `ruff.toml` and non-pyproject black/isort config are not detected in
  v1; it is a best-effort convenience, not a CI lint replacement; the model
  fix-turn needs a live backend (a no-op on `mock`). Spec + plan:
  `docs/specs/2026-06-16-colleague-work-hands-back-lint-clean-code-by-defau.md`
  and `docs/plans/2026-06-16-colleague-work-hands-back-lint-clean-code-by-defau.md`;
  feature doc: `docs/features/lint-gate.md`.
- **Test-integrity gate (#203)** — `colleague work` hands back tests that can
  *actually fail*: a test no longer passes just because it mirrors the
  implementation's own bug (the write/TDD self-confirming false positive). A
  deterministic, code-locked post-loop gate (`colleague/testintegrity.py` +
  `colleague/loop.py` `_maybe_run_test_integrity_gate`, sibling to the lint gate)
  runs the **mirror-detection heuristic** on the work item's **changed files**
  REGARDLESS of model behaviour: it flags the **mirror signature** — an unusual
  identifier (attribute access or string-literal dict key, via stdlib `ast`)
  co-introduced in BOTH a changed test file and the changed module-under-test yet
  found NOWHERE ELSE in the repo (the repo scan prunes `.venv`/`.git`/
  `node_modules`/… vendored trees) — the mechanical signal that a test merely
  mirrors the implementation's own (possibly wrong) assumption about an external
  API. The two real #203 cases: AWS error mapping (`exc.response_error` vs
  botocore's `exc.response`) and Cost Explorer (`TotalEstimate` vs the real key
  `Total`). Recorded on `TaskResult.test_integrity_report` (omit-when-None like
  `lint_report`, so a no-finding run is byte-identical) and surfaced on stderr.
  **Advisory + non-blocking**: never blocks the git handoff, makes no network
  call. **Layered guards:** (1) the deterministic gate (the source of truth); (2)
  a **bounded re-examine turn** (`COLLEAGUE_TESTINTEGRITY_FIX_RETRIES`,
  `EngineConfig.testintegrity_fix_retries`, default 0 = detect-and-record only) —
  on a flagged finding after a clean finish, ONE model turn asks the model to
  verify the symbol against the real API shape and fix it, reusing the lint
  fix-turn pattern (saves/restores the work item's terminal summary/status); (3) a
  **diverse-model reviewer subagent** (`COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL`)
  — the robust guard (a same-model re-examine turn can re-confirm its own mirror),
  auto-spawning a DIFFERENT-model reviewer via the existing subagent launcher (no
  new worktree/merge code, bounded by `MAX_SUBAGENT_FANOUT`) to independently
  re-derive the real API shape, degrading to record-only when unconfigured; (4) a
  model-callable **`check_test_integrity`** loop tool (`colleague/tools.py`,
  all-engines) so a backend MAY self-check mid-work, the gate enforcing
  regardless. **Default-ON with an opt-out** (`COLLEAGUE_TESTINTEGRITY=0` /
  `.colleague/config.json` `{"testintegrity": false}`); a single
  **non-load-bearing** nudge in `_DEFAULT_SYSTEM` mentions test integrity but
  explicitly says the harness gate runs regardless (the operator's "behavior is
  locked in code and harness, not prompts" principle). Runtime-owned (all-engines
  rule): both backends forward `config.testintegrity` /
  `testintegrity_fix_retries` / `testintegrity_reviewer_model` via
  `ContextControls`; a strict no-op when disabled, no files changed, or no mirror
  found. **Honest limits:** a heuristic, not a correctness oracle — it flags a
  *suspicious co-introduced symbol*, never verifies a mock against the live SDK
  (no network, no bundled SDK in v0); Python/`ast`-only (other languages a
  follow-up); test EXECUTION is explicitly NOT the fix (a mirrored test passes, so
  a pytest gate would only re-confirm the bug). Spec + plan:
  `docs/specs/2026-06-16-colleague-s-write-tdd-hands-back-tests-that-can-ac.md`
  and `docs/plans/2026-06-17-colleague-s-write-tdd-hands-back-tests-that-can-ac.md`;
  feature doc: `docs/features/test-integrity.md`.
- **Affected-tests gate (#213)** — `colleague work` runs the tests that
  **transitively import** the work item's changed module(s) before the git
  handoff, so a scoped edit cannot hide a regression in another file the model
  never ran. A deterministic, code-locked post-loop gate
  (`colleague/affectedtests.py` + `colleague/loop.py`
  `_maybe_run_affected_tests_gate`, sibling to the lint and test-integrity
  gates) builds the repo's module import graph with `ast`, collecting **all**
  imports including **function-local / lazy** ones (`ast.walk` over the whole
  tree, not just the module body) — this matters because colleague registers
  every CLI command via a lazy import inside `register()`, so a module-level-only
  graph would dead-end at the `colleague.cli` hub and miss every transitively
  affected test. For each test file it computes the modules reachable within
  `depth` hops (default 3, reaching the #210/t2 motivating case:
  `test_cli_plan.py` reaches the changed `cli_driver.py` at depth 3 via a lazy
  CLI-register import chain) and selects it iff a changed module is in that
  set. The selected set is **capped** (default 20 files); overflow is reported
  honestly (`capped=True`), never silently truncated. Runs `pytest` on the
  selected files; a missing/unrunnable pytest degrades to `status='skipped'`
  with a reason — never a traceback or blocked handoff. On a `failed` status
  after a clean finish, ONE bounded model fix-turn is injected per remaining
  retry (`COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES`, default 1; 0 = detect-and-record
  only), re-running the gate after each. Recorded on
  `TaskResult.affected_tests_report` (omit-when-None). **Advisory +
  non-blocking**: never blocks the git handoff. **Default-ON with an opt-out**:
  `--no-affected-tests`, `COLLEAGUE_AFFECTED_TESTS=0`, or
  `.colleague/config.json` `{"affected_tests": false}` (precedence flag > env >
  config > default-on). The `--test` override bypasses transitive selection and
  uses explicit pytest arguments verbatim. Runtime-owned (all-engines rule):
  both backends forward `config.affected_tests` / `affected_tests_fix_retries` /
  `affected_tests_depth` / `affected_tests_max_files` via `ContextControls`; a
  strict no-op when disabled, no files changed, nothing affected, or pytest is
  unavailable. **Honest limits:** Python/pytest only; best-effort AST-based
  selection (cannot resolve dynamic imports); needs a runnable pytest in the
  isolated worktree else recorded as skipped; the integrator re-run stays the
  backstop. Spec + plan:
  `docs/specs/2026-06-17-colleague-work-runs-the-tests-your-edit-might-have.md`
  and `docs/plans/2026-06-17-colleague-work-runs-the-tests-your-edit-might-have.md`;
  feature doc: `docs/features/affected-tests.md`.
- **Cleanup / reap** — `colleague clean` (`colleague/cli/_commands/clean.py`)
  self-heals a repo a crashed `work` left wedged (#162): a dangling
  `colleague/<id>` ref pointing at a 0-byte loose object breaks `git fetch`.
  The git-touching reap lives in `colleague/handoff.py`
  (`list_colleague_branches` classifies tips corrupt/merged/old/live via
  `for-each-ref` + `cat-file -t`; `reap_colleague_branches` deletes via
  `git update-ref -d`, which works on a corrupt tip; `empty_loose_objects`
  *reports* 0-byte `.git/objects` files) — kept there because `handoff.py` is the
  sanctioned subprocess consumer (`tests/test_boundary.py`), so `clean.py` and the
  doctor check import the helpers and never touch `subprocess` themselves. The
  orphaned-artifact reap (`colleague/artifact.py` `reap_artifacts`) removes 0-byte
  `.colleague/` artifacts + a dangling `last_work`, never a non-empty (gradable)
  one. **Scoped strictly to `colleague/*` refs + `.colleague/` artifacts**
  (never an unrelated branch) and **conservative with `.git/objects`** (reports
  0-byte loose objects + suggests `git prune`, never deletes them). Corrupt is
  always reaped; `--merged` / `--older-than DAYS` are opt-in; `--dry-run` reports
  without changing anything. Surfaced as `colleague clean`, the `ask-colleague
  clean` skill verb, and an **advisory** `doctor` stale-ref check
  (`colleague/oilcheck/stale_refs.py`, `warning` severity — flags a wedged repo,
  never flips report health). Spec + plan:
  `docs/specs/2026-06-06-a-crashed-colleague-work-no-longer-wedges-your-rep.md`
  and `docs/plans/2026-06-06-a-crashed-colleague-work-no-longer-wedges-your-rep.md`.
- **Command templates** — named, parameterized task recipes in
  `.colleague/commands/*.md` (`colleague/commands.py`); expanded into a
  `Task` via `work --command <name> [args…]`.
- **Hooks** — operator-authored shell commands in `.colleague/hooks.json`
  (`colleague/hooks.py`) that fire at `task_start`/`pre_tool`/`post_tool`/
  `finish`; a `pre_tool` hook can allow, deny, or rewrite a tool call.
  A **per-model hooks overlay** at `.colleague/<model>/hooks.json`
  (`<model>` sanitized via `colleague.layers.sanitize_model`, e.g.
  `mmangkad/Qwen3.6-27B-NVFP4` → `mmangkad-Qwen3.6-27B-NVFP4`) is composed
  **ahead of** the base entries for each event — per-model-first precedence
  gives operator-declared model fixes priority via the loop's existing
  first-deny/rewrite-wins rule. Exact-path isolation: model X never loads model
  Y's overlay (no sibling globbing). Strict no-op with no overlay file present.
  No new runtime dep, socket, or daemon. Inspect via
  `colleague hooks list --model <m>` (per-model entries tagged `per-model`).
- **Interactive palette** — `colleague session` (`colleague/cli/_commands/
  session.py`): a foreground TTY loop over the same work path; no parallel
  code path, no daemon. Slash commands come from one `SlashSpec` catalog that
  also derives the `/help` text (single source, drift-tested). On a colour TTY,
  typing `/` opens a **live autocomplete popup** that autofilters slash commands
  as you type and disappears on no-match (Tab/Enter complete, arrows select, Esc
  dismisses) — a stdlib raw-mode reader (`colleague/cli/_commands/
  _session_input.py`, `termios`/`tty`/`select`, no new dep) with a pure-ANSI
  widget (`agentfront.taui.widgets.slash_autocomplete`, imported since #249;
  was `colleague/tui/widgets/slash_autocomplete.py`). Off a colour TTY
  (piped/`--json`/`--no-tui`/Windows) it falls back to plain `input()`,
  byte-identical to before, so agents and pipelines are unaffected. Spec + plan:
  `docs/specs/2026-06-03-colleague-session-shows-a-live-autocomplete-popup.md`
  and `docs/plans/2026-06-03-colleague-session-shows-a-live-autocomplete-popup.md`.
  The first screen is a **delegation cockpit** (#158): two extra `CockpitState`
  panels built by the session optimise for *delegation confidence* — a **Run
  policy** panel (the safety surface: `run_command` gating · file edits ·
  push/PR — honest labels, never "sandboxed") and a **Context** panel (repo,
  branch, working-tree clean/dirty, AGENTS-layer + skill counts, telemetry, and
  `/feedback` availability), both resolved once from existing read-only helpers
  (`policy`/`layers`/`feedback`/`handoff`/`identity`/`telemetry`) at startup +
  after each context-mutating slash action / completed work item — **never on
  the render path**. The work-templates palette is retitled `Work templates`
  (id stays `commands`) and a `Session` panel always answers *what now?* with a
  **suggested next action** (commit-first when dirty, else `type 1 to run
  '<template>'`). Because the Markdown renderer and the TAUI mirror walk all
  panels generically, the agent-facing tiers carry the new panels for free; the
  interactive ANSI tier uses a **borderless, Markdown-feel** renderer
  (`agentfront.taui.render.ansi_flat` since #249, derived from the TAUI mirror so
  it can't drift from Markdown) with **animated emoji state** — a moon-phase glyph
  that cycles by `work.step_count` while a work item runs (motion from real
  steps, no clock/thread) and a steady severity glyph at idle. `/help` is grouped
  by intent (Controls / Inspect / Session) and stays compact; `/help verbose`
  expands every command. The boxed `tui render` ANSI view is unchanged.
  **Agent-native default (#234/#233/#235):** three co-shipped improvements make
  `colleague session` the natural agent-native entry point —
  (1) **Intent routing (#234)** — free-text input is classified by
  `colleague/session_intent.py` `classify_intent(text) -> "work"|"plan"` (stdlib
  `re` only, zero deps) and routed to the right verb without the operator typing a
  subcommand. A `→ work:` / `→ plan:` routing line is logged so the dispatch is
  always visible. Bare numbers and known template names are never reclassified (a
  palette selection is always `work`). The classifier is **high-precision for
  `plan`** — `plan` fires only on an explicit planning trigger, with negative guards
  against the common false positives (e.g. `work on the plan mode feature` stays
  `work`); unmatched or ambiguous input falls through to the `work` default. A
  false-positive *can* still route to `plan`, but never *silently* — the `→ plan:`
  line shows it before the plan path runs, so a misroute is always visible and
  correctable, not hidden. The plan
  branch runs a quick non-interactive spec→plan (`quick=True, workforce=False`) and
  degrades cleanly on a non-live backend (e.g. `mock`) — a `CliError` is surfaced,
  never a crash. **Non-goals:** `colleague work` / `colleague plan` still work for
  scripting and agents that name a subcommand explicitly; intent routing fires ONLY
  on genuine free text in `colleague session`. No new GUI.
  (2) **Session backend override (#234)** — the session resolves its own backend via
  `colleague/config.py` `resolve_session_engine()`: precedence is explicit `--engine`
  flag > `COLLEAGUE_SESSION_ENGINE` env (a session-only override, new) > `COLLEAGUE_ENGINE`
  env > built-in default (`vllm-openai`). There is NO `--session-engine` flag — only the
  env var. `COLLEAGUE_SESSION_ENGINE` lets an operator point the conversational session
  at a different backend than a bare `colleague work` without changing the global default;
  the existing `--engine` flag still overrides everything.
  (3) **Legible action feed (#233)** — the live cockpit feed is now legible at a glance:
  consecutive identical feed lines collapse into a single `<line> ×N` entry instead of
  stacking (e.g. four back-to-back `[culture]` calls become `[culture] agtag issues ×4`);
  the `culture` and `devague` loop tools now surface as `<cli> <args>` / `<move> <args>` in
  the feed target (e.g. `[culture] agtag issues fetch`) instead of a bare `[culture]`
  sentinel; and the per-step hint cap is raised from 48 to 120 characters
  (`_MAX_TARGET = 120` in `colleague/tui/from_work.py`) so long commands are no longer
  cut. The `[tool] summary` feed label is composed in `colleague/tui/from_work.py`
  `work_step`; the consecutive-repeat `×N` collapse lives in the imported
  `agentfront.taui.reducer` (`append_conversation` / `ConversationLine.count`,
  since #249; was `colleague/tui/reducer.py` `_collapse_repeat`). This
  is a pure display change — the underlying `TaskResult` and step trace are unchanged.
  (4) **AgentFront probe reflex (#235)** — `_DEFAULT_SYSTEM` in `colleague/loop.py`
  instructs the backend: before the **first** real use of an unfamiliar CLI or tool in a
  run, read its `learn` / `explain` / `--help` / `--json` affordance first, then act on
  what you found instead of guessing flags or output shape. A tool already used in the
  run needs no re-probe. **Non-goals:** this is advisory and read-only — the reflex
  instructs the model to read a surface, never to install, approve, or trust the tool.
  An enforced harness-level probe is a named follow-up, NOT shipped. Spec + plan:
  `docs/specs/` and `docs/plans/` entries prefixed `2026-06-23-*` (committed on branch
  `spec/agent-native-default`).
  (5) **Mode selection (TUI/TAUI)** — `colleague session` exposes a visible,
  operator-controllable **mode** cycled with **shift-tab** (live ANSI) or the
  keyboard-free **`/mode`** slash: `auto → work → plan → explore → review → auto`
  (`colleague/session_modes.py` is the single-source catalog — `MODES` / `next_mode`
  / `resolve_mode` / `route_for` / `mode_affordance_line`, drift-tested). The active
  mode is written onto `CockpitState.mode` (previously a **dead field** always
  serializing `"planning"`, never set) so every tier shows it — the TAUI JSON mirror
  and Markdown render it directly, and the flat-ANSI status line carries the affordance
  (`mode: [auto] work plan explore review · shift-tab to cycle`). Free-text routing is
  now **mode-aware** (`_work_line` → `route_for`): **`auto` is byte-identical to the
  prior behaviour** (same `classify_intent` call, same `→ work:` / `→ plan:` log);
  `work` / `plan` pin the verb; `explore` / `review` take a **read-only** path; a bare
  number / known template name is still never reclassified (a palette pick is always
  `work`). Shift-tab is decoded in the raw reader as a new `SHIFT_TAB` token → a
  `CYCLE_MODE` sentinel from `_raw_loop` (`colleague/cli/_commands/_session_input.py`),
  every other key path byte-identical. **`/mode`** (in the drift-tested `SlashSpec`
  catalog + `/help`) cycles with no arg, sets by name, and errors with the valid-mode
  hint on a bad name. **explore/review run IN-PLACE under the read-only
  explorer/reviewer role** (`colleague/roles.py`, which withholds `write_file` /
  `edit_file` / `run_command`), so the run provably cannot mutate the tree — no
  commit/branch/PR handoff (`open_pr=False`); review sources its `<base>...HEAD` diff
  operator-side via `handoff.diff_range` because the read-only reviewer cannot run git
  itself. This brings explore/review (previously only `ask-colleague` verbs) to the
  interactive surface for the first time; the parked frame unknown is resolved here
  (in-place under the read-only role, not a throwaway worktree). **Non-goals:** modes
  don't change the `colleague work` / `colleague plan` subcommands; no new
  dep/socket/daemon; the classifier code is unchanged; the shift-tab KEY works only on
  the live-ANSI path (non-TTY uses `/mode`). Spec + plan:
  `docs/specs/2026-06-23-colleague-session-shows-the-mode-you-re-driving-in.md` and
  `docs/plans/2026-06-23-colleague-session-shows-the-mode-you-re-driving-in.md`;
  feature doc: `docs/features/session-modes.md`.
- **Cockpit views (tui)** — `colleague tui` provides three headless views of one
  cockpit state (`TAUIState`): **JSON/TAUI** (programmatic contract + source of
  truth, `tui state`), **ANSI** (visual frame, `tui render` default), and
  **Markdown** (agent-facing readable view — better than raw JSON for an agent to
  glance at, `tui render --format markdown`). The snapshot is a **quad**: `tui
  snapshot` writes `<name>.taui.json` / `<name>.ansi` / `<name>.events.jsonl` /
  `<name>.md`. `tui diagnose` on a quad verifies render faithfulness across the
  captured views; zero findings = faithful. Legacy triples (no `.md`) still read fine.
- **TAUI imported from agentfront (cockpit-on-agentfront, #249)** — the generic
  cockpit (state model, events, reducer, TAUI mirror, the ANSI/flat/Markdown
  renderers, selectors, snapshot/diagnose, widgets, colors, layout) is **imported
  from `agentfront.taui`**, not duplicated in colleague — the sequel to the
  cli-on-agentfront "import, don't duplicate" migration, unblocked by agentfront#43
  (the work-loop cockpit uplift, `SCHEMA_VERSION` `"0.2"`) and agentfront#45 (the
  live-cockpit UI layer: flat renderer + widgets + colors + layout). The whole
  duplicated `colleague/tui/*` package was **deleted**; only two genuinely
  colleague-coupled pieces survive: **`colleague/tui/from_work.py`** (the
  TaskResult/loop-trace → `agentfront.taui` `WorkStep` adapter — it composes the
  `[tool] summary` feed label, the form the `×N` collapse groups on, since
  agentfront's `WorkStep` carries a single `label`) and **`colleague/tui/render/
  driver.py`** (the live raw-terminal `colleague tui live` loop — agentfront ships
  no equivalent raw-input driver). The three non-tui callers
  (`cli/_commands/tui.py`, `_tui_sink.py`, `session.py`) re-point their imports at
  `agentfront.taui.*` and `cockpit.py`/`loop.py` reach the kept adapter. agentfront's
  state is `frozen=True`, so the session/sink rewrote in-place mutation to
  functional `dataclasses.replace` (GAP 11). The conversation feed is now a
  top-level `state.conversation` list (was a `panel.conversation`), so the mirror
  gains `conversation` + `header` keys and several `tui` verbs (`inspect`/`action`/
  `diagnose`/`snapshot`) adopt agentfront's API — the migration is **faithful, not
  byte-identical** (the agentfront API genuinely diverged from colleague's old
  v0.2, e.g. `resolve(state)` takes the state dataclass, `tui action` focuses a
  selector rather than triggering a popup, `Finding` has no `selector`, snapshot
  keys are `json/ansi/events/md`). `tests/test_taui_floor.py` gates the agentfront
  surface colleague depends on; a boundary test
  (`test_colleague_tui_imports_only_the_surviving_adapter_and_driver`) pins that no
  colleague module imports a `colleague.tui.*` module other than the two survivors.
  Consumer-side resume brief + decisions: issue #249. **Honest residual:** the
  `colleague tui live` raw driver and the `from_work` adapter are the one piece the
  generic uplift did not absorb (a possible future agentfront ask); colleague reads
  no agentfront source — the PR touches only the consumer side.
- **Mode profiles** — each work mode (`work`/`plan`/`explore`/`review`) carries
  its own compute/context constraint profile instead of sharing one global knob
  set (`colleague/profiles.py`'s `MODE_PROFILES`: max_steps, context-budget
  fraction, synthesis reserve steps, timeout, fill-line threshold — one explicit
  entry per `session_modes.MODES` name, drift-tested, `auto` is `None` since it
  resolves to a concrete mode first). `colleague/config.py`'s
  `apply_mode_profile` fills only the knobs the operator left untouched, applied
  AFTER `EngineConfig.resolve()`: explicit flag > `COLLEAGUE_*` env > per-model
  overlay (`.colleague/<sanitized-model>/profiles.json`, exact-path) > repo
  overlay (`.colleague/profiles.json`) > built-in catalog profile > untouched. A
  strict no-op with no mode selected (byte-identical config). Wired through
  ONE code path — `colleague/cli/_commands/work.py`'s `execute_work` — shared by
  `colleague work --mode` (validated against `session_modes.MODES`, a typo raises
  a clean choices-shaped error) and the interactive session's mode selection, so
  a session explore/review run gets its profile with zero env vars set.
  `ask-colleague.sh`'s `explore`/`review` adopted the native profile (dropping
  its own caller-side `--max-steps 30` + `COLLEAGUE_SYNTHESIS_RESERVE_STEPS=3`
  overrides in favor of `--mode`), with a stale-CLI fallback (a `--help`
  substring probe) for a colleague checkout that predates `--mode`. **Honest
  limits:** the per-mode numbers are conservative defaults pending live tuning,
  not tuned constants; `colleague plan run` itself is not profiled (it drives
  the model via `Engine.make_complete`, outside `execute_work`). Feature doc:
  `docs/features/mode-profiles.md`.
- **Context budget / graceful degradation** — the bounded tool-loop windows its
  running message history to a configurable token budget before each model turn
  (`colleague/context.py` + `colleague/loop.py` `_complete_with_degradation`)
  and, on a detected context-overflow **or request-timeout** error
  (classified by `colleague/context.py` `classify_degradable`), trims history
  harder and retries a bounded number of times before preserving a readable
  partial result — so a multi-file work item on a small-context model degrades
  instead of hard-failing. A **request timeout** (#154) is degraded too — a
  bloated context makes each completion slow, so trimming can let the next one
  beat the timeout — but it is capped lower than an overflow
  (`_MAX_TIMEOUT_RETRIES` = 1 vs `_MAX_OVERFLOW_RETRIES` = 3) because each timeout
  attempt costs a full `COLLEAGUE_TIMEOUT` window (default 120s, env
  `COLLEAGUE_TIMEOUT`; surfaced in the vLLM `_post_json` legible-timeout message)
  whereas an overflow 400 is instant. On an exhausted give-up the floored budget
  is carried into the next turn so the auto-split/**INCOMPLETE** recommendation
  the loop injects runs against the small window (not the full one that just
  failed) and can actually complete. The
  knob is `COLLEAGUE_CONTEXT_BUDGET` (tokens, on `EngineConfig.context_budget_tokens`,
  default 48000, env `COLLEAGUE_CONTEXT_BUDGET`) — sized for the 64K (65536-token)
  window the lobes rig actually serves the default 27B at (probed 2026-07-02),
  leaving headroom for the completion; raise it for a wider-window model (the
  rig's Gemma4-12B serves 128K → 96000). A companion knob caps each tool result fed back to the model:
  `COLLEAGUE_MAX_OUTPUT_CHARS` (chars, on `EngineConfig.max_output_chars`, default
  25000 — scaled with the budget, ~13% of window, still above the old hardcoded
  20000); both resolve via the same
  `EngineConfig.resolve` precedence and the backends forward them to the loop
  identically (all-engines rule). The work step budget default is
  `COLLEAGUE_MAX_STEPS` (`EngineConfig.max_steps`, default 40). Token counting goes
  through a pluggable `count_tokens` seam — the vLLM backend counts exactly via the
  server's `/tokenize` endpoint, falling back to a zero-dep char heuristic
  (`count_tokens_chars`) when `/tokenize` is absent. **Honest limits:** the budget is best-effort exact
  (exact via `/tokenize`, char-approximate fallback) — NO third-party tokenizer
  library is bundled (`dependencies = []` holds); windowing DROPS oldest history
  with a placeholder note — this lossy windowing is now the **fallback floor**
  beneath the v1 fill-line `compact` move (the **Capacity standard** below, #156),
  which replaces the elided turns with a model-authored summary, falling back to
  this drop-oldest windowing only when the summary turn itself cannot fit; there is
  **no multi-model router / routing policy** (an overflow never switches models); retries
  are bounded (termination preserved). A **request timeout against a genuinely
  unreachable/stuck server still wastes up to `_MAX_TIMEOUT_RETRIES` bounded
  retries** (each a full `COLLEAGUE_TIMEOUT` window) before the partial is
  preserved — shrinking only helps a context-bloat timeout, not a dead server,
  which is why the timeout cap is deliberately low (#154). **Adaptive
  backpressure (#255)** measures per-turn wall-clock latency
  (`colleague/backpressure.py`'s pure `assess`/`shrink_fraction`/
  `throttled_concurrency` classifier + `colleague/loop.py`'s `_timed_complete`/
  `_record_turn_latency`) and, when the rolling mean drifts toward
  `config.timeout`, proactively shrinks the *next* turn's window and throttles
  subagent fan-out (composing with, never replacing, the reactive
  shrink-on-overflow/timeout retry above) — recording ONE
  `capacity_warning` advisory + a phase-notice line on the first departure from
  CLEAR, and restoring the operator's configured concurrency automatically once
  latency clears. Dormant (no clock, no shrink, no throttle) unless
  `request_timeout` is set; never switches model or backend. **Timeout
  survival (#268):** the per-turn request timeout is additionally raised ONCE
  per work item, bounded ×2 (`_make_timeout_escalator` via
  `ContextControls.from_config`, all-engines — the engine closure reads
  `config.timeout` per call so the raise reaches the very next attempt),
  triggered by whichever fires first: the backpressure departure-from-CLEAR
  advisory (proactive) or a timeout-classified degraded retry (reactive, so the
  single #154 retry runs with real headroom instead of hitting the same wall).
  Recorded on `capacity_warning` + a phase notice; subsequent backpressure
  classification runs against the raised cap; documented worst case on a dead
  server grows to `timeout + 2×timeout` and no further. An **engine-failure
  abort now sweeps the iso worktree's WIP** onto the `colleague/<id>` branch
  (the #222 sweep extended to the `except Exception` path in `execute_work`)
  and the error hint names the surviving branch; the effective timeout + its
  source surface in `colleague doctor` (`provider_timeout`), `work --help`,
  and `colleague learn`. Feature doc:
  `docs/features/backpressure.md`. Runtime-owned
  (all-engines rule): the feature fires identically for every backend.
  Specification + plan:
  `docs/specs/2026-06-02-colleague-drives-degrade-gracefully-when-a-task.md`
  and `docs/plans/2026-06-02-colleague-drives-degrade-gracefully-when-a-task.md`.
- **Capacity standard / fill-line decision (v1, #156)** — colleague holds an
  opinion about its own context capacity. When a turn's prompt tokens cross a
  tunable fraction of the context budget (`COLLEAGUE_FILLLINE_THRESHOLD`, on
  `EngineConfig.fillline_threshold`, default `0.8`), the loop
  (`colleague/loop.py` + the pure helpers in `colleague/fillline.py`) injects ONE
  structured decision prompt naming three moves + the capacity numbers; the model
  **declares one by its next action** and the runtime records it on
  `TaskResult.capacity_decision` (`{kind, reason}`, omit-when-None like
  destination/announcement) and acts:
  - **compact** — a bounded model-authored summary turn (`_compact_history` +
    `fillline.apply_compaction`) replaces the working history, preserving the head
    `messages[:2]`; on its own overflow it falls back to lossy windowing (the
    documented floor — degradation extended, not replaced). This is the deliberate
    **v0→v1 graduation**: it supersedes the old "no LLM-generated summary in v0"
    line, recorded honestly, never a silent breach.
  - **split** — a `subagents` call routes through the existing auto-split fan-out
    machinery unchanged (no new worktree/merge code).
  - **finish-with-handoff** — a `finish` call records the continuation summary via
    the existing preserve-partial path.
  A separate **warn-only "too big for one repo" caller warning**
  (`TaskResult.capacity_warning`, set from the up-front coarse complexity assessment
  in `colleague/capacity.py` — deps/folders/files + an instruction token estimate)
  fires when an assignment exceeds even the in-repo split capacity; the work CLI
  emits it to stderr and it is recorded in the artifact. Colleague performs **no
  cross-repo write** (neighbours stay read-only; the operator splits across
  repos/instances). Runtime-owned (all-engines rule): fires identically for `mock`
  and `vllm-openai`, advisory/never-forced, zero-dep, and a strict no-op
  (byte-identical `TaskResult`) when no fill-line event occurs. The fill-line fires
  **at most once per work item** (the singular `capacity_decision`); repeated
  compaction is a documented follow-up. Specification + plan:
  `docs/specs/2026-06-06-colleague-holds-a-standard-for-its-own-capacity-it.md`
  and `docs/plans/2026-06-06-colleague-holds-a-standard-for-its-own-capacity-it.md`.
- **Config resolution** — `colleague/configdir.py`: repo-level
  `.colleague/` overrides user-level `~/.colleague/`. The engine endpoint has a
  **persistent config-file override** at `.colleague/config.json`
  (`colleague/config.py` `load_config_file` → `EngineConfig.resolve(repo_path=…)`):
  the `base_url`/`api_key`/`model` keys feed in as the resolution *default*, so
  the precedence is explicit flag > `COLLEAGUE_*`/`OPENAI_*` env > `.colleague/config.json`
  > built-in default. This is the durable way to point colleague at another
  OpenAI-compatible provider (replace the local vLLM) without re-passing flags or
  env vars each run; stdlib `json` only, malformed/absent file is a strict no-op.
  Wired into the `work`/`session`/`learn-from` paths (each passes `repo_path`).
  `colleague doctor --repo <path>` (and `--probe`) now **reflect**
  `.colleague/config.json`: an optional `repo_path` is threaded through
  `colleague/oilcheck/__init__.py` `diagnose` to the **provider** and
  **reachability** check-groups (`EngineConfig.resolve(repo_path=…)`); all other
  check-groups stay env/defaults only. The resolved config is also viewable via
  the **`colleague config show`** verb (`colleague/cli/_commands/config.py`;
  `config show [--repo PATH] [--json]` + `config overview`), which reuses
  `EngineConfig.resolve(repo_path=…).to_dict()` so the `api_key` is redacted.
  **Honest limit:** the `--repo` default is the cwd, so a bare `colleague doctor`
  outside a repo (or in one without `.colleague/config.json`) is unchanged
  (env + defaults only).
- **Rename back-compat (`convertible` → `colleague`)** — the project was renamed
  from *convertible*. The import package, the `colleague`/`clg` commands, the
  `.colleague/` config dir, and the `COLLEAGUE_*` env vars are the canonical
  names; the PyPI distribution is `colleague` (no longer `convertible-cli`). The
  legacy names are still honored as **deprecated read fallbacks**: `.convertible/`
  config/artifact dirs (read-only, writes go to `.colleague/`; see
  `configdir.LEGACY_CONFIG_DIR_NAME`, `artifact.artifact_read_dirs`,
  `layers._LEGACY_USER_CONFIG_SUBDIR`) and `CONVERTIBLE_*` env vars (each read
  prefers `COLLEAGUE_*` then falls back to `CONVERTIBLE_*`). `identity_env`
  emits **both** `COLLEAGUE_IDENTITY` and `CONVERTIBLE_IDENTITY` so sibling
  CLIs that only know the old name keep working. Historical artifacts
  (`CHANGELOG.md`, `docs/specs/`, `docs/plans/`, `.devague/`, dated drive-notes)
  intentionally keep the old name. The SonarCloud `projectKey` in
  `sonar-project.properties` is `agentculture_colleague`; that is an EXTERNAL
  identity, so the SonarCloud project itself must be re-keyed/recreated to match
  or coverage uploads 404 until it is.
- **Layered per-model config** — `colleague/layers.py`: AGENTS instructions
  (`AGENTS.md` → `AGENTS.colleague.md` → `AGENTS.colleague.<model>.md`, at
  the repo root with a `~/.colleague/` fallback) and skills
  (`.colleague/skills/*.md` → `.colleague/<model>/skills/*.md`) compose into
  the backend system prompt. Resolution builds exact paths for the current model
  and never globs sibling models — per-model isolation is structural. Injected
  once on the `Engine` base class (`system_prompt()`), so every backend inherits
  it (all-engines rule). Surfaced via the `agents` / `skills` introspection
  nouns. The companion **per-model hooks overlay** (`.colleague/<model>/hooks.json`)
  extends this isolation to the hooks layer — see the Hooks bullet above.
  **MCP layering is not built** — colleague reads no `mcp.json` and registers
  no external MCP tools; a live MCP *client* is a re-spec (see scope below). The
  `colleague mcp serve` verb is the unrelated MCP **server** bonus (a
  single-dispatch surface rendered from the same App registry — see the **CLI
  surface (cli-on-agentfront)** part above), not MCP-client layering.
- **Learn-from** — colleague grows its skill set by **learning from a peer
  agent** (`colleague/learn_from.py` + `colleague/cli/_commands/learn_from.py`).
  `colleague learn-from <source>` reads an external agent's skills and adapts
  them into colleague's own `.colleague/skills/*.md` (the write side of the
  read-only `skills` noun). The first/only source is `claude` — Claude Code's
  `.claude/skills/<name>/SKILL.md` — behind a `_SOURCES` registry so future minds
  slot in without a CLI change. **Two stages:** (1) a deterministic, stdlib-only
  **copy** (strip the SKILL.md YAML frontmatter incl. `description: >` block
  scalars, fold the description into a leading summary line so
  `compose_skills`/`_first_summary_line` shows it, stamp a `<!-- learned-from:
  …; adapt: pending -->` provenance marker, keep the body; idempotent; a skill's
  `scripts/` are left in place, never copied); then (2) an optional, **backend-
  driven LLM review-and-adapt** pass (skip with `--copy-only`) that drives the
  configured engine over each written skill **in the working tree with no git
  handoff/branch** (reusing `engine.work`) to fix paths/locations and Claude-isms
  for colleague's tool surface, flipping the marker to `adapt: claude->colleague`,
  and **degrades to copy-only** when no backend is reachable. Safety: a
  colleague-owned skill that differs updates only with `--force`; a hand-authored
  doc (no marker) is `protected` unless `--force`; `--dry-run` previews and writes
  nothing. **Honest limit:** colleague *loads* skills as instructional text, it
  does **not execute** them — a script/Skill-tool/slash-command-dependent skill
  maps only partially (surfaced per skill as `runnable_estimate`). Invokable in
  both modes: the `learn-from` CLI verb (agent/markdown) and the `/learn-from`
  session slash (interactive, `--copy-only`). Zero new runtime deps. Spec + plan:
  `docs/specs/2026-06-06-colleague-learns-from-others-starting-with-claude.md`
  and `docs/plans/2026-06-06-colleague-learns-from-others-starting-with-claude.md`;
  feature doc: `docs/features/learn-from.md`.
- **Piloting / flight** — `colleague work --watch` arms a file-based flight-control
  plane (`.colleague/flight/<id>.*`) the bounded loop appends a live feed to and
  reads stop/guidance from at each turn boundary; pilot it via the `colleague
  flight` noun (`status`/`guide`/`stop`/`list`/`overview`) and the `ask-colleague
  monitor`/`guide`/`stop` verbs. Cooperative (not preemptive), runtime-owned
  (all-engines), strict no-op when not a flight, caller-symmetric + depth-capped,
  no daemon/socket/deps. Spec + plan:
  `docs/specs/2026-06-13-colleague-flights-are-now-piloted-after-ask-collea.md`
  and `docs/plans/2026-06-13-colleague-flights-are-now-piloted-after-ask-collea.md`.
- **Explore never wastes a run** — a read-only explore/drive that exhausts its step
  budget is never a silent no-result. Four threads (issues #194/#192/#191/#190/#188):
  (1) **Forced synthesis (#191)** — when `_work_loop` exits via `_EXIT_BUDGET`/
  `_EXIT_STOPPED` having read context (`step_count > 0`) but never produced a usable
  summary, `colleague/loop.py` `_maybe_force_synthesis` injects ONE no-tools turn
  ("out of steps; answer now from what you've read") and uses its text as the summary,
  reusing `_complete_with_degradation` (windowed) and mirroring the
  `_final_degraded_attempt` retry-cap precedent; `NO_RESULT_PRODUCED` is reached only
  when even that turn is empty. **Extended for review (#202/#197):**
  `_maybe_force_synthesis` *also* fires on the explicit `_EXIT_FINISHED` path when a
  `finish` carries an empty/whitespace summary (a review's deliverable IS the text, so
  a blank finish was a silent `status: ok` no-op) — it forces the answer from what was
  read instead of falling back to the last planning line; a finish with a real summary
  is byte-identical. And a `COLLEAGUE_SYNTHESIS_RESERVE_STEPS` knob
  (`EngineConfig.synthesis_reserve_steps`, `ContextControls.synthesis_reserve`,
  default 0 = byte-identical, forwarded by both backends) holds steps back from the
  reading budget so a big-diff review's verdict turn runs with fresher context;
  `ask-colleague review` defaults to `--max-steps 30` and sets the reserve to 3.
  (2) **Honest status (#192)** — any non-`_EXIT_FINISHED`
  outcome reports `status: incomplete` (`colleague/contract.py` `INCOMPLETE`) with a
  non-zero `work`/`drive` exit (code 2; `ok`→0, `error`→1), so a caller branches on
  status/exit without sentinel string-matching; `ask-colleague.sh` suppresses the
  success-shaped `grade:` footer and warns on a `NO_RESULT_PRODUCED` summary.
  (3) **Advisory fan-out (#188)** — once a survey reads more than
  `COLLEAGUE_FANOUT_FILES` files (`EngineConfig.fanout_files`, default 12, env-tunable),
  `_maybe_offer_mapping_fanout` injects ONE advisory recommendation
  (`colleague/autosplit.py` `build_mapping_fanout_recommendation`) pointing the model at
  the existing `subagents` tool with a per-folder partition; backend-judged, reuses
  `make_batch_spawn`/`batch_spawn` with **no new worktree/merge code** (read-only
  children write nothing, so the merge child no-ops — the FANOUT-slot optimisation is a
  documented follow-up), strict no-op when dormant/under-threshold/already-offered.
  (4) **Loud partials (#194)** — `ask-colleague explore` defaults to `--max-steps 30`
  (write/review stay 20; an explicit flag overrides either), and the partial warning
  names the reached step count + a concrete larger `--max-steps`. **Grep-free (#190):**
  `ask-colleague.sh`'s uv-fallback resolver is pure-bash (`_pyproject_is_colleague`),
  resolving a checkout even on a PATH with no `grep`. Runtime-owned (all-engines);
  forced synthesis + incomplete status + fan-out fire identically for `mock` and
  `vllm-openai`. Spec + plan:
  `docs/specs/2026-06-14-colleague-never-wastes-an-explore-a-read-only-expl.md`
  and `docs/plans/2026-06-14-colleague-never-wastes-an-explore-a-read-only-expl.md`.
- **Colleague finishes what it starts** — two run-completion features born from a
  live dogfood stall (a served 27B narrated `"Let me check:"` with no tool call and
  ended after editing 1 of 4 files; the loop treats a no-tool-call turn as an
  implicit stop):
  - **continue-working** — the single finish-nudge (`_handle_no_tool_turn` /
    `_FINISH_NUDGE`, #142) becomes a **configurable cap**:
    `COLLEAGUE_MAX_CONTINUE_NUDGES` (`EngineConfig.max_continue_nudges`, default 2,
    lifting the hardcoded `_MAX_FINISH_NUDGES = 1`), threaded
    `config → ContextControls → _Work` and consulted in `_handle_no_tool_turn`. A
    stalled run now resumes **past the first stall** instead of stopping after one
    nudge. Forwarded by every backend (all-engines rule); the direct `run()` path
    falls back to `_MAX_FINISH_NUDGES` (back-compat / strict no-op). Termination
    stays bounded by the cap **plus** the existing step/token budget; an explicit
    `finish` still ends immediately (no nudge). The `_FINISH_NUDGE` text already
    said "continue … or call `finish`", so only the cap changed.
  - **auto-compact-on-finish** — a context-rich stop no longer pre-empts the #191
    forced-synthesis. `_handle_no_tool_turn` used to pre-set the trailing prose as
    the summary, which made `_maybe_force_synthesis` no-op; it now leaves the
    summary empty so #191 produces a clean summary from what was read (the prose
    survives only as the `_last_substantive` floor). The #156 fill-line compaction
    summary is captured on a dedicated `_compacted_summary` cell (a later stall
    can't overwrite it, unlike `_last_substantive`) and used as the **fallback**
    clean summary at a stop/budget exit. Summary resolution lives in one helper
    (`colleague/loop.py` `_resolve_terminal_summary`) with an explicit precedence:
    finish summary → **fresh forced synthesis (#191)** → compaction self-summary
    fallback → last-substantive → `NO_RESULT_PRODUCED`. Synthesis runs **before**
    the compaction fallback so a run that compacted and then *kept working* returns a
    summary reflecting the post-compaction work, never the stale pre-work compaction
    note (the Qodo PR #198 stale-compaction-summary fix — an earlier draft preferred
    the compaction summary over synthesis, which was the bug). **Honest scope:** the *"free context to continue"*
    half is already delivered by existing windowing (the hard floor) + the #156
    fill-line (summarize-as-you-grow), which the now-longer continued runs naturally
    trigger — so this adds **no new compaction-firing code**, only makes the clean
    summary survive to the exit. Forced-synthesis (#191) stays the floor for a
    never-compacted run; an explicit clean `finish` keeps the model's own summary;
    a no-content / `step_count == 0` stop is **byte-identical**. **Residual limit:**
    a *short* run (one that never crossed the fill line) that stalls to a stop still
    falls back to its trailing prose when forced-synthesis itself yields nothing — a
    documented follow-up; continue-working's extra nudges are what reduce those
    short-run stops. Runtime-owned (all-engines): both features fire identically for
    `mock` and `vllm-openai`. Spec + plan:
    `docs/specs/2026-06-15-colleague-finishes-what-it-starts-a-run-that-stall.md`
    and `docs/plans/2026-06-15-colleague-finishes-what-it-starts-a-run-that-stall.md`.
- **Plan mode** — colleague plans a complex task itself, the same arc as the
  `/think` → `/spec-to-plan` → `/assign-to-workforce` skills but with **colleague
  as the planning mind** (a different mind from the requester — `/think` keeps
  Claude as planner; the diversity is the point). A new `colleague/plan/`
  subpackage: a native frame model (`frame.py`), the required-kinds convergence
  gate (`convergence.py`), file-based gate checkpoints (`checkpoint.py`), a
  same-model critic reviewer (`reviewer.py`), the spec/plan/workforce stages
  (`spec_stage.py` per-item micro-cycle, `plan_stage.py` items + deterministic
  waves, `workforce.py` fan-out reusing `colleague.subagents`
  `make_batch_spawn`/`batch_spawn` unchanged), the auto-trigger + pushback
  judgment (`trigger.py`/`pushback.py`), and the `orchestrator.py` that drives
  spec→plan→workforce gated at every step (**never self-confirms**;
  planning/implementation never runs before the spec converges). Surfaced as the
  **`colleague plan`** verb (`plan run`/`status`/`overview`; operator gates each
  item, `--yes` auto-confirms, `--review` runs the critic) and the
  **`ask-colleague plan`** skill verb. Engine-agnostic (the orchestrator takes
  injected seams; fires identically for `mock` and `vllm-openai`); native-first
  and **zero-deps** (no devague dependency). A public **`Engine.make_complete`**
  one-shot completion seam lets the verb drive the model outside the work loop
  (`mock` inherits the default — plan mode needs a live backend). The auto-trigger
  is opt-in via `COLLEAGUE_PLAN_OFFER_TOKENS` (`EngineConfig.plan_offer_tokens`,
  default 0 = dormant, strict no-op). Runtime-owned (all-engines). Spec + plan:
  `docs/specs/2026-06-15-colleague-has-a-plan-mode-hand-it-a-vague-or-overs.md`
  and `docs/plans/2026-06-15-colleague-has-a-plan-mode-hand-it-a-vague-or-overs.md`.
  **Degradation-aware proposals (#210/#199/#204, smaller "plan jumps"):** the
  proposal seams (`colleague/plan/cli_driver.py`) used to ask for everything in
  one shot and read `resp.content` only, so a *reasoning* served backend that
  emits its answer into `reasoning` with empty `content` failed with `no JSON
  object found` — plan mode was non-functional on the reference 27B. Proposals now
  route through `robust_simple_complete`: a forced no-thinking JSON follow-up on
  empty content, then a `resp.reasoning` recovery, then a `classify_degradable`
  timeout/overflow shrink-retry (mirroring the loop's `_MAX_TIMEOUT_RETRIES`/
  `_MAX_OVERFLOW_RETRIES`). The jumps are smaller — claims in two calls
  (mandatory kinds, then requirements+honesty), plan items in bounded
  deduped-by-id batches (≤5 items, ≤4 batches; a bad chunk is tolerated, a total
  failure still raises the clean `unusable plan proposal`). `_extract_json_object`
  prefers the object carrying the expected key (`claims`/`items`, so a stray
  prose `{...}` can't shadow the payload) and **repairs a truncated object** (the
  live 27B dropped its final `}`; it appends the implied closers, retreating to
  the last complete element on a mid-token cut). A balanced response is
  byte-identical through all of it. The **spec-less `--quick`/`--no-spec` path**
  (#199) skips the per-claim spec micro-cycle and plans directly from the request,
  still operator-gated at the plan level. The public `Engine.make_complete` seam
  (#204) is pinned by `tests/test_engine_make_complete.py`. Live-validated: the
  27B that failed at the claims stage now yields 11 claims + 8 honesty conditions
  and 4 plan items end-to-end. Feature doc:
  `docs/features/plan-mode.md`; spec + plan:
  `docs/specs/2026-06-17-colleague-plan-mode-now-drives-smaller-degradation.md`
  and `docs/plans/2026-06-17-colleague-plan-mode-now-drives-smaller-degradation.md`.
  Honest limits: the verb still needs a live backend (`mock` inherits
  `make_complete`'s `NotImplementedError`); chunking adds model calls (bounded);
  JSON repair is best-effort (structural truncation, not arbitrary malformed
  JSON); the interactive cross-invocation `plan continue` resume remains a
  documented follow-up.
  **27B-further + honest failure (#215/#224/#226):** the v1.20.0 wall moved off
  "no JSON" onto honesty — the combined requirements+honesty call returned
  claims but **zero honesty conditions**, so every confirmed spec-affecting
  claim failed the gate. `make_propose_claims` now runs a **dedicated
  honesty-only pass** after the claim calls (a single `{honesty:[...]}` batch
  call + a bounded per-claim fallback, cap `_MAX_HONESTY_FALLBACK=8`, all via
  `robust_simple_complete`; keyed on `claim_id` with freshly-minted unique ids
  so a model reusing `"h1"` isn't dropped). A new **`--no-workforce`** plan-only
  mode (`run_plan_mode(workforce=False)`) stops after gating plan items —
  delivering the spec+plan with no wave, no `batch_spawn`, no subagent worktree
  (sidesteps the Wall-2 120s workforce timeout) — default byte-identical. The
  spec gate now **names the real gap**: both `_render_run` and `_run_payload`
  surface `claims_missing_honesty`, never a silent `missing: (none)` (#224);
  `ask-colleague plan` forwards `--quick`/`--no-workforce`/`--timeout` with an
  honest remediation hint on failure (no auto-degrade), and `ask-colleague.sh`
  follows its own `error:`/`hint:` + structured-`--json` contract (#226).
  **Honest limit:** the honesty pass gets a weak model *further*, it does not
  *guarantee* convergence — honesty is never synthesized to force a pass; a
  model that still produces none fails honestly with the #224 reason. The
  convergence rule (honesty mandatory) is unchanged. Spec + plan:
  `docs/specs/2026-06-19-colleague-plan-mode-gets-the-served-27b-further-an.md`
  and `docs/plans/2026-06-19-colleague-plan-mode-gets-the-served-27b-further-an.md`.
- **CLI surface (cli-on-agentfront)** — colleague's agent-first CLI is
  **rendered from one imported agentfront `App` registry** instead of
  hand-maintained argparse scaffolding ("import, don't duplicate").
  `colleague/cli/_app.py` `build_app()` auto-discovers every verb module's
  `register_into(app)` hook; `colleague/cli/__init__.py` `main()` dispatches argv
  against that App via agentfront's `run_cli`. The generic agent-first machinery
  — nested noun/verb dispatch, structured `{code, message, remediation}` errors,
  per-verb `--json`, the bare-invocation no-command handler, `KeyboardInterrupt`
  → 130 — now comes from agentfront's one published consumer-CLI API (agentfront
  is the one sanctioned base dep; see the conventions below). Each verb is a
  **rendered tool** (`app.tool`, exit-0/raise, read-only inspection) or a **host
  command** (`app.add_command`, custom exit codes / streaming / blocking
  server-TTY — `work`/`drive`/`plan`/`session`/`tui`/`flight`/`clean`/
  `learn-from`/`promote`/`mcp`). The four reserved meta-verbs (`doctor`/
  `overview`/`learn`/`explain`) stay colleague-owned via a retained-legacy-parser
  shim in `main()`. Because every operation lives in that one registry, colleague
  also gets a **single-dispatch MCP server** (one `run` tool whose description
  embeds the command catalog, per #246 — `colleague mcp serve`, behind the
  opt-in `colleague[mcp]` extra; no socket/daemon code in colleague, the stdio
  loop is agentfront's `serve_stdio`) and an HTTP app **for free** from the same
  registry — the Cowork bonus. `tests/test_cross_surface_parity.py` proves
  catalog-level set-equality (registry tools == MCP catalog == `learn` catalog;
  host commands absent from all three). **Honest limit:** the migration carries
  *both* paths during transition — net `colleague/cli/` LOC is up (+1468/−445),
  the legacy `_build_parser` (~154 lines) survives only as the meta-verb/session/
  doctor backend, and the raw-LOC maintainer win is deferred to the follow-up
  that fully retires it; the win *today* is structural (one org-wide agent-first
  source + the free MCP/HTTP bonus). Spec + plan:
  `docs/specs/2026-06-25-colleague-s-agent-first-cli-is-rendered-from-an-im.md`
  and `docs/plans/2026-06-26-colleague-s-agent-first-cli-is-rendered-from-an-im.md`;
  feature doc: `docs/features/cli-on-agentfront.md`.

The buildable spec and plan this implementation converged from live in
[`docs/specs/`](docs/specs/) and [`docs/plans/`](docs/plans/) (authored via the
`/think` → `/spec-to-plan` devague workflow).

## v1 scope (hold this line)

**v0 → v1 graduation (#156).** colleague has graduated from v0 to v1: it now holds
an opinion about its own context capacity (the **Capacity standard** above). Two
deliberate, recorded convention changes have landed since v0 — never silent
breaches: (1) the v0 rule *"no LLM-generated summary"* is **intentionally
superseded** by the fill-line `compact` move (a model-authored self-summary), with
lossy windowing retained as the documented fallback floor; and (2) the
*"zero base dependencies"* rule is **intentionally superseded** by **one**
sanctioned base dep, `agentfront` (the **CLI surface (cli-on-agentfront)** part
above) — justified because agentfront's core is pure-stdlib (a base install still
pulls zero third-party transitive deps) and it is the org's shared agent-first CLI
standard; the MCP SDK stays an opt-in `[mcp]` extra and `test_zero_deps.py` becomes
an allow-list of exactly agentfront. Everything else below still holds: the
**no-second-base-dep** / no-socket / no-daemon conventions, the all-engines rule,
and the out-of-scope list (a self-summary is NOT a multi-model router, sandbox, or
daemon; the MCP *server* bonus runs no colleague-owned daemon).

In scope: the runtime, the entry-point plugin contract, exactly two backends
(`mock`, `vllm-openai`), the git/PR handoff, command templates, lifecycle
hooks, the foreground interactive palette, layered per-model AGENTS/skills
config (`colleague/layers.py`), telemetry — opt-in OpenTelemetry traces +
metrics (`colleague/telemetry/`), with the SDK as an optional `[otel]` extra —
the **mesh-member integration**: process-level identity (`colleague/identity.py`),
read-only neighbour clones (`colleague/neighbours.py`), and the curated
`culture` loop tool (`colleague/culture.py`; allow-list: `agtag`, `devex`) —
and the **destination/`devague` tool** (`colleague/devague.py`; curated allow-list
excluding `confirm`/`reject`/`export`), which lets a backend set and converge a
goal-frame when a task warrants one, work toward it, and declare the announcement
on arrival — and the **approval gate** (`colleague/policy.py`):
`.colleague/approvals.json` gating `run_command` CLIs by program token and
hook/command files by checksum — and the **subagent tools** (`subagent` + `subagents`)
(`colleague/subagents.py` + `colleague/worktrees.py` + `colleague/tools.py`):
backend-judged, optional in-process child work items with backend/model switch, depth
cap (2), fan-out cap (4), no per-subagent handoff, isolated per-child git
worktrees, opt-in concurrency via `COLLEAGUE_SUBAGENT_CONCURRENCY` (default 1 =
byte-identical sequential) — and the **work statistics + feedback loop** (the
ROI loop):
always-on per-work-item `WorkStats` in the artifact (`colleague/contract.py` +
`colleague/loop.py`) and a single-record-per-work-item feedback store
(`colleague/feedback.py`) surfaced as `colleague feedback` and the
`ask-colleague feedback` skill verb — and the **capacity standard** (v1, #156):
the proactive fill-line decision (compact | split | finish-with-handoff,
`colleague/fillline.py`), self-compaction with lossy windowing as the fallback
floor, the coarse complexity assessment (`colleague/capacity.py`), and the
warn-only "too big for one repo" caller warning — and the **lint pre-finish gate**
(#200): `colleague/lint.py` + `colleague/loop.py` detect the repo's configured
Python linters and auto-fix the work item's changed files before handoff
(default-ON with a `--no-lint` opt-out), so delegated work lands lint-clean —
and the **test-integrity gate** (#203): `colleague/testintegrity.py` +
`colleague/loop.py` flag the *mirror signature* (a novel identifier co-introduced
in both a changed test and the module-under-test, found nowhere else) on the
changed files after the loop, with a bounded re-examine turn + a diverse-model
reviewer subagent + a model-callable `check_test_integrity` tool (default-ON,
advisory/non-blocking), so a delegated test can no longer pass merely by mirroring
the implementation's own bug — and the **affected-tests gate** (#213):
`colleague/affectedtests.py` + `colleague/loop.py` run the tests that
transitively import the changed module(s) (bounded-depth AST reverse-import
walk, default depth 3, capped at 20 files) before handoff, with a bounded
model fix-turn on failure (`COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES`, default 1),
so a scoped edit cannot hide a regression in a file the model never ran
(default-ON, advisory/non-blocking, degrade-to-skipped when pytest is
unavailable) — and the **work-modes increments** (#254-#259, "colleague's work
modes now fit the machine they run on"): **mode profiles** (#254) — per-mode
compute/context profiles (`colleague/profiles.py` + `config.py`
`apply_mode_profile`) resolved through the existing `EngineConfig` precedence,
byte-identical with no mode selected; **adaptive backpressure** (#255) — the
loop classifies per-turn latency (`colleague/backpressure.py`) and proactively
shrinks the context window + throttles subagent fan-out as turns drift toward
the request timeout; **tier visibility** (#256) — `TaskResult.mode` in the
artifact plus a session-cockpit Capacity/phase/goal panel rendered via the
existing generic panel walk (a genuine `TAUIState` schema addition stays
gated on the upstream agentfront#48 ask); **budget-aware skill curation**
(#257) — built-in roles get real glob-pattern `skill_subset`s
(`colleague/roles.py`) and the composed skills catalog can be token-capped
with a priority order (`colleague/layers.py`), dropping whole skills rather
than truncating; **subagent budget scaling + rig-level concurrency** (#258) —
a fan-out child resolves a clamped share of the parent's context/step budget
(`colleague/subagents.py`) and a file-based cooperative slot
(`colleague/rig.py`) coordinates concurrent top-level work items sharing one
served endpoint; and **task goals** (#259) — optional `Task.goal`/`acceptance`,
an advisory per-criterion self-check turn, and `SubResult.parent` lineage
(`colleague/contract.py` + `colleague/loop.py`), all omit-when-None — and the
**dual-model deepthink escalation** (the **Deepthink / dual-model** part
above): one operator-declared second model reached from a fixed, enumerated
escalation surface, single-model byte-identical (spec + plan:
`docs/specs/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md`
and the matching `docs/plans/` file) — and the **cortex/senses role split**
(the **Cortex / senses** part above): two operator-declared roles (cortex
drives the loop, senses perceives/presents) resolved by name from an optional
`lobes` gateway discovery rung, cortex-only byte-identical (spec + plan:
`docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md`
and the matching `docs/plans/` file) — and the **best-colleague arc** (spec +
plan: `docs/specs/2026-07-02-colleague-is-now-the-colleague-you-always-wanted-i.md`
and the matching `docs/plans/` file; the **Memory**, **Finish recovery +
grounded reads**, and **Background one-shot + mesh residency** parts above):
the memory-informed runtime (eidetic recall-before/remember-after + the
`memory` loop tool, R1), the report-reliability cluster (finish recovery
markers, line-grounded reads, R2), concurrent-run worktree-admin locking
(#239, R6), the background one-shot (`work --background`, R4), the resident
appserver on the agent-lifecycle library embed behind the `[resident]` extra
(R5, decision c17 — the deliberate no-daemon re-spec), and the `livecheck`
verb + refreshed live proofs (R7).
All integrated features
(mesh-member, culture tool, destination, approval gate, subagents, stats+feedback,
the capacity standard, the lint gate, the test-integrity gate, the affected-tests gate,
the six work-modes increments, the dual-model deepthink escalation, the
cortex/senses role split, and the
best-colleague arc) were added via explicit re-specs (spec + plan committed
under `docs/specs/` / `docs/plans/`); they extend the runtime within the
zero-deps / no-socket / no-daemon conventions (the daemonless line now reading:
colleague ships no socket/daemon code of its own — supervision is imported from
agent-lifecycle behind an opt-in extra, and background execution is a one-shot
detached child).

**Out of scope for v0** — do not add without re-speccing: a multi-backend
router / routing policy. Two, and only two, sanctioned increments have landed
at this line, each a re-spec'd, fixed, enumerated surface — never a routing
policy: (1) the **dual-model deepthink escalation** — ONE operator-declared
second model, a fixed enumerated escalation surface, no automatic
task→model routing, no N-model generalization; and (2) the **cortex/senses
role split** — TWO operator-declared roles with a FIXED responsibility
boundary (cortex acts — drives the loop, tools, gates, handoff; senses
perceives/presents — intake, speak-back, media description on operator-facing
surfaces only), resolved BY NAME from an optional `lobes` gateway, no
automatic task→model routing policy, no N-role generalization, no
senses-decides-to-answer-itself. Anything beyond either of those two is still
the excluded router; document the distinction honestly. Explicitly still OUT,
each parked pending its own router-boundary re-spec:
**senses-direct-for-cheap-tasks** — senses answering without cortex at all,
tracked as [colleague#276](https://github.com/agentculture/colleague/issues/276)
(a model deciding per-input whether cortex is needed is itself the start of
the excluded routing policy) — and the **voice loop + retrieval consumption**
— `stt`/`tts`/embedder/reranker roles are discoverable in the lobes
`/capabilities` contract from day one but colleague consumes only
`cortex`/`senses`, tracked as
[colleague#277](https://github.com/agentculture/colleague/issues/277). An
execution sandbox, a colleague-owned daemon/server
mode (**deliberately re-specced by the best-colleague arc, decision c17 — the
third recorded convention change** after the agentfront base dep and the LLM
self-summary: background one-shot execution (`work --background`, a detached
child process with file-based control — `colleague/background.py`, no daemon,
no socket, no polling) and **mesh residency via agent-lifecycle library embed**
(`colleague/resident/appserver.py` behind the opt-in `[resident]` extra:
colleague implements the upstream `Harness` Protocol and wires it to a
caller-supplied Transport through `agent_lifecycle.runtime`'s in-process
`Supervisor` — supervision and transport belong UPSTREAM, colleague still
ships zero socket/daemon code of its own, pinned by `test_boundary.py` +
`test_zero_deps.py`; trust model c19: anyone may ask, non-operator requests
run read-only under the `explorer` role or are refused, only the operator's
identity authorizes writes) are IN scope; anything beyond — a colleague-owned
persistent server process, socket code, or transport implementation — is still
excluded), Codex/Claude/Gemini adapters, a `--no-hooks` escape hatch (there is still
no such flag — the approval gate's checksum-based trust model is the landed
increment of the planned hook trust gate, but it is a policy gate, not a
sandbox; document this gap honestly, never invent a `--no-hooks` flag), and a
**live MCP *client*** (colleague consuming other MCP servers — stdio/socket
transport, tool discovery, dynamic tool registration; the layered config ships
AGENTS + skills only, reads no `mcp.json`, and registers no external MCP tools).
A live MCP client would breach the conventions and needs its own spec — document
this gap honestly, never invent an MCP-client surface. **Re-spec'd IN scope (the
distinction matters):** the **MCP *server* bonus** — `colleague mcp serve`, a
single-dispatch surface rendered from the same imported-agentfront App registry
(the **CLI surface (cli-on-agentfront)** part above), behind the opt-in
`colleague[mcp]` extra. It is **not** a colleague-owned daemon: the blocking
stdio loop is agentfront's `serve_stdio`, colleague writes no socket/daemon
code, and a base install is byte-identical (no server, no socket). Adding an
excluded feature means scope crept.

## The all-engines rule

Mirror of culture's all-backends rule: behavior that belongs to *the contract*
(task fields, result shape, the loop, the artifact) must hold for **every**
backend. The `mock` backend is the contract's reference — if a change makes
`mock` and `vllm-openai` diverge in result shape, that is a bug. The e2e shape
test (`tests/test_e2e_mock.py`) is the guard.

## Conventions

- **One sanctioned base dependency: agentfront.** `pyproject.toml` declares
  `dependencies = ["agentfront>=0.15.0"]` — the **first and only** sanctioned
  base runtime dep, a deliberate, recorded break from the historical
  `dependencies = []` convention (see the **CLI surface (cli-on-agentfront)**
  architecture part above). The floor moved from `0.14.0` (the consumer CLI API,
  agentfront#35) to `0.15.0` to adopt the two consumer-API gaps the migration
  surfaced and which agentfront#38 closed — `Flag(choices=)` and a **public
  single-dispatch MCP `run_tool` accessor** (`app.mcp_server().run_tool`, used by
  the MCP round-trip test instead of the private `_build_run_tool`). Honest
  nuance on `Flag(choices=)`: colleague's `--algo` (on `commands`/`hooks`
  `approve`) is a **value-carrying** flag — its value is consumed via the
  rendered tool's signature param — so it cannot take an explicit `Flag(choices=)`
  without colliding with its signature-derived `--algo` at build time; `--algo`
  is therefore validated **explicitly and early** in the verb (a clean
  choices-shaped `CliError` against `colleague.policy.SUPPORTED_CHECKSUM_ALGOS`),
  not via a parse-time choices flag. It
  is justified because agentfront's own core is **pure-stdlib** (zero
  third-party transitive deps), it is an AgentCulture sibling, and it is
  foundational to the org's shared agent-first CLI standard. So a base
  `pip install colleague` still pulls **zero third-party** packages beyond
  agentfront itself. Everything else stays stdlib: the vLLM adapter speaks the
  OpenAI wire format over `urllib`; commands and hooks use only `json`,
  `subprocess`, `pathlib`. Don't add a *second* base dep without a re-spec —
  dev-only deps go in the `dev` group. Two documented opt-in extras, never base
  deps: **telemetry** (the OpenTelemetry SDK behind the `[otel]` extra, imported
  **lazily** inside `colleague/telemetry/_otel.py` only when telemetry is
  enabled; keep the SDK confined there, never import `opentelemetry` elsewhere)
  and the **MCP server** (the MCP SDK behind the `[mcp]` extra — no socket/daemon
  ships at base). `tests/test_zero_deps.py` is now an **allow-list of exactly
  agentfront**: it imports `colleague.loop` / `colleague.telemetry` /
  `colleague.cli` / `colleague.culture` / `colleague.neighbours` / `colleague.cli._app`
  and asserts no third-party leak beyond agentfront — and that the MCP SDK is
  **absent** without the `[mcp]` extra.
- **Agent-first CLI — rendered from an imported agentfront `App` registry.**
  The live CLI is **rendered from one agentfront `App`** assembled by
  `colleague/cli/_app.py` `build_app()` (the "import, don't duplicate"
  migration — see the **CLI surface (cli-on-agentfront)** architecture part
  above + `docs/features/cli-on-agentfront.md`), not from hand-maintained
  argparse dispatch. A new verb
  is a `colleague/cli/_commands/` module exposing a **`register_into(app)`** hook
  (auto-discovered by `build_app`; it also keeps a `register(sub)` for the
  retained legacy parser). Register it as one of **two classes**: a **rendered
  tool** (`app.tool(...)`) for a read-only inspection verb — a plain function
  whose return value dual-renders via the `rendered(data, text)` helper,
  **always exits 0**, signals failure only by `raise` — or a **host command**
  (`app.add_command(name, handler, configure=...)`) for any verb needing a
  custom exit code (`work`/`drive` exit 2 on INCOMPLETE; `plan`/`tui` exit 1),
  streaming (`flight --follow`), or a blocking server/TTY (`session`, `tui`,
  `mcp serve`). Results to stdout, diagnostics/errors to stderr (never mixed);
  every command supports `--json`; failures raise `CliError` (it subclasses
  agentfront's `AgentfrontError`, so it renders natively — no tracebacks leak).
  A noun with action-verbs must expose `overview`. Add an `explain` catalog
  entry for each new verb. The four **reserved meta-verbs** (`doctor`,
  `overview`, `learn`, `explain`) stay colleague-owned via the retained legacy
  parser shim in `main()` (agentfront reserves them and renders thinner generic
  versions; colleague's are richer). Fully retiring the legacy `_build_parser`
  is a documented follow-up — until then the net `colleague/cli/` LOC is *up*
  (both paths coexist), and the raw-LOC maintainer win is *deferred* to that
  retirement.
- **The vLLM adapter only touches the OpenAI surface** — `base_url`/`api_key`/
  `model` config, `/v1/chat/completions` with tools. Retargeting any
  OpenAI-compatible server must stay a config change, never a code change. ONE
  deliberate carve-out: the vLLM `/tokenize` endpoint is used for exact token
  counting in the context-budget feature (`colleague/engines/vllm_openai.py`
  `_make_count_tokens`); it **degrades gracefully** (returns `None` on any error)
  so retargeting a non-vLLM OpenAI-compatible server WITHOUT `/tokenize` stays a
  config change, never a code change (token precision downgrades to char-approximate
  fallback, correctness unchanged).
- **Hook commands run as subprocesses, never imported.** `colleague/hooks.py`
  uses `subprocess.run` (shell=True) in the repo working directory. Command
  templates are Markdown text files, never executed as Python. No code path
  opens a socket or forks a daemon.
- **Threads and subprocesses are confined to an explicit sanctioned list.**
  `tests/test_boundary.py`'s `_SUBPROCESS_ALLOWED` is the authority — a module
  may import `subprocess` only by joining that list with a stated reason. The
  sanctioned consumers: `hooks.py`, `tools.py`, `handoff.py`, `neighbours.py`,
  `culture.py`, `devague.py`, `worktrees.py`, `lint.py`, `resident/steward.py`,
  `affectedtests.py`, **`background.py`** (the one-shot `work --background`
  detach — `Popen(start_new_session=True)`, no daemon/polling; a dedicated
  boundary test additionally pins no `.wait()`/`.poll()`), **`memory.py`** (the
  eidetic CLI shell-out), and **`livecheck.py`** (the gated live-proof runner).
  Threads (`concurrent.futures`) stay confined to `colleague/subagents.py`.
  Every shell-out targets an operator-installed CLI via explicit allow-listing;
  none opens a socket or forks a daemon. `worktrees.py`'s admin mutations are
  additionally serialized by an advisory `fcntl` lock (#239) so concurrent
  colleague processes cannot corrupt the shared `.git/worktrees/` state.
- **Hooks belong to the runtime, not to backends.** `colleague/loop.py` owns
  hook firing — new backend plugins inherit the full lifecycle layer automatically
  and must not duplicate it. The all-engines rule applies: a hook config that
  fires on `mock` must fire identically on `vllm-openai`.
- **Telemetry belongs to the runtime too.** `colleague/loop.py` (per tool
  call) and the shared `execute_work` path (root + handoff spans) own all
  telemetry; no backend module touches the `telemetry` package. Off by default it
  is a strict no-op (no spans, no SDK import, `TaskResult` unchanged) — protect
  that so the e2e shape test and zero-deps guard keep passing.
- **Repo-shipped hooks run by default (trusted-operator-env model D2).** There
  is no `--no-hooks` flag today. The approval gate (`colleague/policy.py`)
  is the landed increment of the per-repo hook trust gate: it gates hook
  scripts by checksum and `run_command` CLIs by token. It is a **policy gate,
  not a sandbox** — it is bypassable by `sh -c`, pipelines, and shell
  expansion. Document this gap clearly; never document a non-existent
  `--no-hooks` flag.
- **Per-model hooks overlay belongs to the runtime, not to backends.**
  `colleague/loop.py` passes `model=config.model` to `load_hooks` — both
  bundled backends do this. New backend plugins inherit the per-model overlay for
  free (all-engines rule). The overlay is operator-declared and file-based;
  colleague does not auto-detect model biases. Exact-path isolation and strict
  no-op match the AGENTS/skills layering conventions (`colleague/layers.py`).
- **The `culture` tool belongs to the runtime, not to backends.** `colleague/tools.py`
  owns the tool schema and the `ToolExecutor._culture` dispatch; `colleague/culture.py`
  owns the subprocess launch and identity injection. No backend module touches either.
  The all-engines rule applies: the culture tool is offered to every backend identically.
  Every culture integration shells out to an operator-installed CLI — no socket, no
  daemon, no import; `colleague` reads no `mcp.json` and adds no live MCP client.
- **The `devague` tool belongs to the runtime, not to backends.** `colleague/tools.py`
  owns the tool schema and the `ToolExecutor._devague` dispatch; `colleague/devague.py`
  owns the subprocess launch, identity injection, and allow-list enforcement.
  No backend module touches either. The all-engines rule applies: the devague tool is
  offered to every backend identically. The curated allow-list (`new`, `capture`,
  `interrogate`, `park`, `converge`, `status`, `show`) structurally excludes
  `confirm`/`reject` (user-only moves — the backend cannot self-confirm) and `export`
  (operator-only — arrival is recorded as a lightweight announcement, not a spec file).
  Every devague integration shells out to an operator-installed CLI — no socket, no
  daemon, no import.
- **The approval gate belongs to the runtime, not to backends.**
  `colleague/policy.py` is loaded once in `colleague/loop.py` (via
  `load_policy(task.repo_path, model=model)`) and consulted at two points:
  `_deny_by_policy` (for `run_command` calls) and `_fire_hooks` (for hook
  script files before they run). `colleague/commands.py` consults it at
  command-template expansion time. No backend module touches `policy.py`
  directly. The all-engines rule applies: the gate fires identically for
  `mock` and `vllm-openai`. Absent or malformed `approvals.json` is a strict
  no-op — byte-identical to pre-gate behavior. Zero new runtime deps (stdlib
  `json`/`shlex`/`hashlib`/`hmac`). **Checksum-only in v0** — `version`
  pinning is a documented follow-up, not built; do not document it as
  existing.
- **The `doctor` verb is colleague's health check.** It emits a configuration-readiness
  health check across identity, provider, usage, engines, otel-readiness, and
  environment check-groups, in a rubric shape with exit-1-on-unhealthy semantics. The
  **usage** group warns (advisory — stays healthy) when a bare work item would pick the
  no-op `mock` backend. `doctor --probe` adds an opt-in `provider_reachable` ping —
  the one check that opens a network connection, so it is gated behind the flag and
  invoked outside the (no-network) registered check-groups. See `colleague explain
  doctor` for details.
- **Work statistics belong to the runtime, not to backends.** `colleague/loop.py`
  owns `WorkStats` population (`_work_loop` per-turn + `_finalize_stats` on every
  exit path); `colleague/tools.py` accumulates `bytes_written`; the vLLM backend
  only *captures* `message.reasoning` into `ModelResponse`. The all-engines rule
  applies: stats are always-on and identical for `mock` and `vllm-openai`
  (`tests/test_e2e_mock.py` pins the `stats` key). **Honest token limit:** tokens
  are exactly what the response `usage` reports — never estimated. The served model
  reports no reasoning-token breakdown, so reasoning is measured as chars/bytes,
  not tokens; there is no tokenizer and no `bytes/4` heuristic. The optional OTel
  path mirrors the new metrics (`colleague.generated.chars`,
  `colleague.bytes_written`) as a strict no-op when off.
- **The feedback store belongs to the runtime, not to backends.**
  `colleague/feedback.py` is a stdlib JSON store (one record per work item,
  re-grade overwrites) + a per-repo `last_work` pointer written by
  `execute_work`. No backend touches it. Absent file/pointer is a clean no-op
  (`read_feedback` / `get_last_work` return `None`, never raise). It is **not**
  gated by the approval gate and opens no socket/daemon — zero new runtime deps.

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run pytest -n auto                     # tests (parallel)
uv run colleague backends list          # discovered backends (wheels = deprecated alias)
uv run colleague work "<task>" --repo . --engine mock --no-pr
# Backend resolution: --engine > COLLEAGUE_ENGINE > vllm-openai (never silent mock, #53).

# Extensibility layer:
uv run colleague work --command <name> [args…] --repo . --engine mock --no-pr
uv run colleague commands list --repo .          # list discovered templates
uv run colleague commands overview               # surface description
uv run colleague hooks list --repo .             # list configured hooks (shows run_command policy + approval status)
uv run colleague hooks overview                  # surface description
uv run colleague hooks approve <script> --repo . # record checksum approval for a hook script (repo-relative path)
uv run colleague commands approve <name> --repo . # record checksum approval for a command template
# Both approve commands accept --algo sha256|md5 (default: sha256) and --json.
uv run colleague session --repo . --engine mock  # interactive palette (commits locally, no PR; --pr to push+PR)

# ROI loop: work stats (always-on in the artifact) + feedback (grade a work item):
uv run colleague feedback record last --rating 4 --notes "…" --repo .  # grade the most recent work item (or <task_id>)
uv run colleague feedback show last --repo .                           # read a work item's feedback (clean no-op if ungraded)
uv run colleague feedback overview                                     # surface description

# Telemetry (opt-in; needs the [otel] extra):
uv run colleague telemetry status                # resolved telemetry config
uv run colleague telemetry overview              # surface description
uv sync --extra otel                               # install the OpenTelemetry SDK
COLLEAGUE_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  uv run colleague work "<task>" --repo . --engine mock --no-pr  # emits a trace

# Lint + gates CI enforces:
uv run black --check colleague tests
uv run isort --check-only colleague tests
uv run flake8 colleague tests
uv run bandit -c pyproject.toml -r colleague
uv run teken cli doctor . --strict        # agent-first rubric gate
```

The live vLLM proof is opt-in (the reference rig must expose tool calling:
`--enable-auto-tool-choice` plus a model-appropriate `--tool-call-parser`, e.g.
`hermes` or `qwen3_coder`):

```bash
COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v
```

## The `ask-colleague` skill (first-party)

colleague ships one **first-party** Claude Code skill,
[`ask-colleague`](.claude/skills/ask-colleague/) — the *inverse* of the vendored
skills (origin = colleague; see [`docs/skill-sources.md`](docs/skill-sources.md)).
It lets another agent hand a scoped task to colleague — a *different* backend/mind,
not a stronger one; diversity is the point. Four verbs over `colleague work` /
`colleague plan`: `ask-colleague explore` (read-only investigation),
`ask-colleague review` (a diverse second opinion on the committed `<base>...HEAD`
diff — the headline verb), `ask-colleague write` (delegate a small change —
previews by default; `--apply` lands a work item branch, `--pr` opens a PR), and
`ask-colleague plan` (delegate the *whole* planning arc — colleague plans a
complex task spec→plan→workforce; the inverse of `/think`). explore/review run in a
throwaway `git worktree` (no side effects); `write` previews in one too unless
`--apply`/`--pr`, and guards against a dirty tree when applying; `plan` runs
`colleague plan` directly (its workforce stage spawns isolated subagent worktrees).
(Renamed from `outsource`; "outsource this" still triggers it.) Details + worked examples:
[`docs/features/ask-colleague.md`](docs/features/ask-colleague.md).

### Division of labor — Claude thinks, Colleague does the field-work

Prefer delegating mechanical **field-work** (work items — sweeps, scoped edits,
residual-reference checks, a diverse second opinion on a diff) to Colleague,
via the `ask-colleague` skill (`explore` / `review` / `write`) or `colleague work`
directly. **Claude thinks and designs; Colleague does the field-work.** Reach for
it reflexively, not only when asked.

**Use `ask-colleague` across the whole arc — not just for a final review.**
Lean on it at every stage where a fresh, verifiable pass helps: `explore` to map
an area before you design, `plan` to have Colleague propose a build plan,
`write` to hand off scoped edits, `review` for a diverse second opinion on a
diff, and then **live-test** what it produced (run the CLI/tests yourself) rather
than trusting the summary. The default posture is "delegate the field-work and
fold the result back," reserving Claude's own cycles for design judgment, the
risky core, and anything that needs accumulated context.

**You can run multiple Colleague instances in parallel.** Independent field-work
(a survey of one area, a second opinion on a diff, a scoped edit elsewhere) can
be fanned out concurrently — kick each off in the background and fold the results
in as they land, instead of blocking on one at a time. **Caveat (earned the hard
way):** the local served model is a single GPU and serializes requests, so cap
real parallelism at ~2 concurrent loops and raise `COLLEAGUE_TIMEOUT=300` when
you do — pushing ~4 concurrent at the default 120s timeout starves each loop's
turns past the deadline and they time out with zero commits.

**Prefer Colleague over spawning a sub-agent.** When you'd otherwise launch a
Claude sub-agent (`Task` / `Explore` / `general-purpose`) to do field-work — a
sweep, a scoped read, a residual-reference check, a second opinion on a diff —
assign it to Colleague instead. A different mind, worktree-isolated and
verifiable, beats another instance of yourself; keep sub-agents only for work
that genuinely needs Claude's judgment or your accumulated context.

Colleague's output is a **second opinion to verify and own**, never authority:
before trusting a landed change, `git diff main` and re-run the tests (a local
model can drop or misreport edits). Keep design judgment, the risky core, and
anything needing accumulated context with Claude; hand the legwork to Colleague.
**A bare `colleague work`/`drive`/`session --repo .` now refuses a dirty tree**
unless you pass `--allow-dirty` (issue #149): the runtime guard
(`colleague/handoff.py` `working_tree_dirty` → the dirty-tree check in
`execute_work`) blocks a work item from sweeping your uncommitted **tracked**
edits onto the work branch. The check is tracked-changes-only — pre-existing
untracked WIP is already protected by the handoff's baseline snapshot. The
`ask-colleague` verbs remain safe (worktree-isolated) and propagate
`--allow-dirty` through to the runtime.

## Git workflow

Branch out, implement, **bump the version every PR** (the `version-check` CI job
blocks merge otherwise — use the `version-bump` skill), create the PR via the
`cicd` skill, address review, merge. Distribution is `colleague`; the
command and import package are `colleague`. PyPI publish is via Trusted
Publishing on merge to `main`.

## Conventions and workflow

**Memory discipline — recall before, remember after.** This repo keeps its
eidetic memory **in-repo and public**: records resolve to
`<repo-root>/.eidetic/memory` — committed, and shared with the team and mesh
peers (the `claude` and `colleague` backends both read the same
`colleague` scope), so memory travels with the repo, not a private
home-dir store. Make it a per-task habit:

- **`/recall` before you start.** Search the store for the area you're about
  to touch — prior decisions, gotchas, "have we done this before?" — so you
  build on what's already known instead of re-deriving it. Do this before
  non-trivial tasks, not just when asked.
- **`/remember` when something worth keeping surfaces.** A non-obvious
  decision and its rationale, a constraint, a fix and *why* it was needed, a
  gotcha that cost time, a fact the next session would otherwise re-learn.
  Capture it as it happens, not at the end when it's faded.

A plain `/remember` lands the note in `./.eidetic/memory` in this repo — no
flag needed (the wrappers here default to `--visibility public`; in-repo
routing needs `eidetic >= 0.10.0`, older CLIs keep records in `$HOME`). Keep
something out of the committed store only by passing `--visibility private`
(routes to `$HOME/.eidetic/memory`, never committed); `/recall` reads both
stores and merges. Don't store what the repo already records (code structure,
git history, what's already in this file or `CHANGELOG.md`) — store what you'd
have to re-derive. These are the `recall`/`remember` skills (`.claude/skills/`),
backed by the `eidetic` store.
