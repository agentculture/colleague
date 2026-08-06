# Build Plan — change-content consumption lane

slug: `change-content-consumption-lane` · status: `exported` · from frame: `change-content-consumption-lane`

> A three-tier colleague run now consumes what cortex configures: an applied worker.prompt.strategist note lands verbatim (bounded) in the worker's next-episode composed system prompt, an applied worker.tools narrowing filters the next episode's offered tool schema AND its executor allow-list (narrows, never adds), the work front arms the config plane itself — lifecycle constructed when three-tier is armed, configurator windows before episode 1 and between episodes, config events folded onto TaskResult.`config_events` — cortex knowledge entries are auto-stamped with their host-known entry-level origin, the flight feed names the seat that actually acts, and the NEBULA RUN benchmark re-runs strategist-live against the recorded pre-#366 baseline.

## Tasks

### t1 — Lattice content field + empty-narrowing refusal

- instruction: colleague/lattice.py + tests/`test_lattice.py` only. Add optional content: str field to ChangeUnit (default empty). Extend `_check_field_target_shape`: content rides only the two \*.prompt.strategist targets; add the length check against layers.`STRATEGIST_SECTION_MAX_CHARS` (import the constant, do not duplicate 4000); add the empty-`tool_ids` refusal to the worker.tools branch. Write the failing tests FIRST. Do not touch the forbidden-key scan.
- covers: c2, h2, c26, h20
- acceptance:
  - a ChangeUnit with content on worker.prompt.strategist or senses.prompt.strategist validates; content on any other target refuses whole with a reason naming the field/target shape
  - content whose stripped length exceeds `STRATEGIST_SECTION_MAX_CHARS` refuses whole; a content-less strategist unit stays valid (every existing `test_lattice.py` case still passes)
  - a worker.tools unit with an EMPTY `tool_ids` list refuses whole with a reason naming the empty narrowing

### t2 — Flight run-start line names the acting seat

- instruction: colleague/flight.py + its tests. Thread the seat label into `append_run_start` (default cortex — the unarmed byte-identical floor). Prefer resolving the seat where the flight handle is constructed (it can read the resolved config) over changing loop.py; if the loop call site must pass one arg, keep the change to the run-start emit only — the turn loop stays untouched (h11).
- covers: c9, h9
- acceptance:
  - with three-tier armed the run-start feed line names the worker seat; unarmed emits the current cortex-started line byte-identically (both arms tested against the recorded feed JSON)

### t3 — Tool-narrowing consumption: schema + executor intersect

- instruction: colleague/tools.py (one narrow helper beside `curate_schemas`), colleague/engines/`vllm_openai.py`, colleague/engines/mock.py, PLUS one typed field on colleague/config.py EngineConfig: `config_lifecycle` (Optional, default None — EngineConfig is a plain unfrozen dataclass; the loop already reads it via getattr forward-compatibly, this makes the seam typed). Read the snapshot via config.`config_lifecycle` at work() start -> snapshot().`tool_set`. Executor: compose the narrowing into the allowlist seam it already has (allowlist=role) — never a second refusal mechanism. Snapshot `tool_set` () means not-narrowed (c26 made narrow-to-nothing unrepresentable).
- covers: c8, h8
- acceptance:
  - with an applied non-empty snapshot `tool_set`, the offered schema is the intersection of the role-curated surface and the `tool_set`, on BOTH mock and vllm-openai (all-engines test)
  - the executor refuses a narrowed-away tool with the same refusal shape role withholding produces; a `tool_set` entry outside the role surface adds nothing
  - an empty/absent narrowing is byte-identical to today on both engines

### t4 — Review-input assembler (pure)

