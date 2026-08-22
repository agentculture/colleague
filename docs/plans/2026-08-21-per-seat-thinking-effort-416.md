# Build Plan — per-seat thinking effort (#416)

slug: `per-seat-thinking-effort-416` · status: `exported` · from frame: `per-seat-thinking-effort-416`

> Colleague sends a per-seat thinking setting: deepthink/design seats keep the checkpoint's full effort while shallow seats (senses front door, talker, read-only scouts) turn thinking off — resolved where each seat is built, never per turn, and byte-identical when unset.

## Tasks

### t1 — Effort model: colleague/effort.py (NEW) — ladder enum, seat/role/design tables (v3), `resolve_effort` precedence, payload fragment

- instruction: Pure stdlib, no imports from loop.py/config.py (config imports effort, not the reverse). Keep it under 200 lines. Precedence: `kill_switch` > `parent_override` > `seat_override`(env/config) > role table > seat table > unset. 'default' is the kill-switch sentinel meaning 'send nothing'. Document in the module docstring that 'high' == 'xhigh' on Qwen3.8 (probe 2026-08-22) and is sent verbatim anyway.
- covers: c32, h22, c37, h25, c36, h24, c40, h26, c26, h17
- acceptance:
  - colleague/effort.py exports LADDER = ('off','low','medium','high','xhigh'), `DEFAULT_SENTINEL`='default', `SEAT_TABLE` / `ROLE_TABLE` / `DESIGN_SITE_TABLE` exactly as c36+c40 (cortex/worker medium, deepthink xhigh, evaluator medium, senses off, writer medium, planner medium, reviewer low, validator low, explorer off, top-level explorer low; `spec_stage` xhigh, `plan_stage` high, workforce/autosplit/fillline-split/subagent-decomposition xhigh)
  - `resolve_effort`(`kill_switch`, `parent_override`, `seat_override`, role, seat, site) returns the highest-precedence non-None value in the c32 order; tests/`test_effort.py`::`test_precedence_table` covers every adjacent pair
  - `to_chat_template_kwargs`('off') == {'`enable_thinking`': False}; a rung → {'`reasoning_effort`': rung} with 'high' verbatim; None/unset → None (no key); `validate_effort`('bogus') raises CliError naming the ladder
  - a parametrized test pins every row of the v3 table (c36/c40)

### t2 — Config wiring: EngineConfig.`reasoning_effort` + per-seat overrides (env/config.json), `to_dict`, config show

