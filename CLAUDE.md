# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

Each architecture part below is a few lines + a pointer to its feature doc; the deep detail (history, invariants, honest limits, full module list, spec+plan) lives in [`docs/features/`](docs/features/), which links its spec/plan
under [`docs/specs/`](docs/specs/) / [`docs/plans/`](docs/plans/). A bare `Doc:`
name is a file under `docs/features/`. Trim discipline (decision c17 / honesty h4):
no fact was dropped — everything moved to its pointer target.

Some harness mechanisms are ported (as small stdlib Python, never a vendored
dependency) from Qwen Code and its Google Gemini CLI lineage; provenance is
tracked in [`docs/adopted-from.md`](docs/adopted-from.md) (see also
[`NOTICE`](NOTICE)).

## What colleague is

**Colleague CLI is a swappable coder-agent harness that turns different model
backends into repo workers behind one shared task runtime.** One runtime, many
minds. The architecture, part by part:

- **Mind / backend** — the model/coder backend.
- **Adapter** — invokes one backend (`colleague/engines/`, an `Engine` subclass
  with `work(task, config) -> TaskResult`). Doc: `engines.md`.
- **Task runtime** — the shared contract (`colleague/contract.py` +
  `contract_coerce`/`contract_configevents`/`contract_records`/`contract_reports`/
  `contract_senses`/`contract_taskresult_io` siblings, split under the 1000-line
  hard ceiling: `Task`/`TaskResult`); optional `Task.goal`/`acceptance` → an
  **advisory** acceptance self-check (never flips status). Doc: `task-goals.md`.