- instruction: NEW module colleague/reviewinput.py + tests/`test_reviewinput.py`. Two pure functions returning ConfiguratorReviewInput; accept only Task/TaskResult objects, never a message list (structural pin 1 at the assembler). Bound the digest (cap total chars, truncate file lists with an honest '+N more'). No I/O.
- covers: c27, h21
- acceptance:
  - a pure function composes the before-episode-1 digest from Task instruction + goal/acceptance, and the between-episodes digest from a TaskResult's terminal facts (summary, exit reason, steps, changed files, gate outcomes), with a hard size bound
  - no field of the worker conversation history appears in the output (a history-shaped input is not even accepted by the signature)

### t5 — Lifecycle folds real text; replace semantics for strategist + tools

- instruction: colleague/configlifecycle.py + tests/`test_configlifecycle.py`. In `_apply_change`: `WORKER_PROMPT_STRATEGIST` folds (change.content.strip(),) REPLACING the tuple (not appending); `WORKER_TOOLS` already replaces — add the test stating it. Update the module docstring paragraphs that call the marker opaque (they become false). `child_snapshot` semantics unchanged here (t9 consumes it).
- depends on: t1
- covers: c3, h3, c29, h23, c30, h24
- acceptance:
  - an applied strategist unit's verbatim stripped content lands in snapshot.`strategist_sections` (no more origin#N markers); the digest moves exactly once per applied proposal and only at a sanctioned window (existing timing pins still green, marker expectations UPDATED)
  - a second strategist application across a later window leaves exactly ONE current note (the later); a unit at the content cap applies without raising
  - a second worker.tools application REPLACES the narrowed set — narrow-then-replace widens back up to (never past) the role-curated ceiling in the consuming intersect

### t6 — Configurator: origin auto-stamp, content key, visible degradation

- instruction: colleague/configurator.py + colleague/configevents.py + tests. Stamp entry origins in `_build_change_unit` (host-known fact — set entry\['origin'\]='cortex' when absent; never overwrite a present one before discarding? NO: discard any model-supplied origin then stamp — authority is never self-declared). Add `EVENT_KIND_DEGRADED` to configevents `EVENT_KINDS` (contract coercion picks it up automatically); append it in `review_and_queue` on both degraded paths with the reason.
- depends on: t1
- covers: c4, h4, c31, h25
- acceptance:
  - a cortex knowledge entry lacking origin validates post-stamp with origin=cortex; a model-supplied origin (entry-level or unit-level) is still discarded
  - a changes entry may carry content (string) for a strategist target; content joins `_RECOGNIZED_CHANGE_KEYS`; `_SYSTEM_PROMPT` documents the content field and drops the carries-no-extra-fields-today line
  - both degraded early-returns (no cortex dial; completion exception) append a visible degraded record to the stream, distinguishable from a healthy empty-changes reply which appends nothing and is NOT degraded

### t7 — Prompt consumption seam: strategist text into the composed system prompt

