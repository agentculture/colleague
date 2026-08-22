# per-seat thinking effort (#416)

> Colleague sends a per-seat thinking setting: deepthink/design seats keep the checkpoint's full effort while shallow seats (senses front door, talker, read-only scouts) turn thinking off — resolved where each seat is built, never per turn, and byte-identical when unset.
> instruction: verify: tests/`test_thinking_effort.py`::`test_unset_is_byte_identical` passes; docs/features/thinking-effort.md exists

## Audience

- operators running colleague against a lobes/vLLM rig serving a thinking checkpoint (Qwen3.8 cortex today), and the colleague runtime's own seats (cortex/worker, deepthink, senses/Talker, evaluator, subagent roles) as consumers of a per-seat thinking setting
  - instruction: check docs/features/thinking-effort.md names both readers: the operator (config surface) and the seat table (runtime)

## Before → After

- Before: every seat runs at the checkpoint's template default (xhigh) because colleague sends no thinking knob at all (`vllm_openai.py` `_build_chat_payload`: model/messages/temperature/tools/stream only); shallow calls pay full reasoner prices; plan/split decisions get no more effort than the acting seat
  - instruction: git show main:colleague/engines/`vllm_openai.py` | grep -c `chat_template_kwargs` == 0
- After: each seat is built with its own thinking setting from a fixed per-seat table (deepthink/main unset=checkpoint default; senses/Talker + read-only roles off; writer unset), operator-overridable, visible in config show + the artifact; design calls (plan/auto-split/fill-line) run on cortex at full effort; a too-hard/too-long run leaves a split-next-time record recall surfaces on the next attempt; unset = byte-identical wire + result
  - instruction: `COLLEAGUE_DUMP_REQUEST`=1 on a senses turn shows `chat_template_kwargs`.`enable_thinking`:false; on a deepthink turn no `chat_template_kwargs` key; unset config → payload dict equal to the pre-change fixture

## Why it matters

- \#415: small requests finish in ~2 min while module briefs stall 23–75 min on a --max-num-seqs=2 rig; #417: cortex is at xhigh on every turn by default, and lower rungs are NOT reliably cheaper and degrade parsed output, while thinking-off is −75% total tokens on shallow calls with equal correctness — the saving is seat-shaped, so the knob must be seat-shaped
  - instruction: cite colleague#415 + colleague#417 tables in the feature doc

## Requirements