- instruction: Mirror the temperature knob at config.py:3602 and the `to_dict` block at :3876. Keep the edit to config.py minimal (the file is 4284 lines, #413) — put parsing helpers in colleague/effort.py (t1) and call them. Add the lines to cli/`_commands`/config.py next to temperature (l.72). t2 is the ONLY task that edits config.py: it also sets the acting seat's effort in resolve(), the top-level explorer→low rule (config.role == 'explorer'), and the `too_long_min` knob — t4/t5/t8 consume these, they do not edit config.py.
- depends on: t1
- covers: c5, h5, c16, h12, c26, h17
- acceptance:
  - EngineConfig gains `reasoning_effort` (Optional\[str\], default None) and `reasoning_effort_seats` (mapping seat-name→value) resolved in resolve() via `_pick`: `COLLEAGUE_REASONING_EFFORT` (global / kill-switch 'default') and `COLLEAGUE_`<SEAT>`_REASONING_EFFORT` for SEAT in CORTEX|WORKER|DEEPTHINK|SENSES|EVALUATOR|DESIGN, plus config.json keys `reasoning_effort` / `reasoning_effort_seats`; flag > env > config.json > default
  - EngineConfig.`to_dict`() carries '`reasoning_effort`' and '`reasoning_effort_seats`' on mock and vllm-openai identically; with nothing set both are None/{} and every pre-existing `to_dict` pin (tests/`test_config_`\*.py) still passes
  - colleague config show prints the resolved effort table (one line per seat) and names the winning layer when the kill-switch is set
  - an unknown value in env or config.json raises CliError at resolve() naming the ladder (c37)
  - config.py ALSO owns (so no other wave-2 task touches it): the acting seat's effort in resolve() (cortex/worker medium via `resolve_effort`), the top-level --role explorer → low rule, and the `too_long_min` knob (`COLLEAGUE_TOO_LONG_MIN` / config.json `too_long_min`, default 20) consumed by t8

### t3 — Wire: `_build_chat_payload` emits `chat_template_kwargs` from the seat's effort; ladder-400 retry-once + warning; byte-identical when unset

- instruction: Edit only colleague/engines/`vllm_openai.py`: in `_build_chat_payload` add the fragment from effort.`to_chat_template_kwargs`(`config_effort`) after tools; put the 400 classifier in a small helper `_is_ladder_400`(exc) beside `_is_model_not_found_404` (l.168) and the retry in `_make_complete` next to the existing refresh retry (l.~957) — keep both single-shot and disjoint by status code. Also refresh the stale comment at l.262 (rig now reports `completion_tokens_details`.`reasoning_tokens`) without changing token accounting.
- depends on: t1, t2
- covers: c2, h2, c7, h6, c27, h18, c33, h23, c1, h1, c17, h13
- acceptance:
  - with config.`reasoning_effort` None the payload dict from `_build_chat_payload` equals the pre-change payload key-for-key (tests/`test_vllm_openai.py` + `test_headless_streaming.py` pins unchanged); with 'off' it carries exactly {'`chat_template_kwargs`': {'`enable_thinking`': False}}; with a rung exactly {'`chat_template_kwargs`': {'`reasoning_effort`': rung}}; never both keys, never `preserve_thinking`
  - a scripted `_post_json` raising HTTPError 400 whose body contains 'reasoning effort' on a request that carried `chat_template_kwargs` → exactly one retry without the key, TaskResult.warnings gains one entry naming the seat and the server's supported ladder; a 400 without that body text is NOT retried; the stream path (`_post_json_stream`) gets the same treatment
  - scripted 404→400→200: exactly one stale-pin refresh and one ladder retry, model id refreshed, key dropped, two warnings (c33)
  - a mock server that silently ignores the key produces a run identical to today (no new error path)

### t4 — Main seats carry their table effort: deepthink.py, senses.py (+frontdoor), `tae_loop.py`, agents/runtime.py seat builders

- instruction: One-line additions at each dataclasses.replace site (deepthink.py:84, senses.py:294, frontdoor.py if it builds its own seat, `tae_loop.py`:225, agents/runtime.py:250). Do NOT edit config.py or loop.py (t2 owns the acting seat + config). Per-seat override comes from config.`reasoning_effort_seats` (t2).
- depends on: t2
- covers: c3, h3
- acceptance:
  - `deepthink_engine_config` sets `reasoning_effort` via `resolve_effort`(seat='deepthink') (xhigh default); `senses_engine_config` → seat 'senses' (off); `tae_loop` seat builders → 'senses' for the front, 'evaluator' for the evaluator (medium), 'worker' for the worker; agents/runtime.py build → the profile purpose's seat (talker→senses, `thinker_coder`→cortex, worker→worker); the acting cortex/worker seat in config.resolve() → 'cortex'/'worker' (medium)
  - each builder is covered by one test asserting the seat's resolved effort and that an operator per-seat override wins

### t5 — Roles + children: Role.effort field (v3 rows), subagent child builds key on the CHILD role/purpose, explicit parent override recorded, top-level --role rule (explorer low, others = acting seat)

- instruction: Files: roles.py, subagents.py, tools.py (schema), agents/delegation.py (record). Do NOT edit config.py (t2 owns the top-level explorer rule) or loop.py. Keep subagents.py edits local to `_child_config_for_profile` and the bare-role build.
- depends on: t1, t2
- covers: c13, h8, c28, h19
- acceptance:
  - roles.py Role gains effort: Optional\[str\]; `BUILTIN_ROLES` carry writer medium, planner medium, reviewer low, validator low, explorer off; an operator role overlay can set/override it
  - subagents.py child builds (l.655 and l.833) set `reasoning_effort` from `resolve_effort`(role=child role, seat=child purpose seat, `parent_override`=spec.effort) — a parent at off delegating to a cortex/thinker child yields a child payload WITHOUT `enable_thinking`:false; an explicit SubagentSpec.effort override is applied AND recorded on the delegation record / #411 ledger when armed
  - top-level colleague work --role explorer resolves the acting seat to low (off selectable via override); --role reviewer|validator|writer|planner at top level keep the acting seat's medium
  - the subagent/subagents tool schema accepts an optional effort field restricted to the ladder

### t6 — Design call-site: `DESIGN_CALL_SITES` constant; plan `spec_stage` xhigh / `plan_stage` high / workforce xhigh; auto-split + fill-line split + subagent decomposition at xhigh on the cortex seat

- instruction: Put `DESIGN_CALL_SITES` + `design_effort` + `design_seat_config` in a NEW colleague/design.py (not effort.py — t1 owns that file) importing the ladder from effort.py. Files: design.py, plan/`spec_stage.py`, plan/`plan_stage.py`, plan/workforce.py, autosplit.py (the recommendation builder's completion), fillline.py, subagents.py decomposition call (one line), loop.py (one or two lines passing the design seat config — loop.py is over the size limit, #413).
- depends on: t2, t5
- covers: c14, h9
- acceptance:
  - colleague/effort.py (or a sibling design.py) exports `DESIGN_CALL_SITES` = frozenset({'plan.`spec_stage`','plan.`plan_stage`','plan.workforce','autosplit','fillline.split','subagents.decompose'}) and `design_effort`(site) → xhigh/high/xhigh/xhigh/xhigh/xhigh per c36
  - plan/`spec_stage.py`, `plan_stage.py`, workforce.py build their completion from a design seat config (cortex seat + `design_effort`(site)) even when the acting seat is medium/off; autosplit recommendation and the fill-line split decision likewise; a test per site asserts the payload's `reasoning_effort`
  - adding a call-site means editing the constant; a grep/AST guard asserts no other module passes a literal effort to a completion

### t7 — Observability: effort as trace data on the #411 ledger invocation record and the OTel work span

- instruction: Read the value off the seat EngineConfig at record time; do not compute it from the table again. Files: ledger.py, agents/runtime.py (record site), telemetry/`_otel.py`.
- depends on: t4, t5
- covers: c29, h20
- acceptance:
  - ledger.py invocation/agent records carry `reasoning_effort` beside model when the seat ran with one set; absent (not null-filled) when unset so unarmed/unset ledgers are byte-identical
  - telemetry/`_otel.py` sets span attribute `reasoning_effort` beside model/`max_steps` only when set; tests/`test_telemetry`\*.py pin presence/absence

### t8 — Retroactive split-next-time record: too-hard/too-long signals → eidetic lesson on remember-after; recall-before surfaces the split recommendation

- instruction: Files: memory.py (record builder + recall rendering) and incompletion.py (expose the reason) ONLY — import autosplit.`build_split_recommendation`, do not edit autosplit.py (t6) or config.py (t2 adds the `too_long_min` knob). Gate on the existing memory triple-gate; isolated runs still target the operator repo.
- depends on: t2
- covers: c15, h10
- acceptance:
  - a run ending with incompletion reason budget-exhausted, a chain budget-exhausted exit, steps at `max_steps`, or wall-clock > `COLLEAGUE_TOO_LONG_MIN` (default 20; config.json `too_long_min`) writes ONE lesson record via memory.py's remember-after lane: kind 'split-next-time', task slug, reason, steps, duration, and the autosplit child-count hint
  - on the next run whose recall-before hits that record, the recall block renders autosplit.`build_split_recommendation` text up front (before the first step); a run with no matching record is byte-identical
  - the record is written only after the run ends — a grep guard asserts no write path from loop.py's step handling; no change to the running seat or effort

### t9 — Guards + all-engines pins: unset byte-identical across mock and vllm-openai; no per-turn effort writes; result-shape parity

- instruction: Model the guard on tests/`test_agents_boundary.py`::`test_no_routing_function_takes_instruction_text` (and keep its non-vacuous twin). Freeze the fixture from main before t3 lands (git show main:…).
- depends on: t3, t4, t5
- covers: c1, h1, c3, h3, c18, h14
- acceptance:
  - tests/`test_thinking_effort_boundary.py`: AST/grep guard asserting `reasoning_effort` is assigned only in config.py, effort.py, roles.py, the five seat builders, subagents.py child builds and `design_seat_config` — never in loop.py step handling, `tae_loop` turn handling or `senses_loop` moves
  - tests/`test_e2e_mock.py` (or a sibling) proves TaskResult/artifact key sets are identical on mock and vllm-openai with the knob unset AND set (effort only appears in the config snapshot)
  - a payload-equality pin: unset config → `_build_chat_payload` output equals a frozen pre-change fixture for tools-on, tools-off, streamed and blocking shapes

### t10 — Docs: feature doc with the v3 table + honest limits (#417, probes, n=1), CLAUDE.md (THREE carve-outs + architecture bullet), engines/deepthink/config-resolution/roles docs, doc-test alignment

- instruction: Write the table ONCE in the feature doc and reference it from the others (CLAUDE.md trim discipline: pointer, not duplicate). Record honestly that 'high' == 'xhigh' on Qwen3.8 and that effort×tool-calling rests on the t11 arm.
- depends on: t3, t4, t5, t6, t7, t8
- covers: c12, h7, c16, h12, c19, h15, c18, h14, c17, h13
- acceptance:
  - docs/features/thinking-effort.md exists: audience (operator + seat table), the v3 table verbatim (matches tests/`test_effort.py` row-for-row), precedence order, kill-switch, ladder-400 degrade, the probe record and #417 scope limits under 'Honest limits', and cites #415/#417
  - CLAUDE.md: the vLLM-adapter convention sentence reads THREE carve-outs (tokenize, stale-pin, `chat_template_kwargs`) and a new architecture bullet points at thinking-effort.md; docs/features/engines.md, deepthink.md (four-point surface notes xhigh default), config-resolution.md (new knobs), subagent-roles.md (Role.effort) updated
  - markdownlint-cli2 passes on every touched doc; the doc-test-alignment skill reports no drift

### t11 — Live arm + success signals: tests/`test_vllm_live_thinking_effort.py` (gated) and the in-session live run on explorer/reviewer/validator/planner children

- instruction: Run in this session before merge (Ori q5). Use a temp repo (never a dirty tree); cap concurrency at 2 and `COLLEAGUE_TIMEOUT`=300 (GPU serializes). Record exact `reasoning_tokens` per seat in the live-testing row.
- depends on: t3, t4, t5
- covers: c20, h16
- acceptance:
  - `COLLEAGUE_VLLM_E2E`=1 pytest tests/`test_vllm_live_thinking_effort.py`: a senses/Talker completion reports usage.`completion_tokens_details`.`reasoning_tokens` == 0; a deepthink completion reports > 0; an acting-seat completion at medium returns a tool call; `reasoning_tokens` absent → the test reports 'unmeasured', not pass
  - a live colleague work --engine vllm-openai run on a throwaway repo that fans out explorer (off), reviewer (low), validator (low), planner (medium) children completes with each child forming tool calls and finishing; the run's artifact + ledger show each child's effort; result recorded as a row in docs/live-testing.md
  - if any read-only child fails to form tool calls at its default, the role's default is reverted to unset in roles.py in the same PR (c25) and the doc says so

### t12 — Release: version bump (minor), CHANGELOG, PR via cicd, address review

- instruction: Use the version-bump skill then the cicd skill; link #416, #417, #415 in the body; note the twelfth sanctioned increment wording only if the spec says so (it does not add a routing policy — say so explicitly).
- depends on: t9, t10, t11
- covers: c12, h7
- acceptance:
  - pyproject version bumped minor + CHANGELOG entry naming #416/#417; uv run pytest -n auto green; black/isort/flake8/bandit clean; teken cli doctor --strict passes; PR opened with the cicd skill and signed

## Risks

- [unknown_nonblocking] effort × tool-calling is measured only by t11's in-session arm (n small, one checkpoint); a read-only child at off/low may degrade tool-call formation on the `qwen3_coder_thinking` parser — mitigation is the c25 revert in the same PR (task t11)
- [unknown_nonblocking] loop.py (5132 lines, #413/#415) and config.py (4284) are over the file-length limit — t2/t6 edits there must stay to a few lines or delegation stalls; keep logic in colleague/effort.py (task t6)
- [unknown_nonblocking] 'high' equals 'xhigh' on the served Qwen3.8 template (probe 2026-08-22): the `plan_stage`=high tier buys no saving on this checkpoint; it is kept as operator intent for checkpoints with a real high rung (task t1)
- [unknown_nonblocking] Thor's no-MTP cortex and the 35B worker template may expose a different or no ladder; c27's retry-once is the runtime guard, unmeasured until a Thor run (task t3)
- [unknown_nonblocking] the local GPU serializes: t11's live fan-out of 4 children will take tens of minutes; cap at 2 concurrent, `COLLEAGUE_TIMEOUT`=300 (task t11)