- instruction: colleague/engine.py (base `system_prompt`) + tests. Read getattr(config, '`config_lifecycle`', None); if present and snapshot.`strategist_sections` non-empty, pass the single current note as `strategist_section`= RAW text to `system_prompt_for` (and `compose_role_prompt` path equally — check its signature; if it lacks the kwarg, thread it). layers.py should need nothing (c17); if it does, record the deviation.
- depends on: t5
- covers: c7, h7, h27
- acceptance:
  - with an applied strategist note on the attached lifecycle, mock and vllm-openai compose the SAME strategist section into their system prompt (all-engines test on the shared base-class path); no note composes byte-identical to today
  - the final composed prompt contains exactly ONE strategist heading (the RAW-text contract: engine passes snapshot content, never a pre-composed section), and a strategist-only composition still carries the engine base (the #363 T3 trap pinned)

### t8 — Contract + artifact: fold surface and verbatim applied content

- instruction: colleague/contract.py + colleague/artifact.py + tests. The mapper lives beside `_coerce_config_events` in contract.py (configevents.py belongs to t6 this wave — do not touch it). Boundary events map onto the baseline/boundary vocabulary configevents already has; pick the honest kind, never invent one here. The content field rides ConfigEvent's existing payload shape if it has one, else extend `to_dict`/`from_dict` compatibly (old artifacts must still load).
- depends on: t5, t6
- covers: c6, h6, c36, h29
- acceptance:
  - a mapper turns configlifecycle events + applications into configevents.ConfigEvent records (kinds mapped honestly: proposed/refused/applied/boundary); TaskResult.`config_events` round-trips them through `to_dict`/`from_dict` and the artifact on disk
  - each APPLIED strategist unit's verbatim content rides the applied record (bounded by the lattice cap); refused records stay reason-only; an unarmed run's artifact omits `config_events` entirely (omit-when-empty pinned)
  - an artifact update helper rewrites `config_events` on an already-persisted artifact (the front folds AFTER the loop wrote it) and `read_artifact` round-trips

### t9 — Work front arms the config plane

- instruction: colleague/cli/`_commands`/work.py + a NEW tests/`test_work_config_plane.py`. Arm inside `execute_work`/`execute_work_chain` so BOTH fronts (CLI + session) inherit — never in `cmd_work` argv parsing. Read arming from the resolved config (config.worker is not None), configurator via `configurator_enabled`(`repo_path`). Use reviewinput assemblers (t4). Reset/fresh lifecycle per top-level task (the h22 rule); --continue rounds are fresh top-level tasks (q1 decision recorded on the frame).
- depends on: t4, t6, t8
- covers: c5, h5, c28, h22
- acceptance:
  - three-tier armed (config.worker resolved): lifecycle + stream constructed, catalog built from the run's actually-resolved tool surface, `run_configurator_window` at `WINDOW_BEFORE_EPISODE_1` before the first dispatch (plain work AND chains) and `WINDOW_BETWEEN_EPISODES` in `execute_work_chain`'s go-verdict path; lifecycle attached to config so loop + engines consume it
  - no three-tier: byte-identical (no lifecycle, no windows, no events; artifact shape unchanged). three-tier armed + configurator OFF: lifecycle constructed, windows are strict no-ops (reviewed=False), ZERO completions issued — both pinned
  - the cumulative fold updates BOTH the in-memory TaskResult and the on-disk artifact after each window (q2 decision); a run killed between fold and artifact-update loses at most the last window's events (stated in a test comment, crash-window honest)

### t10 — Subagent child inheritance consumes the snapshot

- instruction: colleague/subagents.py + tests. Read `child_snapshot`() from the parent's lifecycle at spawn and hand the child a tiny FROZEN adapter that quacks like the lifecycle's read surface (snapshot() returning the frozen snapshot; nothing else) on the child config's `config_lifecycle` field — the t3/t7 engine seams then consume it unchanged. Never hand the child the real lifecycle object (children never propose, never observe turns). Prompt assertion needs t7's seam — dep recorded.
- depends on: t3, t5, t7
- covers: c35, h28
- acceptance:
  - a child spawned under an applied narrowing cannot call a narrowed-away tool (offered schema and executor both refuse — pinned); its composed prompt carries the current strategist note; grandchildren at depth>1 inherit identically
  - a child spawned with no narrowing applied is byte-identical to today; queued-but-unapplied proposals never reach any child

### t11 — Structural pins re-proven + hermetic end-to-end proof

- instruction: tests only: extend tests/`test_configurator_boundary.py` + tests/`test_loop_config_lifecycle.py`, NEW tests/`test_content_lane_e2e.py`. Each lane's new test must FAIL on the pre-arc tree (h17 failing-first — state the pre-arc failure in the test docstring). This task owns the c1/h1 announcement-level proof: one e2e test per announcement lane.
- depends on: t6, t7, t8, t9
- covers: c10, h10, c22, h16, c23, h17, c1, h1, c32, h26
- acceptance:
  - `test_configurator_boundary.py` still proves loop.py never imports configurator AND no cortex-authored text enters the worker MESSAGE HISTORY with content flowing — the composed system prompt asserted as the ONLY carrier; `test_loop_config_lifecycle.py` proves mid-episode digest constancy with a real applied note
  - a hermetic mock end-to-end test: scripted cortex reply with strategist content + tool narrowing -> next episode's composed prompt carries the text, offered schema narrowed, artifact carries the applied content — no rig, no network
  - containment pinned: over-cap refuses whole, the section renders only under the named heading in every engine's prompt, an UNARMED run has no code path by which cortex text reaches any prompt (grep-level + behavioral)

### t12 — Docs flip + zero-diff boundary verification

- instruction: Docs only: docs/features/three-tier.md, docs/experiments/2026-08-06-experiment-c-strategist-value.md. Claim only what a cited test proves (h14). CLAUDE.md's three-tier bullet gets one line on the consumption lane pointing at the feature doc (trim discipline).
- depends on: t9
- covers: c16, h14, c24, h18, c11, h11, c12, h12
- acceptance:
  - docs/features/three-tier.md Honest limits rewritten: d2/#366 sections describe the WIRED lane citing the pinning tests; the strategist-ships-opt-in-and-OFF statement survives verbatim; the value claim stays conditional on the benchmark (h18)
  - boundary verification recorded: git diff main shows colleague/chain.py zero-or-docstring-only and no colleague/loop.py turn-loop changes — cited in the docs task's PR notes
  - docs/experiments/2026-08-06-experiment-c-strategist-value.md gains the origin-stamping fix pointer (repeat verdict lands with its own record)

### t13 — Experiment C repeat: origin-stamping fix, end-to-end verified+applied

- instruction: Live leg (rig required). Re-run the EXISTING pre-registered runner — do not redesign the experiment. Record the repeat as a new dated file under docs/experiments/ linking the original; an inert or negative outcome is recorded as-is (h13 discipline applies here too).
- depends on: t6, t9
- covers: h4
- acceptance:
  - re-running the committed experiment C mismatch fixture (tools/experiments/`experiment_c.py`) on the live rig yields verified+applied where the baseline run refused; results recorded in a dated docs/experiments/ record with the pre-registered protocol referenced
  - 0 entry-origin refusals across the repeat's mismatch trials; the control arm still shows 0 false interventions

### t14 — NEBULA RUN benchmark: strategist-live arm vs recorded baseline

- instruction: Live leg, LAST by design (the c23-precedent gate: benchmark before delivery summary + PR close-out of the arc). Seed /home/spark/git/ship-game fresh (one seed commit, clean tree). Env: `COLLEAGUE_THREE_TIER`=1 `COLLEAGUE_CONFIGURATOR`=1 `COLLEAGUE_TIMEOUT`=420 `COLLEAGUE_MAX_STEPS`=80, lobes-armed. Continue policy: --continue until done, rounds counted. Consumption evidence comes from the artifact (q5 verbatim content decision) — cite task ids, not vibes.
- depends on: t9, t11, t13
- covers: c15, h13, c25, h19, c21, h15
- acceptance:
  - fresh ship-game repo, the VERBATIM protocol prompt and env from the #366 comment, changing ONLY the configurator arming; acting seat artifact-verified as the worker
  - mechanical stats (rounds, steps, wall time, finish states, files/LOC, `config_events` counts incl. >=1 verified+applied+CONSUMED change with artifact evidence, 0 entry-origin refusals) posted to #366 BEFORE quality grading; an inert strategist outcome reported as-is
  - the baseline-vs-live comparison table lands on #366 with the operator-grade column left to Ori; the #366 thread then carries protocol + results end to end (h15)

## Risks

- [unknown_nonblocking] per-window cortex review latency on a serializing rig — one extra completion per armed window; unmeasured until t14 runs (frame park v1)
- [follow_up] oilcheck/doctor configurator-armed readiness line (oilcheck/`three_tier.py` mirrors three-tier arming only) — follow-up, not this arc (frame park v2)
- [unknown_nonblocking] live rig availability + model set drift for t13/t14 (worker/cortex/senses adverts have gone stale before — #363 section 7)
