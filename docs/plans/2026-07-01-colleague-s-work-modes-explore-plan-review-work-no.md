# Build Plan — colleague's work modes — explore, plan, review, work — now fit the machine they run on: each mode carries its own context/compute profile (step budget, context budget, synthesis reserve, timeout) instead of one global knob set; skills are curated to the mode instead of always-all; subagent orchestration respects the served model's real concurrency; every work item carries a visible task+goal; and all of it is legible on all three surfaces — the human TUI, the agent markdown/TAUI, and the bot/app JSON — with each improvement area tracked as a concrete GitHub issue.

slug: `colleague-s-work-modes-explore-plan-review-work-no` · status: `exported` · from frame: `colleague-s-work-modes-explore-plan-review-work-no`

> colleague's work modes — explore, plan, review, work — now fit the machine they run on: each mode carries its own context/compute profile (step budget, context budget, synthesis reserve, timeout) instead of one global knob set; skills are curated to the mode instead of always-all; subagent orchestration respects the served model's real concurrency; every work item carries a visible task+goal; and all of it is legible on all three surfaces — the human TUI, the agent markdown/TAUI, and the bot/app JSON — with each improvement area tracked as a concrete GitHub issue.

## Tasks

### t1 — R1: mode-profile catalog module (new colleague/profiles.py): per-mode profiles for work/plan/explore/review + pure resolve_profile()

- covers: c10
- acceptance:
  - resolve_profile returns a complete profile (max_steps, context_budget_fraction, synthesis_reserve_steps, timeout, fillline_threshold) for each of work/plan/explore/review and None for absent/unknown mode
  - a drift test pins exactly one profile per session_modes.MODES entry so a new mode cannot ship without a profile decision

### t2 — R1: EngineConfig.resolve gains the profile default layer (config.py) + ContextControls threading (loop.py) + per-model profile overlay via sanitize_model

- covers: h1
- acceptance:
  - with a mode set, unset knobs fill from the profile while an explicit flag or COLLEAGUE_* env still wins (precedence test: flag > env > config.json > profile > built-in)
  - a run with no mode resolves byte-identical to today (e2e mock shape test unchanged)
  - a per-model profile overlay resolves via the exact sanitize_model path — model X never loads model Y's overlay

### t3 — R1: wire mode->profile at the entry points: colleague work --mode + session mode selection (work.py, session.py)

- depends on: t1, t2
- acceptance:
  - colleague work --mode m and a session mode selection resolve the same profile through one code path (assert on the resulting ContextControls)
  - session explore/review runs get profile budgets with zero env vars set

### t4 — R1: ask-colleague.sh adopts native profiles (drop caller-side env overrides)

- depends on: t3
- covers: c8
- acceptance:
  - the wrapper no longer exports max-steps/synthesis-reserve env defaults — it passes --mode; an explicit --max-steps still overrides in both directions (wrapper test)

### t5 — R2: backpressure helpers (new colleague/backpressure.py): rolling turn-latency classification against timeout fractions

- covers: c11
- acceptance:
  - pure helpers classify a synthetic latency series into armed/escalated/cleared against timeout fractions with no clock and no thread (unit tests)

### t6 — R2: loop integration — armed backpressure shrinks the next window and throttles subsequent fan-out; advisory recorded (loop.py)

- depends on: t5, t2
- covers: h2, c4
- acceptance:
  - when rolling latency crosses the arm threshold the next completion gets a smaller history window and subsequent batch_spawn concurrency is reduced; a healthy-latency run is byte-identical (strict no-op test)
  - tightening lands in the artifact as an advisory warning, never an error, and never switches model or backend

### t7 — R3: record mode on TaskResult + artifact, omit-when-None (contract.py + work.py wiring)

- depends on: t3
- covers: c12
- acceptance:
  - TaskResult.mode round-trips through the artifact when a mode drove the run and is absent otherwise (e2e mock shape unchanged without mode)

### t8 — R3: file the upstream agentfront ask — TAUIState capacity block, phase, goal + mode/phase event kinds (the #249 upstream-first pattern)

- covers: h3
- acceptance:
  - an agentfront issue is filed naming the exact state/event additions and colleague's consumer-side adoption plan; the link is recorded in docs/features

### t9 — R3: capacity/phase/goal in the session cockpit via the existing generic panel walk (session.py, _tui_sink.py) — no schema bump needed