- EngineConfig gains ONE per-seat thinking knob (closed ladder: off | low | medium | xhigh, default unset) that colleague/engines/`vllm_openai.py` `_build_chat_payload` (line 878, the SINGLE payload builder every seat's `_make_complete` passes through) emits as `chat_template_kwargs` — `enable_thinking`:false for off, `reasoning_effort` for a rung; unset = key omitted = byte-identical body
  - instruction: parametrized payload test over {unset, off, low, medium, xhigh}
  - honesty: the payload carries `chat_template_kwargs` ONLY when the seat's setting is non-unset: off → {"`enable_thinking`": false}; a rung → {"`reasoning_effort`": <rung>}; never both keys, never any other key (`preserve_thinking` is never sent)
- The knob is set where the seat is BUILT — the five dataclasses.replace seat sites (deepthink.py:84, senses.py:294, `tae_loop.py`:225, agents/runtime.py:250, subagents.py:655/833 child builds) each carry their own value from a FIXED per-seat table; the loop never changes it per turn
  - instruction: tests/`test_thinking_effort_boundary.py`: assert no assignment to the field outside config.py/roles.py/the seat builders
  - honesty: the five seat-build sites set the field once from the table; nothing under the loop's per-turn path (loop.py step handling, `tae_loop` turns, `senses_loop` moves) writes or rewrites it — pinned by a grep/AST guard like `test_agents_boundary`'s router guard
- Operator override follows the existing knob contract: flag > env (`COLLEAGUE_REASONING_EFFORT` + per-seat `COLLEAGUE_`<SEAT>`_REASONING_EFFORT`) > config.json > default, resolved in config.py resolve() beside temperature (line 3602), surfaced in 'colleague config show' (cli/`_commands`/config.py:72) and in the artifact config snapshot `to_dict`() (config.py:3876) — identical on mock and vllm-openai so the all-engines rule holds on the RESULT shape
  - instruction: tests/`test_config_thinking_effort.py` mirrors `test_config_senses.py`'s `to_dict` pins; run on both engines
  - honesty: precedence is flag > env > config.json > default for the global knob AND each per-seat override; config show prints the resolved table; EngineConfig.`to_dict`() carries the same keys on mock and vllm-openai (all-engines)
- Docs + pins: CLAUDE.md's 'TWO carve-outs' sentence becomes three; docs/features/engines.md, deepthink.md (the four-point surface gains a recorded default effort), config-resolution.md, and a new feature doc; payload-key pins in tests/`test_vllm_openai.py` / `test_headless_streaming.py` / `test_deepthink_config.py` gain the unset-omits-key proof
  - instruction: run the doc-test-alignment skill on the PR
  - honesty: CLAUDE.md (carve-outs = three + a new architecture bullet), docs/features/thinking-effort.md, engines.md, deepthink.md, config-resolution.md and roles docs all describe the shipped surface; doc-test-alignment passes
- Per-role effort: roles.py Role gains an effort field (explorer/reviewer/validator/planner off by default per q1, writer unset); the delegating parent can override per delegation (subagents.py child builds / agents delegate message) and the override is recorded with the child seat's attribution — child never exceeds what the parent could grant
  - instruction: tests/`test_roles_thinking_effort.py`: builtin defaults, overlay, parent override recorded on #411 ledger when armed
  - honesty: Role carries an effort field with the q1 defaults; an operator role overlay can change it; a parent delegation override is applied to the child seat AND recorded on the delegation/ledger record (never silently); roles without a value inherit the parent seat's
- Design call-site at full effort: plan mode (plan/`cli_driver.py` `to_simple_complete` over the main seat), the auto-split recommendation (autosplit.py) and the fill-line compact|split decision (fillline.py) are a NAMED design call-site run by cortex at the checkpoint default effort — the cortex agent's design sub-role — even when the acting seat is set lower; a fixed enumerated table of call-sites, not a task→effort decision
  - instruction: test: the three call paths build their completion from the design seat config; grep guard on the constant
  - honesty: the design call-site is ONE enumerated constant naming exactly plan mode (plan/`cli_driver`), the auto-split recommendation and the fill-line compact|split decision; those calls go to the cortex seat at the checkpoint default effort even when the acting seat is off; adding a call-site means editing the constant, never a runtime decision
- Retroactive too-hard/too-long detection (Ori): a run that ends budget-exhausted / INCOMPLETE (incompletion.py reasons, chain budget-exhausted) or whose WorkStats duration/steps cross a recorded threshold leaves a 'too large — split next time' record with the task slug on the memory remember-after lane (memory.py, rung-1 substance) so the recall-before block on a future attempt at the same/similar task surfaces a split recommendation (autosplit.`build_split_recommendation`) up front — detection is post-hoc and recorded, never a per-turn router
  - instruction: tests/`test_memory_split_record.py`: record shape; recall block renders the recommendation; no loop.py write path
  - honesty: the split-next-time record is written ONLY after a run ends, from enumerated signals (q4), onto the existing remember-after lane with the task slug and the measured evidence (reason, steps, duration); recall-before surfaces it as a split recommendation; it never changes the running loop's seat or effort
- Rollback / containment: ONE global kill-switch (`COLLEAGUE_REASONING_EFFORT`=default or config.json `reasoning_effort`: "default") forces every seat, role and design call-site to unset → the byte-identical pre-increment wire in one env var, no redeploy, no code change
  - instruction: test: kill-switch set + per-seat overrides set → every payload omits `chat_template_kwargs`
  - honesty: with the kill-switch set, no payload from any seat carries `chat_template_kwargs` regardless of per-seat/role/env overrides, and config show prints the switch as the winning layer
- Graceful degrade across checkpoints: a seat call that carried `chat_template_kwargs` and gets HTTP 400 whose body names the ladder (probe 2026-08-21: 'Unexpected reasoning effort bogus. Supported types are xhigh (default), medium, and low.') is retried ONCE without the key and a TaskResult warning names the seat + the server's supported ladder; the run never fails on the knob (closes the Thor/35B unknown-ladder risk v3 at runtime)
  - instruction: test: scripted `_post_json` 400-then-200 → one retry without the key + warning; a non-ladder 400 is NOT retried
  - honesty: the retry fires at most once, only on a 400 whose body names the reasoning ladder, only for a request that carried the key; the warning lands on TaskResult.warnings naming seat + ladder; any other 400 surfaces exactly as today
- Child-seat inheritance keys on the CHILD: a subagent/cross-role child takes its effort from ITS OWN role/purpose in the table; the parent seat's value never flows down implicitly (a Talker at off delegating to Thinker/cortex must not silence the Thinker) — only an explicit per-delegation override (c13/q3) crosses, and it is recorded
  - instruction: test: Talker(off) → delegate Thinker → child payload has NO `enable_thinking`:false; explicit override → present + on ledger
  - honesty: a child's effort is computed from the child's own role/purpose row; a parent value reaches the child only via the explicit override path and is then visible on the delegation/ledger record
- Observability: the effort each invocation ran at is trace data on the #411 task-ledger invocation record (ledger.py, beside model) and on the OTel work span (telemetry/`_otel.py` beside model/`max_steps`) — so per-seat attribution answers 'what effort did this call run at' without re-deriving the table
  - instruction: test: ledger record + span attribute carry `reasoning_effort`; absent when unset
  - honesty: the ledger invocation record and the OTel span carry the effort only when the seat ran with one set (absent = unset), keeping the unset artifact/ledger byte-identical
- Explicit precedence for the resolved effort of any seat, highest first: kill-switch (c26) > explicit per-delegation parent override (c13/c28) > per-seat env/config override (c5) > role-table default (c13) > seat-table default (c6/c31) > unset; the order is one documented function (`resolve_effort`) with a table test, never re-derived at a call site
  - instruction: tests/`test_thinking_effort.py`::`test_precedence_table` covers every adjacent pair
  - honesty: `resolve_effort` is the only place precedence is computed; every seat builder calls it; a table test covers each adjacent pair
- Retry composition: the ladder-400 retry (c27) and the existing same-role stale-pin 404 refresh retry (`vllm_openai`.`_make_complete`, plan task t9) are disjoint by status code and each fires at most once per call — a call can see at most one of each, never a loop; the 400 retry keeps the refreshed model id
  - instruction: test: scripted 404→400→200 → two distinct single retries, model refreshed, key dropped, two warnings
  - honesty: a scripted 404→400→200 sequence yields exactly two retries, the refreshed model id persists, the key is dropped, and both warnings land
- The default table (v2, replaces c6): cortex/worker acting seat medium · deepthink/muse xhigh · evaluator medium · senses/Talker off · design call-site TIERED: plan/`spec_stage.py` xhigh, plan/`plan_stage.py` high, plan/workforce.py + autosplit.py split recommendation + fillline.py split decision + subagents fan-out decomposition xhigh · subagent children: writer medium, explorer/reviewer/validator/planner off · top-level --role explorer low (off selectable), other top-level roles = acting seat (medium) · global kill-switch → unset
  - instruction: tests/`test_thinking_effort.py`::`test_default_table` pins every row; feature doc renders the same table
  - honesty: every row of the table is pinned by one parametrized test and rendered verbatim in docs/features/thinking-effort.md; the acting seat never sends xhigh unless the operator overrides
- Ladder v2: the operator-facing enum is off | low | medium | high | xhigh (plus default=kill-switch); high is sent VERBATIM (probe 2026-08-22: the Qwen3.8 template accepts it; it is an alias of xhigh on that checkpoint — recorded in the doc as a checkpoint fact, not normalized away) — supersedes c4's normalize-high-to-xhigh clause; unknown values still refused at resolve() and a ladder-400 still degrades per c27
  - instruction: unit: =high → payload `reasoning_effort`:high, no warning; =bogus → CliError
  - honesty: 'high' reaches the wire verbatim and the doc states it equals xhigh on Qwen3.8 (probe + #417), so an operator choosing high over xhigh on this checkpoint gets no saving — honestly recorded, not hidden
- Default table v3 children rows (replaces the children rows of c36): writer medium · planner medium · reviewer low · validator low · explorer off — every other row of c36 unchanged
  - instruction: tests/`test_thinking_effort.py`::`test_default_table` pins the v3 rows; docs/features/thinking-effort.md renders them
  - honesty: the rendered table in the feature doc and the parametrized pin agree row-for-row with c39; no other row of c36 moves

## Honesty conditions

- with no thinking setting configured anywhere, every vllm-openai payload dict and every TaskResult/artifact key set is byte-identical to main — the increment is invisible until armed
- a server that ignores `chat_template_kwargs` produces the same colleague behavior as today (no new error path, no retry); the adapter adds no non-OpenAI endpoint — only one extra body key on the existing /chat/completions call
- both readers are served by ONE surface: the operator edits config.json/env, the runtime reads the same resolved table — no second config format
- the before-state is verifiable on main: zero occurrences of `chat_template_kwargs`/`reasoning_effort`/`enable_thinking` in colleague/ (#416's own grep)
- every sentence of the after-state maps to a confirmed requirement (c2–c5, c13–c15) — no after-state claim ships without a requirement behind it
- the why cites measured rig evidence (#415, #417) and states its limits (n=1/cell, 4 prompts, effort×tools unmeasured) rather than asserting a universal saving
- success is measured on the live rig (`reasoning_tokens` from usage.`completion_tokens_details`, exact — never estimated) plus unit pins; if the served checkpoint stops reporting `reasoning_tokens` the live signal is reported as unmeasured, not as pass
- the probe is n=1 per cell on one checkpoint, one box, one day; it lowers the odds of a surprise, it does not replace the live arm

## Success signals

- (1) with the default table armed on the live rig, a senses/Talker completion reports usage.`completion_tokens_details`.`reasoning_tokens` == 0 and a deepthink completion reports > 0; (2) with nothing configured, 100% of the payload pins in tests/`test_vllm_openai.py` + `test_headless_streaming.py` pass unchanged (byte-identical); (3) 'high' never reaches the wire (normalized to xhigh) and an unknown value exits non-zero at resolve, 0 HTTP 400s from the ladder
  - instruction: live: `COLLEAGUE_VLLM_E2E`=1 pytest tests/`test_vllm_live_thinking_effort.py`; unit: pytest tests/`test_thinking_effort.py`

## Scope / boundaries

- `chat_template_kwargs` is a vLLM extension, so this is the THIRD graceful-degrade carve-out to 'the vLLM adapter only touches the OpenAI surface' (after /tokenize and the armed-lobes stale-pin refresh, CLAUDE.md conventions): a server that ignores the key behaves exactly as today; vLLM merges the request kwargs per key so lobes' `preserve_thinking`:true (#93) is never clobbered; unset = byte-identical
  - instruction: scripted `_post_json` mock that drops the key → run completes identically; CLAUDE.md carve-out sentence reads THREE

## Assumptions

- Probe 2026-08-21 (read-only via the local gateway, cortex Qwen3.8-27B-NVFP4): `enable_thinking`:false forms a correct tool call (`read_file`{path:README.md}, `reasoning_tokens` 0, 26 completion tokens) on the `qwen3_coder_thinking` parser; low/high (alias) also form it; stream:true + the key returns usage with `reasoning_tokens` 0; a thinking-on assistant turn followed by an OFF turn under `preserve_thinking` answers correctly (391+9→400). n=1 each — the in-session live arm (c25) is still the proof
  - instruction: feature doc 'Honest limits' records the probe and its n=1

## Scope exploration

- `s1` — `colleague/engines/vllm_openai.py::_build_chat_payload (l.878) + _make_complete`: ONE payload builder for every vllm-openai completion (model/messages/temperature/tools/`tool_choice`/stream); no `reasoning_effort`, `extra_body` or `chat_template_kwargs` today; reasoning read back from message.reasoning|`reasoning_content` — the only place the knob needs to hit the wire
  - seeds: `c2`, `c7`
- `s2` — `seat-build sites: deepthink.py:84, senses.py:294, tae_loop.py:225, agents/runtime.py:250, subagents.py:655/833`: five dataclasses.replace(config, model/`base_url`/`api_key`/`context_budget`, `refresh_seat`=None, `on_delta`=None) sites — every seat inherits every other EngineConfig knob unchanged, so a new per-seat field flows naturally and is set exactly once per seat
  - seeds: `c3`, `c8`
- `s3` — `colleague/config.py EngineConfig (l.2926) + resolve() temperature (l.3602) + to_dict() (l.3876); cli/_commands/config.py config show (l.72)`: existing knob contract (`_pick` flag>env>config.json>default, `COLLEAGUE_`\*/`CONVERTIBLE_`\* aliases, artifact snapshot, redacted show) is the template for the new knob; seat sub-configs DeepthinkConfig/SensesConfig/WorkerConfig/SeatConfig (l.2682–2769) are where per-seat overrides can be parsed
  - seeds: `c5`
- `s4` — `colleague#417 + lobes-cli#192 evidence (docs/evidence/2026-08-21-measure-reasoning-effort-cortex-spark.txt)`: Qwen3.8-27B template ladder is low/medium/xhigh, default xhigh, high=alias, unknown value → HTTP 400; `enable_thinking`:false is the real OFF; low/medium are not monotonic cheaper, degrade instruction-following and flipped a decision; OFF scored 4/4 on shallow prompts; request kwargs merge per key over `preserve_thinking`
  - seeds: `c4` (rejected), `c6` (rejected), `c7`
- `s5` — `CLAUDE.md conventions: 'vLLM adapter only touches the OpenAI surface' + TWO carve-outs (/tokenize, armed-lobes stale-pin)`: `chat_template_kwargs` is a third non-OpenAI key; must be a graceful degrade like the other two, and the convention text must be updated to three
  - seeds: `c7`, `c12`
- `s6` — `tests/test_agents_boundary.py::test_no_routing_function_takes_instruction_text (+ no_router_guard_is_not_vacuous)`: the AST guard pins that no function takes instruction text to pick a model per turn — a per-turn effort choice would be the same excluded router; a fixed per-seat table is the sanctioned shape
  - seeds: `c9`
- `s7` — `colleague/engines/mock.py make_complete (raises; no wire payload)`: mock builds no payload, so effort can only be observable via the config snapshot on mock — the all-engines rule constrains the RESULT shape, not the wire
  - seeds: `c10`
- `s8` — `lobes-cli templates/fleet/docker-compose.yml (--default-chat-template-kwargs, issue #93) + lobes-cli CLAUDE.md l.100–130 + lobes/cli/_commands/route.py _ROUTE_EXTRA_BODY`: lobes already sends `chat_template_kwargs`.`enable_thinking`:false per request in its own route verb; fleet default stays `preserve_thinking` only — colleague must not edit the compose
  - seeds: `c11`
- `s9` — `colleague/profiles.py ModeProfile`: mode profiles bundle `max_steps`/context fraction/synthesis reserve/timeout/fillline — compute/context only; effort is per seat, not per mode
  - seeds: `c8`
- `s10` — `colleague/roles.py BUILTIN_ROLES (explorer/planner/reviewer/validator read_only=True, writer) + is_read_only()`: no 'scout' role exists — the read-only roles are explorer/reviewer/validator/planner; per-role effort could live on Role (operator-overlayable) or be keyed on `read_only` at the seat table
  - seeds: `c6` (rejected)
- `s11` — `colleague/plan/cli_driver.py to_simple_complete (adapts the loop CompleteFn) + autosplit.py / fillline.py (in-loop on the main seat)`: plan mode, auto-split and fill-line compact/split ride the MAIN seat's completion — no named design call-site today; raising design-time effort needs a call-site, not a seat
  - seeds: `c6` (rejected)
- `s12` — `tests pinning the payload key set: test_vllm_openai.py, test_headless_streaming.py, test_deepthink_config.py, test_config_*.py (to_dict keys)`: payload-shape and config-snapshot pins exist and will need the unset-omits-key / new-key proofs
  - seeds: `c12`
- `s13` — `colleague/engines/vllm_openai.py l.262 comment (no completion_tokens_details) vs #417 (rig now reports reasoning_tokens)`: stale comment; exact reasoning-token accounting is adjacent work, parked
- `s14` — `lobes.py / LobesRoles RoleInfo (model/endpoint/context)`: the lobes /capabilities contract carries no thinking-ladder advert — colleague cannot discover the served template's ladder; validation is a static client-side enum for now (Thor/35B ladder unknown)
- `s15` — `colleague/incompletion.py reasons (no-progress-zero-steps, budget-exhausted, tool-protocol-broken) + chain.py CONTINUABLE_REASONS + artifact.py WorkStats`: budget-exhausted / INCOMPLETE and WorkStats (steps, duration, tokens) already land on the artifact per run — the post-hoc 'too hard/too long' signal exists, nothing consumes it on the NEXT attempt
  - seeds: `c15`
- `s16` — `colleague/memory.py remember-after (build_lesson_record l.378, rung-1 failure substance) + recall-before block (build_recall_block l.327); autosplit.py build_split_recommendation`: the recall-before/remember-after lane is the natural carrier for a 'split next time' record keyed on the task; the split recommendation builder already exists reactively in-loop and can be surfaced up front from recall
  - seeds: `c15`
- `s17` — `colleague/roles.py Role dataclass (name, tools, read_only, overlayable by operator) + subagents.py child builds + agents/delegation.py typed delegate message`: Role is the per-role home for effort; the #411 delegation path already records narrowing from parent to child, so a parent effort override rides the same record
  - seeds: `c13`
- `s18` — `colleague/plan/cli_driver.py + autosplit.py + fillline.py as ONE design call-site`: three design-time decisions all ride the main seat today; naming them a call-site lets cortex design at full effort while the acting seat stays cheaper
  - seeds: `c14`
- `s19` — `challenge pass / adjacent-systems lens: realtime.py (/v1/realtime ears-only), stt/tts seats, continuation.py, layers.py per-model overlay`: realtime/stt/tts are not chat completions → unaffected; continuation re-resolves EngineConfig from env/config at resume (table is static, nothing to rehydrate); per-model exact-path overlay is orthogonal to per-seat effort — clean pass
- `s20` — `challenge pass / hidden-dependency lens: lobes gateway pass-through + lobes-cli route verb`: probes via <http://localhost:8001> (the gateway, Bearer) show `chat_template_kwargs` pass through to vLLM intact; lobes' own route verb already sends `enable_thinking`:false through the same path
  - seeds: `c30`
- `s21` — `challenge pass / failure-mode lens: server 400 on unknown rung; h8 parent→child inheritance; Talker→Thinker delegation`: 400 body is self-describing (ladder named) → retry-without-key is safe and legible (c27); implicit parent→child inheritance would silence the Thinker (c28 corrects h8's 'inherit the parent seat')
  - seeds: `c27`, `c28`
- `s22` — `challenge pass / observability+rollback lens: ledger.py invocation record, telemetry/_otel.py span attrs, config kill-switch`: attribution records carry model but no effort today (c29); one env var forces byte-identical (c26)
  - seeds: `c26`, `c29`
- `s23` — `challenge pass / unstated-assumption lens: evaluator seat effort, 'high' handling`: q1's 'tools-off shallow seats off' silently covers the evaluator whose verdict is consequential → q6; the server ACCEPTS 'high' as an alias so c4's normalize-to-xhigh is a convenience, not a guard — both recorded
- `s24` — `challenge pass 2 / overlooked-actors lens: colleague/cli/_commands/work.py --role (l.2292/2696) + .claude/skills/ask-colleague/scripts/ask-colleague.sh --role forwarding (l.393)`: a typed role is ALSO a top-level work flag, not only a subagent child — the role-table OFF default would hit ask-colleague review/explore on the main cortex seat; q7 raised
- `s25` — `challenge pass 2 / failure-mode lens: vllm_openai._make_complete stale-pin 404 refresh (single retry) × c27 ladder-400 retry`: two single retries on disjoint codes compose safely if pinned (c33); without the pin a 404-then-400 path could double-count or loop
  - seeds: `c33`
- `s26` — `challenge pass 2 / lifecycle lens: config.py EngineConfig.resolve() unknown config.json keys; older colleague + newer config.json`: no unknown-key refusal found in resolve() — an older colleague reading a config.json with the new key ignores it silently (degrade, not break); a newer colleague on an older rig is covered by c27
- `s27` — `challenge pass 2 / concurrency+operations lens: colleague/rig.py cooperative slot (--max-num-seqs=2), session cockpit/tui consumers of the config snapshot`: effort changes per-request occupancy, not slot count — no rig-budget change; cockpit/tui read no temperature-class knobs today so no render change is required (observability lands via ledger/OTel per c29)
- `s28` — `challenge pass 2 / security lens: request headers, endpoints, key hygiene`: no new endpoint, header or secret — one body key on the existing Bearer'd /chat/completions; same-origin key hygiene (#348) untouched — clean pass
- `s29` — `challenge pass 2 / counter-evidence lens: v1 closed before the arm ran (c25)`: v1 is closed by a COMMITMENT (in-session live arm + revert-on-degradation), not by evidence — the probe (c30) lowers the odds; the plan must carry the arm as a gated task or the closure is vibes
- `s30` — `challenge pass 2 / re-decision q8: colleague/plan/spec_stage.py, plan_stage.py, workforce.py; autosplit.py; fillline.py; subagents.py fan-out`: the three plan stages map 1:1 onto Ori's xhigh/high/xhigh tiers; splitting surfaces (auto-split, fill-line split, subagent decomposition) are the 'breaking a task into subtasks' call-sites → xhigh
  - seeds: `c36`

## Decisions

- q1 (Ori 2026-08-21): default table — deepthink/muse + acting cortex/worker seat unset (checkpoint default, xhigh); senses front door/Talker + tools-off shallow seats off; read-only subagent roles (explorer/reviewer/validator) off; writer unset
- q2 (Ori 2026-08-21): planning/design is a named call-site run BY CORTEX at full effort — plan mode, auto-split recommendation, fill-line split decision — the cortex agent's design sub-role, not a new lobes role; a fixed call-site table, never a router
- q3 (Ori 2026-08-21): effort lives on the subagent ROLE (roles.py Role field, operator-overlayable) and the delegating parent agent may override it per delegation, recorded with the child seat
- q4: too-hard/too-long signals are enumerated — budget-exhausted (incompletion/chain), steps at cap, wall-clock > `COLLEAGUE_TOO_LONG_MIN` (default 20) — and the split-next-time record is an eidetic lesson on the remember-after lane, surfaced by recall-before
- q5: read-only subagent roles ship OFF now; the effort×tool-calling proof runs live in this session on explorer/reviewer/validator/planner before merge (it is a plan task + live-testing row, not a deferral); a degradation reverts the role default to unset
- q6: the tae evaluator seat runs UNSET (full effort); 'tools-off shallow seats → off' in q1 covers senses/Talker only — the default table reads: deepthink/muse unset, cortex/worker unset, evaluator unset, senses/Talker off, read-only roles (explorer/reviewer/validator) off, planner role + design call-site unset, writer unset
- q7: subagent children only — a top-level --role does not inherit the role table, except the explorer role at top level (ask-colleague explore) which defaults to LOW with OFF selectable (Ori: 'explore gets none or low thinking; default thinking is low'); top-level reviewer/validator keep the main seat's unset
- q8 (supersedes c21 cortex/worker=unset, c31 evaluator=unset): acting cortex/worker seat default = MEDIUM; deepthink/muse = xhigh; design call-sites are TIERED — spec stage xhigh, spec→plan stage high, workforce split/fan-out + auto-split + fill-line split + subagent decomposition xhigh; workforce/subagent children run medium/low/off (never xhigh by default); senses/Talker off; top-level explore low (off selectable)
- q9: writer subagent children medium; explorer/reviewer/validator/planner children off; evaluator medium — the cheap tier is medium/off, never low by default (#417: low degrades instruction-following)
- Ori 2026-08-22 (amends c36/c38 children rows): subagent children — validator LOW, reviewer LOW, planner MEDIUM, explorer OFF, writer MEDIUM; top-level --role explorer stays low (off selectable)

## Open parks

- [unknown_nonblocking] The rig now reports usage.`completion_tokens_details`.`reasoning_tokens` (#417) while `vllm_openai.py`:262 still says the server reports none — exact reasoning-token accounting on WorkStats is adjacent, not this increment; file separately
- [unknown_nonblocking] Thor's no-MTP cortex and the 35B worker seat's template may implement a different or no `reasoning_effort` ladder — the validation ladder might need to be per served checkpoint (unknown until measured)
- [unknown_nonblocking] `senses_loop` prompted-JSON moves, the fill-line compact summary and the rung-2 distill child at OFF/unset — parse-quality at OFF is covered only by the in-session live arm; the deterministic compaction validation (empty summary never replaces history) is the containment if OFF degrades a summary
- [follow_up] doctor --probe could read the served ladder from the 400 body ('Supported types are …') as a one-call readiness rubric line; not this increment

## Resolved vagueness

- [unknown_blocking] Effort × tool-calling is UNMEASURED (#417 scope note): a scout/worker loop WITH tools at `enable_thinking`:false may degrade tool-call formation on `qwen3_coder_thinking` parser; needs a live arm (the #415 many-small-requests experiment is the natural bed) before turning off thinking on any tool-bearing seat by default — resolved: q5/c25: the effort×tool-calling arm runs live in THIS session on the read-only roles before merge; a degradation reverts the role default to unset — the unknown is closed by a measured plan task, not assumed away
