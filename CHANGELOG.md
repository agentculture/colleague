# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.71.0] - 2026-08-31

### Added

- The hire increment (t9-t18/t20, the twelfth sanctioned surface): `hire_colleague`/`assign_to_colleague` behind `COLLEAGUE_HIRE` (default OFF, byte-identical unset) — Hire/Roster (cap 4) with a prompt-never-grants hired role, a bounded two-round tools-off negotiation, one child per assignment, `TaskResult.hires` (omit-when-empty), a refs-not-payloads ledger event, hires dead at every continuation cut; confinement: children, agents-mode sets and the batch pool never hold the pair. Evidence-trail digests on the survey purposes (path:start-end + <=5-line excerpt + commands run; parent-side uncited marker). compare_arms hires/assignments columns. Rows 64c + 65 pre-registered, run and recorded: the digest shape PASSES its ranged rule 3/3 (26/28 ranged post-digest reads vs row 63 zero); the hire arm records hires 0/3 with the armed surface inside both cost bars — COLLEAGUE_HIRE stays default-OFF on that evidence.

### Fixed

- _CITATION_RE accepts table/en-dash citation formats (row 64c: 10/12 real digests were format false-negatives).

## [1.70.0] - 2026-08-30

### Added

- `COLLEAGUE_<PURPOSE>_CONTEXT_BUDGET` — an opt-in per-purpose child context-window cap (#458 re-scoped after the steps-vs-turns correction: the 12-turn cap was applying all along; the cost was children inheriting the parent's window and re-sending a growing history — 300–846k tokens per child in rows 63/64). Wired `efforttables.purpose_context_override` → `spawn(context_budget_tokens=…)` → `ChildSpec` (explicit beats derived; the associate seat still takes min(child, seat)); unset/invalid = byte-identical. The row-64b experiment lever, promoted to a `PURPOSE_CONTEXT` default only if the arm wins.

### Fixed

- #458 corrected on the record: `max_steps` bounds model turns, not tool calls; both child-config paths apply `spec.max_steps`; rows 63/64's `incomplete` children are the cap firing.

## [1.69.1] - 2026-08-30

### Added

- `docs/deliveries/2026-08-30-delegation-follow-ups-a7-p3-hire.md` — the delivery summary for PR #464 (Phase A of the delegation-follow-ups plan): planned-vs-actual for t1–t23, the five approved deviations, drift, evidence and claims (row 64 re-run: 14/14 Nemotron children, ranged verification 3/3, wall miss 1.626), and the remaining work (Phase B hire increment, t19 parked, #458/#459).

## [1.69.0] - 2026-08-30

### Added

- `TaskResult.offered_tools` — the rendered tool names stamped by mock and vllm-openai identically (omit-when-None beside `prompt_digest`); the arm rows identify a surface arm off the artifact, not the prompt digest (delegation-follow-ups t2).
- `COLLEAGUE_ACTING_ADD_TOOLS` — a depth-0 add knob on the acting surface (names restricted to `tools.SCHEMAS`, applied after the drop, children untouched); the A7 raw-vs-purpose fair-fight instrument (t1).
- `COLLEAGUE_HIRE` / config.json `hire` (default OFF) and `acting_add_tools` on `EngineConfig` + `config show` (t4); the `hire_colleague` tool itself is Phase B (#457).
- Live-testing overlays P2-0 (P2's first paragraph = the honest P3 control) and P3 (size-conditional delegation prose) + the requested-delegation brief `arm-large-surface-requested.md` (t3).
- Associate seat sampling profiles (`colleague/associate_config.py`): `depth` (temperature 0.6, top_p 0.95, `enable_thinking: true`, `max_tokens` omitted) on every associate lane by default, `triage` (0.2, thinking off, 2048) only via `COLLEAGUE_ASSOCIATE_PROFILE` / per-value overrides; `config show` prints the profile (t23, #461).
- `docs/features/associate-validation.md` — how to validate the associate/Nemotron seat with colleague on real cases: preconditions read off the rig, the operator's measured usage contract (#461, both comments — the correction wins), a five-case ladder, artifact reads, pass bars, known failure shapes (t21).
- Live-testing rows 59–64 (A7, P2-0, P3, R-cortex, R-nemotron): the raw-vs-purpose fair fight delegated 0/3 by either form, P3 0/3 does not promote, requested delegation R-cortex 3/3 compliant at 3.2× wall with a full redo, R-nemotron run 1 all children refused (#460).

### Changed

- A top-level `--role reviewer` and the read-only modes `--mode explore|review` now reason at `low` on the acting seat (`effort.TOP_LEVEL_ROLE_TABLE` gains `reviewer`, new `TOP_LEVEL_MODE_TABLE`; `EngineConfig.mode` is a runtime-only field stamped by the work front) — the operator's rule: the associate is the fast reviewer, and whenever it is not taken cortex at `medium` is slow (a 20 KB diff review overflowed its synthesis turn at 274k reasoning chars). Kill-switch, per-seat/global knobs and an explicit `--role` still win; unset runs are byte-identical.
- Test pins updated for the artifact's `offered_tools` key (chain e2e, result fidelity, senses all-engines, three-tier gates, deepthink guards) and the file-length ratchet baseline moved with its sanctioned command for the modules this arc grew (the per-arc convention since v1.65); the three associate per-value override knobs are now rows in the adopt-from-qwen-code knob table.
- `docs/features/purpose-tools.md` + CLAUDE.md record the `delegation-follow-ups` arc: #456's two gaps closed negatively, the purpose child's step cap found unapplied (#458), the seat-per-lane decision rule deferred to measurement (#459).
- The associate seat is clamped to the SERVED window: ONE `/tokenize` probe per (url, wire model) discovers `max_model_len` (128,000 on the reference rig vs a 1,048,576 advert) and `context_budget_tokens = min(budget, served − output margin)`; the served-window map is keyed by (url, model) (t22).

### Fixed

- Review findings (a colleague second opinion on the knobs/contract diff, task `8e658025caa2`, cortex at `low`): a nested config.json `{"hire": {"enabled": false}}` used to stringify to a dict repr that `_parse_bool` read as ARMED — it now reads `enabled` like `agents`; an EMPTY curated surface stamped `offered_tools: []` where the docstring promised an absent key — both engines now stamp `None` for an empty surface (byte-identical to the pre-field artifact); the vllm half of the all-engines stamp, the add-knob→`offered_tools` composition and the non-JSON `config show` lines are now pinned.
- PR #464 review round (Qodo 4/5/6/7 + 13 SonarCloud smells): failed `/tokenize` probes are memoised per `(url, model)` and the miss→probe→store sequence runs under one lock (never a repeat 10 s probe, never two probes from a concurrent batch); `COLLEAGUE_ASSOCIATE_THINKING` accepts explicit true/false spellings only and IGNORES a typo (the profile's value stands) instead of silently disabling thinking; the associate compact/synthesis lanes now window their request to the SEAT's served-window budget before dispatch (`associate_seats.window_to_seat`, through `loop._seat_complete`) instead of failing on the wire and falling back; `_build_chat_payload`'s associate branch extracted to `_apply_associate_profile` (byte-identical payloads) and the composite test assertions split.
- #460 — a purpose child on the associate seat inherited a 768k budget, hit `400 maximum context length`, and the alias→served-id retry turned it into `404 role_infeasible` with the original error lost; `retry_role_alias` now recognises a context-length 400 (no retry) and, when the served-id retry also fails, raises a folded error carrying BOTH bodies (t22).

## [1.68.0] - 2026-08-30

### Added

- Prompt/surface unification (t5): one role resolution feeds both the composed system prompt and the curated tool surface, so an operator overlay at .colleague/agents/writer.md now reaches a bare run
- markup_tool_calls run counter (t6) via the new colleague/toolmarkup.py — detection only, never execution, making #360 dropped-markup visible
- TaskResult.prompt_digest (t7): a sha256 of the composed system prompt beside config_digest, omitted-when-None, so a prose arm is attributable from the artifact
- actingsurface.strip_child_forbidden_tools / CHILD_FORBIDDEN_TOOLS (t11): a spawned child never inherits the raw subagent/subagents, independently of what the acting seat's allow-list carries — kept as defence in depth after arm 4 itself was rejected (see Changed)
- The P0/P1/P2 prose overlays under docs/live-testing/overlays/ (t12) as staged experiment instruments, not shipped defaults
- Live-testing rows 51-58: the row-49 validity re-run and the pre-registered 21-run arm matrix with its measured results

### Changed

- The default prompt now names the six typed purpose tools instead of subagent/subagents (t9, 174 -> 165 words); tests/snapshots/prompttext_v1.txt regenerated under deviation d1
- docs/features/purpose-tools.md, docs/features/adopt-from-qwen-code.md and CLAUDE.md record the arc conclusion: neither the prose nor the surface lever moved the delegation rate; task shape did
- Corrected two stale figures that reported allow-list name counts as rendered tool surfaces
- Arm 4 (t11) REVERTED on its own evidence (Qodo 3888125915): the raw subagent/subagents are off the acting seat again and cortex/worker hold only the six typed purposes, because A4 measured 0/3 delegation with them present and no subagent/subagents call occurred in any of the 21 matrix runs; docs/features/purpose-tools.md and CLAUDE.md record the arm as tested-and-rejected rather than deleting it, and docs/live-testing.md rows 49-58 keep every measured figure

### Fixed

- COLLEAGUE_UPDATE_SNAPSHOTS=1 was a silent no-op because conftest scrubs COLLEAGUE_* before each test; the flag is now read at import time (#454)

## [1.67.0] - 2026-08-29

### Added

- acting-seat-scoped tool drop knob `COLLEAGUE_ACTING_DROP_TOOLS` — a named drop-set applied at depth 0 only through the existing `narrow_role_by_tool_set`, so the acting seat can lose a tool while spawned children keep it (unset = byte-identical)
- `stream_guard_trips` on `WorkStats.counts` — stream-guard trips are now a countable artifact field, not just a warning (#438 guidance 5)
- the two arm briefs for the purpose-tools-get-chosen matrix, plus the deterministic large-surface fixture generator `scripts/make_large_surface_fixture.py`

### Changed

- stream max-lifetime default raised 900s -> 1800s: 900s was too tight for a real test-first task on the reference rig
- the idle guard no longer counts SSE keepalive comment lines as activity, on both the read1 and fallback paths — a gateway relaying keepalives over a dead upstream no longer looks alive (#438 guidance 4)
- backpressure's proactive request-timeout raise is suppressed while stream guards are armed; the reactive raise is unchanged (#438 guidance 3)

### Fixed

- the non-streaming blocking fallback is now bounded by the same StreamGuards as the streaming path, sharing ONE guard object per turn so a failed stream attempt gets no fresh lifetime window (#438 guidance 1)

## [1.66.0] - 2026-08-28

### Added

- Purpose tools (#443): six typed delegation tools on the top-level acting seat — web_survey/code_survey (scout child, on the associate seat when armed), review/validate/plan (reviewer/validator/planner children on cortex), handover_to_colleague (writer child on cortex) — each a fixed purpose → fixed role → fixed seat + rung; new colleague/purpose_schemas.py, colleague/actingsurface.py, colleague/efforttables.py, colleague/distilleffort.py, colleague/cli/_commands/_effort_groups.py
- Associate sub-seat effort (#442): ASSOCIATE_SEAT_TABLE (distill=low, others off) with `COLLEAGUE_ASSOCIATE_REASONING_EFFORT_<SEAT>` / `reasoning_effort_seats["associate.<seat>"]` overrides; PURPOSE_TABLE + PURPOSE_STEPS per purpose with `COLLEAGUE_<PURPOSE>_REASONING_EFFORT` / reasoning_effort_purposes; config show + /effort render all three groups
- Distill child effort plumbing: the detached rung-2 distill child sends its rung, raises max_tokens when thinking is on, retries once on a ladder-400, and records finish_reason=length as its own failure reason
- One work-item-wide web budget spanning purpose children + parent-side urls fetched: report; purpose delegations exempt from the armed-agents ⊆-parent check; docs/features/purpose-tools.md; live rows 49/50 (pre-registered, filled: both MISS on the bar, row 50 mechanism proven); delivery record docs/deliveries/2026-08-28-purpose-tools-associate-seat.md

### Changed

- REPLACE, not add (recorded, one-way): cortex/worker no longer hold raw web/subagent/subagents — CLAUDE.md records purpose tools under sanctioned increment (1); children never hold purpose tools; resident peer turns withhold web_survey as well as web
- scripts/compare_arms.py counts purpose steps in delegations/associate_calls; delegation armed-facts sentence spliced onto web_survey/code_survey
- docs: thinking-effort.md gains the ASSOCIATE_SEAT_TABLE + PURPOSE_TABLE tables; adopt-from-qwen-code.md states ROLE_TABLE[scout]=off; web-scout.md honesty line 33 marked superseded

### Fixed

- loop.resolve_role agents-narrowing guard used a strict-subset test that silently fell through to the full surface once purpose names existed
- purpose child rung never leaks from the parent or the global rung (PURPOSE_TABLE passed as the explicit override; kill-switch still wins)

## [1.65.1] - 2026-08-28

### Changed

- **web-scout-associate delivery record** — the deviation store gains d16–d18 (the PR #444 CI/Qodo/Sonar fix tasks t15–t21) and the delivery summary records them; no code change.

## [1.65.0] - 2026-08-28

### Added

- **web-scout** — a curated read-only ``web`` loop tool over the operator-installed WebGlass CLI (``colleague/web.py`` backend, ``web_schemas.py`` schema + dispatch splice, ``webbudget.py`` per-work-item call budget, ``delegation_text.py`` armed-facts sentence): hidden when ``webglass`` is absent from PATH or ``COLLEAGUE_WEB=0`` (byte-identical off-state), a structural verb allow-list (``search`` / ``page open|read|inspect|extract|links``), process-group containment on timeout, WebGlass evidence ids rendered verbatim FIRST on the step trace, and the scout seat gains the tool (never a router). Doc: ``docs/features/web-scout.md``.

### Changed

- CLAUDE.md: one architecture bullet (Web scout) + a v1-scope clause that the web tool is a new surface over an operator CLI, not a router.

## [1.64.0] - 2026-08-27

### Added

- **adopt-from-qwen-code** — harness mechanics ported (as small stdlib Python, cite-don't-import) from Qwen Code and its Google Gemini CLI lineage, each behind one off-knob and pinned byte-identical to ``main`` when off (``tests/test_knobs_byte_identical.py``): a window-clamped ``max_tokens`` on every main-loop completion with per-seat ceilings and one length escalation (``colleague/outputclamp.py``, ``turnbudget.py``); the per-turn ``/tokenize`` round-trip replaced by one run-start probe plus a usage-anchored estimate (``tokenestimate.py``, ``COLLEAGUE_EXACT_TOKENS=1`` restores it); parallel batches of concurrency-safe tool calls with a fail-closed read-only shell checker — the sixth recorded convention change, one bounded thread pool in ``toolbatch.py`` (``toolbatch_loop.py``, ``COLLEAGUE_TOOL_CONCURRENCY``); first-class ``grep_search`` + ``glob`` tools (ripgrep with a stdlib fallback; ``search_tools.py``, ``search_schemas.py``); ``read_file`` ``offset``/``limit`` paging with ``Read lines X-Y of N`` (``readpage.py``); a deterministic tolerant edit tier plus prior-read enforcement, no LLM repair (``editmatch.py``, ``editgate.py``); head+tail tool-output truncation with a 0600 spill file the model can page (``truncation.py``; ``colleague clean`` reaps it); rule-based microcompaction before the fill-line offer (``microcompact.py``); stream idle/lifetime guards (``streamguards.py``); always-on loop guards (``loopguards.py``); adopted prompt text with per-model tool-call examples (``prompttext.py``) — **opt-in** via ``COLLEAGUE_PROMPT_VARIANT=qwen`` after the measurement showed it costs 2.3× wall-clock / 3× reasoning on Qwen3.8 (the pre-arc ``v1`` text stays the default; #437); the opt-in **associate** seat (``COLLEAGUE_ASSOCIATE_MODEL=lobes``, addressed by role name via the gateway proxy, streaming like cortex; ``associate*.py``) with a read-only ``scout`` role and an enumerated seat tuple; run counters, doctor ``harness`` rows and ``config show`` clamp/window lines. Credit: ``NOTICE`` + ``docs/adopted-from.md`` (one row per port). Doc: ``docs/features/adopt-from-qwen-code.md``.
- ``scripts/compare_arms.py`` + the pre-registered before/after measurement (``docs/live-testing.md`` rows 41+).

### Changed

- Measurement (``docs/live-testing.md`` rows 41–46, anchor #440): every arm misses the pre-registered 0.7×/0.8× bar; with the ``v1`` prompt the mechanics are at parity (1.10× wall / 1.07× turns on game-benchmark) and more reliable (branch game runs 8/9 finished vs main 2/3; two gateway hangs cut at 900 s vs main's 5,400 s floor). Prompt wording and thinking effort (#421) are the levers, not the ported mechanics.
- ``COLLEAGUE_MAX_OUTPUT_CHARS`` is now a **ceiling** over per-tool defaults (25,000 / 30,000 for ``run_command``); the old tail-cut suffix is gone.
- CLAUDE.md: the vLLM carve-out list reads two per-turn carve-outs plus one run-scoped probe; convention change (6) recorded.

### Fixed

- A silent gateway stall no longer holds a turn for the 5,400 s stall floor — the stream idle guard cuts it at 240 s (issue #415 shape; evidence in ``docs/features/adopt-from-qwen-code.md``).

## [1.63.1] - 2026-08-22

### Added

- Colleague skill adaptations for the four devague-chain legs missing from ``.colleague/skills/``: ``scope``, ``challenge``, ``deviate``, ``summarize-delivery`` — the full seven-leg devague method chain (scope → think → challenge → spec-to-plan → assign-to-workforce → deviate → summarize-delivery) now composes into every backend's layered skills catalog (``colleague skills list``: 12 → 16). Each carries a How to run in colleague section mapping moves onto the curated ``devague`` loop-tool allow-list and the agent-agnostic CLI surface (``confirm``/``reject``/``export`` stay user- or operator-only by structural exclusion).

### Changed

- Refreshed the three stale ``.colleague/skills/`` adaptations to the current upstream surface: ``think`` (``--title`` export hygiene, ``--instruction`` + re-confirm rule, S1/S2 gate warnings, the ``question`` pending-decision loop, the ``scope`` pointer), ``spec-to-plan`` (the ``instruct`` move, one task id per ``confirm``, the ``waves --json`` subagent-brief payload, text hygiene), ``assign-to-workforce`` (the End-state section via ``devague plan deliverables``, the verbatim-brief rule, the missing After the final PR → summarize-delivery leg). Fixed the self-referential provenance marker in ``assign-to-workforce`` and the stale supplier identifier (steward → guildmaster) across the devague-chain docs. Doc-only; no code change — the full suite is green (9165 passed, 23 skipped opt-in live proofs).

## [1.63.0] - 2026-08-22

### Added

- qwen-direct single-model default — the FIFTH recorded v0→v1 convention change (spec `docs/specs/2026-08-22-qwen-direct-no-gemma.md`, plan `docs/plans/2026-08-22-qwen-direct-no-gemma.md`, doc `docs/features/qwen-direct.md`): 1 colleague instance = 1 model = 1 agent; a bare run on a lobes-armed rig resolves exactly one served model (cortex) and dials nothing else.
- Session `/model` with no argument lists the gateway's `/v1/models` roster + role → model lines and marks the current seat; `/model <id>` also re-derives the context budget from the role's advertised window (`min(window, current)`); session `/effort` shows the per-seat thinking-effort table (`effort_of`) and switches a seat for the session only (`effort.apply_operator_effort`).
- Bare CLI `--model` / `--effort` (no value) print the served-model list / the per-seat effort table and exit 0 (`colleague/cli/_commands/_listing.py`, pure renderers shared with the session).
- `config show` and `lobes show` name every advertised role colleague does NOT consume by default (`not consumed (opt-in): senses → … — COLLEAGUE_SENSES_MODEL=lobes`; `--json not_consumed`).
- An unarmed session PARKS a typed/voiced mid-run line for cortex via flight guidance (`_park_talk_for_cortex`) instead of dropping it; `/voice`, `/speak`, `--voice` print one honest 'senses not armed — dormant' line on the default path.
- Tests: `tests/test_single_model_default.py` (one model on the default path, sentinel-only fallbacks, artifact has no senses key), `test_session_model.py`, `test_session_effort.py`, `test_cli_flags_listing.py`, `test_cli_not_consumed.py`; live proof row 40 in `docs/live-testing.md` + `docs/evidence/2026-08-22-qwen-direct-no-gemma-results.md`; workforce ledger `docs/evidence/2026-08-22-qwen-direct-no-gemma-workforce-ledger.md`.

### Changed

- Senses and muse lobes discovery are OPT-IN: `EngineConfig.resolve()` reaches `_senses_lobes_fallback` / `_deepthink_lobes_fallback` only when the declared model is the `lobes` sentinel (`COLLEAGUE_SENSES_MODEL=lobes` / `COLLEAGUE_DEEPTHINK_MODEL=lobes`, or config.json `senses.model` / `deepthink.model`); an explicit model id still declares a seat directly; rollback is one declaration.
- Sanctioned increment (4) presence-default-everywhere is superseded: the senses presence loop, front door, streaming/narration and clarify live behind the opt-in; `CLAUDE.md` + 8 feature docs marked accordingly.
- Slash config actions (`_act_*`, `_CONFIG_ACTIONS`) extracted from `session.py` into `colleague/cli/_commands/_session_actions.py` under the file-length ratchet (session.py 4052 → 3979 lines); `apply_operator_effort` lives in `colleague/effort.py` (the sanctioned assignment site).
- ask-colleague prompt templates now demand per-step progress narration (the model's text beside a tool call rides the flight feed) and an answer-so-far near budget.

### Fixed

- #422: the three lobes-unarmed tests (`test_cli_lobes.py` ×2, `test_config_lobes.py`) are hermetic against a checkout whose `.colleague/config.json` arms lobes (`--repo tmp_path`); the full suite is green on such a checkout.
- Discovery-by-default pins in `test_config_evaluation_mode.py`, `test_config_worker.py`, `test_voice_config.py`, `test_config_lobes_deepthink.py` flipped to the opt-in sentinel.

## [1.62.1] - 2026-08-22

### Changed

- **In-repo eidetic memory records** from the post-#416 colleague runs (the
  #418 / #422 fix dispatches on the merged v1.62.0 tool) — remember-after
  lessons + the first `split-next-time` records written by the new lane
  (`colleague/memory.py`). Memory is public and committed by convention
  (CLAUDE.md "Memory discipline"); no code change.

## [1.62.0] - 2026-08-22

### Added

- **Per-seat thinking effort (#416)**: colleague sends `chat_template_kwargs` per seat — `enable_thinking:false` for off, `reasoning_effort` for a rung — from a fixed v3 table (cortex/worker medium · deepthink xhigh · evaluator medium · senses/Talker off · subagent children writer/planner medium, reviewer/validator low, explorer off · top-level `--role explorer` low · design call-sites: plan spec stage xhigh / plan stage high). Operator overrides: `COLLEAGUE_REASONING_EFFORT`, `COLLEAGUE_<SEAT>_REASONING_EFFORT`, config.json `reasoning_effort` / `reasoning_effort_seats`. Kill-switch `COLLEAGUE_REASONING_EFFORT=default` restores the byte-identical pre-#416 wire. `config show` prints the resolved table (`colleague/effort.py`, `colleague/design.py`, `colleague/roles.py` `Role.effort`, subagent tool schema `effort`).
- **Ladder-400 graceful degrade**: a server that rejects the rung is retried once without the key + a `TaskResult` warning (`colleague/engines/vllm_openai.py`), disjoint from the stale-pin 404 refresh.
- **Effort as trace data** on the #411 ledger invocation record and the OTel work span (only when set).
- **Retroactive split-next-time record**: budget-exhausted / steps-at-cap / wall-clock > `too_long_min` (default 20, `COLLEAGUE_TOO_LONG_MIN`) runs leave an eidetic lesson that recall surfaces as a split recommendation (`colleague/memory.py`).
- **Docs**: `docs/features/thinking-effort.md`; `docs/live-testing.md` row 39; workforce ledger `docs/experiments/2026-08-22-per-seat-thinking-effort-416-workforce-ledger.md`.

### Changed

- The vLLM adapter convention now lists THREE graceful-degrade carve-outs (`/tokenize`, armed-lobes stale-pin refresh, `chat_template_kwargs`).
- The acting seat's DEFAULT now sends `medium` (decision c35/c36 — colleague#417: xhigh-by-default was the rig template's choice, not ours).

### Known limits

- Auto-split / fill-line split / decomposition design sites are pinned at the builder level only (no dedicated completion exists — follow-up).
- Effort × tool-calling measured n=1 per cell (#417 + live-testing row 39).

References: #416, #417, #415, #418.

## [1.61.0] - 2026-08-21

### Added

- **Model-bound agents (#411) — the eleventh sanctioned increment.** A THIRD independent opt-in (`agents` / `COLLEAGUE_AGENTS`; arming it with `three_tier` or `thought_action_evaluation` refuses, naming both): a typed `AgentProfile` per agent (purpose → lobes role → served model as trace data, validated tool profile, authority ceiling, lineage), a per-invocation `InvocationRecord` (context manifest + tool-surface digest; `token_estimate` never enters `Usage`), the append-only task ledger at the operator repo (`.colleague/ledger/<id>.jsonl`, fcntl-locked, replay-deterministic snapshot + digests, fail-closed reader), per-agent context reconstruction (pinned nucleus, `context_mode` inherit|clear, explicit provenance rank), typed `delegate|ask|inform|challenge|handoff|return` messages with a `MAX_AGENT_MESSAGES` budget, `DelegationRequest` envelopes that only NARROW (child ⊆ parent), subagents that may bind a DIFFERENT lobes role, continuation that rehydrates from the ledger, talker (senses) invocation records, `TaskResult.agents` (omit-when-unarmed, mock parity), a `doctor` `agents` group and `config show` line. Reference topology by role: Talker=`senses`, Worker=`worker` (dormant, deviation d3), Thinker/Coder=`cortex`, Associate=`associate` (reserved fast coder); a missing role is a RECORDED cortex fallback, never a refusal. Docs: `docs/features/model-bound-agents.md`.
- **#410 — SIGTERM writes the partial artifact unconditionally**: `colleague/salvage.py` exposes the loop's live partial; the signal handler writes the stamped artifact (status error, incompletion `interrupted`) BEFORE the WIP commit, so `work --continue` always has its seed.
- **#400 — step-stall watchdog**: `colleague/stallguard.py` + `COLLEAGUE_MAX_STEP_STALL` — a PROGRESS bound (time since the last completed step; default `max(5400 s, 6× mean turn latency)`), consulted per SSE frame; crossing it ends the episode with a preserved partial + `{kind: step-stall}` warning (not continuable).
- **Truncated turns**: an empty-content `finish_reason=length` turn is accounted exactly, recorded as `{kind: truncated-turn}` and routed through the shrink-and-retry lane instead of the finish nudge.

### Changed

- `three_tier` is superseded by the agents increment (kept as the benchmark baseline); `_refuse_conflicting_execution_modes` now refuses any two armed modes naming both.

## [1.60.0] - 2026-08-20

### Added

- Per-model overlay rollover advisory (docs/features/per-model-configuration.md): `.colleague/<sanitized-model-id>/` overlays are exact-id-keyed — a model rollover silently orphans old-id dirs; the operator renames them (nothing migrates automatically).
- COLLEAGUE_TIMEOUT guidance for long-context runs (docs/features/graceful-degradation.md): the default stays 120.0; raise per-run for deep prefill — headless streaming (#393) + timeout survival (#268) are the degrade story.
- Truncation-aware distillation outcomes: the rung-2 child completion now reports finish_reason/reasoning-vs-content split, and a truncated or empty-content completion writes an explicit reason onto the distill outcome marker — never a silent empty lesson.

### Changed

- Default model pin: unsloth/Qwen3.6-27B-NVFP4 -> unsloth/Qwen3.8-27B-NVFP4 (#404) — the Spark cortex rollover (1,048,576-token YaRN context, authed /capabilities probe 2026-08-20); the stale id 404s on the gateway.
- Context budget default 48000 -> 131072 (a moderate raise for the 1M window, decision c10 — not a max-out; prefill at depth runs minutes), _DEFAULT_MAX_OUTPUT_CHARS 25000 -> 68000 (same ~13%-of-window-chars ratio).
- Distill child cap _DISTILL_MAX_TOKENS 1600 -> 4096 (+180s timeout), sized from live 3.8 measurements: the hardest realistic rung-2 payload spent 1449/1600 tokens (90.6%), and reasoning is 88-93% of every spend.
- oilcheck _PROBE_MAX_TOKENS 128 -> 512: measured live, the three-tier worker seat (Qwen3.6-35B-A3B) truncates mid-reasoning at 128 and the probe misreports tool calling as ACCEPTED-BUT-IGNORED; the 3.8 itself passes at 128 with 4x headroom.
- Current-state docs/skills sweep to the new id: README, model-selection.md, live-testing.md reference-rig table, stats-and-feedback.md, ask-colleague SKILL.md + wrapper fallback; dated proof rows and changelog history untouched.

## [1.59.0] - 2026-08-10

### Added

- **Thought → action → evaluation: a three-seat authority split (#397)** — the
  tenth sanctioned increment, an INDEPENDENT opt-in
  (`thought_action_evaluation` / `COLLEAGUE_THOUGHT_ACTION_EVALUATION`),
  byte-identical when unarmed. The **front** (`senses` role, no repo tools)
  commits a typed versioned `Thought` while the raw operator input is preserved
  verbatim; the **worker** (`worker` role) realizes it as an `ActionProposal`
  naming exactly one live thought; the tools-off **evaluator** (`cortex` role)
  judges fidelity and returns only `execute | rethink | replan | block`. Seats
  resolve BY ROLE NAME from the lobes gateway — never by parsing model names —
  and a rig missing a role refuses to arm rather than falling back silently.
  Arming this together with `three_tier` refuses: two modes cannot both own the
  acting seat.
- The whole chain lands append-only on `TaskResult.evaluation_ledger` with real
  seat/model attribution (omit-when-None).
- Component-attributed, role-scoped lessons: a lesson names the seat that
  failed and reaches only that seat on recall, and an evaluator verdict alone
  can never promote durable memory — a verdict is a diagnosis, not evidence.

### Changed

- The `strategist` vocabulary is renamed to `evaluator` across the living
  surface (code, tests, `docs/features/three-tier.md`). Dated records under
  `docs/specs/`, `docs/plans/`, `docs/deliveries/` and `docs/experiments/` keep
  the old word as provenance. Persisted artifacts need no migration — proven by
  a committed compat test.

### Honest limits

- The mode has **no live-rig proof**; all tests use scripted seat doubles, and
  whether placing intent in the front seat improves outcomes is a hypothesis
  under test, not a result. The measuring experiment is deliberately not in
  this release.
- With the mode armed there is no implicit lesson author — cortex IS the
  evaluator and the worker IS the actor — so rung-2 distillation requires an
  explicitly declared `distiller_checkpoint` or falls to the rung-1 floor.

## [1.58.0] - 2026-08-10

### Changed

- **The distillation lesson schema is REPLACED, not extended (#396).** The
  three-key `cause`/`lesson`/`next_delta` shape gives way to an answer-shaped
  `pattern`/`constant`/`reason`, where `constant` is validated against a
  repo-anchor fingerprint so a lesson must pin something concrete (an
  identifier, path, value or invariant) rather than narrate a process. The
  refuse-whole stance and length bounds carry over unchanged; there is no
  dual-schema validator. Rationale: the #387 proof found lesson SPECIFICITY to
  be the variable — answer-shaped lessons changed behaviour, process-shaped
  ones produced an identical trace.
- Provenance (component target, artifact ids, evidence source) lives in record
  METADATA or a versioned envelope — never as keys in the validated payload.

### Added

- **Retrieval-precision instrumentation on `TaskResult.memory`.** The
  remember-after path stamps a deterministic class key that the next run scores
  against, so "did the class-relevant lesson surface in top-k" is measurable
  rather than assumed. The rule (`class-key-slug-v1`) is documented in
  `docs/features/memory.md` and pinned by a test that reads the doc.
- **Recall hygiene, colleague-side only.** Relevance thresholding over the
  score/signal fields eidetic already returns, plus supersedes resolution within
  a recalled batch. Every exclusion is recorded on `TaskResult.memory` — never
  silent. Disabled by env, behaviour is byte-identical to before.

A memory-less run still serializes with no `memory` key at all.

## [1.57.0] - 2026-08-10

### Changed

- **Headless work streams SSE by default (#393).** `colleague work` previously
  armed streaming only when a delta sink was attached (the interactive
  session's lane), so every headless turn took the blocking request path whose
  read returns only once the whole completion is generated — making the request
  timeout a per-turn *generation* ceiling. Streaming now arms uniformly across
  every vllm-openai completion; the existing mid-stream to blocking fallback
  and keepalive tolerance are unchanged, and the result shape is byte-identical
  on every path (the all-engines rule; `tests/test_e2e_mock.py` untouched).
  `COLLEAGUE_STREAM=0` restores the blocking transport exactly.
- Backpressure (#255) thresholds and timeout-survival (#268) classification are
  deliberately KEPT rather than re-keyed under streaming, with the reasoning
  recorded in `docs/features/backpressure.md`: every backpressure action is
  tighten-only and advisory, so the signal lost precision but not direction.

Measured on the reference rig: a big-context audit that died at the 240s socket
timeout pre-change completed post-change, and a single turn sustained 2780s
with no timeout. See #400 for the consequence — the socket timeout had been
acting as an accidental no-progress watchdog, and nothing replaced it.

## [1.56.2] - 2026-08-08

### Added

- #387 exp-2 executed in full: the #378 correction-diff ablation ran both 8-task arms on the Transformer benchmark — FALSIFYING on the pre-committed c20 bar (ON 57 vs OFF 38 correction lines; ledger row 32, delivery claim flipped, full evidence under docs/experiments/2026-08-08-prove-self-learning-387-arms/)

### Fixed

- find_artifact never resolves the rung-2 distill sidecar instead of the slugged artifact (#391) — grade-time correction capture was dead on every armed run with a distill child since v1.56.0
- code-lesson records now carry the eidetic-required text body (#392) — every code-lesson store failed silently since v1.56.0; the #378 correction-diff lane stores lessons in production for the first time

## [1.56.1] - 2026-08-07

### Added

- #387 proof-session evidence: live-testing row 34 (self-taught warm-vs-cold, outcome FALSIFYING per the confirmed bar — lesson specificity named as the operative variable), row-32 benchmark-exists note, the memory.md self-taught counterpoint, the prove-self-learning-387 spec/plan/delivery artifacts, and issues #388/#389

### Fixed

- recall() now parses the eidetic >= 0.13 --json envelope ({query, mode, truncated, items}) alongside the legacy bare-list shape — every armed run had been silently recording recalled=0 (#389; caught live in the #387 proof session, regression test pins both shapes)

## [1.56.0] - 2026-08-07

### Added

- **Self-learning arc** (spec `docs/specs/2026-08-07-self-learning-arc.md`, the
  ninth sanctioned increment): rung-2 lesson distillation at remember time —
  schema-validated cause→lesson→next-delta (`colleague/lessons.py`), author
  resolved BY ROLE (deepthink/muse > armed-lobes main > rung-1 floor), a
  bounded detached child (`colleague/distill.py`) with outcome markers,
  `distill_attempts`/`distill_validated` alive-counters on `TaskResult.memory`,
  an independent kill switch (`COLLEAGUE_MEMORY_DISTILL`), and a doctor
  distillation check group (`colleague/oilcheck/distillation.py`).
- **Rung-1 completion (#379)**: `compose_lesson_text` folds lint-gate fixes,
  test-integrity findings, and affected-tests failures verbatim-bounded.
- **`colleague strive`** — the necessity loop (#377): bounded attempts with a
  schema-enforced hypothesis ledger (refuse-whole), delta declared BEFORE
  execution, novelty stalls recorded honestly, the measure command
  approval-gated and run in the episode worktree, and REAL per-attempt work
  episodes via `Engine.work` on `sub/strive-<goal-slug>`;
  `chain.CONTINUABLE_REASONS` pinned unchanged.
- **Repo-anchored code-lessons (#378 core)**: `build_code_lesson_record`
  (distinct id namespace, verbatim evidence, bounded confidence), the
  integrator-correction diff teacher (`colleague/correction.py` — tip SHA vs
  the PR's squash commit scoped to `changed_files`, honest no-diff records;
  `TaskResult.tip_sha` persisted at handoff), and the seamless auto-trigger
  lane (grade-time + work-start capture, observable sidecar, never blocks the
  grade).
- **Feedback author provenance**: operator vs cortex records side by side;
  cortex-authored records are excluded from `feedback export` by default
  (`--include-cortex-authored` opts in) so a model grading its own work never
  silently trains itself.
- **Plan-mode diagnosability + the 35B (#376)**: a total claim-parse failure
  persists the raw proposal text before raising; the previously-failing 35B
  invocation now reruns to a parsed, converged frame (live-verified).
- Behavior-level e2e (`tests/test_e2e_selflearning.py`): a deliberately failed
  run's record teaches a second run — content asserted verbatim (#380 lesson:
  an explicit integration task + behavior e2e gate).

## [1.55.1] - 2026-08-07

### Fixed

- Lesson-grade remember-after, rung 1 (#379): the memory gate's post-run
  record now folds in the failure substance the result already carries —
  the #313 incompletion record (reason, evidence, recommendation), the
  error string, and stale-pin refresh warnings — so a future run's recall
  learns WHAT failed instead of step counts alone. Composition extracted
  to `colleague.memory.compose_lesson_text` (deterministic, no model turn);
  ok-run records stay stub-compatible.

## [1.55.0] - 2026-08-06

### Added

- Session streaming: senses replies render incrementally into the conversation
  (fence-tolerant JSON-envelope extractor `colleague/senses_stream.py`,
  owned-line transient paints, mid-stream containment with partial-render +
  marker); session cortex turns run streamed so per-read timeouts reset.
- Narration: senses-authored `<<higher self thought>>` (cortex) and
  `<subconscious thought/actions>` (three-tier worker) lines at boundary
  beats — user-display only, machine-checked out of every model context.
- Speak-only voice lane: `--speak` / `/speak` (default off) speaks senses
  replies through a voice-session-free playback path; the mic gate (c27)
  untouched.
- Model-pin hygiene: same-role stale-pin refresh at resolution + call time
  (main seat only, `EngineConfig.refresh_seat`), structured warnings on
  `TaskResult.warnings` (omit-when-empty), and a doctor `model_membership`
  probe; gateway fetches send the resolved Bearer key.
- Live proof runner `tools/live_proofs/session_streaming_proof.py` (t12).

### Fixed

- `_DEFAULT_MODEL` refreshed from the stale `sakamakismile` id to the served
  cortex id (#371); a muse-discovered deepthink 404 no longer cross-role
  refreshes onto the cortex model (#375); front-door replies speak under
  speak-only (found by the live proof).

## [1.54.0] - 2026-08-06

### Added

- Change-content consumption lane (#366): an applied worker.prompt.strategist note lands verbatim (bounded, 4000-char cap) in the worker's next-episode composed system prompt via the shared Engine.system_prompt path (all-engines), and an applied worker.tools narrowing intersects BOTH the offered tool schema and the executor allow-list (narrows, never adds; empty narrowing refuses at the lattice)
- Work front arms the config plane: EpisodeConfigLifecycle + ConfigEventStream constructed when three-tier is armed, configurator windows run before episode 1 (plain work AND chains) and between chain episodes, and the cumulative fold lands config events onto TaskResult.config_events and the persisted artifact (contract.map_configlifecycle_events + artifact.update_config_events)
- ChangeUnit.content field (strategist targets only, refuse-whole extended); lifecycle folds verbatim text with REPLACE semantics for strategist notes and tool sets (recovery from over-narrowing at any later window)
- Configurator auto-stamps entry-level origins on cortex knowledge entries (closes the experiment C refusal nuance — repeat run: 4/4 verified, 0 refusals), accepts the content key, and records visible degraded events (EVENT_KIND_DEGRADED) on both degraded review paths
- Subagent child inheritance: children consume a frozen snapshot adapter (narrowed tools + strategist note; never the mutable lifecycle); grandchildren inherit identically
- Flight run-start line names the acting seat (worker in three-tier mode); hermetic content-lane e2e proof + structural pins re-proven with content flowing

### Changed

- docs/features/three-tier.md Honest limits: the d2/#366 content-lane gap sections flip to describe the wired lane with pinning-test citations; strategist stays opt-in + OFF; value claim stays conditional on the NEBULA benchmark arm

### Fixed

- Known gap recorded honestly: the engine-failure artifact path performs no config-plane fold (in-flight window events are not persisted onto a failure artifact)

## [1.53.0] - 2026-08-06

### Added

- Three-tier execution mode (eighth sanctioned increment, #364): worker acts / senses relays / cortex configures — opt-in via config.json `three_tier` or `COLLEAGUE_THREE_TIER`, byte-identical when unconfigured
- `worker` role resolution from the lobes gateway with loud refusal when armed-but-unresolvable, plus same-origin api-key hygiene (lobes.py, config.py)
- `finish_reason` end-to-end: `ModelResponse.finish_reason`, the five-state classifier (`colleague/finishstate.py`), and always-on per-seat `TaskResult.finish_states` (decision c30 — unconditional observability)
- Typed change lattice + authority ceiling (`colleague/lattice.py`): refuse-whole ChangeUnits, host-declared CapabilityCatalog that cannot mint ids, worker may write only senses.knowledge
- Episode-boundary config lifecycle (`colleague/configlifecycle.py`): immutable per-episode snapshots, sanctioned before-episode-1/between-episodes windows, the T1 no-tool boundary counter
- Append-only config event stream on the artifact (`colleague/configevents.py`): baseline-as-event (T8), digest from replay alone, liveness by counters never armed
- Opt-in cortex configurator (`colleague/configurator.py`, default OFF): typed units only, structurally pinned to never touch the worker's history or wrap the acting seam
- Bounded task-local strategist prompt section via layers.py (`compose_strategist_section`)
- Seat-aware attribution: `worker ▸ working…` when the worker acts; legacy lines byte-identical (attribution.py, livecheck.py, presence surfaces)
- Doctor three-tier readiness group (oilcheck): worker advertised/dialable/tool-calling/id-matches-advert — the #363 §7 stale-model-id deafness fails loud
- Structural senses relay fidelity (senses.py): verbatim worker-answer containment, raw-answer fallback with recorded degradation, four SensesRecord counters, the embodiment 6/6 domain-mismatch regression
- Three pre-registered promotion gates with committed verdicts under docs/experiments/: A senses fidelity SUPPORTING (6/6 visible, 0/6 replacement), B worker promotion PROMOTES (4/4 vs 0/4, the c23 live performs-better gate), C strategist value SUPPORTING (4/4 detection, 0/4 false intervention)
- Named structural-gate suite tests/test_three_tier_gates.py (byte-identical, loud refusal, finish-state distinguishability, CI presence)
- docs/features/three-tier.md + the eighth-increment record in CLAUDE.md; live three-seat proof recorded in docs/live-testing.md

### Changed

- In three-tier mode the acting dial becomes the worker's own and deepthink is never constructed; legacy resolution byte-identical (config.py)

## [1.52.1] - 2026-07-23

### Added

- tests: degrade-path pins for the realtime lane's previously untested new code — bounded handshake-failure close, send-failure degrade (exactly one notice), six defensive pump frame-handling cases, a raising on_event callback, and the session lane's no-op/idempotence/dial-failure/speak-degrade/drain-race paths.

### Fixed

- realtime: a FAILED handshake now closes the WebSocket under the module's bounded `_WS_CLOSE_TIMEOUT_SECONDS` (the same bound `RealtimeSession.close()` enforces) — a misconfigured/unauthorized rig that never acks the close frame could otherwise stall session startup for websocket-client's 3s default (Qodo review, PR #356).
- session: a voice lane whose `start_capture()` fails now reaps the dialled realtime session AT the failure (bounded close + pump-thread join) instead of holding an idle WebSocket + pump thread until `_end_voice_lane()`. The lane is left in exactly the dial-failure shape (`_voice_session is None` + degraded), so drain/speak/toggle all take one path (Qodo review, PR #356).
- CI/coverage: the coverage job now syncs --extra voice. tests/test_realtime_client.py genuinely needs websocket-client (it dials colleague's REAL sync WS client against a stdlib fake server); without the extra that whole file skipped and its exercised lines of colleague/realtime.py read as UNCOVERED new code. Pinned by a test so it cannot silently regress; the sibling plain-`uv sync` test job stays extra-free, keeping the extra-ABSENT degrade paths proven.
- tests: dropped the whole-file pytest.importorskip("sounddevice") from tests/test_realtime_devices.py — the imported name was never used (every test fakes the lazy import), so the gate bought nothing and silently skipped 22 tests on any run without the [voice] extra. The media-arc "whole-file importorskip hides pins" lesson, landing again.
- sonar: fixed 5 OPEN issues on the arc's new code — 2x S7632 (a comma inside a `# noqa: CODE - explanation` trailer reads as a second, bogus suppression code) and 3x S5778 (hoisted the non-throwing constructor out of three pytest.raises blocks).

## [1.52.0] - 2026-07-22

### Added

- Realtime speech — the SEVENTH sanctioned increment: talk to senses by voice while cortex works, over the rig lobes gateway /v1/realtime WebSocket. An EARS-ONLY session (never response.create — senses stays the mind; replies ride the existing synthesize() lane): colleague/realtime.py (sync websocket-client behind [voice], ONE sanctioned pump thread, base64 event codec, degrade-never-raise), RealtimeConfig discovery via the stt role realtime_vad_session advert (env/config.json outranks; #348 same-origin key rule on the WS dial), continuous capture + client-edge half-duplex gate + device selection, session /voice + --voice opt-in (mic NEVER hot by default, c27) with honest off/live/muted/degraded lane state and bounded teardown, run_realtime_check + ALL ProofResult runners wired into colleague livecheck, byte-identical negative-space proofs, seventh-increment docs, and the first real-microphone live validation of the whole stack (Reachy Mini mic; p50 4.60s under the spoken-brevity shape / 5.63s default, honestly recorded in docs/live-testing.md).

## [1.51.1] - 2026-07-22

### Changed

- docs: voice-lane live proofs flipped SKIP -> PASS and recorded (closes #304) — the rig speech proxy 502 is fixed (lobes-cli#89/#92 closed): stt round-trips a VERBATIM transcript, tts returns real wav audio, and run_presence_narration_check reports passed live (probed 2026-07-22); docs/live-testing.md rows 22/23 + the presence-narration limit, docs/features/senses-live-presence.md and docs/features/presence-default-everywhere.md honest limits updated. No code change.

## [1.51.0] - 2026-07-17

### Added

- `_senses_lobes_fallback` and `_voice_lobes_fallback` in `colleague/config.py` — the senses and voice lobes discovery rungs now apply the same same-origin `api_key` hygiene the deepthink rung got in #347 (closes #348): an explicit key always wins (`COLLEAGUE_SENSES_API_KEY` / `COLLEAGUE_VOICE_API_KEY`, or a `config.json` `senses.api_key` / `voice.api_key` — model-less sections work, mirroring `deepthink.api_key`), otherwise the main key is inherited only toward the main endpoint's own origin, else the no-auth default.
- Ten hygiene tests across `tests/test_config_lobes.py` and `tests/test_voice_config.py`, mirroring the deepthink block — including the mixed-origin voice case pinning the conservative single-field rule.
- api_key-hygiene passages in `docs/features/cortex-senses.md` and `docs/features/senses-live-presence.md`, citing #349 (the follow-up unified withheld-key notice).

### Changed

- UPGRADE NOTE — behavior change on lobes-DISCOVERED roles only: a cross-origin discovered senses/stt/tts role that previously inherited the main `api_key` now resolves the no-auth default (`EMPTY`). If your rig serves a discovered role on a different origin than the main endpoint and relied on the inherited key, arm it explicitly via `COLLEAGUE_SENSES_API_KEY` / `COLLEAGUE_VOICE_API_KEY` or the `config.json` `senses.api_key` / `voice.api_key` keys (model-less sections work). The voice rung is conservative single-field: ONE cross-origin armed role withholds the main key from the whole `VoiceConfig` (the per-role `stt_api_key`/`tts_api_key` split is a named follow-up). Declared (env/config.json-with-model) senses/voice paths are unaffected; the deepthink rung is untouched.

## [1.50.0] - 2026-07-17

### Added

- Deepthink discovery rung (two-machines-two-minds arc, the SIXTH sanctioned increment): with lobes armed and no deepthink declared via env/config.json, EngineConfig.resolve() fills the deepthink target from the gateway's advertised muse role — muse's own dial target, main api_key, and a context_budget derived from the role's window at the deepthink default ratio (48000/65536); env/config.json always win, no muse = byte-identical (colleague/config.py, tests/test_config_lobes_deepthink.py)
- lobes.py resolves the muse role as a fifth optional role (present/absent/malformed tolerated like stt/tts); colleague lobes show lists it with its config-proxy ready-kind (colleague/lobes.py, colleague/cli/_commands/lobes.py)

### Changed

- CLAUDE.md scope line records six sanctioned increments (deepthink-from-muse as a resolution rung; the #332 remainder — trigger tables, parallel deliberation, synthesis — stays OUT)
- deepthink.md documents the muse rung + the current rig pairing (Qwen3.6-27B main on spark, Gemma-4-31B deepthink on thor via the gateway muse proxy, both 256K); cortex-senses.md consumed-roles list de-staled
- docs/live-testing.md records the cross-machine retarget proof (tool point, partial) and the zero-model-id discovery proof (DeepthinkCall point=tool tokens=1415 duration=60.4s degraded=False under a lobes-URL-only config)
- test_dual_live.py acceptance task carries the #122-style explicit read_file+finish invite (bare ask zero-stepped live)

## [1.49.0] - 2026-07-16

### Added

- Gate dropped-path note (#342): the chained union gate set records once per run every prior-episode path its existence filter removed ("N prior-episode path(s) no longer exist and were not graded"), on capacity_warning + a phase notice; nothing-dropped runs byte-identical
- Structured gate-deferral marker (#341): TaskResult.gates_deferred (omit-when-False) + ChainView.deferred_gate_episodes (accumulated deferring episode ids, omit-when-empty, degrade-to-empty from_dict) — consumers never string-match capacity_warning
- Halted-chain deferral surfacing (#341): the chain outcome line names the deferring episodes and their kept ungated WIP branches; a continue-regate test pins work --continue as the documented remedy (the finishing episode gates over the inherited union)
- Completed-chain deferral detection (#340 option B): the one completing shape that skips final gates (ok-finish + declared fill-line handoff) warns on the outcome line and carries the warning in the handoff PR body (composed --body; the no-warning path keeps gh pr create --fill byte-identical; never gh pr edit)
- Follow-ups filed: #343 (gate-time git-status sweep, decision 2a+file-2b on #342 part 2) and #344 (render deferred_gate_episodes in cockpit/tui)

### Changed

- All eight config.json override loaders read via the at-home per-key merge (#339): lint, testintegrity, watch, coherence, memory, affected-tests, presence (config.py) and icons (icons.py) — a repo file omitting a key no longer hides the user-level default; one regression test per loader
- Docs record the gate scope decision (#342, 2a): pre-finish gates grade model-authored edits (write_file/edit_file + subagent merges); run_command mutations are the approval-gate domain (lint-gate.md, work-and-loop.md)

### Fixed

- until_done no longer leaks into subagent children via config inheritance (#337): run_subagent resets it alongside the c22 chain-marker resets, so children of an armed run no longer arm the fill-line chain consumers

## [1.48.0] - 2026-07-16

### Added

- COLLEAGUE_COMPACTION_CAP operator knob (#334): env > config.json top-level compaction_cap > default 4 (fillline.DEFAULT_COMPACTION_CAP); 0 or any non-positive = unlimited; visible in colleague config show
- Chained-run gate deferral (#335): a chain-dispatched episode whose exit is continuation-shaped (budget-exhausted or a declared finish-with-handoff) skips the four pre-finish gates and records one deferral note; the final finish-shaped episode runs all four over the union of the chain's changed files still existing in its worktree; the skip keys on the chain-dispatch marker (never config.until_done) so subagent children of an armed run still run their gates; the continuation predicate is imported from colleague.chain and pinned by an equivalence test

### Fixed

- run_session marks --max-steps in config.explicit_knobs like cmd_work (#336), so the work-mode profile can no longer refill a session-passed --max-steps; the session-chain e2e now proves the flag path instead of the COLLEAGUE_MAX_STEPS env workaround

## [1.47.0] - 2026-07-15

### Added

- **Indefinite run — episode chaining** (`--until-done`; spec + plan `docs/{specs,plans}/2026-07-15-indefinite-run.md`, feature doc `docs/features/indefinite-run.md`; live evidence: eidetic `work-lesson-54ead8272f22`, a real task cut at steps=46 with "step budget exhausted"):
  - `colleague work --until-done` and `colleague session … --until-done` (plus `--max-episodes N`, default 5 armed, `0` = unlimited; `COLLEAGUE_UNTIL_DONE` / `COLLEAGUE_MAX_EPISODES` / `.colleague/config.json`) chain bounded episodes automatically: `execute_work_chain` — one implementation on both fronts, forwarded to `--background` children — re-dispatches a budget-exhausted episode via `resolve_continuation` over the pure `colleague/chain.py` verdicts. The continuable allow-list is exactly `{"budget-exhausted"}` (mapped from the persisted `not_finished` flag when the #313 soft rule suppresses the record on a partial-delivery budget exit); ok / error / pilot-stop / tool-protocol-broken / no-progress exits each halt deliberately. Unarmed runs are byte-identical.
  - Tree carry: episode N+1's isolation worktree bases on episode N's `colleague/<id>` branch tip (`isolation_worktree_add` `base_ref`, ref-verified); the #222 WIP sweep feeding it is best-effort, so a missing prior branch degrades to HEAD with a recorded warning — never a crash.
  - Handoff fires ONCE at chain end (ok-finish only): every episode dispatches with push/PR suppressed, the final branch carries the cumulative diff, intermediate `colleague/*` branches are reaped (ancestors of the kept final only); a halted chain never pushes and keeps every branch as WIP. Read-only chains stay handoff-free (the commit-evidence no-progress guard doesn't apply to them — the episode cap bounds them).
  - Verbatim config inheritance (nothing re-resolves env/config.json mid-chain), `ChainView` accounting on every chained artifact (exact per-episode sums, `"chain"` key omit-when-None; `--continue --until-done` resumes a cut chain's accounting via `read_chain_view`), between-episode flight pilot-stop + `episode-transition` markers on the prior feed (watch-gated), chain-aware `feedback record` (grades every episode in the lineage; cycles/missing artifacts terminate cleanly), and an unrepairable compaction note taking finish-with-handoff when chaining is armed.
  - Per-episode gate cost stated honestly: the lint / affected-tests / test-integrity gates re-run every episode (deferral to chain end is a recorded follow-up, not built). `--max-episodes 0` with trivial-but-real progress each episode never halts — explicit operator intent; flight stop + heartbeat are the brakes.

### Changed

- **Fill-line re-arms per crossing** (default-on, supersedes v1's "fires at most once per work item", #156): a resolved compact re-arms once the run drops back under the line; total compaction turns capped at `DEFAULT_COMPACTION_CAP = 4` per run (a module constant, not yet an operator knob; cap reached is recorded on `capacity_warning` + a phase notice, never silent).
- **Compaction summaries are validated before replacing history** (default-on): `validate_compaction` deterministically cross-checks the MAIN model's note against the run's own goal + changed-file trace evidence and repairs omissions; an empty/whitespace summary is REJECTED — the `(no summary produced)` silent-amnesia path is gone (unarmed rejection keeps the lossy-windowing floor; no deepthink lane — the recorded window-asymmetry decision).
- Docs updated to the new line: `capacity-standard.md` (drops "fires at most once"), `continue-working.md`, `session-continue-heal.md`, `graceful-degradation.md`, `honest-incompletion.md`, the CLAUDE.md architecture bullet, and the features README index.

## [1.46.0] - 2026-07-15

### Added

- **Interactive finishes what it starts** (#167, #168, #169; closes #170 as the interactive-redesign increment — spec + plan `docs/{specs,plans}/2026-07-15-interactive-finishes-what-it-starts.md`, built via the full devague arc /scope → /think → /challenge → /spec-to-plan → /assign-to-workforce with 3 recorded deviations):
  - `colleague work --continue <id|last>` (short `-c`) and session `/continue` resume a cut work item by seeding the new run from its persisted artifact's continuation record (`colleague/continuation.py` reusing `build_continuation` verbatim, ~1.3K tokens probed); a completed (ok) item is refused (`nothing to continue: <id> finished ok` — the wrong-run guard, since a SIGKILL-cut run may have written no artifact), missing/corrupt artifacts error naming the id; lineage recorded as omit-when-None `TaskResult.continued_from` on every artifact write (success + failure paths).
  - The session heals the dirty-tree refusal with ONE explicit choice (#168): a colour-TTY dispatch that would hit the #149 guard renders the 3-choice prompt (`colleague/heal.py` — commit-onto-work-branch as a one-run waiver / stash with the created ref + `git stash pop` recovery via `handoff.heal_stash` / abort on empty input), each choice carrying its consequence AND undo verbatim (the cockpit label-state-consequence policy). Off-TTY / `--json` / `--allow-dirty` sessions fall through byte-identically; the runtime guard is untouched (test-pinned).
  - The PR a run just opened is one glance away (#169): `Ledger.pr_url` reconciled verbatim from `TaskResult.pr_url` (never synthesized, never claimed mid-run), a Last-run panel PR row and a post-run `· PR: <url>` line rendered only when the handoff actually returned one (local-only output pinned byte-identical).
  - Feature doc `docs/features/session-continue-heal.md` with the executed boundary grep gate (no resident/plan/subagents/engine-resolution hunks in the arc diff) and the flow→test acceptance sweep; CLAUDE.md architecture bullet.

## [1.45.4] - 2026-07-15

### Fixed

- Consumer-repo trust batch — five field-reported bugs, one PR:
  - `.colleague/` bookkeeping self-ignores (#322): every write choke point (artifact write, `last_work` pointer, feedback record, flight arm) drops an idempotent self-ignoring `.gitignore` (the `uv`/`.venv` pattern), so a consumer repo that never gitignored `.colleague/` can no longer stage the run trace with `git add -A`; the operator-committable `commands/`/`skills/` overlays stay visible.
  - Broken tool-call channel guard (#321): `UnknownToolError` names the valid tools in its message, the loop tracks a consecutive unknown-tool streak (any call reaching a real tool resets it), and at 3 consecutive misses the run stops as `tool_protocol` with an honest `tool-protocol-broken` incompletion pointing at the serving-side parser/template (#320) — instead of burning the whole step budget and blaming the task (`write-no-changes`).
  - `colleague config show` provenance (#317): every config.json that contributed a key is listed with its keys and the subset that wins the per-key merge (`config_file: <path> sets [k1, k2] (wins: k1)`), highest precedence first; the `--json` payload carries the same list under `config_files`. Implemented by a colleague `write --apply` drive (task c345c539b2e7).
  - `front_load_review_diff` bounds the buffering (#324): the review diff is piped through `head -c cap+1`, so the wrapper never materializes a pathological diff in memory before the cap check; git is SIGPIPE'd early and the pipe exit is absorbed under `set -o pipefail`.
  - Handoff skips literal `~` pollution (#275): a literal `~*` entry at the repo root (a run_command test writing `~/…` relative to the repo) is never committed onto the work branch; the skip is surfaced in the handoff note alongside the gitignored-output advisory.

## [1.45.3] - 2026-07-15

### Fixed

- SonarCloud main quality gate: 12 python:S5863 findings — the `assert f(x) == f(x)` determinism tests across 9 test files rewritten as two-variable comparisons (`first = f(x); second = f(x); assert first == second`), semantics preserved; clears the new-code reliability rating back to A. Swept by a colleague `write --apply` drive (task 2f2396d7ac62), reviewed by a colleague review drive, operator-verified (6181 passed).
- `colleague learn` command map now names `clean` (crash recovery) and `session` (the interactive palette) in both the text and `--json` payloads (#185).
- The vendored ask-colleague skill wrapper invokes the canonical `colleague work` verb instead of the deprecated `drive` alias at all four drive sites, and the dirty-tree hint names `work` too (#187).

## [1.45.2] - 2026-07-15

### Changed

- Skills refresh: the vendored devague-family skills (think, spec-to-plan, assign-to-workforce, summarize-delivery) brought to current source — steward→guildmaster rename, devague#77, agex→devex localization
- Added devague origin skills: challenge (blind-spot discovery pass between /think and /spec-to-plan), scope (idea→scope exploration ahead of /think), deviate (record a first-class deviation when a workforce run must diverge from the confirmed plan)

## [1.45.1] - 2026-07-10

### Changed

- docs: live-testing ledger + feels-alive delivery summary now reference the filed lobes-cli#103 (gateway SSE buffering) instead of a pending draft

## [1.45.0] - 2026-07-10

### Added

- Token-streaming: the vLLM engine consumes SSE (`stream:true` + `stream_options include_usage`) over stdlib urllib when a delta sink is armed, feeding an optional runtime `EngineConfig.on_delta` seam; the mock engine emits a synthetic delta stream (all-engines rule). Unarmed runs are byte-identical (no `stream` key on the wire); usage tokens stay verbatim-from-server or honestly absent, never estimated (feels-alive arc, tasks t3/t4).
- Cockpit live generation tail: both live cockpit surfaces (`colleague session` and `work --tui`) fold a throttled tail of the model's in-progress generation onto the STATUS line (the `fold_phase` pattern) — visible generation instead of a silent `thinking…`; off-TTY/piped/`--json` never arm and stay byte-identical; deltas never advance `step_count` or reach the events sink/flight feed (t6).
- `colleague coherence` CLI noun (score/show/overview): on-demand coherence measurement of markdown files and finished work items via the operator-installed coherence CLI, reusing the #294 gate's scoring seam + lobes embed relay — advisory, never a gate; clean actionable skip when the CLI is absent (t7, colleague-built).
- Streaming livecheck: `classify_streaming_check` + a gated live proof (`tests/test_vllm_live_streaming.py`, registered in the livecheck ledger) grading first-delta latency from wall-clock evidence — honest SKIP on an unreachable rig and on the terminal-burst signature of an SSE-buffering intermediary (t9).

### Changed

- CLAUDE.md cut from 158,454 to 25,564 bytes (~39.6K → ~6.4K est. tokens of per-session context): each architecture part is now a few lines + a pointer to its feature doc; all trimmed detail relocated verbatim into docs/features/ (t8; operator decision c17).
- Streaming degrades, never breaks: a mid-stream disconnect, malformed SSE frame, missing terminal frame, or a stream-refusing server (400/422 naming stream) falls back to ONE blocking request within the same turn; backpressure still measures one wall-clock span per turn (t5).

### Fixed

- `lobes.embed_env` now folds the embedder role's advertised path prefix (`/v1`) into the relayed `EIDETIC_EMBED_URL`/`COHERENCE_EMBED_URL` base — a bare-origin relay 404'd both the #294 coherence gate and the new coherence verb on the real rig.
- Delta-stream arming defaults opt-OUT for external progress sinks (an opt-in default crashed the resident appserver's sink on the missing `on_delta` attribute).
- `coherence show` rendered signature fixed to `(ref, repo='.')` so `colleague coherence show last` works; `coherence score` accepts the single path string the rendered surface passes (the agentfront registry has no variadic positionals) and resolves paths absolute before scoring.

## [1.44.0] - 2026-07-10

### Added

- At-home arc, leg 1 — per-key config merge: `configdir.resolve_files` returns every existing `.colleague/config.json` match across `[repo/.colleague, repo/.convertible, user/.colleague, user/.convertible]` instead of only the first; `config._merged_config_json` folds them per top-level key (repo wins per-key, user fills the gaps) so a machine-wide `~/.colleague/config.json` `{"lobes": ...}` default now arms every repo on the machine and survives a repo-level config that never mentions `lobes`. `colleague lobes show` gained `--repo` and now resolves via the same `resolve_lobes_gateway_url(repo_path)` precedence the runtime consults, drift-tested against `colleague config show` so the two can never disagree.
- At-home arc, leg 2 — the owned input line: `colleague/cli/_commands/_input_line.py`'s `OwnedInputLine` gives `colleague session`'s colour-TTY talk lane a sanctioned reader thread (the 4th recorded thread-confinement sanction) so a mid-run update prints ABOVE the operator's in-progress typing instead of destroying it. Off a colour TTY the session is byte-identical.
- At-home arc, leg 3 — self-knowledge (#306): `colleague/selfknowledge.py`'s deterministic `classify_selfknowledge` + `build_guide_index` + `build_self_facts` give both minds a real answer to "what model are you?" — cortex-side, `loop.py`'s `_maybe_inject_self_knowledge` injects one advisory guide-index-plus-resolved-facts message before a self-knowledge-classified turn (ordinary turns byte-identical, test-pinned); senses-side, `frontdoor.py`'s `run_frontdoor` gains `config=`/`gateway_url=` params so a `SENSES_DIRECT` answer is enriched with the same resolved facts.
- `COLLEAGUE_HOME` env override (`CONVERTIBLE_HOME` deprecated fallback) for test-hermeticity — points config resolution at a fake home directory instead of the developer's real `~/.colleague/`.
- docs/features/at-home-on-your-machine.md documenting the arc; two follow-up issues filed ([#316](https://github.com/agentculture/colleague/issues/316) guide/docent role, [#317](https://github.com/agentculture/colleague/issues/317) `config show` contributing-files listing).
- `docs/deliveries/2026-07-10-colleague-now-feels-at-home-on-your-machine.md` — the arc's planned-vs-actual accountability artifact, produced by the newly vendored `summarize-delivery` skill (origin: devague; the delivery-side closure leg of the `/think` -> `/spec-to-plan` -> `/assign-to-workforce` chain).

### Changed

- Convention break #4 recorded: `threading`/`concurrent.futures` confinement is extended from `colleague/subagents.py` to also include `colleague/cli/_commands/_input_line.py` (the session's owned-input-line reader thread) — confined to the colour-TTY session path only, never the runtime work loop, bounded join, degrade-never-crash.

### Fixed

- `OwnedInputLine.stop()` no longer leaves a ghost reader on stdin (PR #315 review). The reader parked in a blocking `os.read`, so it could only observe the stop event on the operator's *next keystroke*: the bounded join always timed out and returned while the thread still held stdin, leaving two readers racing for the next key (stolen keystroke, corrupted echo) plus a ~1s stall after every work item. The reader now waits on `select` with a short poll tick, so it observes the stop event without a keystroke; `stop()` also retains the thread handle if one ever outlives the join, so a later `stop()` re-joins rather than silently forgetting it. Verified on a real PTY (`stop()` 0.040s, thread dead) and regression-pinned by `tests/test_input_line.py::test_stop_is_prompt_when_the_reader_is_parked_on_an_idle_stream` — a fake in-memory stream structurally could not catch this.
- `livecheck.classify_at_home_check` split into three per-leg graders behind a dispatch table, clearing SonarCloud `python:S3776` (cognitive complexity 29 > 15). Behavior unchanged.

## [1.43.0] - 2026-07-09

### Added

- Honest-incompletion contract (#313): when a work item produces no expected deliverable, colleague reports status: incomplete with a structured TaskResult.incompletion {reason, evidence, recommendation} instead of a silent ok. Runtime-owned (all-engines), role/intent-aware, deterministic reason->advice map, omit-when-None (a delivering run is byte-identical). ask-colleague surfaces it as an incomplete: diagnostic. livecheck.classify_honest_incompletion_check grades the live proof.

### Changed

- Soft-rule refinement (#313): a clean finish with a substantive, non-meta summary is a deliverable even for a write run with 0 changed files (a legitimate no-change-needed run); only an empty/meta finish, budget/stop, or zero-step run is flagged incomplete.
- ask-colleague keeps the grade: hint on a gradable failure (#139) — only the NO_RESULT_PRODUCED sentinel suppresses it (#192) — while adding the incompletion diagnostic.

## [1.42.0] - 2026-07-09

### Added

- #308: run-start marker + phase heartbeat on the flight feed so `colleague talk`/senses surface a real status during a long completion instead of "I don't know" (distinct type-tagged records; #206 step-only invariant preserved)
- #309: steer plan mode mid-run through the flight lane — `colleague plan run --watch` arms a plane and applies stop/guidance at the orchestrator's stage/wave boundaries (OrchestratorResult.steering); steering is now uniform across work/drive/explore/review/plan
- #311: a senses-direct front-door turn writes a standalone auditable `.colleague/senses-direct/<id>.json` SensesDirectRecord (verbatim text); strict no-op when unarmed/--cortex-only; routing unchanged
- docs/features/pilotable-runs.md documenting the arc; livecheck classifiers classify_flight_reachable_check/classify_flight_liveness_check

### Changed

- #307: the flight plane is now armed by DEFAULT on every run (work/drive/session) — opt out with --no-watch / COLLEAGUE_WATCH=0 / .colleague/config.json {"watch": false} (precedence flag>env>config>default). A deliberate, recorded default flip (opt-in -> opt-out); stdout + TaskResult stay byte-identical since the feed is a side file. The session default-arms the file plane too (c18)

### Fixed

- #310: the flight plane was armed INSIDE the throwaway isolation worktree for `colleague work`/`--background`, so `colleague talk`/`flight`/steering were disconnected and destroyed on cleanup. It is now armed at the OPERATOR repo (Task.flight_repo_path set by _setup_isolation, resolved via loop._flight_repo_path) — reachable and surviving worktree cleanup

## [1.41.0] - 2026-07-09

### Added

- **Talking to one teammate (the senses front door)** — the FIFTH sanctioned router-exclusion increment, landing the previously-parked #276 (senses-direct) as a fixed, enumerated, repo-untouching surface. Senses now fronts the interactive session and the resident/talk front: a deterministic classifier (`colleague/frontdoor.py` `classify_frontdoor`, ambiguous->cortex) lets senses answer a confidently non-repo turn (greeting / question about colleague itself / general non-repo conversation) DIRECTLY with NO cortex work item (no branch, no eidetic record), grounded in a curated fact-set (`colleague/architecture_facts.py`); anything touching the repo always dispatches to cortex. The intake ack now renders BEFORE the routing line (ack-first), and a `cortex working` hand-off line (`colleague/attribution.py`) makes the two lobes unmistakable. Shared `run_frontdoor`/`FrontDoorOutcome` decision; c19-safe on the resident. Live proof `colleague/livecheck.py` `classify_one_teammate_check` (SKIPs honestly when senses is unarmed). Feature doc `docs/features/talking-to-one-teammate.md`.

### Changed

- `colleague session` free-text WORK lines now consult the senses front door first when senses is armed; unarmed / --cortex-only / off-colour-TTY sessions are byte-identical.
- CLAUDE.md scope reconciled: #276 (senses-direct) moves from parked to landed as the fifth bounded increment.

## [1.40.0] - 2026-07-08

### Added

- **Presence default everywhere (the fourth sanctioned router-exclusion
  increment).** Colleague's middle-manager presence — senses (Gemma)
  acknowledges, proactively updates, relays your words to cortex, and answers
  conversationally while cortex (Qwen) does the repo work — is now the DEFAULT
  state on every front: the interactive session, the `colleague talk` attach, a
  background run, the mesh resident (reply-to-origin, c19-safe), and a one-shot
  `colleague work` (beats to stderr; `--json` stays parseable). Senses gets its
  own bounded *agentic loop* (`colleague/senses_loop.py`) whose "tools" are a
  curated, coordination-only move surface (`colleague/senses_moves.py`:
  dispatch_to_cortex, guide_cortex, read_flight, reply_to_operator, clarify,
  wait) expressed as prompted-JSON over the tools-off completion — nothing
  tool-shaped reaches the wire, cortex stays the only repo actor, and #276 stays
  parked. One front-agnostic pump (`colleague/presence_engine.py`), a bounded
  degradation ladder (loop → beats → off), the shared `SensesBlock` artifact
  contract across all fronts, and per-front livecheck classifiers
  (`colleague/livecheck.py`). Closes #300. Live-proven 2026-07-08 on the real
  rig (the rig now serves a tool-calling cortex, closing the #66 gap). Feature
  doc: `docs/features/presence-default-everywhere.md`.

### Changed

- **Deliberate, recorded convention break (c19):** an off-TTY / piped session
  with senses armed now carries labeled `senses:` presence lines (presence is
  the default on every front, no longer colour-TTY-only). The broken
  byte-identical tests are enumerated in `tests/test_presence_pin_breaks.py`;
  `--json` stdout stays machine-parseable (presence rides stderr). Senses
  unarmed and `--cortex-only` remain byte-identical on every front.

## [1.39.1] - 2026-07-08

### Changed

- Preserve eidetic recall reinforcement in the in-repo public memory store
  (`.eidetic/memory/colleague__public.jsonl`): passive `recall_count` /
  `last_recall` bumps on three records after the talking-to-one arc (PR #301)
  merged. Memory-only change — no code touched.

## [1.39.0] - 2026-07-07

### Added

- Talking-to-one middle-manager presence (spec 2026-07-05, plan 2026-07-06): talking to colleague in the interactive session now feels like talking to one person — senses (Gemma) fronts, cortex (Qwen) works
- Acknowledgment turn: senses speaks FIRST on split-mode intake — a senses-authored ack rides the ONE existing intake completion (ContextPacket.ack, zero extra calls); a degraded/missing ack renders a FIXED dispatch notice, never fabricated understanding
- Proactive interim updates: colleague/senses.py run_senses_update (tools-off, grounded strictly in the live feed tail) fired at existing progress-sink boundaries, cadence-gated by the new pure colleague/presence.py (phase-change / every-N steps / per-run cap via COLLEAGUE_SENSES_UPDATE_STEPS/_PHASE/_CAP; cap hit recorded once, never silent)
- Clarify-first: on low-confidence intake WITH omissions senses may ask before dispatching (COLLEAGUE_SENSES_CLARIFY_CONFIDENCE/_MAX; a go-word/EOF always dispatches — clarification can never withhold work); answers join the instruction verbatim and intake re-perceives the refined whole
- Conversation continuity: a session-lifetime rolling operator/senses history threads into every senses call (intake, clarify, updates, talk, speak-back), windowed to senses OWN budget senses-side, dropping oldest whole entries first; ack/update/clarify exchanges fold onto TaskResult.senses (kind-ed chat entries + senses-update records) so the whole exchange is reconstructable from the artifact alone
- Livecheck lane: classify_middle_manager_check + classify_front_latency_check grade every announcement beat from artifact + transcript evidence; gated live proof tests/test_vllm_live_talking_to_one.py LIVE-PASSED 2026-07-06 (ack in senses own words, 1/1 update rendered, conversational answer; median senses turn 0.83s, target <3s) — docs/live-testing.md rows 24-26
- Feature doc docs/features/talking-to-one.md + CLAUDE.md architecture bullet (a DEEPENING of the third sanctioned router-exclusion increment — cortex acts, senses converses; #276 stays parked); follow-ups filed as colleague#300 and lobes-cli#92

### Changed

- run_senses_intake/speakback/talk/update accept an optional rolling history kwarg (absent = byte-identical); the update prompt grounds in the packet interpretation
- Session presence lane is gated on the talk lane predicate: off-TTY / piped / --no-tui / --cortex-only / senses-unarmed stay byte-identical (test-pinned), and recording an ack/update/clarify never advances step_count (the #206 invariant)

### Fixed

- Stale uv.lock (colleague 1.38.1 bump from #299 had not refreshed the lock, tripping the #149 dirty-tree guard on the first colleague work run)
- Review fixes (PR #301): `COLLEAGUE_SENSES_UPDATE_CAP=0` is now a true hard disable — `should_update()` returns no "cap" reason and the session emits no "cap reached" chatter (was documented as "disabled entirely" but still logged a one-time cap line); `is_go_word()` strips all trailing/leading punctuation via `string.punctuation` so `go?` / `go ahead?` dispatch immediately (was only `.!,`); `run_senses_update()` windows the WHOLE assembled prompt (goal `about` line + header + feed) before folding history, so an unbounded `packet.interpretation` can no longer push the prompt over the senses budget; `ContextPacket.from_dict()` defensively coerces `ack` (non-string → None, stripped, empty → None, capped at 500 chars) so a malformed artifact never crashes `_render_ack`
- Lint (SonarCloud): merged implicitly-concatenated strings in `run_senses_update` (S5799), removed the unused `point` parameter from `run_senses_update` (S1172), and narrowed a broad `pytest.raises(Exception)` to `dataclasses.FrozenInstanceError` in `test_presence.py` (S5958)

## [1.38.1] - 2026-07-07

### Added

- Two eidetic memory records to the shared public store: a `sonar-s7632-noqa-inline-prose-gotcha` reference (SonarCloud python:S7632 flags the `# noqa: CODE - inline prose` form as malformed suppression syntax; use canonical `# noqa: CODE` + a preceding reason line) and the `colleague-291-arc-built-2026-07-06` note (the #291 integration-front arc built + flywheel live-proof, ledger rows 19-23).

## [1.38.0] - 2026-07-06

### Added

- **Integration-front arc (#291)** — colleague becomes the operator front of the
  Culture.dev toolchain: `colleague organs list` + a no-network `doctor` organs
  check-group + `docs/organs.md` (#297); the published artifact + feedback
  contract `docs/contract.md` v1 with `feedback export` (#296); the **coherence
  gate** — fourth rack gate scoring changed docs via the coherence CLI with
  frame provenance and configured-detection, default-ON warn-only (#294); the
  **experiment noun** — detached sloth training runs with status/list/summarize
  `--remember` to eidetic and `clean` reaping (#295); per-role lobes dialing
  end-to-end (closes the #292 follow-on) and the one-embedder `embed_env`
  pass-through into eidetic/coherence shell-outs (#293); a colleague-side
  memory-convention drift-test (eidetic-cli#28) and boundary pins (no
  cultureagent import; `/v1/embeddings` never consumed). Flywheel live-proven
  (`docs/live-testing.md` rows 19-23).

### Changed

- `colleague/lobes.py` speaks the lobes >= 0.38 contract: per-role reachable
  endpoints (lobes-cli#87 closed), live-probed stt/tts readiness with a bounded
  503+Retry-After warming retry (lobes-cli#89 closed); `VoiceConfig` gained
  independent `stt_base_url`/`tts_base_url` (#292).

## [1.37.0] - 2026-07-04

### Added

- Cockpit UX (#285): colleague session now reads like a real coder-agent cockpit in both states. Idle answers identity -> permissions -> workspace -> capacity -> next action with a first-class Next panel; running visibly changes the screen with a live status line (phase / step N/max / current op / event-stamped elapsed), an Active-run panel (goal / changes-so-far / last action), collapsed templates, and an authoritative Last-run mutation ledger on finish.
- New pure colleague/cockpit_run.py (I/O-free, clock-free run-state + ledger: fold/RunState/observed_ledger/reconcile/status_line) shared identically by the session `_WorkSink` and the work --tui CockpitProgressSink.
- New colleague/icons.py emoji|ascii|none vocabulary applied to colleague-composed cockpit labels (flag > COLLEAGUE_ICONS > config.json > default emoji).
- Disambiguated mode facts (session_modes.mode_facts): behavior, source (auto vs pinned), and execution profile rendered as three distinct facts instead of one conflated line.

### Changed

- Run policy panel restructured into an aligned label-state-consequence grammar claiming ONLY enforced gates (push/PR + approvals.json when present); no invented confirmation gate, never described as sandboxed.
- Session slash commands regrouped into runtime / workspace / git-publish / inspect / session (/pr under its own publish-boundary heading); the Work templates panel retitled suggested work; the capacity signal is neutral-empty (no warning glyph until a real warning).
- Filed upstream agentfront asks #50 (renderer-level icon switch) and #51 (WorkItem.max_steps/started_at) rather than forking a renderer (#249 rule).

### Fixed

- Preserved the #233 legible action feed: the running-state transcript/ledger separation is delivered via the Active-run/Last-run ledger panels, keeping the tool-step ×N feed in the conversation (an early draft that removed it regressed test_agent_native_e2e).

## [1.36.1] - 2026-07-04

### Added

- Spec + plan for the coder-agent cockpit UX arc (#285): idle/running cockpit states, mode-semantics disambiguation, mutation ledger, conversation vs run-activity split, /help regrouping, icons option (devague /think + /spec-to-plan; docs/specs/ + docs/plans/ 2026-07-03-colleague-s-cockpit-now-reads-like-a-real-coder-ag)

## [1.36.0] - 2026-07-03

### Added

- Senses live presence + voice (third sanctioned router-exclusion increment): while cortex drives a work item, the operator converses with senses concurrently — senses answers in seconds from live run context (flight feed + context packet), operator words become flight guidance injected at the next tool-call boundary, and audio rides in/out via new lobes stt/tts roles.
- Senses talk lane colleague/senses.py run_senses_talk (tools-off, grounded, degrade-never-raise, explicit cortex: relay override).
- stt/tts wire clients colleague/voice.py (pure urllib transcribe/synthesize) + opt-in [voice] extra colleague/voice_devices.py (mic capture + speaker playback behind lazy sounddevice/soundfile imports; base install carries no audio dep).
- Voice role resolution: colleague/lobes.py resolve_roles parses optional stt/tts roles + VoiceConfig on EngineConfig through the senses precedence chain (absent = byte-identical).
- `colleague talk <task-id>` attach verb (flight-plane senses REPL) + interactive session concurrent lane (thread-free select() stdin poll at progress-sink boundaries) + resident appserver synthesized-wav file-link replies with c19 trust-gated relay (non-operator can never inject guidance).
- Awareness invariant: every applied injection produces a flight-feed line + TaskResult.senses.injections record; talk exchanges fold into TaskResult.senses.chat at finish (omit-when-empty; #206-safe).
- Livecheck classifiers (classify_senses_latency_check / classify_injection_reached_check / classify_voice_lane_check) + docs/live-testing.md rows 19-23.

### Changed

- TaskResult.senses SensesBlock gains omit-when-empty injections/chat (a run with no live lane is byte-identical).
- CLAUDE.md scope line updated from two to three sanctioned increments at the router-exclusion line; #277 voice lane (stt/tts) now consumed, embedder/reranker retrieval lane + #276 stay parked.

### Fixed

- Live rig honest limit: the gateway speech proxy 502s for both stt and tts (probed 2026-07-03) — voice.py degrades cleanly (None + one notice, text reply byte-identical) and the voice round-trip live proofs SKIP honestly, never a fabricated pass.

## [1.35.2] - 2026-07-03

### Added

- Spec + plan: senses live presence + voice (devague /think + /spec-to-plan) — talk to senses while cortex works: concurrent senses chat lane (session + a planned `colleague talk` flight-attach verb), operator words relayed into the running loop via the existing flight guidance plane at turn boundaries, stt transcript in / tts wav out behind a planned [voice] extra (un-parks #277 lane 1; #276 stays parked). Live-probed 2026-07-03: senses answers 1.3-1.6s during an in-flight cortex completion; STT proxies via the gateway; TTS 502s rig-side (parked non-blocking + lobes-cli issue follow-up). Docs only — no runtime change in this PR.

## [1.35.1] - 2026-07-03

### Added

- 4 cortex/senses build lessons recorded to the shared eidetic store (lobes capabilities endpoint-not-reachable gotcha, the Sonar S107 hot-file param-bundle pattern, the do-not-fabricate-proof-evidence testing lesson, and the oilcheck-groups-stay-offline invariant) — recallable by both the claude and colleague backends.

## [1.35.0] - 2026-07-03

### Added

- Cortex/senses role split: colleague resolves its minds by role from the lobes gateway (GET /capabilities via urllib) as a config rung (flag > env > config.json > lobes > builtin, zero model ids in colleague) — cortex (Qwen3.6-27B @128K) the authoritative tool-calling mind, senses (Gemma-4-12B @32K) a structurally tools-off multimodal front door.
- colleague/lobes.py role-resolution client; SensesConfig + lobes discovery rung; colleague/senses.py intake/speak-back/media-bridge invocation layer (tools-off, degrade-never-raise, verbatim original preserved).
- Session + mesh-resident split mode: free-text intake -> ContextPacket (mode=split artifact) with display-layer speak-back shaping, --cortex-only / --debug-senses flags. The media bridge prefers a declared multimodal senses over deepthink.
- Read-only colleague lobes noun (show/overview/--json + explain/learn/parity); cortex-senses measurement livecheck (run_cortex_senses_check) — live-proven 2026-07-03 on the served rig (cortex-only vs split, verbatim preserved, runtime facts only).

### Changed

- Second sanctioned increment at the router-exclusion boundary (after deepthink): two declared roles with fixed responsibilities, no automatic task->model routing. senses-direct (#276) and voice/retrieval (#277) stay out-of-scope, each pending its own re-spec.

### Fixed

- Vocabulary: removed 8 pre-existing brain-as-role-vocabulary uses (resident/promote surfaces) — now cortex/senses/lobes/engine; enforced by a no-brain grep test.

## [1.34.1] - 2026-07-03

### Added

- Cortex/senses arc spec + build plan (#274): converged devague frame and 13-task/6-wave plan for the two-model redesign — cortex (Qwen @128K) owns the tool loop, senses (Gemma @32K) is a structurally tools-off front door (intake ContextPacket, media perception, speak-back), roles resolved by name from the lobes contract (lobes-cli#81) with zero hardcoded model ids; the second sanctioned increment at the router-exclusion boundary. Follow-ups tracked: #276 (senses-direct), #277 (voice + retrieval).

## [1.34.0] - 2026-07-02

### Added

- Media input on all fronts: images and audio ride the task contract to a multimodal main model — `colleague work --attach PATH` (repeatable, composes with --command), the session's `/attach` slash (staged one-shot for the next work line), and mesh `attach: <path>` line references on the resident surface
- `Task.attachments` on the contract ({path, media_type}, omit-when-None) + `colleague/media.py` pure-stdlib helpers (validation, data-URI part builders, per-tile token estimate, part flattening)
- `view_media` read-only loop tool — the media sibling of read_file: `_safe_path`-confined, 4MB-capped, images-only, curated into read-only roles; the image folds into a follow-up user parts message
- Delivery verification (decision c25): the first media-bearing completion's token contribution classifies each attachment delivered/dropped/unknown/bridged onto omit-when-None TaskResult.media — zero extra turns; 'delivered' never claims understood
- Media-comprehension bridge (decision c24): with a dual-model config whose second model is declared multimodal (COLLEAGUE_DEEPTHINK_MULTIMODAL / config.json deepthink.multimodal), a text-only main + attached media escalates one tools-off media-bearing digest to the multimodal endpoint and folds the description back (TaskResult.deepthink point=media-bridge)
- Mesh media trust (anti-exfiltration): operator-only arbitrary paths; a non-operator attach: reference must resolve inside the repo working tree (resolve-then-contain, symlink-escape refused) and still runs read-only under explorer
- livecheck media proofs: image end-to-end (PASS requires delivered AND the answer naming the color — never trusts a 200) and the audio delivery check (grades from token evidence; honestly SKIPs on a rig that drops input_audio); ledger rows in docs/live-testing.md — image proof PASSED live on the served Gemma4 2026-07-02
- Gemma4-as-main STAGED not flipped: a test-proven per-mode per-model overlay recipe (96000@128K) with the modeless no-op pinned; the default stays the 27B at 48000, gated on the external serving-side Gemma tool parser

### Changed

- Budget accounting is part-aware: the exact /tokenize counter receives a text-flattened copy plus a 260-token per-part estimate; the char fallback charges the same estimate; windowing/compaction drop a parts message whole, never sliced mid-part
- Deepthink digests flatten media parts to text placeholders — a parts list structurally never reaches a text-only second-model wire; with the bridge armed, the declared-text-only MAIN wire carries no parts either (flattened placeholders; real parts travel only on the bridge escalation)

### Fixed

- A media-refusing endpoint no longer hard-fails the run: the text-only 27B rejects image parts with HTTP 400 (live-probed, verbatim test fixture) — the loop now flattens to placeholders, retries once, and records the media dropped
- tests/test_resident_media.py's module-level importorskip skipped the whole file (including the pure anti-exfiltration trust pins) in an environment without the resident extra — now a skipif marker on exactly the four appserver-dependent classes
- Background `--attach` dropped attachments (PR #272 review): `_background_child_argv` reconstructed the detached child's argv without the repeatable `--attach` flag, so `colleague work --background --attach PATH` silently ran with `Task.attachments=None` — now forwarded as absolute paths (repo-relative references stay correct across the child's CWD), regression-pinned
- `Task.attachments` are size-capped on all surfaces (PR #272 review): `media.validate_attachment` now rejects directories/special files (`is_file()`) and enforces a 16 MiB `MAX_ATTACHMENT_BYTES` cap at the single funnel shared by CLI/session/mesh — closing the OOM/oversized-prompt gap that previously only the `view_media` tool guarded (a mesh requester could reference any large in-repo file)
- Mesh `attach:` containment is repo-anchored, not CWD-anchored (PR #272 review): `check_attachment_path` resolved a relative reference against the resident process's CWD, so a valid repo-relative `attach:` (e.g. `docs/img.png`) was wrongly refused when the resident ran with a CWD other than the repo root — now anchored to `repo_path` before the resolve-then-contain check; symlink-escape and outside-repo refusal preserved

### Internal

- Reduced cognitive complexity (SonarCloud S3776) via behavior-preserving helper extraction — `_complete_with_degradation` (loop.py, 17->13, extracting `_attempt_completion_or_retry_plan`), `_build_task` (work.py, extracting `_collect_attachments`), and the resident `feed_message` (appserver.py, 21->~2, extracting `_resolve_attachments`/`_dispatch_and_reply`); no functional change

## [1.33.0] - 2026-07-02

### Added

- Timeout survival mid-flight (#268): a bounded one-time x2 raise of the per-turn request timeout (`_make_timeout_escalator`, wired through `ContextControls.from_config` for every backend), triggered by whichever fires first — the backpressure departure-from-CLEAR advisory (proactive) or a timeout-classified degraded retry (reactive, so the single #154 retry runs with real headroom instead of hitting the same wall). Recorded on `capacity_warning` + a phase notice; backpressure classification follows the raised cap.
- Engine-failure aborts preserve partial work (#268): the `except Exception` path in `execute_work` now commits the iso worktree's WIP onto the `colleague/<id>` branch (the #222 sweep extended to the exception path) and the error hint names the surviving branch, so an orchestrator can resume from the partial instead of spelunking.
- The timeout surface is documented (#268): `colleague doctor` gains a `provider_timeout` check (effective per-turn timeout + source: env COLLEAGUE_TIMEOUT / deprecated CONVERTIBLE_TIMEOUT / default), `colleague work --help` gains an env-knobs epilog, and `colleague learn` names the knob.

## [1.32.0] - 2026-07-02

### Added

- CI surface-agreement gate: `tests/test_surfaces_agree.py` runs agentfront.testing's `assert_surfaces_agree` on colleague's real App, pinning that the CLI/MCP/HTTP/TAUI surfaces cannot drift (#262; agentfront floor moves to >=0.20.0).
- Markup-shaped forced-synthesis guard (#264): when the synthesis turn's own output is literal tool-call markup, the loop retries once with a plain-prose instruction, salvages the prose prefix otherwise, and never ships markup as the terminal summary; recovery recorded honestly as `finish_recovered: "markup-synthesis"`.
- Defense-in-depth tool dispatch (#269): any non-ToolError handler crash now bounces back to the model as a self-correcting step error naming the tool, never aborting the flight; engine-failure CLI errors name the exception class when the payload is bare (e.g. `KeyError: 'path'`).

### Changed

- Default context budget right-sized to the served rig: `_DEFAULT_CONTEXT_BUDGET` 192000 -> 48000 (the lobes rig serves the default 27B at a 64K window, probed live 2026-07-02; the old default assumed the retired 256K serving and drove long runs into overflow/latency churn). `_DEFAULT_MAX_OUTPUT_CHARS` scales with it (100000 -> 25000, the same ~13%-of-window proportion). Both remain env/config-overridable; raise the budget for a wider-window model (Gemma4-12B at 128K -> 96000).

### Fixed

- Batch-subagent changed files now reach the parent tracker (#263): `subagents` merges every child's `changed_files` into the executor like the single `subagent` path always did — the artifact no longer under-reports, and the lint/test-integrity/affected-tests gates no longer silently skip batch-delegated edits.

## [1.31.0] - 2026-07-02

### Added

- Memory-informed runtime (best-colleague arc R1): `colleague/memory.py` shells out to the operator-installed eidetic CLI (allow-list exactly `recall`/`remember`, identity injected, strict no-op when the CLI is absent) — the SAME store + scope the operator's remember/recall skills use, so colleague's and Claude's lessons are mutually visible; the loop does recall-before (one char-capped advisory prior-lessons message at task start) and remember-after (a deterministic per-work-item lesson — status, steps, tool counts, honesty signals — INCOMPLETE runs included), recorded on omit-when-None `TaskResult.memory`; armed only when `config.memory` (default-ON, opt-out `COLLEAGUE_MEMORY=0` / config.json `{"memory": false}`) AND the repo carries a `.eidetic/` store AND the CLI is installed; isolated runs target the operator repo via `config.memory_root` (a lesson written to the throwaway worktree would die with it)
- Model-callable `memory` loop tool (verb=recall|remember) offered to every backend; read-only roles get recall only (remember is a write-capable shell-out, refused by the role-aware executor)
- Finish recovery (R2): the loop re-parses a finish emitted as literal tool-call markup in message content (#248 mode B) and fires forced synthesis on a thin headline-only (#248 mode A) or meta describes-a-report-it-never-contains (#231) finish after a read-heavy zero-write run — each recovery recorded honestly on omit-when-None `TaskResult.finish_recovered`
- Line-grounded `read_file` output (#240): `cat -n`-style true line numbers prefixed BEFORE truncation so cited line numbers are copy-derived, never re-counted from drifting context; display-only, never round-trips into `edit_file` matching
- Background one-shot (R4): `colleague work --background` detaches the run as a session-leader child (`colleague/background.py` — the ONE sanctioned detach module, `Popen(start_new_session=True)`, stdio to `.colleague/background/<id>/`, machine-readable `{id, pid, log_dir, flight}` start payload, flight plane auto-armed); `colleague clean` reaps dead-pid background residue and never a live run
- Resident appserver (R5, decision c17): `colleague/resident/appserver.py` behind the opt-in `[resident]` extra embeds `agent_lifecycle.runtime` (>= 0.9) as a library — colleague implements the upstream `Harness` Protocol, an inbound mesh Message becomes an `execute_work` work item, replies carry the result; c19 trust policy in `colleague/resident/trust.py` (anyone may ask; non-operator requests run read-only under `explorer` or are refused; only the operator's identity authorizes writes); base install stays byte-identical (no agent-lifecycle import, no socket, no daemon)
- `colleague livecheck` verb (R7): an endpoint probe + env-gated live-proof runner surfacing which live validations the current rig can actually run
- Concurrent-run worktree correctness (#239, R6): `git worktree` admin mutations serialized by an advisory `fcntl` lock + a pid-liveness marker on isolation worktrees, so concurrent colleague processes can no longer corrupt shared `.git/worktrees/` state (empirically ~3% corruption over 288 unlocked cycles → 0 locked) and `clean` never lists a LIVE run's worktree as reapable

### Changed

- `working_tree_dirty` (#149 guard) ignores `.eidetic/`-only changes — store reinforcement is colleague's own state, not operator dirt; the records still sweep onto the work branch so lessons travel with the work
- `docs/live-testing.md` ledger refreshed with live evidence: edit_file (×20 across real TDD builds), memory warm-vs-cold (10→2 steps, 23.4k→4.3k tokens), spontaneous unprompted `subagents` delegation, mode-profiles and dual-model rows flipped to VALIDATED (incl. the deepthink degrade path proven via a stale-listed model, #66)
- Dev deps aligned to deployed upstreams: `agent-lifecycle>=0.9` (`[resident]`/`[culture]` extras), agentfront 0.20.0 in the lock

### Fixed

- A malformed model tool call (missing required argument) now costs ONE non-ok step with a self-correcting message, never the run: per-tool `_require` validation raises `ToolError` ("read_file requires 'path'") and the loop's dispatch boundary converts residual argument-shaped errors (KeyError/TypeError/ValueError) into a recoverable failed step — live evidence: a 12-step run with 4 folded sub-results died on a bare `KeyError('path')` escaping as `engine 'vllm-openai' failed: 'path'`
- Memory lessons from isolated runs no longer die with the reaped worktree (recall/remember target `config.memory_root` = the operator repo)

## [1.30.0] - 2026-07-02

### Added

- Dual-model deepthink escalation: an operator-declared second model (`.colleague/config.json` `deepthink` section / `COLLEAGUE_DEEPTHINK_MODEL`/`_BASE_URL`/`_API_KEY`/`_CONTEXT_BUDGET`) reachable from a fixed, enumerated surface — the backend-judged `deepthink` loop tool, plan-mode proposals, the acceptance self-check, and the test-integrity reviewer default (same-endpoint only); absent config is byte-identical single-model
- `colleague/deepthink.py`: one bounded tools-off completion per escalation via the public `Engine.make_complete(config, tools=[])` seam, windowed to the deepthink model's OWN context budget (per-endpoint `/tokenize`-exact via the new `Engine.make_count_tokens` seam, char fallback); degrades, never raises — a dual run never fails because deepthink is unreachable
- Work-loop escalations recorded on `TaskResult.deepthink` (`{point, tokens, duration, degraded}`, omit-when-None); one `make_deepthink_run` binding per work item injected into both the tool executor and ContextControls by every backend (all-engines rule)
- Env-gated live dual-model proof (`tests/test_dual_live.py`, `COLLEAGUE_DUAL_E2E=1`) + wall-clock benchmark procedure (`scripts/bench_dual.py`, quality graded via the feedback loop) — recorded as PENDING in `docs/live-testing.md` until the rig serves a tool-calling backend
- Boundary + drift guards: `tests/test_deepthink_boundary.py` pins the import allow-list for the deepthink seam (engines + plan.py only; loop.py/tools.py stay injection-only), the tools-off sweep, and the feature-doc/CLAUDE.md honest-line wording; `tests/test_deepthink_guards.py` pins byte-identical single-model + zero-dep invariants
- Feature doc `docs/features/deepthink.md` + CLAUDE.md architecture bullet, including the honest not-a-router line and the synthesis/compaction-stays-on-main decision (window asymmetry)

### Changed

- `Engine.make_complete` gains an optional `tools` parameter (None = engine default, unchanged; `[]` = tools-off — nothing tool-related on the wire); `curate_schemas` offers the `deepthink` tool schema only under dual config, available to read-only roles (pure computation)
- With dual config and no explicit `COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL`, the test-integrity reviewer subagent defaults to the deepthink model when the two endpoints share a base_url
- `colleague plan` proposals route through the deepthink model under dual config, with per-call fallback to the main model (stderr-visible)

## [1.29.0] - 2026-07-02

### Added

- Per-mode constraint profiles (#254, spec R1): `colleague/profiles.py` catalog (work/plan/explore/review; auto=None, drift-tested) + `apply_mode_profile` in `colleague/config.py` — a new DEFAULT layer under flags/env (explicit flag > env > `.colleague/<model>/profiles.json` > `.colleague/profiles.json` > built-in profile), applied through one `execute_work(mode=...)` code path shared by `colleague work --mode` and the session's mode selection; `ask-colleague` explore/review adopt `--mode` natively (with a stale-CLI fallback).
- Adaptive compute backpressure (#255, spec R2 — the mechanism for #229): `colleague/backpressure.py` + loop integration — rolling per-turn latency vs the request timeout arms ARMED/ESCALATED, proactively tightening the next window and throttling subagent fan-out (CLEAR restores the configured width), with ONE capacity_warning-style advisory; strict no-op on healthy latency, forwarded to every backend via `ContextControls.from_config`.
- Rig-level cooperative concurrency budget (#258, spec R5): `colleague/rig.py` — `.colleague/rig.json` declares the endpoint's sustainable width; `execute_work` holds one file-based slot per top-level work item (PID-stamped, stale slots self-heal, degrades OPEN, no daemon/socket/threads).
- Subagent budget scaling (#258, spec R5): at fan-out width W>1 each child inherits a clamped share (parent//W, floored) of max_steps + context budget instead of the full config; per-item overrides win; all-read-only batches stop reserving the merge slot (items cap + width may use the full MAX_SUBAGENT_FANOUT).
- Tasks carry their goal (#259, spec R6): `Task.goal`/`Task.acceptance` render as a distinct prompt block; a CLEAN finish of a criteria-bearing task runs ONE advisory acceptance self-check turn recorded on `TaskResult.acceptance_outcomes` (never flips status); `SubResult.parent` records immediate-parent lineage; the plan workforce passes `PlanItem.acceptance` structurally; `colleague plan continue` resumes an interrupted plan run from its checkpoint.
- Budget-aware skill curation (#257, spec R4): built-in read-only roles get real (glob-aware) skill subsets; `<!-- skill-priority: N -->` marker + token-capped composition (`COLLEAGUE_SKILLS_TOKEN_CAP`, default 0 = uncapped) dropping whole skills with an explicit omitted-N note; `skills list --role/--budget` inspection.
- Tier visibility, colleague-side half (#256, spec R3): `TaskResult.mode` recorded in the artifact (omit-when-None); the session cockpit gains a Capacity panel, a goal line, and a LIVE phase status (thinking/synthesizing/compacting — the #206 follow-up, resolved for both cockpit consumers via `fold_phase`); the TAUI schema half is the upstream ask agentfront#48.

### Changed

- `ask-colleague.sh` explore/review no longer export caller-side step/reserve defaults — the runtime mode profile owns them (explicit --max-steps still wins in both directions).
- `ContextControls` gains request_timeout + throttle_fanout (compare-excluded), forwarded once in `from_config` (all-engines rule).

### Fixed

- Session/`work --tui` cockpits no longer drop #206 phase notices — a slow synthesis turn shows as a live status instead of a silent wait (documented follow-up resolved).
- `_first_summary_line` no longer mistakes a leading HTML comment (priority/provenance markers) for a skill's catalog summary.

## [1.28.1] - 2026-06-29

### Fixed

- session: shift-tab no longer stacks a `mode → …` line in the conversation feed on every press (issue #251). The active session mode is already shown in place by the status-line affordance (`mode: … [work] …`), so `_cycle_mode` no longer also appends to the append-only feed — rapid cycling left every prior mode on screen. `/mode` keeps its one-shot confirmation.

## [1.28.0] - 2026-06-29

### Added

- **TAUI floor surface gate** — `tests/test_taui_floor.py` now gates the full `agentfront.taui` surface colleague depends on (state/events/reducer/mirror/selectors/snapshot/diagnose/colors + the render/widget UI layer), plus a boundary test (`test_colleague_tui_imports_only_the_surviving_adapter_and_driver`) pinning that no colleague module imports a `colleague.tui.*` module other than the two survivors.

### Changed

- **Cockpit rendered from imported `agentfront.taui` (#249).** The whole duplicated `colleague/tui/*` cockpit package (state, events, reducer, TAUI mirror, the ANSI/flat/Markdown renderers, selectors, snapshot/diagnose, widgets, colors, layout) is now **imported from `agentfront.taui`, not duplicated** — the sequel to the cli-on-agentfront migration, unblocked by agentfront#43 (work-loop cockpit, `SCHEMA_VERSION` 0.2) and agentfront#45 (live-cockpit UI layer). The duplicated modules were deleted; only `colleague/tui/from_work.py` (the loop-step -> `agentfront.taui` `WorkStep` label adapter) and `colleague/tui/render/driver.py` (the `colleague tui live` raw-terminal loop, which agentfront does not ship) survive. The three non-tui callers (`cli/_commands/tui.py`, `_tui_sink.py`, `session.py`) re-point at `agentfront.taui.*`.
- **Raised the agentfront floor to `>=0.19.0`** (was 0.18.0) to adopt agentfront#45's live-cockpit UI layer (flat renderer + widgets + colors + layout).
- **Session/sink rewritten for `frozen=True` cockpit state (GAP 11).** agentfront's `TAUIState` is immutable, so the session and progress sink replaced in-place mutation with functional `dataclasses.replace`.
- **`colleague tui` verbs adopt agentfront's diverged cockpit API (faithful, not byte-identical).** The mirror gains top-level `conversation` + `header` keys (the feed is now `state.conversation`, not a `panel.conversation`); `tui inspect`/`action` use `resolve(state, ...)` (state dataclass, not the mirror dict) and `tui action` focuses a selector via `SelectorAction`; `tui snapshot` paths are keyed `json/ansi/events/md`; `tui diagnose` reports `{ok, findings:[{bug_class, message}]}` (Finding has no `selector`); the boxed `tui render` ANSI frame is now a plain-text Markdown-like render (agentfront's `render_ansi` emits no SGR escapes).

### Fixed

- **`tui snapshot --name` path-traversal guard restored.** agentfront's `write_snapshot` joins the name into the stem with no traversal guard, so a `--name ../escape` would write the quad outside `--dir`; the verb now rejects a non-plain `--name` with a clean `CliError` (`_validate_snapshot_name`).

## [1.27.0] - 2026-06-27

### Added

- **Early, choices-shaped `--algo` validation** on `colleague commands approve` and `colleague hooks approve`. A bad `--algo` (e.g. `crc32`) now fails immediately with a clean `error: invalid --algo 'crc32'` / `hint: choose one of: sha256, md5` (structured under `--json`) *before* any file/name lookup, instead of the previous late, file-existence-masked `could not checksum …` message. Validated against the new public `colleague.policy.SUPPORTED_CHECKSUM_ALGOS` tuple (single source of truth).

### Changed

- **Raised the agentfront floor to `>=0.15.0`** to adopt the two consumer-API gaps the CLI migration surfaced and which agentfront#38 closed: `Flag(choices=)` + a public single-dispatch MCP `run_tool` accessor.
- **The MCP round-trip test now uses the public `app.mcp_server().run_tool` accessor** (agentfront 0.15.0, #38 Ask 2) instead of reaching into the private `agentfront.mcp_surface._build_run_tool`.
- Recorded the honest limit of agentfront#38 Ask 1 for colleague: `--algo` is a *value-carrying* flag (its value is consumed via the function signature), so it cannot take an explicit `Flag(choices=)` without colliding with its signature-derived `--algo` at build time — hence the explicit early validation above rather than a parse-time choices flag (the two `approve` docstrings now state this accurately, replacing the stale "agentfront's Flag carries no choices" note).

## [1.26.0] - 2026-06-26

### Added

- **colleague's agent-first CLI is rendered from an imported agentfront `App` registry** instead of hand-maintained argparse scaffolding ("import, don't duplicate"). `colleague/cli/_app.py` `build_app()` auto-discovers every verb module's `register_into(app)` hook and `colleague/cli/__init__.py` `main()` dispatches argv against that App via agentfront's `run_cli` — so nested noun/verb dispatch, structured `{code, message, remediation}` errors, per-verb `--json`, the bare-invocation no-command handler, and `KeyboardInterrupt`→130 now come from agentfront's one published consumer-CLI API. Each verb is a **rendered tool** (`app.tool`, exit-0/raise, read-only inspection) or a **host command** (`app.add_command`, custom exit codes / streaming / blocking server-TTY — `work`/`drive`/`plan`/`session`/`tui`/`flight`/`clean`/`learn-from`/`promote`/`mcp`); the four reserved meta-verbs (`doctor`/`overview`/`learn`/`explain`) stay colleague-owned via a retained-legacy-parser shim. Gated on agentfront#35 (the consumer CLI API, shipped in agentfront 0.14.0). Spec/plan: `docs/specs/2026-06-25-*` / `docs/plans/2026-06-26-*`; feature doc: `docs/features/cli-on-agentfront.md`.
- **`colleague mcp serve` — a single-dispatch MCP server bonus** (#246), rendered from the same App registry: ONE `run` tool whose description embeds the command catalog (a "CLI on MCP"), so a platform like Cowork can discover and drive colleague. Runs over stdio (blocking); `colleague mcp overview` describes the surface. Behind the opt-in `colleague[mcp]` extra — absent it, `mcp serve` fails with a clean CliError naming the install, binds no socket, starts no daemon; the blocking stdio loop is agentfront's `serve_stdio` (no socket/daemon code in colleague). HTTP (`app.http_app()`) is a further free bonus from the same registry.
- **Cross-surface parity test** (`tests/test_cross_surface_parity.py`) pinning catalog-level set-equality across the three registry-derived catalogs — the CLI registry tools == the single MCP dispatch tool's command catalog == the `learn` catalog, with host commands consistently absent from all three — so an operation registered once appears on every surface with no drift.

### Changed

- **`agentfront>=0.14.0` is now colleague's one sanctioned base runtime dependency** — a deliberate, recorded break from the historical `dependencies = []` convention, justified because agentfront's core is pure-stdlib (a base `pip install colleague` still pulls zero third-party transitive deps) and it is the AgentCulture org's shared agent-first CLI standard. The MCP SDK ships behind the opt-in `colleague[mcp]` extra, never a base dep. `tests/test_zero_deps.py` becomes an allow-list of exactly agentfront and asserts the MCP SDK is absent without the extra.
- **`CliError` now subclasses agentfront's `AgentfrontError`** so every colleague error renders natively as structured stderr through the rendered dispatch path.

## [1.25.0] - 2026-06-24

### Added

- **Vendored the `remember` + `recall` memory skills from eidetic-cli**
  (cite-don't-import) — the write/read halves of eidetic's shared memory
  surface, so this agent (Claude and its colleague backend) can persist facts
  across sessions and recall them later from one store. `remember` drives
  `eidetic remember` (idempotent upsert of one JSON record or an NDJSON batch on
  stdin, dedup by id + content hash); `recall` drives `eidetic recall` with four
  search modes — exact / approximate / keyword / hybrid — each hit carrying text,
  full provenance metadata, a relevance score, and a freshness signal. Folds in
  PR #244 (closed in favour of this combined PR). Propagated by rollout-cli's
  `eidetic-memory` recipe.
- **Memory-discipline "Conventions and workflow" section in `CLAUDE.md`** — a
  per-task *recall-before / remember-after* convention so the vendored skills are
  actually used: `/recall` before non-trivial work to build on prior decisions,
  `/remember` when a non-obvious decision, constraint, fix-and-why, or gotcha
  surfaces. Documents this repo's memory as **in-repo and public** (records
  resolve to `<repo-root>/.eidetic/memory`, committed + team/mesh-shared).

### Changed

- **Refreshed the `remember` + `recall` wrappers to eidetic-cli 0.10.0**
  (cite-don't-import) — picks up eidetic's **project-local store routing**: PUBLIC
  records inside a git repo go to `<repo-root>/.eidetic/memory` (committed,
  team-shared), PRIVATE records (or any record outside a repo) go to
  `$HOME/.eidetic/memory` (never committed), an explicit `EIDETIC_DATA_DIR` still
  wins, and recall reads both stores and merges. Carries the 0.9.3 hardening
  (interactive-stdin guard, `help` as a search term, SIGPIPE-safe suffix parsing).
- **Recipe policy override: default visibility is `public`** (not eidetic's
  upstream `private`) — a plain `/remember` lands the note in `./.eidetic/memory`
  in this repo, kept as part of the repo; pass `--visibility private` to route a
  record to `$HOME` instead. Wrapper `usage()` text, the per-wrapper scope
  comments, and both `SKILL.md` files (frontmatter + body) now describe this
  public-by-default behaviour consistently (resolves the PR #244 doc/code
  mismatch). Runtime dep: the `eidetic` CLI on PATH (else a local eidetic-cli
  checkout with `uv`) — **`eidetic >= 0.10.0`** for the in-repo routing.

### Fixed

- **Scope-resolution no longer fails open silently.** When a `culture.yaml` is
  found but its `suffix` cannot be parsed (or parses to an invalid token), the
  wrappers no longer fall back to eidetic's broad `default`/`public` scope
  without warning; the empty-suffix path emits an explicit stderr warning and the
  resolved suffix is validated before use (resolves the PR #243 "silent scope
  fallback leak" finding). `stdout` stays clean for `--json` consumers.

## [1.24.0] - 2026-06-23

### Added

- colleague session: visible, operator-controllable mode cycled with shift-tab (live ANSI) or the keyboard-free /mode slash — auto/work/plan/explore/review; new single-source colleague/session_modes.py catalog
- colleague session explore/review modes: read-only investigation/diff-review reachable from the interactive session for the first time (in-place under the explorer/reviewer role, no commit/branch/PR)
- handoff.diff_range: operator-side `<base>...HEAD` diff source for the read-only reviewer

### Changed

- colleague session free-text routing is now mode-aware: auto is byte-identical to the prior classify_intent behaviour; work/plan/explore/review pin the verb; a number/template pick is never reclassified
- CockpitState.mode (previously a dead field) now carries the live session mode across the TAUI JSON, Markdown, and flat-ANSI tiers, with a shift-tab affordance on the status line
- raw-mode reader decodes shift-tab (ESC[Z) into a SHIFT_TAB token / CYCLE_MODE sentinel; every other key path byte-identical

### Fixed

- read-only roles (explorer/reviewer/planner/validator) now bypass the dirty-tree guard AND skip the write handoff in `execute_work`: a read-only run (session explore/review, ask-colleague) starts even with operator WIP present and the handoff's `git add -u` never sweeps that WIP onto `colleague/<id>` and reverts it (silent data loss). New `roles.is_read_only` predicate; runtime-owned so every read-only caller inherits it. (Qodo, PR #245)

## [1.23.0] - 2026-06-23

### Added

- Agent-native default session (#234): a free-text goal typed into `colleague session` is intent-routed to `work` or `plan` without naming a subcommand, on colleague's own served backend by default. New `COLLEAGUE_SESSION_ENGINE` env var overrides the session backend (precedence: --engine > COLLEAGUE_SESSION_ENGINE > COLLEAGUE_ENGINE > vllm-openai).
- AgentFront-surface probe reflex (#235): the default system prompt instructs colleague to check an unfamiliar tool's learn/explain/--help/--json surface before first real use (read-only; enforced harness probe is a tracked follow-up, #241).
- `colleague.session_intent.classify_intent` — a deterministic, stdlib-only work/plan keyword classifier.
- `colleague.config.resolve_session_engine` — session-scoped backend resolution.

### Changed

- Legible session action feed (#233): consecutive identical feed lines group into `<line> ×N`; the culture/devague tools render as `<cli/move> <args>` (what ran + on what) instead of a bare `[culture]`; the per-step hint cap is raised from 48 to 120 characters so long commands are not cut.

## [1.22.1] - 2026-06-21

### Changed

- Relicensed the project from MIT to Apache 2.0 — full Apache 2.0 LICENSE text, pyproject `license`/classifier metadata, and the README License section. Aligns with sibling AgentCulture repos (e.g. data-refinery-cli).

## [1.22.0] - 2026-06-19

### Added

- plan mode: a dedicated honesty-only proposal pass (a focused {honesty:[...]} batch call + a bounded per-claim fallback, cap 8, all via robust_simple_complete) so the spec stage gathers honesty conditions reliably on a weak served model — the v1.20.0 wall where the combined requirements+honesty call returned claims but zero honesty (#215)
- plan mode: a --no-workforce plan-only mode (run_plan_mode(workforce=False)) that delivers the spec+plan and skips the timeout-prone workforce fan-out — no wave, no batch_spawn, no subagent worktree; default unchanged (#215)
- ask-colleague plan: forwards --quick/--no-workforce and --timeout, with an honest remediation hint on failure (no silent auto-degrade) (#215)

### Changed

- plan mode honesty conditions are minted with fresh unique ids during the dedicated pass so a model reusing "h1" across focused calls is no longer silently dropped

### Fixed

- plan mode reporting: the spec gate now names the real gap — _render_run and _run_payload surface claims_missing_honesty instead of a silent "missing: (none)" when honesty is the only failure (#224)
- ask-colleague.sh: _preserve_artifact diagnostics use the error:/hint: contract, and print_result emits a structured {code,message,remediation} object in --json mode instead of plain text (#226)

## [1.21.0] - 2026-06-19

### Added

- Interrupt safety for delegated work items (#222): an interrupted `colleague work` / `ask-colleague write --apply` no longer strands your work. On the isolated work path, a SIGTERM (a caller's `timeout`), a Ctrl-C, or a cooperative `flight stop` now commits the model's WIP to the `colleague/<id>` branch before exiting, instead of orphaning it as uncommitted files in an `iso-*` worktree (`colleague/cli/_commands/work.py` `_arm_interrupt_commit` + `worktrees.py` `commit_iso_worktree_wip`, reusing the existing commit primitive). Runtime-owned (all-engines); armed only on the isolated path, never the in-place session path.
- `colleague clean` reaps orphaned `.colleague/worktrees/iso-*` worktrees (#222) BEFORE the `colleague/*` branch reap, so a SIGKILL/OOM leftover (where the branch is still checked out in the orphan worktree) is recovered in one command (`worktrees.py` `reap_orphaned_iso_worktrees` / `list_iso_worktrees`, scoped strictly to `iso-*` — never a `sub/*` child or an unrelated worktree; it spares an iso worktree whose `colleague/<id>` work item is a currently-active flight, and `--dry-run` is honored).

## [1.20.1] - 2026-06-19

### Added

- AGENTS.colleague.md worker base layer — distilled load-bearing conventions from CLAUDE.md, injected by layers.py whenever colleague drives a work item in its own repo (it previously ran the generic default prompt, since layers.py reads the AGENTS cascade, not CLAUDE.md) (#225).
- tests/test_doc_config_drift.py — a doc-to-config drift guard that reads the live colleague/config.py constants and asserts the feature docs quote them, so the budget/depth drift cannot silently recur (#225).
- Seven backfilled `docs/features/` docs for shipped-but-undocumented features (#225, gap 3): write-isolation, approval-gate, capacity-standard, cleanup-reap, config-resolution, continue-working, explore-never-wastes — each distilled from CLAUDE.md + its spec/plan and wired into `docs/features/README.md` (the approval-gate + capacity entries were previously README-blockquote stubs pointing elsewhere).
- Adapted 10 of the 12 vendored `.colleague/skills/*.md` from `adapt: pending` to `adapt: claude->colleague` (#225, gap 4) via the `learn-from claude` stage-2 pass — colleague (the 27B, now reading the new AGENTS.colleague.md base layer) remapped Claude script invocations to colleague's real `culture`/`run_command`/`subagent`/`run_tests` tool surface. `ask-colleague` (colleague's own first-party skill) and `sonarclaude` (the adapt only shallowly prefixed a non-existent script path — reverted to honest `pending`) are intentionally left unadapted.

### Fixed

- Stale feature-doc values corrected against colleague/config.py (#225): MAX_SUBAGENT_DEPTH 2 -> 4 (+ the global MAX_SUBAGENT_TOTAL=24 budget) in subagents.md/parallel-subagents.md; default context budget 24,000 -> 192,000 tokens in graceful-degradation.md; hooks.md trust-gate line updated (the approval gate shipped, the --no-hooks flag is still absent); work-and-loop.md tool table now lists the curated/optional tools (devague/subagent/subagents/check_test_integrity/run_tests) instead of reading as the complete surface.

## [1.20.0] - 2026-06-18

### Added

- `colleague flight status --follow` — stream a flight's live feed via a stdlib poll loop (no daemon, socket, or new dependency); `ask-colleague monitor` now invokes it, so its documented "live feed" is accurate (#219).
- `ask-colleague review` front-loads a filtered, capped diff (`git diff --stat` + the diff body with lockfile/vendored noise excluded, capped to `COLLEAGUE_MAX_OUTPUT_CHARS`) into the review instruction, so the model gets the whole change in ~1 turn instead of ~8 sequential read turns (#220a).
- Advisory review fan-out: a review reading across more than `COLLEAGUE_REVIEW_FANOUT_FOLDERS` folders is nudged once to delegate per-folder read-only `reviewer` subagents via the existing `subagents` tool (no new worktree/merge code). Dormant by default — byte-identical when off (#220b).

### Fixed

- `ask-colleague write --apply` dirty guard narrowed to tracked files (`git status --porcelain --untracked-files=no`), so a prior `explore`/`review` probe's untracked `.colleague/` artifacts no longer block an apply; matches the runtime `working_tree_dirty` guard (#217).
- `SKILL.md` provenance paragraph no longer asserts the consumer's sibling skills are vendored from guildmaster — it reads accurately in any consumer and defers sibling-skill provenance to the consumer's own `docs/skill-sources.md` ledger (#218).

## [1.19.0] - 2026-06-18

### Added

- **Subagent roles — a typed workforce, with read-only roles that cannot write.**
  A delegated subagent can be a typed *role*: a tailored system prompt, a curated
  subset of the tool surface, and a curated skill subset. Built-in roles
  (`colleague/roles.py`): `explorer`/`planner`/`reviewer` (read-only), `validator`
  (read + a dedicated read-only `run_tests` tool, no write), `writer` (full
  surface). A read-only role withholds `write_file`/`edit_file`/`run_command` and
  the role-aware `ToolExecutor` refuses any withheld tool, so it provably cannot
  mutate the tree. The engine resolves `config.role` once (`mock`==`vllm-openai`):
  curated `SCHEMAS` (`curate_schemas`), a role-composed prompt (`compose_role_prompt`
  via the one layered-config path), and the role-aware executor; the applied role
  is recorded on `TaskResult.role`/`SubResult.role` (omit-when-None → a role-less
  run is byte-identical).
- **Deeper recursion + a global agent budget.** `MAX_SUBAGENT_DEPTH` raised from 2
  to 4; a single `MAX_SUBAGENT_TOTAL=24` global budget (a thread-safe counter)
  bounds the TOTAL agents spawned under one top-level work item regardless of
  nesting shape, charged before any child work so every shape terminates; nested
  batches are now permitted. Env-tunable via `COLLEAGUE_SUBAGENT_DEPTH` /
  `COLLEAGUE_SUBAGENT_TOTAL`.
- **Surfaces for selecting + inspecting roles:** a `role` parameter on the
  `subagent`/`subagents` loop tools, `colleague work --role`, `ask-colleague …
  --role`, the plan workforce's per-child role, and a new `colleague roles`
  inspection noun (distinct from `agents`, which inspects AGENTS instruction files).
  Operator prompt overlays at `.colleague/agents/<name>.md` (+ per-model overlay).
- Selection is backend-judged and optional; omitting a role is byte-identical to
  the pre-role full-surface delegation. Runtime-owned (all-engines rule), zero new
  runtime deps. Spec/plan under `docs/specs|plans/2026-06-17-…typed-subage.md`;
  feature doc `docs/features/subagent-roles.md`.

### Fixed

- **`run_tests` read-only guarantee is now literal (PR #221 review).** The
  validator role's curated pytest runner already rejected option-like args and
  confined paths; it now also disables pytest's cache plugin
  (`-p no:cacheprovider`) and bytecode caching (`PYTHONDONTWRITEBYTECODE=1`), so a
  read-only validator run leaves no `.pytest_cache`/`__pycache__` behind — the tree
  stays byte-identical. It additionally strips `PYTEST_ADDOPTS` / `PYTEST_PLUGINS`
  from the subprocess env, closing the env-injected option/plugin vector the `--`
  separator does not (surfaced by an `ask-colleague` diverse-mind audit).
- **`load_role` symlink confinement (PR #221 review).** On top of the strict
  role-name guard, a resolved role file that escapes `.colleague/` is now refused
  (mirrors `colleague.layers._within` / `ToolExecutor._safe_path`), so a symlink
  planted in the config dir can't pull an arbitrary file into the system prompt.
- **SonarCloud S107 on `EngineConfig.resolve`.** The new `subagent_depth` /
  `subagent_total` knobs are now resolved env-only (like `temperature`/`timeout`),
  keeping `resolve` under the 13-parameter ceiling. They remain tunable via
  `COLLEAGUE_SUBAGENT_DEPTH` / `COLLEAGUE_SUBAGENT_TOTAL`.
- **De-duplicated the engines' `ContextControls` forwarding.** Both backends now
  build their context controls through one `ContextControls.from_config()` factory
  — a single source for the config→controls mapping that strengthens the
  all-engines rule (a backend that diverges is now a test failure).

## [1.18.0] - 2026-06-18

### Added

- colleague work pre-finish **affected-tests gate** (#213): after the loop and before the git handoff, run the tests whose bounded-depth transitive import closure (incl. function-local/lazy imports, default depth >=3) reaches a changed module, so a scoped edit can no longer hide a regression in another file the model never ran. Sibling to the lint (#200) and test-integrity (#203) gates in colleague/affectedtests.py + colleague/loop.py. Advisory + non-blocking, default-ON with --no-affected-tests / COLLEAGUE_AFFECTED_TESTS=0 / config opt-out, an explicit --test override, a bounded model fix-turn (COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES, default 1), an honest file cap, and degrade-to-skipped when pytest is unavailable. Recorded on TaskResult.affected_tests_report (omit-when-None). Runtime-owned (all-engines).

## [1.17.0] - 2026-06-17

### Added

- colleague plan run --quick / --no-spec: spec-less quick-plan path that skips the per-claim spec micro-cycle and plans directly from the request, still operator-gated at the plan level (#199).
- docs/features/plan-mode.md documenting the degradation-aware proposal path.
- tests/test_engine_make_complete.py pinning the public Engine.make_complete one-shot completion seam (#204, verify-and-close).

### Changed

- Plan-mode proposals are degradation-aware and take smaller jumps (#210): robust_simple_complete adds a forced no-thinking JSON follow-up on empty content, a resp.reasoning recovery, and a classify_degradable timeout/overflow shrink-retry; claims are proposed in two calls and plan items in bounded deduped-by-id batches. Makes colleague-as-planner functional on a reasoning served backend (the reference 27B), which previously failed with no JSON object found.

### Fixed

- _extract_json_object prefers the top-level object carrying the expected key (claims/items) so a stray prose object cannot shadow the payload, and repairs a JSON object truncated mid-structure (a reasoning model dropping its final brace) by appending the implied closers — the live 27B plan-items failure mode.
- Chunked proposals dedup by id and a total parse failure still surfaces the clean unusable plan proposal error (partial chunk failures are tolerated).
- PR #214 review (Qodo): the spec-less --quick path now invokes the operator gate (decide) on the proposed plan items before workforce execution, so a quick plan is never run ungated; robust_simple_complete preserves the first response's reasoning when the follow-up turn is empty (no lost JSON); and _call_with_retry shrinks the longest user message on an overflow retry instead of re-sending the same too-large payload.

## [1.16.0] - 2026-06-17

### Added

- `colleague quickstart` — a guided first-run walkthrough for new users (the "where do I start?" path the flat --help did not answer); text + --json, with an explain catalog entry.
- `WorkStats` now records `engine` and `model` so a work item ROI block names which mind produced it (comparable across backends).
- A grouped, scannable getting-started cheatsheet is appended to `colleague --help`.

### Changed

- `colleague explain` (bare) now hints the per-topic form `colleague explain <topic>`; the --json contract is unchanged (raw catalog markdown).
- `colleague backends list` prints a `NAME\tTARGET` header row so the two columns are labelled.
- `colleague config show` reports `config_file: (none — using env vars + built-in defaults)` instead of a bare `none`.

### Fixed

- `colleague tui render` no longer dumps raw ANSI escape codes to a non-TTY/piped stdout — it strips them via the existing should_color/strip_ansi gate (surfaced by a colleague-on-colleague CLI dogfood).

## [1.15.0] - 2026-06-17

### Added

- Test-integrity gate (#203): a code-locked, runtime-owned post-loop gate that flags the *mirror signature* — a novel identifier (attribute or string-literal dict key) co-introduced in BOTH a changed test file and the module-under-test yet found nowhere else in the repo, the mechanical signal that a test merely mirrors the implementation's own wrong assumption (the write/TDD self-confirming false positive). Pure-stdlib detection (colleague/testintegrity.py), recorded on TaskResult.test_integrity_report (omit-when-None) and surfaced on stderr; advisory + non-blocking (never blocks the handoff, no network). Default-ON (all-engines) with a COLLEAGUE_TESTINTEGRITY opt-out.
- Bounded re-examine turn (COLLEAGUE_TESTINTEGRITY_FIX_RETRIES, default 0): on a flagged finding after a clean finish, ask the model to verify the symbol against the real API shape and fix it, preserving the work item's terminal summary/status.
- Diverse-model reviewer subagent (COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL): the robust guard — auto-spawns a DIFFERENT-model reviewer to independently re-derive the real API shape; degrades to record-only when unconfigured.
- Model-callable check_test_integrity loop tool (all-engines) so a backend MAY self-check mid-work.
- docs/features/test-integrity.md feature doc.

## [1.14.0] - 2026-06-16

### Added

- Lint pre-finish gate (#200): `colleague work` (and `drive` / `ask-colleague write --apply`) detects the repo's configured Python linters (black/isort/ruff via pyproject.toml, flake8 via .flake8/setup.cfg/tox.ini) and auto-fixes the work item's changed files before the git handoff, so delegated work lands lint-clean without an integrator lint-fix pass. Default-ON with an opt-out (`--no-lint`, `COLLEAGUE_LINT=0`, or `.colleague/config.json` `{"lint": false}`). When reporter violations remain after a clean finish, a bounded model fix-turn (capped by `COLLEAGUE_LINT_FIX_RETRIES`, default 1) is injected; the gate is non-blocking and surfaces residual on stderr + in `TaskResult.lint_report`. Runtime-owned (all-engines rule), zero new runtime deps, curated linter allow-list.

## [1.13.0] - 2026-06-16

### Added

- ask-colleague review/explore + colleague work: a pre-completion progress signal so a long model turn on a slow backend is visibly working, not stalled (#206). The bounded loop now fires a phase notice through the existing per-step progress sink (#38) right BEFORE every model completion — `thinking…` before a normal turn, a louder `synthesizing…` before the no-tools forced-synthesis turn (#191/#202), and `compacting…` before a fill-line summary turn (#156). Previously a single completion (above all the final synthesis turn, observed at ~15 min on a serializing 27B) emitted nothing and was indistinguishable from a hang.

### Changed

- Phase notices are encoded as a progress event with an EMPTY tool name (a reserved sentinel — a real tool always has a name): the plain stderr sink renders the detail as a standalone line, while the structured cockpit and tui-events sinks skip it so `tui replay`/`snapshot` stay step-only. Runtime-owned and all-engines (fires identically for `mock` and `vllm-openai`); a strict no-op without a progress sink; zero new deps/threads. The flight feed is untouched — the synthesis turn runs after the feed is reaped, so a piloting agent already reads the run as ended, not stalled. A live-cockpit `synthesizing` status line is a documented follow-up.

## [1.12.0] - 2026-06-16

### Added

- **Delegation never silently betrays you** — a four-issue trust pass on `colleague work` / `ask-colleague write --apply` / `review`, so a delegated run never silently misplaces, strands, empties, or abandons your work. Spec + plan (authored via the `/think` → `/spec-to-plan` → `/assign-to-workforce` arc): `docs/specs/2026-06-16-when-you-delegate-to-colleague-it-never-silently-b.md` and `docs/plans/2026-06-16-when-you-delegate-to-colleague-it-never-silently-b.md`.
  - **`write --apply` is worktree-isolated (#196/#201)** — `colleague work`/`drive` (and therefore `ask-colleague write --apply`) now run the bounded loop inside a throwaway git worktree created at the operator's HEAD on the `colleague/<id>` branch (`colleague/worktrees.py` `isolation_worktree_add`/`isolation_worktree_remove`, wired in `execute_work`). The operator's working tree and checked-out branch are never touched, a model self-commit *during* the loop lands on `colleague/<id>` instead of the operator's branch (`colleague/handoff.py` `head_sha` + `_finish_self_committed`, gated on the new `base_sha` arg), and two concurrent runs get distinct `iso-<id>` worktrees so they can never cross-pollute. Degrades to the in-place path when there is no HEAD to isolate from or the worktree can't be created — a work item that ran before always still runs.
  - **An empty `finish` on review/explore is never a silent ok (#202)** — `colleague/loop.py` `_maybe_force_synthesis` now also fires on the explicit `_EXIT_FINISHED` path when the finish summary is empty/whitespace, forcing ONE no-tools turn to produce the answer from what was read instead of falling back to the last planning line. A finish carrying a real summary is byte-identical.
  - **A read-heavy review reserves synthesis budget (#197)** — new `COLLEAGUE_SYNTHESIS_RESERVE_STEPS` knob (`EngineConfig.synthesis_reserve_steps`, `ContextControls.synthesis_reserve`, default 0 = byte-identical, forwarded by both backends): the loop holds that many steps back from the reading budget so the forced-synthesis verdict runs with fresher, less-windowed context. `ask-colleague review` now defaults to `--max-steps 30` (alongside `explore`) and exports `COLLEAGUE_SYNTHESIS_RESERVE_STEPS=3` for the read-heavy verbs.

### Notes

- `--allow-dirty` is unchanged: the in-place dirty-tree guard (#149) is kept as the acknowledgement gate. Because `write --apply` now isolates at HEAD, the q1 decision (uncommitted edits are excluded from an isolated run — commit them first to include them) is a clean-HEAD-isolation behavior; a fuller `--allow-dirty` messaging refinement is a documented follow-up.
- Built via `/assign-to-workforce` with **colleague as the writer for the tests + the shell wiring** (t2/t5/t6, engine `vllm-openai`, Qwen3.6-27B) and Claude for the runtime edits (t1/t3/t4) — a different mind doing the field-work, every diff TDD-gated. Follow-ups filed: review/explore progress signal during long synthesis (#206), internal lint pre-finish gate (#200).

## [1.11.0] - 2026-06-15

### Added

- **Plan mode (`colleague plan`)** — colleague now plans a complex task itself: the same arc as the `/think` → `/spec-to-plan` → `/assign-to-workforce` skills, but with **colleague as the planning mind** (a different mind from the requester; the diversity is the point — `/think` keeps Claude as the planner). Native-first and zero-deps (no devague dependency); the orchestrator is engine-agnostic and fires identically for `mock` and `vllm-openai` (all-engines rule). New `colleague/plan/` subpackage:
  - **frame** (`frame.py`) — native plan-mode data model: claims, honesty conditions, steps with a mandatory/optional attribute; stdlib-only, JSON round-trip.
  - **convergence** (`convergence.py`) — the required-kinds gate (announcement, audience, after_state, before_state-or-why, boundary, success_signal + a confirmed honesty condition on every spec-affecting claim); optional steps are skippable.
  - **checkpoint** (`checkpoint.py`) — durable file-based gate state under `.colleague/plan/<id>.json`; resume from the last resolved gate; no daemon/socket.
  - **reviewer** (`reviewer.py`) — a same-model critic (different system prompt) that critiques a proposed item before the operator gate; advisory, never confirms; disabled → byte-identical no-op.
  - **spec / plan / workforce stages** (`spec_stage.py`, `plan_stage.py`, `workforce.py`) — per-item capture→interrogate→review micro-cycle; plan items sized for one bounded child with acceptance criteria + deterministic dependency waves; workforce fan-out reusing `colleague.subagents` `make_batch_spawn`/`batch_spawn` unchanged (FANOUT=4/DEPTH=2), surfacing (never force-merging) conflicts.
  - **judgment** (`trigger.py`, `pushback.py`) — auto-trigger an advisory plan-mode recommendation for a complex task; push back when a task is too small for the pipeline.
  - **orchestrator** (`orchestrator.py`) — drives spec→plan→workforce gated at every step; **never self-confirms**; planning/implementation never runs before the spec converges.
- **`colleague plan` CLI verb** — `plan run` / `plan status` / `plan overview` (+ `explain plan`); the operator gates each item on stdin, `--yes` auto-confirms for non-interactive/agent use, `--review` runs the critic. Needs a live backend.
- **`Engine.make_complete`** — a public one-shot completion seam so non-work-loop features (plan mode) can drive the model directly; `vllm-openai` implements it, `mock` inherits the default (plan mode needs a live backend).
- **Auto-trigger** — `COLLEAGUE_PLAN_OFFER_TOKENS` (`EngineConfig.plan_offer_tokens`, default 0 = dormant): a normal work item injects ONE advisory recommendation to enter plan mode for a complex task; opt-in, strict no-op when dormant, forwarded by every backend (all-engines rule).
- **`ask-colleague plan`** — the inverse-skill surface: a delegating agent hands the whole planning arc to colleague.

Specification + plan: `docs/specs/2026-06-15-colleague-has-a-plan-mode-hand-it-a-vague-or-overs.md` and `docs/plans/2026-06-15-colleague-has-a-plan-mode-hand-it-a-vague-or-overs.md`. Follow-ups filed: spec-less "quick plan" (#199), internal lint pre-finish gate (#200), `Engine.make_complete` seam (#204).

## [1.10.0] - 2026-06-15

### Added

- continue-working: a configurable no-tool-call nudge cap (`COLLEAGUE_MAX_CONTINUE_NUDGES`, default 2, lifting the hardcoded `_MAX_FINISH_NUDGES=1`) so a stalled run resumes past the FIRST stall instead of stopping after one nudge — the t5-class failure where a served 27B narrated "Let me check:" without a tool call and ended after editing 1 of 4 files. Forwarded by every backend via `ContextControls` (all-engines rule); the direct `run()` path falls back to 1 (back-compat). Termination stays bounded by the cap plus the step/token budget.
- auto-compact-on-finish: a context-rich stop no longer pre-empts #191 forced-synthesis by pre-setting mid-thought trailing prose as the summary, so a stopped run gets a clean model-authored summary instead of junk like "Let me check:"; and a fill-line (#156) compaction summary is captured on a dedicated cell and used as the fallback summary at a stop/budget exit when synthesis yields nothing. An explicit finish keeps the model own summary; strict no-op when no stall/compaction occurs.

### Changed

- The summary at a stop-without-finish is now produced by forced-synthesis / a captured compaction summary rather than raw trailing prose (the prose survives only as the last-substantive floor when both yield nothing). A no-content / step_count==0 stop is byte-identical. Summary resolution is consolidated in `colleague/loop.py` `_resolve_terminal_summary`.

### Fixed

- Stale-compaction-summary regression (Qodo PR #198 review): on a stop/budget exit, forced synthesis (#191) now runs BEFORE the compaction self-summary fallback, so a run that compacted mid-flight and then kept working returns a summary reflecting the post-compaction work instead of the stale pre-work compaction note. An earlier draft preferred the compaction summary over synthesis.
- Stale stop-summary docstrings/comments (Qodo PR #198): `_handle_no_tool_turn` and the `_compacted_summary` cell are re-documented to match the current behavior (cap-based nudging; the trailing prose is no longer pre-set as the summary; the compaction summary is a fallback, not preferred).
- SonarCloud S3776 (`run()` cognitive complexity 18→under threshold): summary resolution, the nudge-cap default, and the outcome-flags/status mapping are extracted into helpers (`_resolve_terminal_summary`, `_resolve_nudge_cap`, `_apply_outcome_flags`).
- SonarCloud S107 (`EngineConfig.resolve` parameter count): the unused explicit `temperature`/`timeout` keyword arguments are dropped (no caller, no CLI flag, no test passes them); both still resolve from `COLLEAGUE_*` env vars (with `CONVERTIBLE_*` fallbacks) and built-in defaults.

## [1.9.0] - 2026-06-15

### Added

- Explore/drive never wastes a run (#188/#191): a budget-exhausted or stopped run that read context but never finished now performs one forced no-tools synthesis turn and returns that as the summary, falling back to NO_RESULT_PRODUCED only when even that turn is empty.
- Advisory subagent fan-out for wide read-only mapping (#188): once a survey reads more than COLLEAGUE_FANOUT_FILES files (default 12, env-tunable), the loop injects one advisory recommendation to fan out per-folder via the subagents tool. Backend-judged, strict no-op when dormant; the explore prompt now steers wide maps toward subagents.
- ask-colleague explore gets its own default step budget (30 vs 20 for write/review, #194) and an actionable partial-run warning naming the reached step count and a concrete larger --max-steps to retry with.

### Changed

- A run that does not cleanly finish now reports status:incomplete with a non-zero exit (#192) instead of a misleading status:ok, so callers can detect a no-result/partial run without sentinel string-matching. ask-colleague.sh suppresses the success-shaped grade footer and warns on a NO_RESULT_PRODUCED summary.

### Fixed

- ask-colleague.sh uv-fallback resolver is grep-free (#190): a pure-bash _pyproject_is_colleague check resolves a colleague checkout even on a PATH with no grep.

## [1.8.0] - 2026-06-14

### Added

- **Pilot a running work item ("flights").** A work item dispatched with `colleague work --watch` becomes a *watchable flight*: the runtime arms a file-based control plane under `.colleague/flight/<task_id>.{feed.jsonl,control.json}` and, at each turn boundary in the bounded loop, appends a live-feed record and reads a per-flight control file. The dispatching agent — Claude **or** a colleague work-loop — pilots it via the new `colleague flight` noun: `flight status` (watch the live feed), `flight guide <id> "<msg>"` (inject mid-flight guidance the model picks up on its next turn), `flight stop <id>` (cooperative stop that preserves a partial result), `flight list`, and `flight overview`. The `ask-colleague` skill gains matching `--watch` / `monitor` / `guide` / `stop` verbs. Control is **cooperative, not preemptive** (applied only at turn boundaries — never mid-model-call), file-based (**no daemon, no socket, zero new deps**), runtime-owned (fires identically for `mock` and `vllm-openai` — the all-engines rule), and a **strict no-op** when a work item is not a flight (byte-identical `TaskResult`). Caller-symmetric and depth-capped (`COLLEAGUE_FLIGHT_DEPTH`, fork-bomb guard). A cooperative stop is recorded as a partial (`stopped_without_finish`), never a bare `ok` with no result.

## [1.7.1] - 2026-06-13

### Fixed

- resident channel discovery shelled a non-existent `<roster_cli> roster` subcommand, so a promoted resident silently degraded to its owned channel only and never auto-joined existing mesh channels; discovery now uses `culture channel list` (steward has no channel-listing verb), so the resident joins discovered channels like #general/#system as the spec intends.

## [1.7.0] - 2026-06-12

### Added

- **`ask-colleague.sh` gains a `--json` flag (any verb).** Stdout now carries **only** the result JSON, with every diagnostic/digest line on stderr — satisfying the cross-repo CLI `--json` contract (qodo rule 824501, surfaced re-vendoring into dgx-spark-cli#12). The drive verbs (`explore`/`review`/`write`) emit the normalized `TaskResult` (with `artifacts_path` rewritten to the preserved copy) that `colleague drive --json` already produced; `feedback` and `clean` forward `--json` to colleague, which supports it natively. The human digest, the `write` preview diff, and partial-drive warnings all move to stderr in `--json` mode so stdout stays valid JSON for a machine consumer.

### Fixed

- **`--json` no longer leaks a dead `artifacts_path` for a `write` preview (#186 qodo finding-3).** A preview drives in a throwaway worktree that the EXIT trap deletes, so its `artifacts_path` names a dir that is gone by the time the caller reads the JSON. The non-`--json` digest already gates the printed `artifact:` line on the survives-flag (`ASK_COLLEAGUE_GRADABLE`); the `--json` branch now mirrors that gate — `artifacts_path` is dropped when the artifact is not gradable and rewritten to the preserved copy when it is — so a machine consumer never receives a path into the cleaned-up worktree.
- **`--json` now echoes the `task:`/`grade:` hints to stderr for a gradable drive (#186 qodo finding-2).** The hints follow the convention every work item emits while keeping stdout pure JSON (the `task_id` is in the payload too); a preview stays hint-free since it is not gradable.
- **`ask-colleague.sh` no longer over-requires tools (qodo bug).** `require_tools` was a single blanket check demanding `python3`/`git`/`grep`/`mktemp` for *every* verb, so `feedback`/`clean` — thin pass-throughs to the `colleague` CLI that never touch python3/mktemp — failed `exit 2` in minimal environments. The check is now verb-specific: `feedback`/`clean` need only `git` (the shared work-tree guard); `explore`/`review` and a `write` preview need `git`+`python3`+`mktemp`; `write --apply`/`--pr` (no throwaway worktree) needs `git`+`python3` but not `mktemp`. `grep` is dropped from the hard requirement (it is only used by the `uv`-fallback resolver, which degrades to the clear "colleague not found" message when absent).

## [1.6.4] - 2026-06-12

### Added

- **Colleague owns the model-gear boundary (#182).** A model-server failure on a tool-calling request is now Colleague's to make legible + catchable, not the caller's to debug. Three changes: (1) `colleague doctor --probe` does a real tool-calling round-trip (`tool_calling` check) that **reads and verifies the response**: WORKS (the server emitted a `tool_call` for a tool-demanding prompt) / ACCEPTED-BUT-IGNORED (a 2xx with no `tool_call` — the false-green this catches) / TIMED-OUT (the tool path hung) / TOOL-CALLS-UNSUPPORTED (400 → enable `--enable-auto-tool-choice` + `--tool-call-parser`) / SERVER-CRASHED (a 500 whose body names `EngineCore` → the build can't serve tool calls) — catching a server that answers `GET /v1/models` but crashes on the tools requests Colleague actually sends; (2) the vLLM engine maps such a 500 to an actionable error (likely cause + a `doctor --probe` pointer), preserving the upstream body and degrading to a generic "server returned a 500" for any other 500; (3) `COLLEAGUE_DUMP_REQUEST=1` dumps the exact outgoing request payload to stderr (the api_key is a header, never in the dump).
- **Audience:** the caller (an agent, via `ask-colleague`) gets a clean Colleague error; the operator (who runs the server) gets the actionable remediation. **Before:** `doctor --probe` went green on a server that then crashed mid-work, and the crash surfaced as a bare `HTTP 500 … EngineCore` after minutes. **Honest limit:** the probe sends a *minimal* request, so a size-dependent crash (the original #182 case crashed only on a large diff) can pass the probe and surface as the legible engine error instead. Zero new dependencies (stdlib `urllib`); spec + plan under `docs/specs/` / `docs/plans/`.

## [1.6.3] - 2026-06-12

### Fixed

- `ask-colleague.sh`: `resolve_colleague()` now honors `--repo` for the `uv` local-dev fallback — with `colleague` off `PATH` and `--repo` pointing at a colleague checkout it resolves via `uv run --project <checkout> colleague` instead of failing `colleague CLI not found`. The upward `pyproject` walk is factored into a `_colleague_via_uv` helper tried against `$PWD` then the resolved `$REPO` (#181, surfaced vendoring into culture).
- `ask-colleague.sh`: a `colleague drive` failure now propagates colleague's documented tri-state exit code (0/1/2, #161) end-to-end instead of collapsing every non-`ok` drive to `1`. The real drive rc is captured (no more `|| true`) and threaded into `print_result`, which exits `0` on success, `2` on an environment/setup failure (and on its own parse-level failures), else `1` (#180 finding-1, surfaced vendoring into agentirc).
- `ask-colleague.sh`: a `write` preview (and a read-only run whose artifact was not preserved) no longer prints an `artifact:` line pointing into the throwaway worktree that is deleted on exit. The print is gated on the existing `ASK_COLLEAGUE_GRADABLE` survives-flag, unified with the `grade:` hint (#180 finding-2).

These are wrapper-only fixes — no change to colleague's Python CLI, the prompt templates, or `SKILL.md`. The downstreams that vendor `ask-colleague` verbatim (steward, agentirc, culture) re-vendor to pick them up (#179). New black-box regression tests in `tests/test_ask_colleague_skill.py` cover all three (fake `colleague` stub on `PATH`, no live model).

## [1.6.2] - 2026-06-12

### Added

- docs: a "Two senses of learn" section disambiguating colleague learn (read-only self-teaching prompt) from colleague learn-from (absorbs a peer agent skills, writes files); surface learn-from in the README CLI + feature tables and cross-reference learn <-> learn-from across agent-cli.md and learn-from.md.

### Changed

- docs: lead README with a plain-English problem statement; move Quickstart, a "When to reach for colleague" section, and a common-commands table to the top; promote the vLLM setup to its own section.
- docs: regroup the docs/features index into 7 categories with a "start here" path, and add the 6 pages that were missing from it (learn-from, auto-split, graceful-degradation, parallel-subagents, tui, resident-promote).
- docs: sweep stale "v0" labels now that the project is v1.

## [1.6.1] - 2026-06-12

### Changed

- The `[culture]` install hint, `colleague explain promote`, and `docs/features/resident-promote.md` now document the `uv tool install --python 3.12 'colleague[culture]'` form and call out the Python >=3.12 requirement — the missing `--python 3.12` (uv defaulting to a <3.12 interpreter) was the cause of the `does not satisfy Python>=3.12` install failure, not the extra itself.

### Fixed

- `colleague promote` now surfaces a pre-existing / differing `culture.yaml` (e.g. promoting inside an AgentCulture repo such as colleague's own checkout) as an actionable error pointing at `--force`, instead of leaking it as the top-level `unexpected: ConflictError … file a bug` internal-error wrap.
- Test suite is now hermetic with respect to provider environment variables. A new `tests/conftest.py` autouse fixture clears `COLLEAGUE_*` / `CONVERTIBLE_*` / provider `OPENAI_*` env vars before every test, so the config + oilcheck tests that assert built-in defaults pass regardless of a developer box exporting them for a live rig (they previously passed in CI but failed locally). Also refreshes `test_oilcheck_provider._PROVIDER_ENV_KEYS`, which still listed only the legacy `CONVERTIBLE_*` names and let the canonical `COLLEAGUE_API_KEY` leak through after the convertible→colleague rename.

## [1.6.0] - 2026-06-12

### Added

- **Resident promotion — `colleague promote`** (mesh-member graduation): colleague graduates from a born-and-trained task runner into a persistent **resident** member of the Culture mesh. The same colleague that drives bounded `colleague work` items is elevated *in place* into a long-lived peer that owns a channel and answers messages. Built on agent-lifecycle's asyncio runtime seam + the agentirc-cli wire, both opt-in behind the new `[culture]` extra (base install stays `dependencies = []`). New `colleague/resident/` package: `ColleagueHarness` (the bounded loop adapted onto agent-lifecycle's `Harness`, no git handoff — h10/h3), `IRCTransportAdapter` (Transport + Presence), `IRCConnection` (the live IRC wire over `asyncio.open_connection`) + `serve_live`, `build_resident_supervisor` (the pump bridge), identity minting (`culture.yaml` + prompt, reuses `colleague/identity.py`), channel selection (queries the Culture roster/steward, owns `#<nick>`), self-registration, and `steward.py` (the one sanctioned subprocess consumer). Surfaced as the `colleague promote` verb + the `/promote` operator skill. Spec + plan: `docs/specs/2026-06-10-colleague-graduates-from-a-born-and-trained-task-r.md` / `docs/plans/2026-06-12-colleague-graduates-from-a-born-and-trained-task-r.md`; feature doc: `docs/features/resident-promote.md`.

### Changed

- The boundary guard (`tests/test_boundary.py`) now narrows the no-async rule: `colleague/resident/` is the **sanctioned async/networked exception** (the `c11` narrowing — "no daemon on the work-item path"). `asyncio` is permitted under `resident/` only; `socket` stays forbidden everywhere (agentirc-cli owns the wire); `subprocess` is confined to `resident/steward.py`. The bounded `colleague work` path stays byte-identical and async-free (guarded by `tests/test_resident_no_work_path.py`); the e2e mock TaskResult shape is unchanged.

## [1.5.0] - 2026-06-10

### Added

- `edit_file` loop tool — an exact-string partial-edit primitive (a sixth base tool) whose cost scales with the change, not the file size, so a scoped edit to a large existing file no longer needs a whole-file `write_file` rewrite (#174).

### Changed

- The agent loop system prompt now nudges the model to prefer `edit_file` over `write_file` for edits to existing files; the `bytes_written` stat counts only the bytes an edit authors into a file.

## [1.4.0] - 2026-06-10

### Added

- colleague tui --repo PATH: opt-in flag on tui state/render/inspect/action/snapshot that prepends a live Context panel (repo + branch + working tree) so the headless TAUI (tui state) and TUI (tui render, ANSI + Markdown) surfaces show the current repo and branch — not just the interactive session.
- colleague/cockpit.py: shared, stdlib-only repo-context builder (resolve_repo_context / build_repo_context_panel / build_cockpit_state) reused by the session and the headless tui command so repo/branch resolve identically across surfaces.

### Changed

- The live colleague session / autocomplete popup now opens BELOW the colleague input line (modern completion UX) instead of above it, with the typing cursor restored to the input line.
- colleague tui render --state is now optional (matching state/inspect/action/snapshot), so colleague tui render --repo . renders the live repo cockpit standalone.
- session._facts() now resolves branch/dirty/repo-identity through colleague.cockpit (single source of truth).

## [1.3.0] - 2026-06-08

### Added

- ``colleague config show`` / ``config overview`` verb: prints the resolved provider
  configuration (base_url, model, max_steps, temperature, timeout,
  context_budget_tokens) with api_key redacted. Reflects .colleague/config.json
  when --repo is given.
- ``colleague doctor --repo`` now reflects .colleague/config.json: provider and
  reachability groups accept an optional repo_path, so doctor diagnoses the
  current repo's persistent config-file override.

### Changed

- Documented the .colleague/config.json provider override in
  docs/features/model-selection.md (worked OpenAI/OpenRouter examples; corrected
  default-model table).

## [1.2.0] - 2026-06-08

### Added

- Persistent config-file override for the engine endpoint: .colleague/config.json (repo-level, falling back to user-level ~/.colleague/config.json) feeds base_url/api_key/model into EngineConfig.resolve as the resolution default, so colleague can be pointed at any OpenAI-compatible provider (replacing the local vLLM) without re-passing CLI flags or env vars. Precedence: explicit flag > COLLEAGUE_*/OPENAI_* env > .colleague/config.json > built-in default. Wired into the work/session/learn-from paths; stdlib json only; absent/malformed file is a strict no-op (colleague/config.py load_config_file).

### Changed

- EngineConfig.resolve gains an optional repo_path keyword; when omitted, behavior is byte-identical to before.

## [1.1.0] - 2026-06-06

### Added

- colleague `learn-from <source>`: learn skills from a peer agent (first source: claude) — read `.claude/skills/<name>/SKILL.md` and adapt each into colleague's own `.colleague/skills/<name>.md` (deterministic, stdlib-only copy: frontmatter strip incl. block scalars, description-first summary line, learned-from provenance marker; idempotent create/skip/update/protect).
- Optional stage-2 LLM review-and-adapt pass driven by the configured backend over each written skill in the working tree (no git handoff); --copy-only skips it and it degrades to copy-only when no backend is reachable.
- /learn-from session slash command (deterministic copy, --copy-only).
- colleague explain learn-from + docs/features/learn-from.md.

## [1.0.0] - 2026-06-06

### Added

- Capacity standard (#156): proactive fill-line decision (compact | split | finish-with-handoff) recorded on TaskResult.capacity_decision; self-compaction summarizes the working history to itself with lossy windowing as the fallback floor; coarse complexity assessment in colleague/capacity.py; warn-only "too big for one repo" caller warning (TaskResult.capacity_warning). Tunable via COLLEAGUE_FILLLINE_THRESHOLD (default 0.8).

### Changed

- v0 -> v1 graduation: the v0 "no LLM-generated summary" convention is intentionally superseded by self-compaction; lossy windowing remains the documented fallback floor.

## [0.42.0] - 2026-06-06

### Added

- `colleague clean` verb + `ask-colleague clean`: reap stale/corrupt `colleague/*` branches and orphaned 0-byte `.colleague/` artifacts left by a crashed work item (which can wedge `git fetch`), scoped strictly to `colleague/*` and conservative with `.git/objects` (#162)
- Advisory doctor stale-ref check (`colleague_stale_refs`, warning severity) that flags a wedged repo and points at `colleague clean` (#162)

### Changed

- Handoff is crash-resilient: a catchable interruption (`HandoffError` / `KeyboardInterrupt`) before the commit lands restores the operator ref and reaps the orphan `colleague/<id>` branch; the success path is byte-identical (#162)
- `ask-colleague.sh`: user-input errors (bad/missing verb, flag, arg, path; dirty-tree guard) now exit 1 not 2, matching the CLI 0/1/2 contract; environment errors stay 2 (#161)
- `ask-colleague` SKILL.md: explore/review side-effect cells no longer claim unqualified None (they write a gradable `.colleague/` artifact); added a consumer gitignore note for `.colleague/` (#161)

## [0.41.0] - 2026-06-06

### Added

- Slash dropdown grouped tree with tag badges (#160): the colleague session / autocomplete popup is now a borderless (frameless) grouped tree — commands sit under one icon per intent group (📁 Controls / Inspect / Session) with compact capability/risk tag badges ([read-only], [git], [pr], [writes], …) next to each command; filtering preserves group context and the selected command shows its summary.
- New SlashSpec.tags metadata feeds the popup, /help, and the cockpit tiers from one source; a shared tag/group formatter (colleague/tui/widgets/slash_autocomplete.py) keeps them from drifting.
- /help compact renders the emoji tag form; COLLEAGUE_SLASH_TAG_STYLE=icons switches the live popup to icon badges.
- PanelItem.tags so the slash-command tree (slash.* panels, one per group) reaches the agent-facing Markdown and TAUI/JSON cockpit tiers; the borderless live session view skips them (the / popup covers that).

### Changed

- /help and /help verbose now render group icons and tag badges; the compact help lists each command on its own line under its group instead of a dense name row.
- TAUI mirror schema bumped to 0.2 (panel items gained an optional tags list).

## [0.40.0] - 2026-06-06

### Added

- Session delegation cockpit (#158): a Run policy panel (run_command gating, file edits, push/PR) and a Context panel (repo, branch, working-tree state, AGENTS-layer and skill counts, telemetry, /feedback availability) on the first session screen, plus a suggested next action that always answers "what now?".
- Borderless, Markdown-feel interactive ANSI cockpit renderer (colleague/tui/render/ansi_flat.py) with an animated emoji state glyph (moon-phase while a work item runs, steady severity glyph at idle); derived from taui.serialize so it cannot drift from the Markdown view.
- Grouped compact /help (Controls / Inspect / Session) plus a richer /help verbose.

### Changed

- The session work-templates palette is retitled "Work templates" (panel id unchanged); the policy + context panels flow into the Markdown and TAUI tiers for free.
- Promoted handoff._current_ref to public handoff.current_ref (read-only branch accessor) so the cockpit can surface the current branch.

### Fixed

- The Session panel's suggested next action no longer goes stale (#159 review): `_refresh_context()` now recomputes and replaces the leading suggestion in place after `/pr`, `/base`, `/model`, `/engine`, and a completed work item, so the cockpit keeps its "always answer what now?" promise (it previously rebuilt only the policy + context panels).
- The Run policy panel labels `run_command` honestly (#159 review): an empty allow-list paired with a deny-list now reads `deny-list: … (all others allowed)` and a section with no rules reads `present, no rules (effectively ungated)`, instead of misleadingly claiming `gated (deny unlisted)` — matching what `Policy.check_run_command` actually enforces (an allow-list only gates when non-empty).
- The Run policy panel no longer crashes on a malformed `approvals.json` (#159 review): allow/deny values are coerced through a string-list sanitizer mirroring `policy._str_list`, so an `allow` given as a dict or a list with non-string members degrades gracefully instead of raising `TypeError` during render.

## [0.39.2] - 2026-06-05

### Added

- `colleague/context.py` `is_request_timeout` + `classify_degradable` — sibling detectors that drive the loops degradation and auto-split gates for both overflow and request-timeout signals (all-engines rule).

### Changed

- The `doc-review` command template is now self-scoping: it audits a few surfaces per pass and recommends a per-surface split early, so a large doc set no longer blows the request timeout. CLAUDE.md and `docs/features/graceful-degradation.md` document the timeout-degradation path and its honest limit (a dead/stuck server still wastes the bounded timeout retries).

### Fixed

- A request timeout mid-completion now degrades gracefully like a context-overflow instead of hard-failing with no deliverable (#154): the loop trims history and retries (capped lower, `_MAX_TIMEOUT_RETRIES=1`, since each timeout costs a full `COLLEAGUE_TIMEOUT` window), and on an exhausted give-up injects the auto-split/INCOMPLETE recommendation against a carried-forward floored window so the model can still produce an INCOMPLETE report. The vLLM `_post_json` now wraps a read-phase `TimeoutError` legibly (keeps "timed out" for the detector, surfaces the `COLLEAGUE_TIMEOUT` knob).
- `_complete_with_degradation` now honours `classify_degradable`'s overflow-takes-precedence rule across a mixed sequence (#157 review): an overflow seen *after* an earlier timeout restores the higher `_MAX_OVERFLOW_RETRIES` cap instead of staying pinned to the lower timeout cap, so the cheap overflow retries are no longer starved by the earlier timeout. The reactive shrink-and-retry was refactored into focused helpers (`_open_degradation_window`, `_shrink_for_retry`, `_plan_degraded_retry`, `_final_degraded_attempt`) to drop its cognitive complexity below the SonarCloud threshold, and the new `# noqa` suppression comments were normalised to a parsable form.

## [0.39.1] - 2026-06-05

### Changed

- Docs terminology cleanup to match the `drive`->`work` rename and align "outsource" wording to "delegate": `drive` (noun)->`work item`, `drive branch`->`work branch`, `colleague drive`->`colleague work`, and outsource(d)->delegate(d) across the ask-colleague SKILL.md, stats-and-feedback, and escalation docs; back-compat/rename-history lines intentionally preserved.
- CLAUDE.md: added a Prefer Colleague over spawning a sub-agent guidance paragraph to the division-of-labor section.

## [0.39.0] - 2026-06-05

### Added

- Auto-split (#151): when an assignment is too large for one context window, colleague now recommends splitting it into up to ~4 hand-over child assignments via the existing `subagents` tool instead of degrading lossily or failing. Advisory and backend-judged: the reactive trigger fires at the degradation-exhaustion point (when bounded overflow retries are exhausted) and is sequenced BEFORE escalation; the model decides whether to split. A coarse up-front instruction estimate adds an early advisory hint. The fan-out + merge reuse `colleague.subagents.make_batch_spawn`/`batch_spawn` verbatim. Capacity is a tunable `COLLEAGUE_AUTOSPLIT_TARGET` knob (default ~1M tokens), structurally clamped to `MAX_SUBAGENT_FANOUT - 1`. Runtime-owned (all-engines rule); zero new deps; a strict no-op when no trigger fires.

## [0.38.0] - 2026-06-05

### Added

- `--allow-dirty` flag on `colleague work`/`drive` and `colleague session` to opt into running against a dirty working tree.

### Fixed

- Dirty-tree guard (#149): a bare `colleague work`/`drive`/`session` against a repo with uncommitted *tracked* changes now refuses up front instead of silently sweeping those edits onto the work branch. The check is tracked-changes-only (pre-existing untracked WIP is already protected by the handoff baseline); pass `--allow-dirty` to opt in. The `ask-colleague` skill propagates `--allow-dirty` through to the runtime.

## [0.37.0] - 2026-06-05

### Changed

- **Renamed the core operation `drive` → `work`** — the last car-themed term, now
  aligned with colleague's work-partner framing. The CLI verb is **`colleague work`**;
  the run/record noun is a **"work item"** (`WorkStats`, `WorkItem`, `WorkStep`,
  `WorkSummary`, `WorkAborted`, `execute_work`, `_work_loop`). `Engine.drive()` →
  **`Engine.work()`** (every backend). Back-compat: **`colleague drive` is a deprecated
  alias** (still resolves; `--help` row labelled deprecated), so existing invocations,
  scripts, and the `ask-colleague` wrapper keep working. `colleague explain drive`
  still resolves. Reflected in `colleague learn`, `colleague explain`, and all docs.
- `Engine.drive()` → **`Engine.work()`** carries a **back-compat bridge** for
  out-of-tree plugins: a legacy backend that still implements `drive()` (not
  `work()`) is bridged automatically (`Engine.__init_subclass__` aliases its
  `work` to `drive` with a `DeprecationWarning`), and the base `Engine.drive()`
  delegates to `work()` so callers using the old method name still work — so a
  pre-rename plugin keeps instantiating and running via `registry.load`.
- The `feedback` "last" pointer file is now `.colleague/last_work`; the legacy
  `.colleague/last_drive` is still **read** as a fallback (old repos resolve `last`).
- TUI/TAUI: the cockpit `Drive` snapshot class → `WorkItem`; the snapshot JSON key
  `"drive"` → `"work"` and the Markdown section `## Drive` → `## Work`; the trace event
  type `"drive_step"` → `"work_step"`. Old snapshots/traces (carrying `"drive"` /
  `"drive_step"`) are still **read** (back-compat fallbacks), so `tui replay`/`diagnose`
  on pre-rename artifacts keep working.

### Breaking

- **OTel span/metric renamed** `colleague.drive` → `colleague.work` and
  `colleague.drive.duration` → `colleague.work.duration`. A span name cannot be
  aliased transparently, so existing dashboards/queries on `colleague.drive` must be
  updated.
- **`whoami` / `overview` JSON keys renamed** `drive_engine`/`drive_model` →
  `work_engine`/`work_model` (text labels: "work engine:" / "work model:"). Consumers
  parsing these keys must update.

## [0.36.0] - 2026-06-05

### Changed

- **Renamed the first-party `outsource` skill to `ask-colleague`** — a peer-framed name (you *ask a colleague*; you don't *outsource* to a vendor) that fits colleague as a daily work partner and lowers the bar to reach for it. The four verbs are unchanged: `ask-colleague explore | review | write | feedback`. Back-compat: the "outsource this" trigger phrase still fires the skill, and `colleague explain outsource` still resolves. The wrapper is now `.claude/skills/ask-colleague/scripts/ask-colleague.sh`; the feature doc is `docs/features/ask-colleague.md`. Reflected in `colleague learn` and `colleague explain`.
- **Renamed the `wheels` CLI noun to `backends`** (`colleague backends list | overview`) — retiring the old *convertible*-era car-themed name in favour of colleague's "one runtime, many minds" vocabulary. `wheels` is kept as a **deprecated alias** (it still resolves; its `--help` row is labelled deprecated, and `colleague explain wheels` resolves to the `backends` entry). `registry.WheelInfo` → `registry.BackendInfo`.

### Removed

- Retired the trucking-themed `convoy` alias for `colleague explain subagent` (the `subagent` / `subagents` names are unchanged).

## [0.35.2] - 2026-06-05

### Fixed

- Bare `colleague drive` now echoes a `grade: colleague feedback record <task_id> --rating N` hint in its result block (#144) — the ROI-loop nudge was previously emitted only by the `outsource` wrapper. The placeholder is shell-safe (`N`, not `<1-5>`) so the line is copy-pasteable; JSON output is unaffected.
- `colleague feedback record` now emits a stderr advisory when no identity resolves (no `--by`, no `culture.yaml` nick / `.colleague/identity.json`), instead of silently leaving `by` empty (rendered as `(unknown)` in text) (#145). The record still writes; `--json` stdout is untouched.

## [0.35.1] - 2026-06-05

### Added

- docs/cli-experience-evaluation.md — a hands-on, live-rig evaluation of the agent-facing CLI/DX experience (companion to the TUI-rendering evaluation).

### Fixed

- `overview` Identity now mirrors `whoami` — it surfaces the live-resolved `drive engine` + `drive model` instead of a bare `model:` (the mesh model, often `unknown`) that silently disagreed with `whoami`.

## [0.35.0] - 2026-06-05

### Added

- TaskResult.stopped_without_finish — flags a drive that ended on a no-tool-call turn without ever calling finish (colleague#142); serialized in the artifact and surfaced by the outsource wrapper

### Fixed

- Loop no longer treats a no-tool-call turn as a clean finish: it nudges the model once to call finish (recovering the common mid-task trail-off), and a stubborn stop is flagged via stopped_without_finish instead of silently returning trailing narration as an authoritative result (colleague#142)

## [0.34.2] - 2026-06-05

### Added

- tools/tui_sim: deterministic asciinema .cast simulations of the TUI (palette + slash autocomplete, drive cockpit, skill/error popups, full end-to-end ride) built from the real pure render seams — dev-only, zero new runtime deps
- docs/tui-experience-evaluation.md: a frame-by-frame human-experience evaluation of the TUI drawn from the recordings
- `_Session.__init__` gains an optional `user_home` (default `None` = current behavior) plumbed to `discover_commands`, so a caller can scope palette command discovery hermetically

### Fixed

- tools/tui_sim recordings are now hermetic: `build_session` pins `user_home` to the repo so a contributor's personal `~/.colleague/commands` can't leak into the palette and break byte-identical regeneration (PR #141 review)
- tools.tui_sim progress log moved to stderr, keeping stdout clean (agent-first results/diagnostics separation)

## [0.34.1] - 2026-06-05

### Changed

- Live-testing ledger: field-audited the always-on DriveStats block against a real drive (drive a6c5f0c1fd13) — flipped the Drive stats row from partial to validated and added a re-checkable §0 procedure. bytes_written verified exact (101) against the committed file; tool_counts/step_count/files_changed mirror the live step trace; usage tokens verbatim. No code change; closes out epic #128.

## [0.34.0] - 2026-06-05

### Added

- `colleague feedback list` (and `outsource feedback list`) — list every recorded drive newest-first by request, status, and grade; the durable way to find a drive when the order is forgotten. Reads the authoritative task_id from each artifact's contents, so the filename scheme does not matter (#132).
- `feedback record last` / `feedback show last` now echo the resolved drive's id + request to stderr, so a `last` mis-resolve is never silent; every `outsource` drive digest prints `task:` and a copy-paste `grade:` hint (#132).
- Request-slugged artifact filenames (`<task_id>.<slug>.json`) and drive branches (`colleague/<task_id>-<slug>`) so a drive is recognisable in an `ls` / `git branch` listing; `colleague/slug.py` + `artifact.find_artifact`/`read_request` resolve both bare and slugged names (back-compat) (#132).

### Changed

- `last` is now writes-only across the outsource flow (#132): `outsource explore`/`review` preserve their artifact but no longer move the `last_drive` pointer (the skill's `_preserve_artifact` stopped writing it), so a read-only probe can never steal a grade meant for a consequential write. A probe is graded by its printed task_id or via `feedback list`. The skill now preserves the artifact by the basename the drive reports (robust to bare or slugged names).
- Refactored `feedback.list_drives` — extracted `_load_drive_artifact` / `_drive_rating` / `_drive_summary` helpers to cut its cognitive complexity from 27 to ~12 (SonarCloud ≤15), with no behavior change (PR #139 review).

### Fixed

- Early-failure drives keep their request (PR #139 qodo): `failed_result` now records `stats.request` + `started_at` when given the instruction, and `execute_drive` passes `task.instruction` on the no-partial path — so an artifact written before the loop runs is still slugged, discoverable-by-request, and sortable in `feedback list` instead of a blank row.
- `outsource`'s `print_result` grade hint no longer requires `status == ok` (PR #139 qodo): a failed-but-gradable drive (colleague writes an artifact on failure, and a failure rated 1/5 is the ROI signal) now emits the copy-paste `grade:` command on the failure digest (stderr).

## [0.33.9] - 2026-06-05

### Added

- Live-validation test `tests/test_vllm_live_context_budget.py` (gated by `COLLEAGUE_VLLM_E2E`) proving context-overflow graceful degradation end-to-end against a real served model: proactive history windowing (a small budget + a chained read task drops oldest turns and inserts the placeholder in real model requests) and reactive trim+retry recovery (an induced overflow shrinks the budget and the retry recovers against the live model) (#127).

### Changed

- Live-testing ledger (`docs/live-testing.md`) row 7 (Context-overflow graceful degradation) marked validated with the §7 result block (proactive drive `36b022abc7f0`, reactive drive `0323db53b1dd`); every matrix row + epic #128 is now validated live.

## [0.33.8] - 2026-06-05

### Added

- End-to-end telemetry validation through the production `execute_drive` path: `tests/test_telemetry_e2e.py` (engine-agnostic, runs in CI when the `[otel]` extra is installed) asserts the full root + per-tool + handoff span tree (nested in one trace) and all metrics, and covers the previously-untested `colleague.handoff` span, `colleague.drive.duration`, and `colleague.hook.denials`. `tests/test_vllm_live_telemetry.py` (gated by `COLLEAGUE_VLLM_E2E`) adds a live-model composition stamp (#126).

### Changed

- Live-testing ledger (`docs/live-testing.md`) row 6 (Telemetry end-to-end) marked validated with the §6 result block (live drives `eff14af763d4`, `02c811085cb6`).

## [0.33.7] - 2026-06-05

### Added

- Live-validation test `tests/test_vllm_live_neighbours.py` (gated by `COLLEAGUE_VLLM_E2E`) proving operator-configured neighbour read-only clones fire end-to-end against a real served model: clone-on-start + read, cleanup-on-finish, and gitignored (#125).

### Changed

- Live-testing ledger (`docs/live-testing.md`) row 5 (Neighbours read-only clones) marked validated with the §5 result block (drives `711505cb4c3f`, `09d31abcf160`).

## [0.33.6] - 2026-06-05

### Added

- docs/live-testing.md §4 marked ✅: loop tools `culture` + `devague` validated live (#124). 4a — drive `2395f7d5d9b9` called `culture(cli='devex', args=['--version'])` and it shelled out (`exit=0`, identity injected). 4b — drive `80cb15c5f9cd` called `devague` `new` + `status` (both `exit=0`; `new` wrote only a self-contained `.devague/`), and the model declared a `destination` on finish as a live bonus. Allow-lists / `confirm`/`reject`/`export` exclusions / identity injection / destination-in-artifact stay DETERMINISTIC (schema `enum` makes a forbidden value unreachable live) — cited, not re-proven.
- tests/test_vllm_live_loop_tools.py — gated (`COLLEAGUE_VLLM_E2E=1`) live proof that a real model reaches the `culture` + `devague` tools and they shell out to the operator-installed CLIs; tasks constrained to zero-side-effect subcommands.

### Changed

- `_DEFAULT_SYSTEM` (colleague/loop.py) now names the `culture` tool and its `agtag`/`devex` CLIs — the same #122-style gap (an unnamed loop tool is invisible to the live model). Advisory, runtime-owned (all-engines). Pinned by `tests/test_destination_loop.py::test_default_system_advertises_culture_tools`.

## [0.33.5] - 2026-06-04

### Added

- docs/live-testing.md §3 marked ✅: gated configs enforcement validated (#123). 3a/3c/3d proven LIVE against the reference rig (drives `324819918d83`/`21dff9b0fb93` run_command deny/allow, `a30324e89aa3`/`23fa581fc19a` hook deny/rewrite, `5a590ffb360f` per-model overlay); 3b (checksum-void + command-expand-refused) and 3e (per-model AGENTS/skills composition) proven DETERMINISTICALLY (engine-agnostic — a live model adds no signal).
- tests/test_vllm_live_gated_configs.py — gated (`COLLEAGUE_VLLM_E2E=1`) live proof that a real model's run_command/write_file call hits the approval gate / pre_tool hooks, and that the per-model hooks overlay loads via `load_hooks(model=config.model)`.
- tests/test_gated_configs_enforcement.py — fast deterministic proof of 3b (checksum drift voids a hook approval → skipped; a drifted command template is refused at expand time) and 3e (`system_prompt_for` folds per-model AGENTS/skills into the prompt; a sibling model sees neither). All config lives in throwaway tmp_path — the repo still ships none.

## [0.33.4] - 2026-06-04

### Added

- docs/live-testing.md §2 marked ✅: subagents validated live (#122). Live drive `6c27147eb917` against the reference rig delegated via the parallel `subagents` tool (`COLLEAGUE_SUBAGENT_CONCURRENCY=2`) — two children in isolated `sub/<id>` worktrees, a merge child integrated both branches cleanly, worktrees torn down, `sub_results` folded into the artifact.
- tests/test_vllm_live_subagents.py — gated (`COLLEAGUE_VLLM_E2E=1`) end-to-end proof that a real model reaches the `subagents` tool and the worktree create→merge→cleanup lifecycle runs; asserts on structural facts (`sub_results` populated, worktrees cleaned) robust to model-text variance.

### Changed

- `_DEFAULT_SYSTEM` subagents guidance (colleague/loop.py) now names the parallel `subagents` batch tool and its isolated-worktree/merge-child/conflict-surfacing nature, and invites delegation on naturally-parallel multi-file tasks — it previously described only the singular `subagent` and called delegation "sequential", leaving the live model unaware the batch tool existed (#122). Runtime-owned, so both bundled backends inherit it (all-engines rule). Honest caveat recorded in the ledger: the live model delegates when explicitly invited but not yet spontaneously on a purely implicit task.

## [0.33.3] - 2026-06-04

### Added

- docs/live-testing.md §1 marked ✅: outsource write validated live (#121) — 3 consecutive write --apply + 1 write --pr drive, each diff-verified.
- Lock-in tests that the write prompt leads with the task (descriptive commit subject) and asks for lint-clean edits (tests/test_outsource_skill.py).

### Changed

- outsource write prompt (.claude/skills/outsource/prompts/write.md) now leads with $ARGUMENTS so the drive commit subject / PR title describes the change instead of the boilerplate preamble, and adds a lint-clean rule (max line length + one trailing newline) to curb W292/E501 in whole-file rewrites (#121).
- Added docstrings to ToolExecutor.execute, subagents.spawn/batch_spawn, and VllmOpenAIEngine.drive (the real micro-improvements produced by the write validation drives).

## [0.33.2] - 2026-06-04

### Added

- docs/live-testing.md — live-testing ledger tracking end-to-end validation against a real served model (the layer the unit suite cannot reach: tools the model must choose to invoke + config surfaces that must be present to fire), with a per-feature commit+date staleness stamp. Wired to tracking epic #128 and per-item issues #121-#127.

## [0.33.1] - 2026-06-04

### Added

- Test coverage for `doctor --probe` model-availability gaps: the happy-path match (info/passed), an empty/no-id served set (warning naming "(none)"), an unparseable /models body (verdict omitted, reachability still passes), and partial config (probe targets the resolved {base_url}/models, default model still compared).
- CLI-wrapper tests crossing the `cmd_doctor -> diagnose(probe=...)` seam: `doctor --probe` runs the reachability check and a bare `doctor` omits it (opt-in contract).

## [0.33.0] - 2026-06-04

### Added

- colleague learn --json now carries structured work_with (outsource verbs + drive contract) and teach_with_skills (what skills/AGENTS files to author) blocks for collaborating agents

### Changed

- colleague learn reoriented for agents that work WITH colleague: foregrounds outsource explore/review/write/feedback, the drive contract, the ROI loop, and what skills to create; dropped the clone-the-template framing. Root explain entry and CLI description now lead with the swappable coder-agent harness identity to match

### Fixed

- colleague learn now states that the per-model overlay `<model>` token is the *filename-safe* model id (slashes collapse to dashes, e.g. `Qwen/Qwen3-32B` -> `Qwen-Qwen3-32B`), in both the text and `--json` (`teach_with_skills.model_placeholder`) — following the old wording verbatim would have created a literal `.colleague/<org>/<model>/` overlay that never loads (Qodo review)

## [0.32.2] - 2026-06-04

### Added

- pty-driven regression tests that drive the session raw-mode autocomplete loop (`_raw_loop`) end-to-end over an explicit `os.openpty()` pair, using the production slash-command catalog, autofilter, and popup widget — TAB-complete, free-text submit, arrow select, arg-hint trailing space, backspace edit, Ctrl-C/Ctrl-D quit

### Changed

- Removed the now-stale `# pragma: no cover` on `_raw_loop` (it is genuinely covered by the new pty tests) and corrected the comments in `_session_input.py` / `test_session_autocomplete.py` that claimed the raw loop could not be pty-tested under pytest fd capture

## [0.32.1] - 2026-06-04

### Changed

- CI: bump SonarSource/sonarqube-scan-action v6 -> v8.1.0 (node24 runtime, scanner GPG signature verification). Note: the intermittent 403 from binaries.sonarsource.com is a SonarSource CDN flake and is unaffected by the action version; re-run the job if it recurs.

## [0.32.0] - 2026-06-04

### Added

- colleague session: live `/` autocomplete popup on a colour TTY — autofilters slash commands as you type, restores on delete, vanishes on no-match; Tab/Enter completes, arrows select, Esc dismisses. Stdlib raw-mode reader (termios/tty/select) with a plain-input() fallback so piped/--json/--no-tui/Windows/agent paths stay byte-identical. Zero new runtime deps.

### Changed

- Slash commands now come from a single `SlashSpec` catalog that also derives the `/help` text (drift-tested), so help and the popup cannot diverge.

## [0.31.0] - 2026-06-03

### Added

- Escalation (#106): when a drive cannot withstand a request — DriveAborted (timeout/context-overflow/engine error) or step-budget exhaustion — colleague can open ONE tracked agtag continuation issue carrying a 5-section record (continuation / remaining / what's-needed / suggested split / why). Opt-in via COLLEAGUE_ESCALATE (default off), offline/CI-safe, skipped in linked worktrees, approval-gated, idempotent per task_id; best-effort and observe-only (never masks the drive result). docs/features/escalation.md.
- TaskResult.not_finished (#106): explicit flag set from the drive-loop return value — True iff the step budget was exhausted without calling finish (not via DriveAborted) — replacing the unreliable step_count heuristic for not-finished detection.

## [0.30.0] - 2026-06-03

### Added

- NO_RESULT_PRODUCED contract sentinel — a stable, programmatic signal a caller branches on when a drive produced no output (#109)

### Changed

- A no-finish drive surfaces the model's last substantive assistant content (tracked on every turn, including tool-call turns) as result.summary instead of a content-free 'completed in N step(s)'; the 'stopped at the N-step budget' summary string is removed (budget is inferrable from stats.step_count) (#109)

### Fixed

- drive/outsource results no longer read as empty-looking successes when the model does not call finish — the produced content is surfaced in the result, not buried in the artifact JSON (#109)

## [0.29.13] - 2026-06-03

### Added

- Spec + plan: result fidelity — a no-finish drive surfaces the model's last substantive content (and an explicit empty marker when none) instead of a content-free step count (#109)

## [0.29.12] - 2026-06-03

### Added

- Operator-driven audit fan-out recipe (docs/features/audit-fanout.md): split a too-large doc-review into per-surface scoped drives via assign-to-workforce and synthesize one ranked report (#107)

### Changed

- doc-review command template instructs single-surface-only coverage when given a scope argument (names out-of-scope surfaces), making it fan-out-ready (#107)

## [0.29.11] - 2026-06-03

### Added

- Spec + plan: fan out a large read-only audit across scoped drives — operator-driven (assign-to-workforce); in-drive subagents text-aggregation deferred (issue #107)
- Spec + plan: escalate via agtag when a drive cannot withstand a request — runtime-auto finalize hook, opt-in + offline/CI + approval-gated + idempotent, 5-section continuation contract; build gated on #109 (issue #106)

## [0.29.10] - 2026-06-03

### Fixed

- `doc-review` command template now enforces **finish discipline** (mirroring the proven `review.md`/`explore.md` fixes): it explicitly requires calling the `finish` tool with the itemized report and warns that ending without `finish` returns nothing. Found by dogfooding (#104): a full-repo audit read 18 files then ended with a 101-char non-report. Verified: a scoped audit now reaches `finish` with a real itemized findings list. Added a lightweight self-escalation seed — when the audit is too big to finish, report INCOMPLETE with what is covered, what remains, and a suggested split (the prompt-level seed of #106).
- Stale-doc fixes surfaced by that doc-review dogfood (each verified against the code): the `explain` `_SUBAGENT` entry no longer claims subagents are *"sequential only in v0"* / *"synchronous, no thread"* — parallel subagents shipped v0.29.0 (opt-in `COLLEAGUE_SUBAGENT_CONCURRENCY`, `concurrent.futures`, per-child `sub/<id>` worktrees, a merge child); and the README feature table now lists the two existing pages it omitted (`parallel-subagents.md`, `graceful-degradation.md`). (The audit also false-flagged the `MAX_SUBAGENT_*` constants as moved out of `config.py` — they are not; that finding was rejected on verification.)

## [0.29.9] - 2026-06-03

### Fixed

- `colleague tui snapshot` text output now lists **every** file it writes (the quad). It wrote four files — `.taui.json` / `.ansi` / `.events.jsonl` / `.md` — but the text stdout joined only `("taui", "ansi", "events")`, so the `.md` it had just written was invisible on stdout (the `--json` output already listed it). Text and JSON now agree. Found by exercising `tui snapshot`/`diagnose` for issue #99.
- Refreshed stale `tui` help/doc wording that still called the snapshot a *triple*: the `snapshot`/`diagnose` subcommand help, the `--name` help (was "Base name for the three files" → the four files taui/ansi/events/md), the `tui` module docstring, and the overview verb line. The `legacy triple` references in `tui/snapshot.py` / `tui/diagnose.py` are left intact — a pre-`.md` snapshot genuinely is a triple (back-compat).

## [0.29.8] - 2026-06-03

### Fixed

- `resolve_identity` (`colleague/identity.py`) now falls back to the first agent block's `suffix:` in `culture.yaml` when there is no top-level `nick:`. The canonical clone shape nests the nick as `agents:` → `- suffix: <nick>` (exactly what `colleague whoami` reads), but `resolve_identity` only read a top-level `nick:` and so returned `None` for the standard template — silently emptying both the `COLLEAGUE_IDENTITY` injected into every `culture`/`devague` subprocess (the mesh-member identity propagation) and the `feedback record` `by` default (which `--by` help promised resolves to the identity). The two identity paths now agree; found by exercising the `feedback` ROI loop and seeing `by: (unknown)` despite `whoami` reporting `colleague`. (Per PR #100 review: `resolve_identity` now reads `culture.yaml` at most **once** per call — the `nick:` and `suffix:` scans share a single read buffer instead of re-opening the file on the canonical no-`nick:` path.)

## [0.29.7] - 2026-06-03

### Fixed

- `run_command` tool description now states the fact a small model trips on: each call runs in a FRESH shell with cwd already at the repo root, so `cd` and environment changes do NOT persist between calls — use repo-relative paths, never `cd`. This is the systemic root-cause fix for the thrash that made `outsource review` burn its whole step budget on `cd`/`pwd`/`which` churn; correcting it once at the tool level means every verb and every backend inherits it (all-engines rule), not just the one prompt that was patched.
- `outsource explore` prompt (`explore.md`) brought to parity with the hardened `review.md`: a report that never calls `finish` returns NOTHING, so finish early; and don't repeat near-identical searches — once a search points at the relevant file, read it. A live explore had been calling `finish` on step 19/20 after several duplicate `rg` searches, one redundant search away from the same empty-result failure.

## [0.29.6] - 2026-06-03

### Changed

- `whoami` now reports the live *drive identity* — the `drive_engine` a bare drive would pick (`--engine` > `COLLEAGUE_ENGINE` > default `vllm-openai`) and the `drive_model` it would call — alongside the `culture.yaml` mesh backend. The cheapest probe an agent runs before delegating now names the actual delegate instead of an unrelated persona backend (text relabels `backend:` → `mesh backend:` and replaces the meaningless persona `model:` line with `drive engine:`/`drive model:`; JSON keeps the `backend`/`model` keys and adds `drive_engine`/`drive_model`). `drive_model` is `null` for the no-op `mock` engine, which calls no model.
- The first-party `outsource` skill now encodes a **proactive delegate reflex**: its description and a new `SKILL.md` section give a sharp GO/NO-GO rule for reaching out *unprompted* (default the read-only `review`/`explore` verbs — zero side effects), with guardrails (one-glance readiness via the new `whoami` drive identity; output is a second opinion to verify, not authority; close the loop with `feedback`). Side-effecting `write --apply`/`--pr` still requires a user go-ahead. Docs mirrored in `docs/features/outsource.md`. Skill-only change; no runtime code touched.

### Fixed

- Brought every self-describing surface in line with the new `whoami` output: `learn` (command map + JSON summary), `overview`, the top-level `colleague` `explain` catalog entry, and `docs/features/agent-cli.md` no longer claim `whoami` reports only `culture.yaml` identity — they now describe the mesh identity **plus** the live drive engine/model. (No first-party surface contradicts another.)

## [0.29.5] - 2026-06-03

### Added

- docs: converged spec for model-tailored runtime surfaces (the model-profile layer) — a per-model `.colleague/<model>/profile.json` tailoring tool aliases/availability/descriptions, default-limit hints, and a terminal system-prompt overlay, keyed by `sanitize_model(config.model)` and overriding a shipped package default, while keeping the `Task`→`TaskResult` contract, the artifact (canonical tool names), and the all-engines/zero-deps conventions stable (#89).

## [0.29.4] - 2026-06-03

### Changed

- The `run_command` neighbour-clone guard is now token-aware: it `shlex`-splits the command and refuses only a token that resolves to the clone root (`.colleague/neighbours`) or under it, instead of a raw whole-string substring match — so a benign command that merely *mentions* the path inside a quoted string (e.g. `echo "see .colleague/neighbours"`) is no longer a false positive. Unparseable commands (shlex ValueError) fall back to the stricter substring check, so a malformed command never slips through. Still a best-effort policy gate, not a sandbox (bypassable by `sh -c`, pipelines, shell expansion) (#92).

## [0.29.3] - 2026-06-03

### Changed

- Added direct test coverage for the neighbours `_dest_for` path-traversal guard (malicious/typo names: separators, dot/dotdot, absolute, empty) — previously only exercised indirectly (#92).

### Fixed

- `run_command` now maps **any** subprocess failure to a recoverable `ToolError` instead of aborting the whole drive: a hung command (`subprocess.TimeoutExpired`), a launch failure (`OSError`), or any other error (e.g. `ValueError` on an embedded NUL byte in a model-issued command) is fed back to the model as a non-ok step so the drive continues — matching the `_subagent`/`_subagents` catch-all and the culture/devague/hooks subprocess handling (all-engines rule). `KeyboardInterrupt` still propagates. The 300s budget is now the named `_COMMAND_TIMEOUT_SECONDS` constant (#92).

## [0.29.2] - 2026-06-03

### Changed

- README "Subagents" section rewritten to match the shipped v0.29.0 parallel-subagents behavior (COLLEAGUE_SUBAGENT_CONCURRENCY, the subagents batch tool, per-child `sub/<id>` worktrees, the sequential merge-subagent); it had still described v0 as sequential-only (#92).

### Fixed

- outsource skill default model was stale (mmangkad/Qwen3.6-27B-NVFP4) and no longer matched config._DEFAULT_MODEL or the live rig; aligned the skill script, SKILL.md, docs/features/outsource.md, and the skill test to the served sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP so a bare-default `outsource explore` no longer 404s the rig (#92).
- vLLM engine now raises a legible ConnectionError naming the endpoint when the server is unreachable (urllib URLError: connection refused / DNS / server down), instead of letting the loop surface a cryptic bare `URLError: <urlopen error [Errno 111] Connection refused>`; mirrors the graceful URLError handling already in _tokenize_count, with a regression test (#92).

## [0.29.1] - 2026-06-03

### Changed

- Docs/terminology: replaced the car metaphor with standard agent/runtime vocabulary across README, docs/features/*, CLI help text, docstrings, the explain catalog, and CLAUDE.md (engine→backend, driver→adapter, chassis→runtime, wheels→plugins, garage→registry, dashboard→run report, GPS→telemetry, oilcheck→health check, convoy→subagents, gearbox→router/routing policy). New framing: "One runtime, many minds." No CLI verb/flag, module, or test changes; --engine, wheels/doctor/telemetry/drive, colleague.engines, colleague/oilcheck/, and the all-engines rule name are unchanged (#88).

## [0.29.0] - 2026-06-03

### Added

- Parallel subagents: a new `subagents` (plural) loop tool fans out a batch of child drives that run concurrently via a ThreadPoolExecutor confined to `colleague/subagents.py`, each child isolated in its own throwaway git worktree on a `sub/<id>` branch, integrated afterward by a sequential merge-subagent that surfaces (never force-merges or drops) unresolvable conflicts.
- Opt-in concurrency-width knob `COLLEAGUE_SUBAGENT_CONCURRENCY` (on `EngineConfig`, default 1 = byte-identical to the prior sequential path), bounded by `MAX_SUBAGENT_FANOUT=4` (<=3 parallel workers + 1 merge child) and `MAX_SUBAGENT_DEPTH=2`.
- `colleague/worktrees.py`: per-child git worktree + branch lifecycle with idempotent teardown (zero new runtime deps; concurrent.futures and subprocess are stdlib).

### Changed

- Threads (`concurrent.futures`) are sanctioned in exactly one module (`colleague/subagents.py`) via a new thread-confinement check in `tests/test_boundary.py`; forbidden in every other colleague module. `colleague/worktrees.py` is added to the subprocess allow-list.
- The single-child `subagent` tool, the `mock`/`vllm-openai` engines, and the result/artifact shape are unchanged; the new `subagents` tool is wired through both engines (all-engines rule). Documented in CLAUDE.md and a new `docs/features/parallel-subagents.md`.

### Fixed

- Review hardening (PR #90): a CONFLICTED child's `sub/<id>` branch is now RETAINED on teardown (was force-deleted), so its committed work survives for manual integration as the merge child's summary promises. `teardown_all` is scoped to worktrees under `.colleague/worktrees/` and no longer sweeps every `sub/*` branch (could delete unrelated user branches). `worktree_add` no longer writes the shared `.gitignore` (a thread-race that dirtied the working tree during the parallel phase; `/.colleague/*` is already ignored). Nested batches are forbidden in v0: a child drive's `subagent_batch_spawn` is nulled so it can't run a batch against the parent's worktree/depth.

## [0.28.0] - 2026-06-03

### Added

- Configurable per-tool-result output cap: COLLEAGUE_MAX_OUTPUT_CHARS (EngineConfig.max_output_chars, default 100000), raised from the old hardcoded 20000 so a large read_file/run_command result is not truncated inside the bigger context window. Threaded through the loop and forwarded by every engine (all-engines rule).

### Changed

- Context budget default raised 24000 -> 192000 tokens and drive step budget default 25 -> 40, sized for the upgraded 256k (262144-token) vLLM reference rig (model-gear). Override per environment with COLLEAGUE_CONTEXT_BUDGET / COLLEAGUE_MAX_STEPS.

## [0.27.2] - 2026-06-03

### Changed

- session cockpit (ANSI) now fills the terminal width instead of fixed narrow boxes — all panels and frame separators derive from one detected width and align; threaded a width kwarg through render() and every box widget, with a deterministic default (80) for headless/snapshot callers and shutil.get_terminal_size() for the interactive session + live driver
- session prompt is now a clean "colleague ❯" chevron (dropped the meaningless [planning] mode label), with the typing cursor anchored to the prompt via input()

### Fixed

- slash-command output (e.g. /help) no longer mangles mid-word in the conversation panel — the box wraps at the full width instead of 46 chars
- ANSI render no longer overflows the requested width on a narrow terminal (41–71 cols) when both the skills and conversation panels are visible — the side-by-side layout is guarded and falls back to stacking the panels full-width below the column threshold
- box widgets clamp their derived inner widths to a positive minimum, so a pathologically small `width` can no longer raise on a negative field width or spin the wrap loop forever

## [0.27.1] - 2026-06-03

### Fixed

- Stop tracking `.devex/data/pr/events.jsonl` — a per-machine devex PR event log that was committed by mistake. Untracked (kept on disk) and added `/.devex/data/` to `.gitignore` so `devex pr` runs no longer dirty the working tree.

## [0.27.0] - 2026-06-02

### Added

- Deprecated back-compat fallbacks for the rename (read-only): the legacy `.convertible/` config + artifact directories are still read (new writes always target `.colleague/`), `CONVERTIBLE_*` environment variables are honored as a fallback (`COLLEAGUE_*` takes precedence), and `identity_env` emits BOTH `COLLEAGUE_IDENTITY` and `CONVERTIBLE_IDENTITY` so sibling AgentCulture CLIs keep inheriting the identity.

### Changed

- **Renamed the project from `convertible` to `colleague`.** The import package is now `colleague`, the CLI ships as two console scripts (`colleague` and its short alias `clg`), and the PyPI distribution is `colleague` (no longer `convertible-cli`).
- Config directory is now `.colleague/` and the environment variables are `COLLEAGUE_*` (e.g. `COLLEAGUE_ENGINE`, `COLLEAGUE_MODEL`, `COLLEAGUE_OTEL_ENABLED`, `COLLEAGUE_IDENTITY`, `COLLEAGUE_VLLM_E2E`).
- Engine/renderer entry-point groups are now `colleague.engines` / `colleague.renderers`; OpenTelemetry service/tracer/meter names and span/metric names are now `colleague.*`.
- pyproject URLs point at `github.com/agentculture/colleague`; SonarCloud `sonar.sources` is now `colleague` and `sonar.projectKey` is now `agentculture_colleague` (the SonarCloud project must be re-keyed externally to match, or coverage uploads 404).

## [0.26.0] - 2026-06-02

### Added

- doc-test-alignment skill is now implemented (issue #76 C3), replacing the stub check.sh: a portable, stdlib-only verifier with four checks behind `scripts/check.sh [--only readme|claude|skills|tests] [--repo PATH] [--json]` (exit 0 aligned / 1 drift / 2 usage). (c) SKILL.md script-claims-vs-scripts is deterministic and GATES CI; (a) README + (b) CLAUDE.md commands run safe networkless introspection and statically validate networked/drive commands against `convertible --help` (never executing them); (d) test-name-vs-assertion drift is an advisory AST heuristic with inline/file suppression. JSON shape mirrors doctor: {aligned, checks[{id,passed,severity,message,remediation}]}.
- CI now gates on doc-test-alignment check (c) (deterministic) and runs (a)/(b)/(d) as advisory (non-blocking) in the lint job.

### Changed

- docs/skill-sources.md records doc-test-alignment as a first-party implementation diverged from the guildmaster stub (do not re-vendor over it; upstreaming is a follow-up).

## [0.25.0] - 2026-06-02

### Added

- Context-budget graceful degradation in the bounded tool-loop: the running message history is windowed to a configurable token budget (CONVERTIBLE_CONTEXT_BUDGET / EngineConfig.context_budget_tokens, default 24000) before each model turn, and a detected context-overflow error triggers a bounded trim-and-retry before a readable partial result is preserved — a multi-file drive on a small-context model degrades instead of hard-failing (#76 C1).
- Pluggable count_tokens seam (convertible/context.py): the vLLM engine counts tokens exactly via the server /tokenize endpoint, falling back to a zero-dep char heuristic when /tokenize is absent — no third-party tokenizer library, dependencies = [] holds.
- docs/features/graceful-degradation.md documenting the behavior, the /tokenize OpenAI-surface carve-out, and the honest limits.

### Changed

- convertible drive --json now emits the preserved partial TaskResult to stdout on the failure/overflow path (still exiting non-zero, diagnostics on stderr) so a --json consumer gets a parseable result instead of empty stdout (fixes the #76 "convertible produced no result on stdout" symptom).

### Fixed

- A context-window overflow on a small-context model no longer surfaces as an opaque "no result on stdout"; the loop windows + retries, and any unrecoverable drive returns a status=error result with a non-empty step trace.

## [0.24.0] - 2026-06-02

### Added

- Interactive cockpit session (#74 A2): `convertible session` is rebuilt onto the TAUI cockpit. It renders one `CockpitState` (command palette + conversation + popups) through three tiers chosen automatically — the dynamic ANSI cockpit on a colour TTY (redraw-in-place, error popups on failed steps), static **Markdown** menus when piped/captured (`--no-tui` forces it), and `--json` keeping stdout as pure result JSON with the cockpit as stderr chrome.
- Session slash commands (akin to Claude Code / Codex): read-only introspection that folds an existing noun's output into the cockpit (`/help`, `/commands`, `/skills`, `/agents`, `/config`, `/engines`, `/telemetry`, `/feedback`) and live config actions that mutate the session without a restart (`/engine`, `/model`, `/base`, `/pr`). Plain text (number / template name / free-text) still runs a drive.
- A `command_palette` cockpit widget (`convertible/tui/widgets/command_palette.py`) renders a `commands` panel as a numbered menu (ANSI); the Markdown/TAUI views pick it up via generic panel rendering.

### Changed

- `convertible session` non-interactive output is now the full Markdown cockpit (was a terse numbered list); `--json` stdout is unchanged (one `TaskResult` JSON per drive).
- `execute_drive` accepts an optional `progress_sink` so the session injects a sink bound to its own cockpit state (default `None` keeps the `drive` path byte-identical); the live drive frame-writer is factored into a shared `FrameWriter`.

## [0.23.0] - 2026-06-02

### Added

- Live cockpit during a drive (#74 A1): `convertible drive` renders the TAUI cockpit on stderr as it runs — conversation per step and popups on real events (an `error` popup when a tool step fails). Auto-on an interactive TTY; `--tui` / `--no-tui` force it; off a TTY it falls back to the plain `step N:` lines, byte-identical.
- Live `DriveStep` event stream (#74 A3): `drive --tui-events PATH` appends one JSONL event per step as the drive runs (the format `tui replay` / `tui snapshot` consume); a stream written into the driven repo is treated as harness telemetry, never swept into the drive branch.
- `tui replay --trace <id>.trace.jsonl` (#74 A4): fold a finished drive's loop-step trace into the cockpit. Live and replayed steps read identically — one shared converter (`convertible/tui/from_drive.py`) and the same pure reducer.
- NO_COLOR / TTY-aware color gating helpers (`convertible/tui/colors.py`, #74 A5): the live cockpit strips ANSI escapes when `NO_COLOR` is set or the stream is not a terminal.

### Changed

- A failed `DriveStep` now opens an `error` popup in the pure reducer (so it surfaces identically live, in `tui replay`, and in `tui replay --trace`).
- The ANSI conversation widget now renders the reducer-produced `panel.conversation` and accepts a multi-line per-step summary, so a live drive shows its steps.

## [0.22.0] - 2026-06-02

### Added

- outsource explore/review now copy their artifact (plus a last_drive pointer) back to the real repo before the throwaway worktree is removed, so a read-only outsourced drive can be graded with `outsource feedback last` / `convertible feedback record last` (#75 C4).
- Command-template recipes can be committed in-repo: `.convertible/commands/` is no longer gitignored (run artifacts, hooks.json, approvals.json stay local), with a committed `doc-review` example recipe (#75 C5).
- Reverse-coverage test: every registered CLI verb must have an `explain` catalog entry and every action-noun must expose `overview` (#75 D1).

### Changed

- `convertible drive` now returns you to the branch (or detached commit) you started on after it commits — the `convertible/<id>` drive branch keeps the commit, but a drive no longer strands you on it (all commit paths, incl. `--no-pr` and `session`) (#75 C2). Side effect: successive `session` drives now branch independently from your base rather than chaining on the previous drive.

### Fixed

- The read-only outsource artifact-preservation path (#75 C4) now validates the drive `task_id` as a single safe path segment before joining it into a copy destination (mirroring `convertible/feedback.py`), so a malformed/hostile TaskResult can no longer escape `.convertible/`; and it only reports the preserved real-repo path (and writes `last_drive`) when the copy actually succeeds, never claiming an artifact that isn't there.

## [0.21.1] - 2026-06-02

### Added

- docs/features/subagents.md — the missing feature page for the subagent/convoy loop tool; added to the README feature table and the docs/features index.
- README sections for the tui cockpit, the drive-stats/feedback ROI loop, subagents (convoy), and an outsource narrative (all shipped features that the README narrative omitted).

### Changed

- README: corrected the stale Qwen3-32B reference to the current default model sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP; documented doctor --probe (provider_reachable + provider_model_available); added a CHANGELOG pointer and the missing model-selection/tui/stats-and-feedback feature-table rows. Docs-only — no behavior change (#73, umbrella #72).

## [0.21.0] - 2026-06-01

### Added

- `convertible tui render --format ansi|markdown` — a Markdown render of the cockpit, the agent-facing readable third view beside the JSON (TAUI) mirror and the ANSI live screen; `--json` wraps the chosen format (`{"markdown": ...}`).
- `tui snapshot` now writes a quad — a 4th file `<name>.md` (the Markdown render) alongside `<name>.taui.json` / `<name>.ansi` / `<name>.events.jsonl`; legacy triples without a `.md` still read fine.
- `diagnose` now verifies the Markdown frame too — its RENDER faithfulness check runs against the Markdown when present, so `tui diagnose` on a quad proves the JSON mirror and the Markdown agree (zero findings = faithful; a finding = drift). Markdown and JSON are both pure functions of one `CockpitState`, so any disagreement is a render-fidelity bug, never a data divergence.

### Changed

- diagnose success message now reads "the captured views agree" (a snapshot is a quad, no longer a triple).

## [0.20.0] - 2026-06-01

### Added

- `tui` command — an agent-readable terminal UI (issue #69). Every visual frame has a TAUI (Textual Agentic UI) semantic mirror an agent can read, operate by stable dotted-path selector, snapshot, replay deterministically, and diagnose — no OCR or terminal guessing.
- TAUI semantic mirror (`convertible/tui/taui.py`, schema 0.1): the live sibling of the drive artifact, derived via `serialize(state)` from a canonical `CockpitState`; selectors are dotted paths into the tree (no second table to drift).
- Pure Elm-style core: `event -> reduce(state, event) -> State -> serialize()=TAUI + ANSI render`. The reducer is pure (no clock/randomness); animation advances only via injected `tick` events, so replays are byte-identical.
- Snapshot triple (`<name>.taui.json` + `.ansi` + `.events.jsonl`) + deterministic replay; `tui` headless subcommands `render`/`state`/`inspect`/`action`/`replay`/`snapshot`/`test`/`diagnose`/`overview`, all `--json`, plus a guarded `tui live` foreground TTY driver.
- `diagnose`: a pure stdlib cross-mirror differ that classifies 7 bug classes (state/render/layout/focus/input-routing/theme/popup-lifecycle) with no LLM and no network.
- Renderer-is-a-wheel: a hand-rolled stdlib ANSI renderer ships zero-deps as the default; Rich/Textual is an opt-in `[tui]` extra discovered via a new `convertible.renderers` entry-point group.
- JSON scenario runner (`tui test --scenario`) + bundled `boost-popup.scenario.json`; docs at `docs/features/tui.md`.

## [0.19.0] - 2026-06-01

### Added

- doctor --probe provider_model_available check: warns (advisory) when the configured model is not in the provider/v1/models list, naming both the configured id and the served ids with a remediation; omitted when the list cannot be enumerated
- vLLM engine _post_json now folds the HTTP error body into the raised HTTPError, so a wrong-model 404 reads "…model `X` does not exist" instead of a bare "HTTP Error 404: Not Found"

### Changed

- Built-in default model is now sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP (the model the reference rig serves at localhost:8001), so a bare drive reaches a live model instead of a 404; override with CONVERTIBLE_MODEL or --model

## [0.18.0] - 2026-05-31

### Added

- **Drive statistics + feedback loop (the ROI loop)** — calculate the ROI of outsourcing to convertible. Every drive artifact now carries an always-on `stats` block (`TaskResult.stats` / `DriveStats`): request, ISO start + wall-clock duration, model turns, step count, per-tool counts, files changed, exact UTF-8 `bytes_written`, and reasoning-vs-answer char/byte sizes. Populated chassis-side in `convertible/loop.py` so every engine fills it identically (all-engines rule).
- `convertible feedback record|show|overview` — grade a finished drive by `task_id` or `last` with a 1-5 rating + notes, stored as a single record per drive (`<task_id>.feedback.json`) beside the artifact via a stdlib JSON store (`convertible/feedback.py`). A per-repo `last_drive` pointer (written by `execute_drive`) resolves `last`. An ungraded drive reads back as a clean no-op, never an error.
- `outsource feedback <id|last>` skill verb — grade an outsourced drive (with `--rating`) or show its feedback (without), shelling to `convertible feedback`.
- vLLM engine now captures `message.reasoning` (the chain-of-thought, previously discarded) into `ModelResponse`, measured as reasoning chars/bytes in the stats.
- OpenTelemetry parity: two new metrics `convertible.generated.chars` (attr `kind`=reasoning|answer) and `convertible.bytes_written`, a strict no-op when telemetry is off.

### Changed

- Tokens stay verbatim from the model response `usage` (never estimated). Since the served model reports no reasoning-token breakdown, thought-vs-written is measured as chars/bytes, not tokens (no tokenizer, zero deps) — documented honestly.

## [0.17.0] - 2026-05-31

### Changed

- `outsource write` now **previews by default** (#61): without `--apply`/`--pr` it runs the change in a throwaway `git worktree` at HEAD, prints the would-be diff, and discards it — nothing touches your working tree. New `--apply` flag lands the change on a `convertible/<id>` drive branch in place; `--pr` implies `--apply`. The dirty-tree guard now applies only when actually applying.
- The git-repo guard now covers **every** `outsource` verb (previously only the read-only verbs): a non-repo `--repo` fails fast with a clear message instead of an opaque mid-drive error. `git -C`-style targeting is unchanged.

### Fixed

- outsource: `mktemp -d` is given an explicit template (`${TMPDIR:-/tmp}/outsource.XXXXXX`) so the read-only/preview worktree setup is portable on BSD/macOS mktemp (#61).
- outsource: `print_result` routes the result digest to **stderr** on a failed drive (status != ok), keeping stdout clean for scripting; it still exits non-zero (#61).
- outsource: `review` validates that `--base` resolves to a real commit/ref before interpolating it into the LLM review instruction — fails fast on a bogus/unknown ref (#61).
- outsource: `render_prompt` substitutes `$ARGUMENTS`/`$BASE` in a single `re.sub` pass, so a literal `$BASE` inside the user argument survives verbatim instead of being clobbered by a second replace pass (#61).

## [0.16.1] - 2026-05-31

### Added

- `docs/features/model-selection.md`: an operator guide for how convertible
  resolves the engine/model/endpoint (`--engine`/`--model`/`--base-url` → env
  (`CONVERTIBLE_*`, `OPENAI_*`) → defaults), the fact that there is **no model
  config file**, how to point `vllm-openai` at any OpenAI-compatible server, and
  a recipe to keep `CONVERTIBLE_MODEL` auto-synced to a locally-served model
  (generic `/v1/models` lookup, plus model-gear's `model whoami`). Notes that
  subagents inherit the parent model. Linked from `engines.md` and listed in the
  features index (`docs/features/README.md`). Docs only — no behavior change.

## [0.16.0] - 2026-05-30

### Added

- `outsource` skill (first-party, `.claude/skills/outsource/`): hand a scoped repo task to convertible — a *different* engine/model than the calling agent (the value is diversity, not raw power). Three verbs over `convertible drive`: `explore` (read-only investigation → findings), `review` (an independent second opinion on the committed `<base>...HEAD` diff), and `write` (delegate a small implementation). Read-only verbs run in a throwaway `git worktree` at HEAD, so they cannot touch the working tree; `write` refuses a dirty tree unless `--allow-dirty`. Defaults to a local vLLM model (`mmangkad/Qwen3.6-27B-NVFP4`), overridable via flags/env. Advertised in `convertible learn` and `convertible explain outsource`.

## [0.15.0] - 2026-05-30

### Added

- Subagent delegation ("convoy"): mid-drive, an engine can call a `subagent` tool to delegate a scoped sub-task to a nested in-process child drive on an optional different engine and/or model; the child runs the same bounded loop with no git handoff, and its result is folded back into the parent loop and recorded on `TaskResult.sub_results` (omitted when empty). Engine-judged and optional (like the devague tool), NOT an automatic router/gearbox. Sequential-only and bounded (depth 2 / fan-out 4); parallel subagents are a parked follow-up. Chassis-owned (all-engines rule), zero new runtime deps, no daemon/socket/fork.

## [0.14.0] - 2026-05-30

### Added

- Approval gate: operator-declared `.convertible/approvals.json` gates what the harness executes — `run_command` CLIs by program token (allow/deny, shlex) and hook scripts + command templates by checksum. Approval is tamper-protection: `approve` records a file checksum and a later edit voids it (sha256-default, md5 honored). Skills/AGENTS load freely (declarative, never gated). Per-model overlay, strict no-op default, chassis-owned (all-engines rule), stdlib only. Policy gate, not a sandbox.
- `commands approve <name>` / `hooks approve <name>` CLI verbs record a checksum approval; `commands`/`hooks`/`skills list` show approval/accessibility status and `hooks list` shows the run_command policy; `explain approve`.

## [0.13.0] - 2026-05-29

### Added

- `CONVERTIBLE_ENGINE` environment variable for engine selection; the engine now resolves `--engine` > `CONVERTIBLE_ENGINE` > `vllm-openai` and never silently falls back to the no-op `mock` (#53).
- `usage` oilcheck check-group (`usage_effective_engine`): `convertible doctor` now warns (advisory, stays healthy) when a bare drive would pick the no-op `mock` engine.
- `convertible doctor --probe`: opt-in provider-reachability ping (`provider_reachable`), the one check that opens a network connection — invoked outside the no-network registered check-groups.
- `convertible session --pr`: opt back into push + PR per drive.

### Changed

- Default engine for `drive`/`session` is now `vllm-openai` (the real bundled engine) instead of `mock`; `mock` is reachable only via an explicit `--engine mock` / `CONVERTIBLE_ENGINE=mock`.
- `convertible session` commits locally by default and no longer pushes or opens a PR per typed line; use `--pr` to enable handoff (replaces session's `--no-pr`). `drive` is unchanged (PR by default).

### Fixed

- Talking to `convertible session` (or driving a question like `drive "what can you do?"`) no longer opens surprise PRs via the no-op mock engine, and `convertible doctor` no longer reports a misleading clean bill of health while a bare run would silently drive `mock` (#53).

## [0.12.4] - 2026-05-29

### Added

- Per-step progress output during a drive: each loop step emits a concise line to **stderr** (`step N: <tool> <target> [ok|err]`) in all modes, so long drives are observable while stdout stays the single parseable `--json` result (#38). Chassis-owned in the loop and threaded via `EngineConfig.progress`; both engines forward it (all-engines rule).

### Changed

- Refactored `loop.run` to extract the bounded turn loop into `loop._drive_loop`, enabling clean partial-result preservation and bringing `run`'s cognitive complexity back under threshold (SonarCloud S3776).

### Fixed

- A drive that raises mid-loop (e.g. a per-request timeout) now preserves the partial result: the accumulated `steps`, `usage`, and `changed_files` are written to the artifact with `status=error` and the `*.trace.jsonl` is populated, instead of being discarded for an empty `failed_result` (#37). The CLI still exits non-zero and surfaces the error.
- The per-step progress sink is fail-safe: a raising progress callback is suppressed and never aborts the drive (same observability-not-control guarantee as hooks and neighbour clones).
- The engine-failure remediation hint only claims a "partial trace" when one was actually written; the no-partial fallback path (fresh `failed_result`, empty trace) says "a result artifact was still written".

## [0.12.3] - 2026-05-29

### Changed

- Handoff commit subject is now a concise single line (`convertible: <first line of instruction, truncated>`, falling back to the task id); the full instruction is preserved in the commit body, and the PR title uses the short subject (#40).

### Fixed

- Handoff now commits **only the task's own work** (#39): all tracked modifications (so `run_command` edits to tracked files are captured) plus the new untracked files the drive itself produced — never pre-existing operator work-in-progress, prior runs' `.convertible/` artifacts, or other incidental untracked files. The drive snapshots untracked files before running and passes that baseline to the handoff. `changed_files` is derived from the staged set so the artifact agrees with what actually landed.
- Gitignored task output (e.g. a gitignored `site/`) is now surfaced in the handoff note (`N file(s) produced but not committed (gitignored): …`) instead of being silently dropped (#39); the gitignore check uses `check-ignore --stdin` (no argv limit, no leading-dash ambiguity).
- A no-op handoff (nothing of the task's own to commit) no longer strands the operator on a freshly-created task branch — staging happens before `checkout -B`, so operator state is left untouched.

## [0.12.2] - 2026-05-29

### Changed

- Refactored `loop.run`, `session.run_session`, and `commands.load_command` into focused helpers to bring cognitive complexity under the threshold (SonarCloud S3776); behavior-preserving (all 799 tests pass).
- Collapsed `telemetry status` to a single return path (SonarCloud S3516 BLOCKER).

## [0.12.1] - 2026-05-29

### Changed

- SonarCloud: stop excluding `.claude/skills/**` — skill scripts are production code and are now analyzed and gated like the rest of the tree.
- Coverage: emit repo-relative paths in `coverage.xml` (`[tool.coverage.run] relative_files`) so SonarCloud imports coverage instead of reporting none.

### Fixed

- Skill shell scripts: 47 lint findings across agent-config/cicd/communicate/assign-to-workforce/think/spec-to-plan/sonarclaude — use `[[ ]]` tests (S7688), name positional params as locals (S7679), route an error to stderr (S7677).
- Code smells in convertible/: dedupe the `--json` help and `.convertible` literals into constants (S1192), give the no-op telemetry methods docstrings (S1186), merge implicit string concatenations (S5799), rename the `_Span._span` field (S1700), tidy the `$N` placeholder regex (S6353), drop the redundant `JSONDecodeError` except clause (S5713), and fix a malformed `noqa` comment (S7632).
- Tests: stop using publicly-writable `/tmp` paths — switch real artifact writes to the `tmp_path` fixture and string-only paths to a neutral placeholder (S5443).

## [0.12.0] - 2026-05-29

### Added

- Per-model fixes — adapt the harness to a model's known biases. `load_hooks` now resolves a per-model hooks overlay `.convertible/<model>/hooks.json` (model token sanitized via `layers.sanitize_model`) and composes its entries ahead of the base `.convertible/hooks.json` per event, so the loop's first-deny/rewrite-wins gives the per-model fix priority. Exact-path per-model isolation (model X never loads model Y's overlay, no sibling globbing); strict no-op for models without an overlay; the driving model is threaded into the loop's hook load automatically (both engines). `convertible hooks list --model <m>` shows the composed set with per-model entries first, scope-tagged; `explain hooks` documents the overlay + precedence. New feature doc `docs/features/per-model-configuration.md` (the car-metaphor: convertible 'adjusts seat and mirrors' to fit the driving model) with an F9 footer-bias worked example. No new runtime dependency, socket, daemon, or `mcp.json`. Built via /assign-to-workforce — 6 TDD-gated tasks across 3 file-disjoint waves.

## [0.11.3] - 2026-05-29

### Added

- Build plan for per-model fixes (`docs/plans/2026-05-29-convertible-lets-an-operator-configure-per-model-f.md`): 6 TDD-gated tasks across 3 dependency waves covering all 15 spec coverage targets — per-model hooks overlay resolution + composition (`hooks.py`), loop wiring, an isolation test, a zero-deps/no-op guard, a `hooks list --model` CLI surface, and an F9 worked example plus a `per-model-configuration.md` feature doc (the car-metaphor 'adjust seat and mirrors'). Converged via devague /spec-to-plan. Plan only; not yet built.

## [0.11.2] - 2026-05-29

### Added

- Spec: per-model fixes that adapt the harness to a model's known biases (`docs/specs/2026-05-29-convertible-lets-an-operator-configure-per-model-f.md`) — converged via devague `/think`. Proposes a per-model hooks overlay (`.convertible/<model>/hooks.json`) resolved with the same `sanitize_model` + `configdir` machinery as `layers.py` and composed with the base model-blind `.convertible/hooks.json`, with the per-model fix evaluated first (first deny/rewrite wins). Spec only; not yet planned or built.

## [0.11.1] - 2026-05-29

### Added

- Drive-evaluation log under `docs/drive-notes/`: a repeatable, time-series record of convertible self-drive experiments — per-run `stats.json` (timing, iterations, operator nudges, tokens, validation, factual findings), qualitative `notes.md`, preserved `output/` (the built site + render) and raw drive `artifacts/`, a cross-run `index.csv`, a `README.md` defining the schema, and a `repro.sh`. First entry: the 2026-05-29 website-self-build drive.

## [0.11.0] - 2026-05-29

### Changed

- culture loop tool: the inspection-CLI allow-list entry is renamed `agex` -> `devex` (issue #33), matching the cicd skill's standardization on the `devex` name in PR #32 (devex is the same tool as agex, invoked under the `devex` name). The engine-visible `culture` tool schema `enum` is now {agtag, devex}. `agtag` is unaffected. Chassis-owned, so every engine sees the renamed allow-list identically (all-engines rule).

## [0.10.0] - 2026-05-29

### Added

- Destination: an engine can set and converge a devague goal-frame via a curated `devague` loop tool when a task warrants one, drive toward it, and declare the announcement on arrival (the car-metaphor sibling to GPS).
- `devague` loop tool (convertible/devague.py + convertible/tools.py): shells out to the operator-installed devague CLI with cwd + CONVERTIBLE_IDENTITY injected; curated move allow-list (new/capture/interrogate/park/converge/status/show) that structurally excludes the user-only confirm/reject and operator-only export. No runtime dep, no import, no socket, no daemon (the culture-tool pattern; all-engines rule).
- Lightweight arrival declaration: additive optional TaskResult.destination + announcement fields (omitted from the JSON artifact when unset, so a no-destination drive serializes byte-identically); finish gains optional destination/announcement, recorded by the loop.
- Chassis system-prompt guidance (inherited by every engine): setting a destination is optional and engine-judged; convergence is advisory and operator-authoritative; the engine cannot self-confirm.

### Changed

- Boundary guards (tests/test_boundary.py) sanction convertible/devague.py as a subprocess transport with no daemon primitives; the zero-deps guard now imports convertible.devague.
- cicd skill (.claude/skills/cicd): the PR lifecycle now drives `devex pr` instead of `agex pr` (devex is the same tool as agex, invoked under the `devex` name); `workflow.sh open` opens PRs via `devex`, never `gh` directly. Agent env override renamed to `STEWARD_DEVEX_AGENT` (legacy `STEWARD_AGEX_AGENT` still honored).

### Fixed

- The `devague` and `culture` loop tools now map a CLI timeout (`subprocess.TimeoutExpired`) and other launch failures (`OSError`) to a clean tool error instead of letting it escape `ToolExecutor` and crash the drive (Qodo review on #32).

## [0.9.0] - 2026-05-28

### Added

- Mesh-member integration: a convertible drive can run as a named AgentCulture identity (convertible/identity.py — culture.yaml nick / .convertible/identity.json, propagated via CONVERTIBLE_IDENTITY)
- Curated culture loop tool (convertible/culture.py): one identity-injected tool shelling out to allow-listed AgentCulture CLIs (agtag, agex) — the documented re-spec of the closed five-tool surface
- Read-only neighbour clones (convertible/neighbours.py): operator-configured .convertible/neighbours.json allow-list, shallow clone, refresh-on-demand, cloned at drive start and cleaned up at finish (ephemeral, empty by default)
- Per-feature mesh-member doc + feature-index and README updates

### Changed

- Tool-loop surface extended from five to six tools (added culture); loop wires neighbour clone-at-start and cleanup-at-finish into the chassis so every engine inherits it (all-engines rule)
- run_command refuses to execute paths inside the neighbour clone tree (best-effort; clones are inert read-only source)

## [0.8.1] - 2026-05-28

### Added

- docs/features/ — a feature index plus one focused doc per shipped feature (drive/loop, engines, handoff, artifact, command templates, hooks, session, layered config, telemetry, doctor, agent-first CLI), each with source pointers and cross-links

### Changed

- README: documented the doctor/oilcheck check-groups, added a Feature docs index, and filled the What-ships-in-v0 list with the layered-config, GPS/telemetry, and doctor features it was missing

## [0.8.0] - 2026-05-28

### Added

- `convertible/oilcheck/` package — a read-only check-group registry + `diagnose()` aggregator that the `doctor` verb renders (chassis-level, like telemetry).

### Changed

- `doctor` is now a configuration-readiness health check (convertible's "oilcheck"), broadened from agent-identity invariants to a full read-only battery: identity, provider config (with redacted api_key + advisory provider_budget warning), engine wheels (all-engines, asserts bundled mock + vllm-openai), otel readiness, and environment (.convertible/hooks.json/command templates, AGENTS/skills layering, git/gh handoff prereqs, CLI integrity). Emits the rubric-shaped {healthy, checks[]} report; exits 1 on any error-severity check. Diagnose-only (no --fix); zero new runtime deps.

## [0.7.0] - 2026-05-28

### Added

- GPS: opt-in OpenTelemetry traces + metrics for a drive (issue #22). Spans (`convertible.drive` -> `convertible.tool.*` -> `convertible.handoff`) and metrics (steps, tokens, tool latency, tool calls, hook denials, drive duration) emit over OTLP from the loop + the shared drive path, so every engine is instrumented identically (all-engines rule).
- `convertible telemetry status` / `overview` introspection noun, plus an explain catalog entry.
- `TelemetryConfig` resolved from `CONVERTIBLE_OTEL_*` / standard `OTEL_*` env vars (`OTEL_SDK_DISABLED` honored as a kill-switch).
- Optional `[otel]` extra (opentelemetry SDK + OTLP/HTTP exporter); install with `pip install "convertible-cli[otel]"`.

### Changed

- `loop.run()` and `execute_drive` accept/own telemetry, defaulting to a no-op resolved from the environment (mirrors the hooks pattern). Off by default it is a strict no-op: no spans, no SDK import, `TaskResult` unchanged.

## [0.6.0] - 2026-05-28

### Added

- Layered per-model config: AGENTS instructions (`AGENTS.md` -> `AGENTS.convertible.md` -> `AGENTS.convertible.<model>.md` at the repo root, with a `~/.convertible/` fallback) and skills (`.convertible/skills/*.md` -> `.convertible/<model>/skills/*.md`) compose into the engine system prompt via `convertible/layers.py`
- `convertible agents` and `convertible skills` introspection nouns (list + overview, `--json`, `--model`)
- `Engine.system_prompt()` base-class helper injects the layered prompt for every engine (all-engines rule)

### Changed

- Both engines (mock, vllm-openai) now pass a model-specific `system_prompt` to the loop; behavior is byte-identical when no AGENTS/skills files exist

## [0.5.0] - 2026-05-27

### Changed

- Bare `convertible` (no subcommand) now opens the interactive harness (the `session` palette) when run at a terminal — the natural "get in and drive" gesture. Piped, redirected, or otherwise non-interactive, it still prints usage, preserving the discoverable surface for scripts and agents. `-h/--help` is unaffected.
- Reframed `convertible drive` help and `explain` text to lead with the goal/instruction ("drive toward a goal") rather than "run a repo task"; the repo is the target, not the headline. No behavior change.

## [0.4.0] - 2026-05-27

### Added

- Convertible ASCII banner on 'drive' and 'session' start (issue #15): decorative chrome shown only on an interactive TTY and suppressed in --json, so it never pollutes the stdout result stream or agent-parsed stderr.

## [0.3.0] - 2026-05-27

### Added

- Command templates discovered under .convertible/commands/*.md, expanded into a Task via `drive --command <name> [args]` ($ARGUMENTS / $1 substitution).
- Lifecycle hooks (.convertible/hooks.json): operator shell commands fired at task_start/pre_tool/post_tool/finish; a pre_tool hook can allow, deny, or rewrite a tool call (Claude-Code-style stdin-JSON + exit-code/structured-stdout I/O contract).
- Interactive foreground palette: `convertible session` over the shared drive path.
- Agent-first CLI: `convertible commands list/overview` and `convertible hooks list/overview`.
- Result artifact now records every hook firing and the originating command.

### Changed

- Hook lifecycle is wired into the engine-agnostic loop, so it binds every engine (all-engines rule); the chassis is no longer purely one-shot.
- Repo-shipped hooks run by default under the trusted-operator-env model (a per-repo trust gate / opt-out is a documented follow-up, not yet built).

### Fixed

- Hook execution and matching failures (subprocess timeout, launch error, invalid matcher regex) now map to a structured fail-closed decision instead of crashing the drive.
- The originating command is persisted in the result artifact on the failure path and for session-run templates (previously recorded as null).
- `convertible session` routes errors/diagnostics to stderr and honors `--json` (one JSON result per drive on stdout, palette chrome to stderr).
- `hooks list` reads entries via the public `HookConfig.all_entries` accessor (removed an unjustified lint suppression).

## [0.2.2] - 2026-05-27

### Added

- README tip (anecdotal, n=1): qwen3_coder handled tool-argument escaping more reliably than hermes for an NVFP4 Qwen3 checkpoint — a hermes run over-escaped docstring triple-quotes into a SyntaxError. Framed as a single observation, not a benchmark.

## [0.2.1] - 2026-05-27

### Changed

- Generalized the vLLM tool-call-parser docs from hermes-specific to model-appropriate (e.g. hermes or qwen3_coder); the engine is parser-agnostic and only needs OpenAI-format tool calls. Touches vllm_openai docstring, the live-proof test docstring, README, and CLAUDE.md.

## [0.2.0] - 2026-05-27

### Added

- convertible drive: run a repo task through a swappable coder engine (bounded agentic tool-loop: read_file/write_file/list_dir/run_command/finish, repo-confined)
- convertible wheels list: discover engine wheels via the convertible.engines entry-point group
- Shared task contract (Task/TaskResult) with lossless JSON round-trip
- Two bundled engines: deterministic networkless mock, and vllm-openai driving any OpenAI-compatible /v1/chat/completions endpoint with tool calling (stdlib urllib, no SDK)
- Git/PR handoff: branch/commit/push + gh pr create, gated by --no-pr/no-remote for offline/CI
- JSON result artifact + step-trace dashboard under .convertible/
- Opt-in live vLLM end-to-end test (CONVERTIBLE_VLLM_E2E=1)

### Changed

- CLAUDE.md expanded from the /init seed into a full runtime prompt for the harness
- README rewritten to document the engine/driver/chassis/wheels architecture and the v0 boundary

### Fixed

- Loop now serializes outbound tool-call `arguments` as a JSON string (OpenAI wire format), so multi-turn vLLM tool loops aren't rejected by strict servers (Qodo #1)
- `drive` attempts handoff whenever the drive succeeds (not only when `write_file` ran), so edits made via `run_command` are committed/pushed; `changed_files` is backfilled from `git status` (Qodo #2)
- Handoff note no longer claims "local commit only" when the push succeeded but `gh pr create` failed (Qodo #4)
- Reduced the "wheel/garage" pun in the running CLI's user-facing output, keeping external messaging engine-centric (Qodo #3)

## [0.1.2] - 2026-05-27

### Changed

- **Renamed the PyPI distribution from `convertible` to `convertible-cli`** — the
  bare `convertible` name was unavailable/ambiguous on PyPI. Only the published
  distribution name changes; the import package (`convertible/`), the `convertible`
  CLI entry point, and the wheel build target are unchanged. Updated the TestPyPI
  install hint in `.github/workflows/publish.yml` to match.

## [0.1.1] - 2026-05-26

### Changed

- **CI gates on the SonarCloud quality gate**
  ([issue #3](https://github.com/agentculture/convertible/issues/3)) —
  added `sonar.qualitygate.wait=true` to `sonar-project.properties` so a failing
  gate fails the `test` job when `SONAR_TOKEN` is set. Token-less repos and fork
  PRs remain green (the scan step is guarded by `if: env.SONAR_TOKEN != ''`).

## [0.1.0] - 2026-05-26

### Added

- **Onboarded into the AgentCulture mesh** ([issue #1](https://github.com/agentculture/convertible/issues/1)).
- **Agent-first CLI** cited from teken's (`afi-cli`) `python-cli` reference
  (`teken cli cite`) — verbs `whoami`, `learn`, `explain`, `overview`, `doctor`,
  and the `cli` noun group. Runtime is self-contained (`dependencies = []`);
  `teken>=0.8` is a dev dependency only. Passes the seven-bundle agent-first
  rubric (`teken cli doctor . --strict`). `doctor` checks the agent-identity
  invariants (prompt-file-present, backend-consistency, skills-present).
- **Mesh identity**: `culture.yaml` (`suffix: convertible`,
  `backend: claude`) and the matching `CLAUDE.md` prompt file.
- **Canonical guildmaster skill kit** (11 skills) vendored under
  `.claude/skills/` (cite-don't-import): `agent-config`, `assign-to-workforce`,
  `cicd`, `communicate`, `doc-test-alignment`, `pypi-maintainer`, `run-tests`,
  `sonarclaude`, `spec-to-plan`, `think`, `version-bump`. Every `SKILL.md`
  carries `type: command` (load-bearing for the culture/claude backend);
  `cicd` / `communicate` consumer-identifying prose adapted, all script bodies
  verbatim. Provenance in `docs/skill-sources.md`. Three skills (`think`,
  `spec-to-plan`, `assign-to-workforce`) originate in `devague`, re-broadcast
  via guildmaster.
- **Build + deploy baseline**: `pyproject.toml` (hatchling), `tests/` (pytest,
  xdist, coverage), `.github/workflows/{tests,publish}.yml` (CI rubric/lint gate,
  PyPI Trusted Publishing), `.flake8`, `.markdownlint-cli2.yaml`,
  `sonar-project.properties`, and `.claude/skills.local.yaml.example`.

### Changed

### Fixed