- depends on: t3, t7
- covers: c2, h9
- acceptance:
  - a Capacity panel (budget tokens, last prompt tokens, fill-line armed/crossed, capacity decision), a phase-aware status (thinking/synthesizing/compacting) and the task goal line render in the live cockpit AND carry to markdown + TAUI JSON via the generic panel walk (mirror/snapshot test)
  - phase display never creates a phantom work step (the #206 invariant holds in the session sink test)

### t10 — R4: populate built-in role skill subsets (roles.py) — explorer/planner/reviewer/validator curated, writer keeps all

- covers: c13
- acceptance:
  - explorer/planner/reviewer/validator get non-None skill_subset; writer keeps the full catalog; a composed explorer prompt omits release/cicd-class skills (composition test)

### t11 — R4: token-capped skill composition with priority + omitted-note, and a composed-vs-omitted inspection surface (layers.py + skills verb)

- depends on: t10
- covers: h4
- acceptance:
  - over-cap catalogs drop whole lowest-priority skills and append an omitted-N-skills note naming them — never a mid-skill truncation; an uncurated role/mode under cap keeps today's full catalog (unit tests, count via the pluggable count_tokens seam)
  - the skills inspection verb shows composed vs omitted for a given role/mode at a given budget

### t12 — R5: child budget scaling at fan-out + read-only batches skip the merge slot (subagents.py)

- covers: c14
- acceptance:
  - at width W>1 each child resolves a clamped share of the parent context/step budget; width 1 is byte-identical; an explicit per-child override wins (unit tests)
  - a batch whose children are all read-only roles does not reserve the merge slot (effective-width test)

### t13 — R5: rig-level cooperative concurrency budget (new colleague/rig.py + .colleague/rig.json, file-based slots; wiring in subagents.py + work.py)

- depends on: t12, t3, t7
- covers: h5
- acceptance:
  - with rig.json declaring concurrency N, spawns beyond N wait on an atomic file-based slot with stale-lock recovery and the wait is visible in the progress feed; absent rig.json is a strict no-op (no lock artifacts created); no daemon, no socket, no threads outside the sanctioned modules

### t14 — R6: goal fields on the contract (contract.py): Task.goal + Task.acceptance, TaskResult.acceptance_outcomes, SubResult.parent — all omit-when-None

- depends on: t7
- covers: c15
- acceptance:
  - an artifact authored without goal/acceptance/lineage is byte-identical (round-trip + e2e mock shape test)

### t15 — R6: loop injects the goal/acceptance block + ONE bounded pre-finish self-check turn recording per-criterion outcomes (loop.py)

- depends on: t14, t6
- covers: h6
- acceptance:
  - with Task.acceptance set, the prompt carries a distinct goal block and one bounded self-check turn records per-criterion criterion/met/evidence as ADVISORY (never flips run status, reuses the lint fix-turn save/restore pattern); with none set the loop is byte-identical

### t16 — R6: plan workforce passes PlanItem.acceptance structurally into Task.acceptance + children record parent task_id lineage (plan/workforce.py, subagents.py)

- depends on: t14, t13
- acceptance:
  - workforce children receive structured acceptance (not only prose) and child artifacts name their parent task_id so a subagent tree is walkable from artifacts alone (integration test)

### t17 — R6: plan continue — surface checkpoint resume as a first-class verb (plan/cli_driver.py + checkpoint.py)

- acceptance:
  - colleague plan continue resumes an interrupted plan run from the last resolved gate without re-asking resolved gates (integration test on a simulated kill)

### t18 — Docs: feature docs per area + CLAUDE.md architecture notes + CHANGELOG + cross-link issues #254-#259 to their landing waves

- depends on: t4, t9, t11, t15, t16, t17
- covers: c1, c5, c7, h8, h12, h13, h14
- acceptance:
  - each shipped feature has a docs/features page naming its scope line and honest limits; CLAUDE.md updated; CHANGELOG entry per the version-bump convention; each issue cross-linked to the plan wave that lands it; stale before-state statements corrected in issue text

### t19 — Validation: e2e mode-run on mock + live on the rig when a tool-calling model is served

- depends on: t4, t9, t11, t15, t16, t17
- covers: c3, h10, h11
- acceptance:
  - on mock: a --mode explore run completes with profile-resolved budgets, capacity panel rendered, artifact carrying mode, zero per-run env tuning
  - on the live rig once a tool-calling model is served: an ask-colleague explore completes inside its profile; if the rig is still down the degradation to mock-only validation is recorded honestly, never claimed as live

## Risks

- [unknown_nonblocking] Exact per-mode profile numbers need live tuning on a working served model — ship conservative defaults in t1, tune in follow-up PRs (task t1)
- [unknown_nonblocking] Full three-tier parity (TAUIState capacity/phase fields + event kinds) is gated on an agentfront release; colleague-side panels (t9) + artifact mode (t7) land independently of the upstream bump (task t8)
- [unknown_nonblocking] The rig currently serves NO tool-calling model (27B stale-listed 404, 4B lacks tool-call parser — see #66 comment); t19 live validation degrades to mock-only until serving is fixed (task t19)
- [out_of_scope] MCP streaming progress (bot follows a live run over MCP) — separate re-spec, not in this plan
- [follow_up] Repeated compaction (#156 v2), custom role tool-allowlists + checksum-gating of role files, capacity-heuristic v2 — documented follow-ups, deliberately not tasks here