- **Tool loop** — the bounded agentic loop (`colleague/loop.py`, split into 26
  `loop_*` siblings — `loop_types`/`loop_transport`/`loop_context`/`loop_senses`/
  `loop_testgates`/`loop_testgates_warnings`/`loop_constants`/`loop_outcomes`/
  `loop_memory`/`loop_synthesis`/`loop_gates`/`loop_run_stages`/`loop_setup`/
  `loop_gatebase`/`loop_hooks`/`loop_flight`/`loop_wire`/`loop_toolexec`/
  `loop_toolturn`/`loop_tae`/`loop_progress`/`loop_turn`/`loop_accounting`/
  `loop_barrier`/`loop_gateescalation`/`loop_deltaheartbeat` — under the
  1000-line hard ceiling, `loop.py` itself stays the entry point) over
  repo-confined tools (`colleague/tools.py` + `tool_schemas`: base six +
  `culture`). Hooks, the progress sink (#38, wired to a real work path since
  #483's `loop_deltaheartbeat`), phase notices (#206), finish recovery
  (#248/#231) live here (all-engines); **a phase notice never advances
  `step_count`**. Doc: `work-and-loop.md`.
- **Plugins** — backends discovered via the `colleague.engines` entry-point group
  (`colleague/registry.py`).
- **Run report + feedback (ROI loop)** — JSON artifact + step trace + always-on
  `WorkStats` (`colleague/artifact.py`; tokens exact from `usage`, never estimated),
  plus a per-work-item feedback store (`colleague/feedback.py`) with a per-repo
  `last_work` pointer (writes-only across ask-colleague, #132); `TaskResult.task_text`
  records the verbatim brief (16 KiB cap, ON by default, `COLLEAGUE_RECORD_TASK_TEXT=0`,
  a continuation propagates the ORIGINAL brief, never the synthesized seed, #481).
  Docs: `artifact.md`, `stats-and-feedback.md`.
- **Telemetry** — opt-in OpenTelemetry, loop-instrumented; off by default, the lazy
  `[otel]` extra. Doc: `telemetry.md`.
- **Mesh-member integration** — process identity (`colleague/identity.py`, via `COLLEAGUE_IDENTITY`), read-only neighbour clones from a `.colleague/neighbours.json` allow-list (`colleague/neighbours.py`), and a curated `culture` tool (`colleague/culture.py`) shelling out to `agtag`/`devex`. Doc:
  `mesh-member.md`.
- **Destination** — a curated `devague` loop tool to converge a goal-frame +
  declare arrival; allow-list excludes `confirm`/`reject`/`export`; optional. Doc:
  `destination.md`.
- **Approval gate** — operator allow-list over what the harness runs (`colleague/policy.py`): `run_command` by token, `hooks`/`commands` by checksum;
  absent = strict no-op. Doc: `approval-gate.md`.
- **Subagents** — delegate sub-tasks via `subagent`/`subagents`
  (`colleague/subagents.py` + `subagents_binding`/`subagents_batch` siblings, split
  under the 1000-line hard ceiling), each child in a `sub/<id>` worktree + a
  sequential merge child; caps `MAX_SUBAGENT_DEPTH`/`_FANOUT`; concurrency opt-in
  (default 1). Doc: `subagents.md`.
- **Subagent roles** — a subagent can be a **typed role** (`colleague/roles.py`); a
  read-only role **provably cannot mutate the tree**; caps depth 4 / total 24. Doc:
  `subagent-roles.md`.
- **Rig budget** — a file-based cooperative slot across separate colleague processes sharing one endpoint; a caller degrades OPEN, never deadlocks. Doc: `rig-budget.md`.
- **Deepthink / dual-model** — a MAIN model + a **deepthink** reasoner
  (operator-declared, or discovered from the lobes `muse` role) on an
  **enumerated** escalation surface; absent = byte-identical. Doc: `deepthink.md`.
- **Thinking effort (#416)** — a per-seat reasoning ladder
  (`off|low|medium|high|xhigh`, plus the `default` kill-switch) resolved
  **where each seat is built**, never per turn FROM CONTENT — per enumerated
  point from a fixed table (amended #484): deepthink/design seats keep full
  effort, shallow seats (senses/Talker, read-only scouts) turn thinking off; the
  v3 default table is pinned row-for-row and rendered once in the feature doc
  (pointer, not duplicate); a ladder-400 retries once without the key;
  byte-identical under the kill-switch. Doc: `thinking-effort.md`.
- **Effort spikes (#484)** — the AMENDED thinking-effort invariant's opt-in
  spike surface (`COLLEAGUE_EFFORT_SPIKES=1`): exactly THREE enumerated points
  keyed by point name against a FIXED table (`colleague/effortspikes.py`) —
  `barrier.pre_mutation` (a one-shot pre-mutation planning turn,
  `loop_barrier.py`), `gate.repeat_failure` (a repeated gate-repair turn,
  `loop_gateescalation.py`), and `fillline.decision` (delegated to the
  already-shipped `effort.DESIGN_SITE_TABLE['fillline.split']`, same module);
  recorded on `TaskResult.effort_spikes` (omit-when-empty); unarmed =
  byte-identical to v1.74.0. **Measured** (`docs/live-testing.md` rows 70-73):
  the barrier fires and plans correctly but bought nothing on correctness at
  2.3× a flat-`low` run's reasoning — default stays OFF. **Trigger fix
  (#487):** the barrier's precondition/trigger key on the file-writing names
  `write_file`/`edit_file` only, so a shell-first survey still reaches it.
  **Two more enumerated points (effort-floor-and-decay arc, five total, drift
  test re-pinned):** `stall.no_write` (after `STALL_TURNS`=10 acting turns
  with no `write_file`/`edit_file` call since start / last spike / last write,
  the barrier's tools-off decision turn fires at `medium`, at most 3 per run —
  a COUNT over tool names, because rows 74-75 showed an `off` floor never
  reaches the pre-mutation barrier) and `start.first_turn` (model turn 1 at
  `medium`, tools on, keyed by position).
  **Effort decay (opt-in `COLLEAGUE_EFFORT_DECAY=1`, `colleague/effortdecay.py`):**
  after any spike the acting turns run `1 → low`, then `off` until the next
  spike resets the clock (convention change (8)); recorded on
  `TaskResult.effort_decay` (omit-when-empty). **Measured (rows 74-77):** an
  `off` floor alone never crosses survey → action (rows 74-75, zero files);
  the full stack on the off floor (row 77) lands a correct branch at 16% of
  the flat-`low` arm's reasoning and 41% of its wall — n=1, still opt-in.
  Doc: `effort-spikes.md`.
- **Per-model sampling defaults + repetition guard (#479)** — every seat's
  completion carries its MODEL CARD's sampling values for the half the
  already-resolved effort rung selects (`off` = the non-thinking half, any rung
  = thinking), instead of the old hard-coded greedy `temperature 0.0`: a FIXED
  builtin table (`colleague/sampling.py`, Qwen3.8 both halves) + a
  server-default wire filter (`colleague/samplingwire.py`, the ONE module that
  names the vLLM extension keys) + the tracked, per-model-merged
  `.colleague/models.json` operator table (`colleague/samplingfile.py`). Keyed
  by model + rung ONLY — nothing inspects the task, so it is never the excluded
  router. An unmatched model sends NO key; `COLLEAGUE_SAMPLING=0` is the
  per-process kill switch; `CONVERTIBLE_TEMPERATURE` is removed (warns) and
  `COLLEAGUE_TEMPERATURE` deprecated for one release (warns). Beside it a
  verbatim-tail **repetition guard** (`colleague/repetitionguard.py`) cuts a
  TURN — never the run, until the third trip — whose reasoning has begun
  repeating. Doc: `sampling.md`.
- **Single-model default — qwen-direct (v1.63)** — **1 colleague instance = 1
  model = 1 agent**: a bare run on a lobes-armed rig resolves exactly ONE served
  model (the `cortex` role) and dials nothing else — senses and muse lobes
  discovery are **opt-in** (the `lobes` sentinel: `COLLEAGUE_SENSES_MODEL=lobes`
  / `COLLEAGUE_DEEPTHINK_MODEL=lobes`, or an explicit model id), the senses
  presence loop and front door sit behind that opt-in, an unarmed session PARKS
  a mid-run line for cortex via flight guidance, `config show`/`lobes show`
  name the advertised-but-not-consumed roles, and `/model` + `/effort` (session)
  / bare `--model` + `--effort` (CLI) list the served options + per-seat effort
  defaults — an **explicit operator choice, never automatic routing**. The
  instance spawns ITSELF as subagents (same model). Doc: `qwen-direct.md`.
- **Adopted harness mechanics (adopt-from-qwen-code)** — harness mechanics
  ported from Qwen Code (and its Google Gemini CLI lineage) as small stdlib
  modules, never a dependency: a window-clamped `max_tokens` on every
  completion, ONE `/tokenize` per run, parallel batches of read-only tool
  calls (convention change (6)), `grep_search`/`glob`, paged `read_file`, a
  tolerant `edit_file` + prior-read rule, spill-to-disk truncation, rule-based
  microcompaction, stream + loop guards, adopted prompt text, and the opt-in
  `associate` seat (`COLLEAGUE_ASSOCIATE_MODEL=lobes`, addressed by role name)
  — validate it on real cases with `docs/features/associate-validation.md`
  before making it a default (#460, lobes-cli#234)
  — each with one off-knob that is byte-identical to main; credit in `NOTICE`
  and `docs/adopted-from.md`. Doc: `adopt-from-qwen-code.md`.
- **Web scout (#436/#435)** — a curated read-only `web` tool over the
  operator-installed WebGlass CLI (hidden when absent / `COLLEAGUE_WEB=0`,
  byte-identical off-state); the scout seat gains the tool, never a router.
  Doc: `web-scout.md`. **Purpose tools (#443)** — cortex/worker no longer hold
  raw `web`/`subagent`/`subagents`; they hold six typed tools — `web_survey`/
  `code_survey` (a scout child, on the associate seat when armed), `review`/
  `validate`/`plan` (reviewer/validator/planner children on cortex) and
  `handover_to_colleague` (a writer child on cortex) — each a FIXED purpose →
  fixed role → fixed seat + rung (`PURPOSE_TABLE`, never leaked from the
  parent), called explicitly: the deepthink precedent (increment 1) applied by
  purpose, never a router. **Arm 4 (plan t11) reversed the delegation half of
  #443's "replace, don't add" as a pre-registered test — and the matrix
  REJECTED it, so the default reverted** (Qodo `3888125915`): the raw
  `subagent`/`subagents` went back on the ACTING seat to test whether their
  ABSENCE, not the typed form, was what suppressed delegation; they are gone
  again because it was not. The arm's child confinement is KEPT as defence in
  depth: `actingsurface.CHILD_FORBIDDEN_TOOLS` strips the raw pair at
  depth >= 1 regardless of what the seat's allow-list carries, so a spawned
  child stays the bounded writer it already was (15 allow-list names, 14
  rendered tools). **MEASURED, and the result is negative
  (`purpose-tools-get-chosen`, `docs/live-testing.md` rows 51–58, 21 runs, zero
  voided, `markup_tool_calls` 0 on all 21):** neither declared lever moved the
  delegation rate — prose A1/A2/A3 all 0/3 (wall/turns vs baseline
  0.560/0.826, 0.908/0.913, 0.866/0.783), surface A4 0/3 (0.522/0.783) — and
  **no `subagent`/`subagents` call occurred anywhere in the matrix, A4
  included** — so #443's removal of the raw pair was NOT what suppressed
  delegation, the restoration bought nothing measurable, and leaving it in
  place would only have reopened a path around the fixed `PURPOSE_TABLE`
  mappings. Tested and rejected on evidence, never quietly undone;
  `docs/live-testing.md` rows 49-58 keep every measured figure. What moved it was
  **task shape**: 0 delegating runs of 15 on the small brief, 5 of 6 on the
  large-surface brief, every delegation a typed `code_survey`; cortex
  substitutes the parallel read-only tool batch for delegation and prefers that
  cheaper form until the surface is too large. Task success was **equal** (5/5
  `ok` delegating, 16/16 `ok` non-delegating), so **"cortex was right not to
  delegate on a brief it can hold" is the supported reading** (claim c46). Two
  limits: the small-brief zero is a FLOOR, not a null (all five small-brief arms
  sat at exactly zero, so that brief cannot detect a prose effect — never
  "prose does not work"), and the one arm meeting the promotion numbers is
  CONFOUNDED (no P0 control on the large brief) and did NOT promote. **The
  shipped default prompt carries no encouragement to delegate** — the t9
  section names the six purpose tools and says "never delegate just to
  delegate"; the imperative prose tested here lives only in staged overlays
  under `docs/live-testing/overlays/`. **The `delegation-follow-ups` arc
  (rows 59–62) closed #456's two gaps negatively — the raw-vs-purpose fair
  fight A7 delegated 0/3 by either form (unanswered, not lost), the size
  trigger P3 0/3 against a clean P2-0 control and does not promote — and
  found the purpose child's step cap unapplied (#458).** Doc: `purpose-tools.md`.
- **Cortex / senses** — minds resolved **by role** from an operator `lobes` gateway:
  cortex drives, senses is a tools-off front door; absent = byte-identical.
  `colleague/senses.py` is split into `senses_common`/`senses_extra` siblings under
  the 1000-line hard ceiling (`senses_loop.py`/`senses_moves.py`/`senses_stream.py`
  stay separate, pre-existing modules). Doc: `cortex-senses.md`.
- **Three-tier execution** (superseded by #411 — kept as the benchmark baseline) — worker acts / senses relays / cortex configures,
  resolved BY ROLE NAME from the lobes gateway (worker role), opt-in via config;
  byte-identical when unconfigured; deepthink absent in three-tier mode;
  the configurator a further opt-in (default off); the consumption lane is
  wired end-to-end (lattice content, lifecycle folds, prompt seam, tool
  narrowing, work front, subagent snapshot, flight seat) — see
  `three-tier.md` § Honest limits for pinning tests; NEVER a routing policy.
  Doc: `three-tier.md`.
- **Thought → action → evaluation (#397)** — a SEPARATE opt-in mode
  (`thought_action_evaluation`; arming it together with `three_tier` refuses):
  the **front** (`senses` role, no repo tools) commits a typed versioned
  `Thought` while the raw operator input is preserved verbatim; the **worker**
  (`worker` role) realizes it as an `ActionProposal` naming exactly one live
  `thought_id`; the tools-off **evaluator** (`cortex` role) judges fidelity and
  returns only `execute | rethink | replan | block` — `replan` keeps the SAME
  thought, `rethink` returns to the front. The evaluator sits on FIVE enumerated
  boundaries, NEVER every tool call, and **alignment is not permission** (host
  policy/approvals gate every route). Presence-mode prose can never authorize
  action; the host — not the worker — classifies consequential actions; the
  whole chain lands append-only on `TaskResult.evaluation_ledger` with real
  seat/model attribution. Byte-identical when unarmed. Doc:
  `thought-action-evaluation.md`.
- **Model-bound agents (#411)** — a THIRD independent opt-in (`agents` /
  `COLLEAGUE_AGENTS`; arming it with `three_tier` or `thought_action_evaluation`
  refuses, naming both): every model invocation is an attributable agent — a
  typed `AgentProfile` (purpose → lobes role → served model as trace data,
  validated tool profile, authority ceiling, lineage) with a per-invocation
  context manifest + tool-surface digest on the append-only **task ledger** at
  the operator repo (`.colleague/ledger/<id>.jsonl`); subagents may bind a
  DIFFERENT lobes role (child surface ⊆ parent, `context_mode` inherit|clear);
  agents exchange typed `delegate|ask|inform|challenge|handoff|return` messages
  (no chain-of-thought field, bounded by `MAX_AGENT_MESSAGES`); continuation
  rehydrates from the ledger; reference topology BY ROLE NAME — Talker=`senses`,
  Worker=`worker` (dormant, d3), Thinker/Coder=`cortex`, Associate=`associate`
  (reserved fast coder); a missing role is a RECORDED cortex fallback, never a
  refusal. Byte-identical when unarmed. Doc: `model-bound-agents.md`.
- **Media input** — images/audio ride to a multimodal main model;
  delivery **verified** onto `TaskResult.media`.
  Doc: `media-input.md`.
- **Integration front (#291)** — colleague is the operator front of the Culture.dev
  organism; landed the coherence gate, the experiment noun, `organs list`,
  the artifact contract + `feedback export`. Index: `docs/organs.md`.
- **Senses live presence + voice** — the operator converses with **senses** while cortex drives; words → guidance at the next tool-call boundary; audio
  via `stt`/`tts` (`[voice]` extra); senses never produces the task answer. Doc: `senses-live-presence.md`.
- **Realtime speech** — the senses talk lane over the rig's `/v1/realtime`
  WebSocket (`colleague/realtime.py`, the ears-only client — never
  `response.create`; senses stays the mind); client-edge half-duplex mute
  (lobes d1) replaces AEC; mic live only on explicit per-session opt-in
  (`/voice`, `--voice`, c27); turn-based voice is the degrade floor. Doc:
  `realtime-speech.md`.
- **Talking to one (middle-manager presence)** — in `colleague session` senses
  acks/narrates/clarifies + delivers conversationally; cortex still does the task;
  clarify never withholds work. Doc: `talking-to-one.md`.
- **Talking to one teammate (senses front door)** — senses answers non-repo turns
  FIRST via a **deterministic** classifier (`colleague/frontdoor.py`,
  ambiguous→cortex); anything touching the repo → cortex, the ONLY repo actor. Doc: `talking-to-one-teammate.md`.
- **Session streaming + narration + speak-only + pin hygiene** — senses replies
  stream into the conversation (`colleague/senses_stream.py` extractor, owned-line
  transient paints, containment); cortex/worker activity narrates at boundary
  beats as `<<higher self thought>>` / `<subconscious thought/actions>`
  (display-only, NEVER model context); `--speak`//`speak` speaks replies while
  the operator types (default off, mic gate untouched); a stale model pin
  same-role-refreshes loudly (main seat only) onto `TaskResult.warnings` + a
  doctor membership probe. Doc: `session-streaming-voice.md`.
- **Memory (best-colleague R1)** — recall-before / remember-after every run (eidetic) onto `TaskResult.memory`; triple-gated; isolated runs target the OPERATOR repo. Rung 1 folds the failure substance verbatim (#379); **rung 2** distills a schema-validated cause→lesson→next-delta (author BY ROLE: deepthink/muse > armed-lobes main > rung-1 floor; a detached bounded child, `distill: detached`, alive-counters on the artifact + doctor). Doc: `memory.md`.
- **Self-learning (strive + code-lessons)** — the necessity loop `colleague strive`
  (four enforced phases, hypothesis ledger refuse-whole, novelty stall recorded
  honestly, measure approval-gated in the episode worktree, real per-attempt
  episodes via `Engine.work` on `sub/strive-<goal-slug>`); repo-anchored
  code-lessons from the integrator-correction diff (`colleague/correction.py`,
  tip SHA vs squash commit, honest no-diff) + the seamless auto-trigger lane
  (grade-time + work-start, observable, never blocks the grade); cortex-authored
  feedback carries provenance and stays OUT of `feedback export` by default.
  Doc: `self-learning.md`.
- **Finish recovery + grounded reads (R2)** — the loop recovers
  literal-markup/thin/meta finishes (#248/#231) onto `TaskResult.finish_recovered`;
  `read_file` is `cat -n` grounded (#240). Doc: `work-and-loop.md`.
- **Honest incompletion (#313)** — a no-deliverable run reports non-`ok`
  (`INCOMPLETE`) + `TaskResult.incompletion`; **soft rule**: a
  substantive non-meta finish = delivered. Doc: `honest-incompletion.md`.
- **At home on your machine** — global config **per-key merge** (a machine-wide `~/.colleague/config.json` arms every repo); **the owned input line** (4th
  sanctioned reader thread); **self-knowledge** (#306). Doc: `at-home-on-your-machine.md`.
- **Background one-shot + mesh residency (c17)** — `work --background` detaches a
  session-leader child (`colleague/background.py`); residency
  (`colleague/resident/appserver.py`, `[resident]` extra) embeds
  `agent_lifecycle.runtime` — **zero socket/daemon code of colleague's own**; trust
  c19 (non-operator read-only or refused). Doc: `resident.md` (+ `background.md`).
- **Auto-split** — a too-large assignment gets a split recommendation into ~4 children (via `subagents`, reusing `batch_spawn`); strict no-op when dormant. Doc:
  `auto-split.md`.
- **Handoff** — branch/commit/push + `gh pr create`, gated for offline/CI
  (`colleague/handoff.py`); crash-resilient (#162 — a catchable pre-commit interruption restores the ref + reaps the orphan branch). Doc: `handoff.md`.
- **Write isolation (#196/#201)** — `work`/`drive` run in a throwaway worktree at HEAD on `colleague/<id>` (`colleague/worktrees.py`); the operator's
  tree + branch are **never touched**; `--allow-dirty` (#149) is the gate. Doc:
  `write-isolation.md`.
- **Lint pre-finish gate (#200)** — auto-fixes changed files with configured linters (`black`/`isort`/`ruff`/`flake8`); default-ON,
  non-blocking. Doc: `lint-gate.md`.
- **Test-integrity gate (#203)** — flags the **mirror signature** (a novel id
  co-introduced in a changed test + its module, found nowhere else) onto
  `TaskResult.test_integrity_report`; + a diverse-model reviewer; advisory; a
  flagged finding on a non-finished outcome now also appends a
  `test-integrity-flagged` warning (#480). Doc: `test-integrity.md`.
- **Affected-tests gate (#213)** — runs the tests that **transitively import** the changed module(s) (`ast` graph, depth 3, capped 20); default-ON,
  degrade-to-skipped without pytest; a `failed` report on a non-finished
  outcome now also appends an `affected-tests-failed` warning (#480) so the
  operator sees it without opening the artifact. Doc: `affected-tests.md`.
- **Import-check gate (#482)** — a fifth pre-finish gate (`py_compile` and a
  subprocess import smoke of every changed `.py` file, worktree-resolved so
  colleague-on-colleague self-hosting can't pass vacuously against an
  installed copy); runs on EVERY exit outcome, no bounded fix-turn;
  `TaskResult.importcheck_report` (set on pass and fail alike, omit-when-None)
  and an `import-check-failed` warning; off-knob `COLLEAGUE_IMPORT_CHECK=0`.
  Doc: `import-check.md`.
- **Cleanup / reap** — `colleague clean` self-heals a repo a crashed `work` wedged
  (#162); the git reap lives in `colleague/handoff.py`; scoped to `colleague/*` refs + `.colleague/` artifacts. Doc: `cleanup-reap.md`.
- **Command templates** — named recipes in `.colleague/commands/*.md`, via `work --command <name>`. Doc: `command-templates.md`.
- **Hooks** — operator shell commands in `.colleague/hooks.json` at four lifecycle
  points (`pre_tool` can allow/deny/rewrite); a per-model overlay composed **ahead**
  (exact-path). Docs: `hooks.md`, `per-model-configuration.md`.
- **Interactive palette** — `colleague session` (`colleague/cli/_commands/session.py`):
  a foreground TTY loop, no daemon; a `SlashSpec` catalog; a delegation cockpit
  (#158); agent-native default (#234/#233/#235); mode selection (shift-tab / `/mode`). Off a colour TTY
  = byte-identical. Docs: `session.md`, `session-modes.md`.
- **Interactive finishes what it starts (#167/#168/#169)** — `work --continue/-c`
  and session `/continue` resume a cut run from its persisted artifact
  (`colleague/continuation.py`, wrong-run guard; lineage on
  `TaskResult.continued_from`); a colour-TTY dirty dispatch offers the 3-choice
  heal (`colleague/heal.py`, consequence+undo verbatim) instead of the #149
  refusal (runtime guard untouched); the Last-run panel + post-run line carry
  the real `pr_url`, never synthesized. Doc: `session-continue-heal.md`.
- **Indefinite run / episode chaining (`--until-done`)** — an ARMED run chains
  bounded episodes past budget-exhausted exits (`colleague/chain.py` allow-list =
  exactly that reason; `execute_work_chain`, both fronts + `--background`): each
  episode's worktree bases on the prior `colleague/<id>` tip (the #222 WIP sweep
  is best-effort → HEAD + recorded warning), handoff fires ONCE at chain end
  (halted chains keep every branch); cap `--max-episodes` (5 armed, 0 = unlimited
  — crawl risk is explicit operator intent, flight stop is the brake); gates
  re-run per episode. AMBIENT (default-on): the fill-line re-arms per crossing
  (capped 4 compactions/run) + deterministic compaction validation (an empty
  summary never replaces history). Doc: `indefinite-run.md`.
- **Cockpit / tui (#285/#249)** — `colleague tui` gives three headless views of one
  `TAUIState` (JSON/ANSI/Markdown) + snapshot/diagnose; the session cockpit changes
  idle→running (claiming only ENFORCED gates, never "sandboxed"); the generic cockpit
  is IMPORTED from `agentfront.taui`, not duplicated. Docs: `tui.md`, `cockpit-ux.md`.
- **Mode profiles** — each mode carries its own compute/context profile
  (`colleague/profiles.py`); `apply_mode_profile` fills only untouched knobs after `resolve()`. Doc: `mode-profiles.md`.
- **Context budget / graceful degradation** — the loop windows history to a token
  budget (`colleague/context.py`) + trims/retries on overflow/timeout before
  preserving a partial. Knobs `COLLEAGUE_CONTEXT_BUDGET`/`_MAX_OUTPUT_CHARS`/
  `_MAX_STEPS`/`_TIMEOUT`; adaptive backpressure (#255) + timeout survival (#268).
  Docs: `graceful-degradation.md`, `backpressure.md`.
- **Capacity standard / fill-line (v1, #156)** — each crossing of `COLLEAGUE_FILLLINE_THRESHOLD` (0.8) injects ONE decision prompt (compact | split
  | finish-with-handoff, `colleague/fillline.py`); **compact** = a validated model-authored summary — the v0→v1 graduation superseding "no LLM summary"; re-arms per crossing (`indefinite-run.md`). Doc: `capacity-standard.md`.
- **Config resolution** — `colleague/configdir.py` (repo > user) + a persistent
  `.colleague/config.json` override (flag > env > config.json > default); `colleague
  config show` (redacted); includes the `convertible`→`colleague` rename
  back-compat. Resolution itself lives in `colleague/config.py`, split into 10
  `config_*` siblings under the 1000-line hard ceiling —
  `config_defaults`/`config_types`/`config_files`/`config_lobes`/`config_seats`/
  `config_modelpin`/`config_flags`/`config_profiles`/`config_resolve`/
  `config_snapshot`. Doc: `config-resolution.md`.
- **Layered per-model config** — `colleague/layers.py`: AGENTS + skills compose into
  the system prompt with **exact-path per-model isolation**; injected once on
  `Engine.system_prompt()`. **MCP layering is NOT built** — reads no `mcp.json`.
  Docs: `layered-config.md`, `per-model-configuration.md`.
- **Learn-from** — `colleague learn-from claude` copies/LLM-adapts Claude skills into `.colleague/skills/*.md`; colleague LOADS skills as text,
  does not execute them. Doc: `learn-from.md`.
- **Piloting / flight (#307-#311)** — a file-based flight plane
  (`.colleague/flight/<id>.*`) the loop feeds + reads stop/guidance from;
  pilot via `flight`/`talk`/`ask-colleague` (no daemon/socket). Armed **by default**
  at the OPERATOR repo (#310, opt out `--no-watch`/`COLLEAGUE_WATCH=0`) with a
  heartbeat (#308); plan-mode steering (#309); a senses-direct `SensesDirectRecord`
  (#311). Docs: `flight.md`, `pilotable-runs.md`.
- **Explore never wastes a run** — a read-only explore that exhausts its budget is never silent: forced synthesis (#191), honest `INCOMPLETE` (#192),
  advisory fan-out (#188), loud partials (#194). Doc: `explore-never-wastes.md`.
- **Colleague finishes what it starts** — continue-working
  (`COLLEAGUE_MAX_CONTINUE_NUDGES`, default 2) + auto-compact-on-finish (summary
  precedence in `_resolve_terminal_summary`). Doc: `continue-working.md`.
- **Plan mode** — colleague plans a task itself (spec→plan→workforce), gated at
  every step, **never self-confirms** (`colleague/plan/`); degradation-aware proposals + a honesty-only pass converge a weak model; needs a live backend.
  Doc: `plan-mode.md`.
- **CLI surface (cli-on-agentfront)** — the agent-first CLI is **rendered from one
  imported agentfront `App`** (`colleague/cli/_app.py`), not argparse; each verb is
  a rendered **tool** or **host command**; yields a single-dispatch MCP server
  (`mcp serve`, `[mcp]`) + an HTTP app; four reserved meta-verbs stay colleague-owned.
  The two largest commands are split under the 1000-line hard ceiling:
  `colleague/cli/_commands/session.py` + 10 `_session_*` mixin siblings
  (`_session_actions`/`_session_const`/`_session_dispatch`/`_session_input`/
  `_session_panels`/`_session_parser`/`_session_runs`/`_session_senses`/
  `_session_slash`/`_session_support`/`_session_talk`/`_session_voice`), and
  `colleague/cli/_commands/work.py` + 7 `_work_*` siblings
  (`_work_background`/`_work_chain`/`_work_configplane`/`_work_parser`/
  `_work_salvage`/`_work_support`/`_work_task`). Doc: `cli-on-agentfront.md`.

## v1 scope (hold this line)

**v0 → v1 graduation.** Seven deliberate, **recorded** convention changes since v0
— never silent breaches: (1) *"no LLM-generated summary"* superseded by the
fill-line `compact` move (lossy windowing retained as the floor, #156); (2) *"zero
base dependencies"* superseded by **one** sanctioned base dep, `agentfront` (base
install still pulls zero third-party transitive deps; `[mcp]` stays an opt-in
extra; `test_zero_deps.py` allow-lists exactly agentfront); (3) the no-daemon line
re-specced by the best-colleague arc (decision c17 — background one-shot + mesh
residency via the agent-lifecycle embed); (4) *"threads confined to subagents"*
extended to the session's input-line reader thread (q1, at-home arc); (5)
*presence-default-everywhere* (sanctioned increment (4)) superseded by the
**qwen-direct single-model default** (spec
`docs/specs/2026-08-22-qwen-direct-no-gemma.md`): senses and muse lobes discovery
are opt-in (the `lobes` sentinel / an explicit model id), a bare run dials exactly
one model, the front door + senses loop live behind the opt-in, and switching a
seat via `/model` is an explicit per-session operator choice — NOT a routing
policy; lobes-cli keeps advertising senses/muse, colleague ignores them by
default and says so; (6) *"threads confined to subagents + the input line"*
extended once more to ONE bounded read-only tool-batch pool —
`colleague/toolbatch.py`'s `run_batch` (cap `COLLEAGUE_TOOL_CONCURRENCY`, default
10; `1` = the sequential loop, byte-identical), the batch orchestration in
`colleague/toolbatch_loop.py` (gates on the main thread before the pool, only
`executor.execute` inside it, bookkeeping in request order after the join),
plan `adopt-from-qwen-code`; (7) the thinking-effort invariant **amended**
(#484, spike surface: exactly THREE enumerated points against a FIXED table,
opt-in `COLLEAGUE_EFFORT_SPIKES`, unarmed byte-identical) — "resolved where
each seat is built, never per turn" now reads "never per turn FROM CONTENT —
per enumerated point from a fixed table," since a spike point keys a rung by
POINT NAME, never by inspecting turn content or a model-supplied value; (8)
the same invariant amended ONCE MORE by the effort-decay arc (spec
`docs/specs/2026-09-02-effort-floor-and-decay-arms.md`): "per enumerated
point, or per fixed POSITION or OFFSET from such a point, from a fixed table" —
(the spike vocabulary grew from three to FIVE — `stall.no_write`, a count
of acting turns without a file write, and `start.first_turn`, model turn 1 —
each re-pinned in the drift test, never content-keyed) —
`colleague/effortdecay.py` keys the acting turns AFTER a spike by their
offset from it (`DECAY_TABLE` `1 → low`, then `off` until the next spike
point resets the clock), pushed through the same sanctioned escalator, opt-in
`COLLEAGUE_EFFORT_DECAY=1` (and spikes armed), unarmed byte-identical; the
reset vocabulary is exactly the three spike points, never content.
Everything else holds.

**In scope:** the runtime + every architecture part listed above (each added via an
explicit re-spec under `docs/specs/` / `docs/plans/`), within the zero-deps /
no-socket / no-daemon conventions — the daemonless line now reads: colleague ships
no socket/daemon code of its own (supervision is imported from agent-lifecycle
behind an opt-in extra; background execution is a one-shot detached child). The
`web` tool is a new surface over an operator CLI (WebGlass), never a router.
Exactly two backends: `mock` (the contract reference) and `vllm-openai`.

**Out of scope for v0** — do not add without re-speccing: **a multi-backend
router / routing policy** (equally the multi-model router: any automatic
task→model or task→backend routing decision). **Eight sanctioned increments** have landed at this line, each a
re-spec'd, FIXED, ENUMERATED surface — never a routing policy (fuller descriptions
in the architecture bullets above + their docs): (1) **dual-model deepthink
escalation** (ONE declared second model — and, under the SAME precedent, the
**purpose tools** `web_survey`/`code_survey`/`review`/`validate`/`plan`/
`handover_to_colleague`: one tool, one fixed role, one fixed seat + rung, called
explicitly by the model; spec `docs/specs/2026-08-28-purpose-tools-associate-seat.md`,
the count stays eleven); (2) **cortex/senses role split** (TWO
declared roles, FIXED boundary — cortex acts, senses perceives/presents — resolved
BY NAME from `lobes`; no senses-decides-to-answer-itself); (3) **senses live
presence + voice** (a concurrent conversational lane + two more FIXED named-role
consumers, `stt` + `tts`; the task always goes to cortex); (4)
**presence-default-everywhere** (senses gains its OWN bounded coordination-only
agentic loop (since v1.63 opt-in, not default — see convention change (5)) — `colleague/senses_loop.py`/`senses_moves.py`, prompted-JSON moves
over a tools-off completion, nothing tool-shaped on the wire — default on all
fronts, closes #300; one recorded break: an off-TTY/piped session with senses armed
carries labeled `senses:` lines, `--json` stays machine-parseable); (5)
**talking-to-one-teammate senses front door** (#276/senses-direct as a FIXED,
repo-untouching surface via a deterministic classifier, ambiguous→cortex;
SUPERSEDES "#276 stays parked"); (6) **deepthink discovered from the lobes
`muse` role** (two-machines-two-minds arc — a RESOLUTION rung only: with lobes
armed and no deepthink declared, the advertised `muse` role fills the ONE
deepthink target onto the SAME four-point enumerated surface; env/config.json
always win, no muse = byte-identical; the #332 remainder — trigger tables,
parallel deliberation, synthesis — stays OUT); (7) **realtime speech** (senses
talk lane over the rig's `/v1/realtime` WebSocket — an EARS-ONLY session
(never `response.create`; senses stays the mind), client-edge half-duplex, mic
live only on explicit per-session opt-in (`/voice`, `--voice`); turn-based
voice is the degrade floor); (8) **three-tier execution mode** (worker acts /
senses relays / cortex configures — THREE declared roles with FIXED authority
boundary, resolved BY ROLE NAME from `lobes`; opt-in via `config.json`
`three_tier` or `COLLEAGUE_THREE_TIER`; byte-identical when unconfigured;
deepthink absent in three-tier mode; the configurator a further opt-in, default
off; NEVER an automatic task-to-model routing policy); (9) **the self-learning
increment** (spec `docs/specs/2026-08-07-self-learning-arc.md`): rung-2 lesson
distillation on a FIXED author precedence (deepthink/muse > armed-lobes main >
none — a resolution rung, not a router), the `strive` bounded mode (an
operator-invoked verb with its own retry policy; `chain.CONTINUABLE_REASONS`
pinned unchanged), and the code-lesson/auto-trigger lane — each surface
enumerated, byte-identical when unarmed; (10) **the thought→action→evaluation
increment** (spec
`docs/specs/2026-08-09-post-387-program-evaluator-rename-self-learn-speci.md`):
THREE declared roles on a FIXED authority boundary — the **front** commits a
typed `Thought`, the **worker** realizes it, the tools-off **evaluator** judges
thought↔action fidelity and returns only the CLOSED vocabulary
`execute | rethink | replan | block` — resolved BY ROLE NAME from the lobes
gateway (`senses`/`worker`/`cortex`), an INDEPENDENT opt-in
(`thought_action_evaluation` / `COLLEAGUE_THOUGHT_ACTION_EVALUATION`, distinct
from `three_tier`; arming both REFUSES), deepthink absent, byte-identical when
unarmed. The evaluator sits on FIVE enumerated boundaries, never every tool
call. **Alignment is never permission** — host policy/approvals still gate every
route; the evaluator cannot write memory, and evaluator/distiller stay separate
authority contracts even on one checkpoint. NEVER an automatic task-to-model
routing policy; (11) **the model-bound-agents increment** (spec
`docs/specs/2026-08-21-model-bound-agents-411.md`): explicit agents bound to
lobes roles — Talker=`senses`, Worker=`worker` (dormant), Thinker/Coder=`cortex`,
Associate=`associate` (reserved) — a typed `AgentProfile` + per-invocation
identity/manifest/tool-surface digest, cross-role subagents that only NARROW,
typed attributable messages, the append-only task ledger + per-agent
reconstruction, an INDEPENDENT opt-in (`agents` / `COLLEAGUE_AGENTS`; arming it
with either sibling mode REFUSES), byte-identical when unarmed; model switching
ONLY through an explicit ledgered delegation — the runtime never picks a model
per turn (pinned by an AST guard); (12) **the hire increment** (plan delegation-follow-ups-a7-p3-hire, D43/D44): `hire_colleague`/`assign_to_colleague` behind `COLLEAGUE_HIRE` (default OFF, byte-identical) — a run-scoped, roster-capped employee on a FIXED builtin base role whose authored prompt can never widen a surface; presentation + explicit calls, NEVER dispatch — the runtime never picks a hire, a model, or a moment; hires die at every continuation cut. Doc: `hire-colleague.md`. `three_tier` is superseded by this increment
and kept as the benchmark baseline. NEVER an automatic task-to-model routing
policy.

Anything beyond those twelve is still the excluded router; document the distinction
honestly. **Still explicitly OUT**, each parked pending its own re-spec: the
**retrieval-consumption lane of #277** (`embedder`/`reranker` roles are
discoverable in the lobes `/capabilities` contract but colleague consumes only
`cortex`/`senses`/`stt`/`tts`); an **execution sandbox**; a **colleague-owned
persistent daemon/server, socket code, or transport** (background one-shot + mesh
residency via the agent-lifecycle embed ARE in scope per c17; anything beyond is
excluded); **Codex/Claude/Gemini adapters**; a **`--no-hooks` escape hatch** (no
such flag — the approval gate is a policy gate, not a sandbox; never invent it);
and a **live MCP *client*** (colleague reads no `mcp.json`, registers no external
MCP tools; never invent an MCP-client surface). **Re-spec'd IN scope:** the **MCP
*server* bonus** — `colleague mcp serve`, a single-dispatch surface from the same
agentfront `App`, behind `[mcp]`; NOT a colleague-owned daemon (the blocking stdio
loop is agentfront's `serve_stdio`; base install byte-identical). Adding an
excluded feature means scope crept.

## The all-engines rule

Mirror of culture's all-backends rule: contract behavior (task fields, result shape, the loop, the artifact) must hold for **every** backend. `mock` is the contract reference — a change that makes `mock` and `vllm-openai` diverge in result shape is a bug (guarded by `tests/test_e2e_mock.py`).

## Conventions

- **One sanctioned base dependency: agentfront.** `pyproject.toml` declares
  `dependencies = ["agentfront>=0.15.0"]` — the first and only sanctioned base dep (a recorded break from `dependencies = []`; agentfront's core is pure-stdlib) — so
  a base `pip install colleague` still pulls **zero third-party** beyond agentfront
  (the vLLM adapter speaks OpenAI over `urllib`; commands/hooks use `json`/
  `subprocess`/`pathlib`). Don't add a *second* base dep without a re-spec (dev-only deps → the `dev` group). Two opt-in extras, never base: `[otel]` (the OTel SDK,
  imported lazily in `colleague/telemetry/_otel.py` only) and `[mcp]` (no
  socket/daemon at base). `tests/test_zero_deps.py` allow-lists exactly agentfront.
- **Agent-first CLI — rendered from an imported agentfront `App`.** A new verb is a
  `colleague/cli/_commands/` module with a **`register_into(app)`** hook, registered
  as a **rendered tool** (`app.tool`, read-only, exits 0, fails only by `raise`) or
  a **host command** (`app.add_command`, custom exit / streaming / blocking TTY).
  Results→stdout, errors→stderr; every command supports `--json`; failures raise
  `CliError`. The four reserved meta-verbs (`doctor`/`overview`/`learn`/`explain`)
  stay colleague-owned via the legacy-parser shim in `main()`. Doc: `cli-on-agentfront.md`.
- **The vLLM adapter only touches the OpenAI surface** — retargeting any
  OpenAI-compatible server must stay a config change, never a code change.
  THREE per-turn carve-outs, all graceful-degrade so a server without them stays
  a config change: — only when lobes is ARMED — the call-time stale-pin
  refresh's one same-role lookup against the gateway (c11/h8; lobes unarmed =
  the original error surfaces unchanged, zero non-OpenAI calls); the
  per-seat `chat_template_kwargs` body key on the existing `/chat/completions`
  call (the thinking-effort ladder, #416 — a vLLM extension a server may
  ignore; unset = byte-identical, a ladder-400 retries once without the key);
  and — the **fourth carve-out**, beside `/tokenize`, the stale-pin refresh and
  `chat_template_kwargs` — **the per-model sampling keys a matched row
  explicitly sets** (#479): `temperature`/`top_p`/`presence_penalty` are plain
  OpenAI keys, so on the builtin Qwen3.8 table `top_k` is the ONLY vLLM
  extension key that reaches the wire (`min_p`/`repetition_penalty` are card
  values already at the server default and are filtered off it). A model
  matching no row sends NO sampling key — byte-identical to pre-#479 — which is
  why NO retry-without-the-keys path ships (the asymmetry with the ladder-400
  retry is deliberate); `COLLEAGUE_SAMPLING=0` is the per-process kill switch.
  Plus ONE run-scoped probe, never per turn: a single `/tokenize` POST at run
  start (exact turn-1 count + `max_model_len` window discovery, `None` on
  error; `COLLEAGUE_EXACT_TOKENS=1` restores the per-turn call — the
  adopt-from-qwen-code arc, t12). Docs: `thinking-effort.md`, `sampling.md`,
  `graceful-degradation.md`.
- **Hook commands run as subprocesses, never imported.** `colleague/hooks.py` uses
  `subprocess.run` (shell=True) in the repo working dir; command templates are
  Markdown text, never executed. No code path opens a socket or forks a daemon.
- **Threads and subprocesses are confined to an explicit sanctioned list.**
  `tests/test_boundary.py`'s `_SUBPROCESS_ALLOWED` is the authority — a module
  imports `subprocess` only by joining that list with a stated reason. The
  sanctioned subprocess consumers: `hooks.py`, `tools.py`, `handoff.py`,
  `neighbours.py`, `culture.py`, `devague.py`, `worktrees.py`, `lint.py`,
  `resident/steward.py`, `affectedtests.py`, `background.py` (the one-shot detach —
  `Popen(start_new_session=True)`, no `.wait()`/`.poll()`), `memory.py`,
  `livecheck.py`, `coherence.py`, `experiment.py` (allow-list exactly `sloth`),
  `strive.py` (the operator-supplied measure command, approval-gated like
  `run_command`), and `correction.py` (git/gh for the integrator-correction
  diff). Threads (`concurrent.futures`) stay confined to
  `colleague/subagents.py`, `colleague/cli/_commands/_input_line.py` (the
  session's colour-TTY reader thread; any failure degrades to cooked-mode),
  `colleague/realtime.py`, and `colleague/toolbatch.py` (the read-only tool-batch
  pool behind `run_batch`, convention change (6)); `colleague/associate.py`
  imports `threading` for ONE lock around the once-per-process `/tokenize`
  probe — no thread. Every
  shell-out targets an operator-installed CLI via explicit allow-listing; none opens
  a socket or forks a daemon. `worktrees.py`'s admin mutations are serialized by an
  advisory `fcntl` lock (#239).
- **The runtime owns hooks, telemetry, the per-model-hooks overlay, the `culture` /
  `devague` tools, the approval gate, `WorkStats`, and the feedback store — not
  backends** (they load in the RUNTIME — `colleague/loop.py` and its `loop_*`
  siblings, the `_work_*`/`_session_*` command modules — never in
  `colleague/engines/`, which is the line that matters; a hook that fires on
  `mock` fires identically on `vllm-openai`). Telemetry off, and an absent
  feedback/`approvals.json`, are strict no-ops. **Tokens are exactly what `usage`
  reports — never estimated** (reasoning is chars/bytes; no tokenizer, no `bytes/4`).
  The `devague` allow-list excludes `confirm`/`reject`/`export`; each tool shells out
  to an operator CLI — no socket/daemon/import; colleague reads no `mcp.json` and
  adds no live MCP client. Approvals are **checksum-only in v0** (`version` pinning
  is a follow-up, not built — do not document it as existing).
- **Repo-shipped hooks run by default (trusted-operator model D2).** There is no
  `--no-hooks` flag today. The approval gate (`colleague/policy.py`) is the landed
  increment of the per-repo hook trust gate (checksum on hook scripts, token on
  `run_command`); it is a **policy gate, not a sandbox** (bypassable by
  `sh -c`/pipelines). Document this gap; never document a non-existent `--no-hooks`
  flag.
- **The `doctor` verb is colleague's health check.** A configuration-readiness
  rubric (identity/provider/usage/engines/otel/environment), exit-1 on unhealthy;
  the **usage** group warns when a bare work item would pick the no-op `mock`
  backend. `doctor --probe` adds the one gated network check (`provider_reachable`).
- **Hard 1000-line file-length ceiling.** `tests/test_file_length_limit.py`
  fails the suite on any tracked source file over 1000 physical lines, with an
  empty, shrink-only `GRANDFATHERED` escape hatch; the soft
  `tests/test_file_length_ratchet.py` (d6) is the complementary per-file
  baseline that only tightens. `scripts/pin_audit.py <path>` is the read-only
  pre-split safety net (path literals, monkeypatch targets, subprocess/thread
  allow-list membership) run before splitting an oversized module. Doc:
  `file-length-limit.md`.

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run pytest -n auto                     # tests (parallel)
uv run colleague backends list          # discovered backends (wheels = deprecated alias)
uv run colleague work "<task>" --repo . --engine mock --no-pr
# Backend resolution: --engine > COLLEAGUE_ENGINE > vllm-openai (never silent mock, #53).

# Extensibility layer (templates / hooks / approvals / session):
uv run colleague work --command <name> [args…] --repo . --engine mock --no-pr
uv run colleague commands list --repo .          # discovered templates (also: hooks list)
uv run colleague hooks approve <script> --repo . # checksum-approve a hook (also: commands approve)
# approve verbs accept --algo sha256|md5 (default sha256) and --json.
uv run colleague session --repo . --engine mock  # interactive palette (--pr to push+PR)

# ROI loop (feedback; work stats are always-on in the artifact):
uv run colleague feedback record last --rating 4 --notes "…" --repo .  # grade the last work item
uv run colleague feedback show last --repo .                           # read it (no-op if ungraded)

# Telemetry (opt-in): uv sync --extra otel; then COLLEAGUE_OTEL_ENABLED=1 +
# OTEL_EXPORTER_OTLP_ENDPOINT=… to emit traces.

# Lint + gates CI enforces:
uv run black --check colleague tests && uv run isort --check-only colleague tests
uv run flake8 colleague tests && uv run bandit -c pyproject.toml -r colleague
uv run teken cli doctor . --strict        # agent-first rubric gate
```

The live vLLM proof is opt-in (`COLLEAGUE_VLLM_E2E=1 uv run pytest
tests/test_vllm_live.py`) and needs a rig exposing tool calling
(`--enable-auto-tool-choice` + a model-appropriate `--tool-call-parser`, e.g.
`hermes` / `qwen3_coder`).

## The `ask-colleague` skill (first-party)

colleague ships one **first-party** Claude Code skill,
[`ask-colleague`](.claude/skills/ask-colleague/) — the *inverse* of the vendored
skills. It hands a scoped task to a *different* backend/mind (not a stronger one;
diversity is the point). Four verbs over `colleague work`/`plan`: **explore**
(read-only), **review** (a diverse second opinion on the committed `<base>...HEAD`
diff — the headline verb), **write** (a small change — previews by default;
`--apply` lands a branch, `--pr` opens a PR), **plan** (the whole
spec→plan→workforce arc — the inverse of `/think`). explore/review run in a
throwaway `git worktree` (no side effects; "outsource this" still triggers it).
Details: [`docs/features/ask-colleague.md`](docs/features/ask-colleague.md).

**Claude thinks and designs; Colleague does the field-work.** Delegate mechanical
field-work (sweeps, scoped edits, residual-reference checks, a second opinion on a
diff) to Colleague **reflexively**, and **prefer it over spawning a Claude
sub-agent** (a different, worktree-isolated, verifiable mind); keep sub-agents only
for work needing Claude's judgment or context. Multiple instances run in parallel,
but the local GPU serializes requests — cap at ~2 loops and raise
`COLLEAGUE_TIMEOUT=300` (~4 at the default 120s time out with zero commits).
Colleague's output is a **second opinion to verify and own, never authority**:
`git diff main` and re-run the tests before trusting a landed change (a local model
can drop or misreport edits). **A bare `colleague work`/`drive`/`session --repo .`
refuses a dirty tree** unless `--allow-dirty` (#149, `handoff.working_tree_dirty`) —
it blocks sweeping your uncommitted **tracked** edits onto the work branch (the
`ask-colleague` verbs stay worktree-isolated and propagate `--allow-dirty`).

## Git workflow

Branch out, implement, **bump the version every PR** (the `version-check` CI job
blocks merge otherwise — use the `version-bump` skill), create the PR via the
`cicd` skill, address review, merge. Distribution / command / import package are
all `colleague`. PyPI publish is via Trusted Publishing on merge to `main`.

## Conventions and workflow

**Memory discipline — recall before, remember after.** This repo keeps its eidetic
memory **in-repo and public**: records resolve to `<repo-root>/.eidetic/memory` —
committed and shared with the team and mesh peers (the `claude` and `colleague`
backends both read the same `colleague` scope). Make it a per-task habit:

- **`/recall` before non-trivial tasks** — search the area you're about to touch
  (prior decisions, gotchas, "have we done this before?") so you build on what's
  known instead of re-deriving it.
- **`/remember` when something worth keeping surfaces** — a non-obvious decision +
  its rationale, a constraint, a fix and *why*, a gotcha that cost time — as it
  happens.

A plain `/remember` lands the note in `./.eidetic/memory` (public; in-repo routing
needs `eidetic >= 0.10.0`); `--visibility private` keeps it in `$HOME` (uncommitted)
and `/recall` reads both. Don't store what the repo already records (code structure,
git history, this file, `CHANGELOG.md`) — store what you'd have to re-derive. These
are the `recall`/`remember` skills, backed by the `eidetic` store.
