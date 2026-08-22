# qwen-direct-no-gemma

> Colleague works Qwen-direct in every mode: Gemma is retired from the served roles colleague consumes — senses is no longer resolved or dialled by default, the senses presence loop is gone from the default path, cortex (Qwen3.8) answers the operator directly; one mind, one hop, less plumbing.
> instruction: verify with the c24 four checks + the CLAUDE.md v1-scope paragraph naming this as the fifth recorded convention change

## Audience

- Ori (the operator of this rig) + the mesh agents that dispatch colleague (ask-colleague, culture peers) + colleague itself reading its CLAUDE.md
  - instruction: check the CLAUDE.md architecture bullets + docs/features/ name the single-agent default and the opt-in

## Before → After

- Before: Today a lobes-armed rig auto-resolves senses (gemma-4-12B via proxy) and would auto-resolve muse (Gemma-31B) when ready; the senses presence LOOP is the default rung, the front door answers non-repo turns, and `COLLEAGUE_PRESENCE`=off only stops the loop — the front door still dials senses; only --cortex-only per invocation gives one-mind behaviour (scope s2/s3)
  - instruction: cite scope entries s2/s3 (config.py l.3420-3441, session.py l.2163) in the spec's before-state
- After: A bare colleague session/work/talk on a lobes-armed rig resolves exactly ONE served model (cortex=Qwen3.8) and dials nothing else: no senses seat, no presence loop, no front door, no muse discovery; the operator's mid-run words park onto the next tool-call boundary and cortex answers in its own turn; the artifact is byte-identical to today's UNARMED (senses never resolved) artifact — NOT to a --cortex-only artifact, which records SensesBlock(mode=cortex-only) when senses was resolved (session.py l.3290)
  - instruction: `COLLEAGUE_DUMP_REQUEST`=1 colleague session on this rig: every request model id == the cortex model; artifact has no senses key at all; diff equals a pre-arc UNARMED artifact (not --cortex-only, which records mode=cortex-only when senses was resolved)

## Why it matters

- Complexity is a problem (doctrine 2026-08-20: solo cortex 100% vs three-tier 0%, failures in the seams) and Qwen3.8 is now fast at the default effort (#424: off 24s); every extra seat/proxy/loop is a failure surface with no measured benefit — one model, one agent, one hop by default
  - instruction: link the doctrine memory + docs/evidence/2026-08-22-per-seat-thinking-effort-416-results.md in the spec's why section

## Requirements

- cortex-only is the DEFAULT-EQUIVALENT: EngineConfig.resolve() no longer fills senses from lobes discovery (config.py `_senses_lobes_fallback`) unless the operator explicitly opts in (explicit `COLLEAGUE_SENSES_`\*/config.json senses section); with no declaration config.senses is None on every front — the existing byte-identical cortex-only floor
  - instruction: add tests: lobes-armed + no declaration → senses None; lobes-armed + `COLLEAGUE_SENSES_MODEL`=x → senses resolved
  - honesty: With no senses declaration, EngineConfig.resolve() on a gateway that advertises senses yields config.senses is None; an explicit declaration (env/config.json) still resolves it — pinned by a test in tests/`test_config_senses.py` (discovery no longer auto-fills)
- Default = Qwen-direct: no senses presence loop (`senses_loop.py`/`presence_engine.py`), NO front door (frontdoor.py / `run_senses_frontdoor` — retired from the default path on session/talk/appserver), no senses streaming/narration/clarify; the operator speaks only with the main agent (cortex), whose reply is the task answer
  - instruction: tests/`test_session_frontdoor.py` gains a default-path case asserting `run_frontdoor` is never called; live: piped session asks 'what model are you running on?' and the answer comes from the cortex model id
  - honesty: session/talk/work/appserver take no senses code path when config.senses is None — the front door classifier is not consulted, no SensesRecord lands on the artifact, and the session's non-repo turn ('what model are you?') is answered by cortex itself
- muse is no longer a discovered Gemma seat: the muse→deepthink discovery rung (config.py `_deepthink_lobes_fallback`) is disarmed by default; 'muse' becomes a CONFIGURATION of the same cortex model/agent — xhigh effort + temperature 0.4 + its own prompt — expressible in config (no prompt/temperature tuning lands in this arc)
  - instruction: tests/`test_config_lobes_deepthink.py`: muse-ready fixture → deepthink None by default; explicit same-model deepthink with effort+temperature → request dump shows `chat_template_kwargs` `reasoning_effort`=xhigh and temperature=0.4
  - honesty: With lobes armed and muse advertised ready:true and no `COLLEAGUE_DEEPTHINK_`\* declaration, config.deepthink is None; an explicit deepthink declaration pointing at the cortex model with `reasoning_effort` xhigh + temperature 0.4 resolves and is honoured on the wire
- CLAUDE.md + docs/features/{presence-default-everywhere,cortex-senses,talking-to-one,talking-to-one-teammate,session-streaming-voice,realtime-speech,senses-live-presence}.md record the default flip as the FIFTH recorded v0→v1 convention change (increment (4) presence-default-everywhere superseded: senses is opt-in, not default) — never a silent breach
  - instruction: grep -rn 'default on every front\|default state on every front\|presence default' CLAUDE.md docs/features/ returns only superseded-marked lines
  - honesty: CLAUDE.md v1 scope paragraph lists this as the FIFTH recorded v0→v1 convention change and increment (4) presence-default-everywhere is marked superseded; every named docs/features/ file states senses is opt-in — checked by grep, no file still says 'default on every front'
- Test suite: the ~55 senses/presence/frontdoor/talk/realtime test files keep passing with senses EXPLICITLY armed in their fixtures; the byte-identical-when-unarmed pins (tests/`test_presence_pin_breaks.py`, `test_session_`\*`_byteident.py`) become the default path; #422's three env-dependent lobes-unarmed tests get fixed in the same move
  - instruction: run it here, on this checkout, not only in CI
  - honesty: uv run pytest -n auto is green on a checkout whose .colleague/config.json is {"lobes": …} (this machine), including the three #422 tests
- colleague config show / doctor / lobes show state plainly which Gemma-served roles the gateway advertises but colleague is NOT consuming (senses, muse), so the operator can see the retirement rather than infer it
  - instruction: golden-output test on a fake gateway payload advertising cortex+senses+muse
  - honesty: colleague config show and colleague lobes show each print one line per advertised role colleague does not consume by default (senses, muse), naming the served model, so the retirement is visible
- Design principle recorded in CLAUDE.md: 1 colleague instance = 1 model = 1 agent; every seat colleague runs is the same served model under a per-seat effort/temperature/prompt configuration; the instance can spawn ITSELF as subagents (the existing subagents/roles surface, same model); there is no second mind in the default path
  - instruction: extend tests/`test_no_brain_vocab.py` or add tests/`test_single_model_default.py`
  - honesty: Every seat colleague builds in the default path (main, deepthink-if-declared, subagent children, evaluator/design seats) resolves to the SAME served model id; an AST/text guard test asserts no default-path code references a second role name for model resolution
- Talking to the main agent while it works PARKS the operator message onto the next possible window (the next tool-call boundary — the existing flight guidance seam, colleague/flight.py) and cortex answers it directly in its own turn; no relay seat, no ack lane
  - instruction: tests/`test_session_talk_lane.py` default-path case + a live session transcript in docs/live-testing.md
  - honesty: A message typed during a running session is delivered verbatim to cortex at its next tool-call boundary via the existing flight guidance seam and cortex's next assistant turn addresses it — no ack is synthesized by any other seat
- Control reasoning effort from the session/TUI: a new /effort slash command — with no argument it shows the current effort per seat/role (the resolved default for the current agent/role, from colleague/effort.py `resolve_effort` + the v3 table), and /effort <rung> \[seat\] switches it for the session (same ladder off|low|medium|high|xhigh + default); the CLI flags behave the same (no value → print the table, don't refuse)
  - instruction: tests/`test_session_effort.py` golden table + request-dump assertion; live row in docs/live-testing.md
  - honesty: In a session with lobes armed: /effort prints one line per seat with its resolved rung (cortex medium, deepthink xhigh, design xhigh, evaluator medium, children per role table) and /effort low cortex changes ONLY that seat's next requests (verified with `COLLEAGUE_DUMP_REQUEST`=1); /effort default restores the kill-switch wire
- /model with no argument lists the SERVED options (the gateway's /v1/models roster via lobes.`fetch_served_model_ids` + role names from /capabilities — e.g. current cortex Qwen3.8 and gemma) and marks the current default per seat/agent/role; /model <id|role> \[seat\] switches for the session so the operator can leave the single-model default by explicit choice, in every mode; the CLI --model with no value prints the same list instead of refusing
  - instruction: tests/`test_session_model.py` with a fake gateway; live: /model on this rig shows unsloth/Qwen3.8-27B-NVFP4 and unsloth/gemma-4-12B-it-qat-w4a16
  - honesty: With the gateway serving cortex+senses: /model (no arg) lists every served id from /v1/models (Bearer attached) plus role→id lines, marking the current default; /model <id> switches the main seat and the next request's model field equals it; an unreachable roster degrades to 'roster unavailable' + the current default, never a stack trace
- The session's mid-run talk lane must deliver a typed/voiced line to cortex when senses is unarmed: today session.py `_talk_senses` returns on pair is None (the line is silently dropped) — the default path must instead write it verbatim as flight guidance (the seam colleague talk already uses for its raw-guide degrade) and render an honest 'parked for cortex at the next boundary' line
  - instruction: tests/`test_session_talk_lane.py`: unarmed session + typed line → a flight guidance record with the verbatim text, no senses call; live transcript in docs/live-testing.md
  - honesty: Unarmed session + a typed mid-run line → exactly one flight guidance record carrying the verbatim text, zero senses requests (`COLLEAGUE_DUMP_REQUEST`=1), and cortex's next turn visibly addresses it
- /model <id> re-derives the seat's context budget from the served role's advertised window (lobes /capabilities context, e.g. gemma 32768 vs Qwen 1048576) and keeps the effort ladder's 400-retry-once in force — a switch never leaves a 200000-token budget pointed at a 32K model; the switch line prints the new budget
  - instruction: session.py `_act_model` today sets only s.config.model (l.~3640); test: /model gemma → config.`context_budget_tokens` derived via `_senses_budget_from_window`-style ratio or the role window; request dump shows the new model id
  - honesty: /model <gemma-id> in a session prints the new model AND the re-derived budget; the next request's model field == the id and the windowed history stays under the role's advertised window
- Rollback is one declaration: `COLLEAGUE_SENSES_MODEL`=<served id> (or config.json senses.model) re-arms the full senses lane exactly as today — `base_url`/`api_key` inherit the main endpoint (gateway routes by model id), presence rung resolves to loop; documented in docs/features/cortex-senses.md as THE opt-in, with the same-origin key rule unchanged
  - instruction: test: lobes-armed + `COLLEAGUE_SENSES_MODEL`=gemma-id → config.senses resolved with `base_url`==main `base_url`; live: one env var brings the old behaviour back
  - honesty: `COLLEAGUE_SENSES_MODEL`=<served id> alone (no `base_url`/`api_key`) re-arms senses on the gateway origin and the pre-arc senses tests pass under that env
- /effort shows what each seat ACTUALLY sends via effort.py `effort_of`(config) (presence-wins rule l.211), never a re-derivation from `SEAT_TABLE`; a /effort switch mutates s.config.`reasoning_effort` / `reasoning_effort_seats`\[seat\] (picked up live by the `reasoning_effort_effective` property, config.py l.3247) and the confirmation line states it is session-only (not persisted to config.json); bad rungs go through effort.`validate_effort` and surface as the slash dispatcher's ValueError style
  - instruction: tests/`test_session_effort.py`: golden table from `effort_of` per seat + switch → next request's `chat_template_kwargs`; catalog/help drift tests (tests/`test_session_autocomplete.py`:151-156, `test_session_cockpit.py`:554-605) updated for the new SlashSpec
  - honesty: In a session, /effort (no arg) prints per-seat lines equal to `effort_of`(seat config) and /effort xhigh cortex is visible on the very next request's `chat_template_kwargs` — and absent from config.json afterwards
- /model (no arg) distinguishes `fetch_served_model_ids` → None (roster unreachable/401: print an honest 'roster unavailable' + current seats) from \[\] (gateway serving nothing); role→model lines come from lobes.`resolve_roles` (no `api_key` needed) and the acting seat from s.config.model; lobes unarmed → 'lobes not armed' + current model, never a crash
  - instruction: precedent call shape config.py l.1870; tests with a fake gateway for None / \[\] / unarmed
  - honesty: With the gateway down, /model prints 'roster unavailable' + the current model and the session continues; with the gateway up it lists every /v1/models id (Bearer attached) — both pinned by tests

## Honesty conditions

- A bare colleague run on this lobes-armed rig sends requests to exactly one model id (the cortex model) — verified by `COLLEAGUE_DUMP_REQUEST`=1, not by reading config
- No change lands in lobes-cli or ~/git/lobes.1 as part of this arc; the gateway still advertises senses+muse after the arc and colleague ignores them by default
- The voice/realtime modules are not modified beyond the guard that makes them no-ops when config.senses is None; /voice and --voice on the default path print an honest 'senses not armed' line instead of failing
- Measured, not assumed: the c24 live row includes wall time for a session ack/answer at cortex medium vs the pre-arc senses ack (22 tok off-effort) — if cortex-direct is > 2x slower on the ack, the assumption is recorded as false in the evidence file, the arc still ships
- CLAUDE.md's architecture bullets read correctly to a mesh agent that has never seen senses: the default is described first, the opt-in second
- The default-path artifact equals a pre-arc UNARMED artifact field-for-field (no senses key at all — contract.py l.1853 omit-when-None), pinned by tests/`test_senses_all_engines.py` + `test_presence_pin_breaks.py` becoming the default-path pin; an explicit --cortex-only with senses opted-in still records mode=cortex-only
- Scope entries s2/s3 cite config.py l.3420-3441 + session.py l.2163 as read on 2026-08-22 at fb81640
- The doctrine and #424 numbers are cited with their files (memory complexity-is-a-problem-doctrine; docs/evidence/2026-08-22-per-seat-thinking-effort-416-results.md), not restated from memory
- All four checks are run on this rig and recorded as a docs/live-testing.md row before the PR merges; a failed check is recorded as failed
- uv run colleague doctor and the default livecheck suite pass with senses unresolved on this rig (SKIP, not FAIL, for the senses checks)

## Success signals

- On this rig: (1) a bare session with `COLLEAGUE_DUMP_REQUEST`=1 shows 0 requests to any non-cortex model id; (2) pytest -n auto green with the ~55 senses/presence test files still exercising the opt-in path; (3) the #422 three lobes-unarmed tests pass on a checkout whose .colleague/config.json arms lobes; (4) colleague config show prints the advertised-but-not-consumed roles (senses, muse)
  - instruction: run the four checks verbatim and paste results into docs/live-testing.md as a new row

## Scope / boundaries

- The lobes gateway keeps serving/advertising senses and muse (lobes-cli/lobes/roles.py: ADDING A ROLE IS EFFECTIVELY IRREVERSIBLE; `ROLE_BACKEND` senses→multimodal backend) — the retirement is colleague-side consumption, not a lobes-cli role removal; rig-side compose changes (lobes.1) are a separate operator action, not part of this arc
  - instruction: git log on lobes-cli shows no commit from this arc; /capabilities still lists senses
- stt/tts + \[voice\]/realtime lanes are dormant in this arc (they are senses consumers today); later they become a colleague feature independent of the served model (or ride the realtime API where the model is irrelevant to colleague) — no re-plumb onto cortex now
  - instruction: grep voice.py/realtime.py diff in the PR: only None-guards + the honest 'senses not armed' line; no cortex plumbing

## Non-goals

- No multi-backend router / task→model routing is introduced (v1 scope line); removing a seat is a subtraction on the fixed enumerated surface, not a policy
- The senses/presence code is NOT deleted in this arc — it moves behind an opt-in (so the eleven increments' docs and tests remain truthful); deletion is a separate re-spec once the opt-in has sat unused
- TAE (#397) and model-bound agents (#411) keep their independent opt-ins and authority contracts; #411's AgentProfile is the natural home for the '1 model = 1 agent' principle (Talker/Thinker/Coder all resolve to the SAME cortex model by recorded fallback when senses is unresolved — agents/profile.py `fallback_from_role`) — no authority change here
- The 'second main agent you can talk to, that can trigger subagents' (turning a senses-like agent back ON) is a LATER opt-in arc, not built here; this arc only makes the single-agent default true and the off state clean

## Assumptions

- Qwen3.8-27B cortex is fast enough at the default seat effort (medium; senses row was off) to carry ack/narration itself — the #424 evidence shows off=24s/xhigh=88s/medium=129s on a small brief and the Talker ack cost 22–141 tok; the complexity doctrine (2026-08-20: solo cortex 100% vs three-tier 0%) is the motivating evidence
- Counter-evidence checked: nothing in the default path needs a second model — media goes to the main model, stt/tts are separate roles, and no livecheck/oilcheck gates on senses being present (`run_cortex_senses_check` SKIPs); the only lost capability is the 22-token gemma ack, replaced by parking + cortex's own reply

## Scope exploration

- `s1` — `lobes gateway /capabilities (live, localhost:8001) + colleague lobes show`: Gemma is exactly two roles: senses=unsloth/gemma-4-12B-it-qat-w4a16 (proxied, `hosted_by` orin, ready) and muse=nvidia/Gemma-4-31B-IT-NVFP4 (ready:false). cortex is already Qwen3.8-27B; stt/tts are parakeet/chatterbox. So 'turn off Gemma' == stop consuming senses+muse
  - seeds: `c3`, `c4`, `c8`
- `s2` — `colleague/config.py resolve() senses block (l.3420-3441) + _senses_lobes_fallback + _resolve_senses`: precedence env > config.json > lobes discovery > absent; discovery ALWAYS fills senses when the gateway advertises it — there is no 'armed lobes, no senses' knob; explicit senses is present iff model is non-empty, so an empty model cannot express 'off' (it falls through to discovery)
  - seeds: `c2`, `c3`
- `s3` — `colleague/config.py resolve_presence_rung + cli/_commands/_presence_sink.py + session.py l.2120/2163`: `COLLEAGUE_PRESENCE`=off / config.json presence:off turn off the presence LOOP only; session.`_run_frontdoor` still dials senses when config.senses is set and not `cortex_only` — so presence:off is not Qwen-direct. --cortex-only (work.py l.2728, session.py l.3931) is the only full disarm, per-invocation
  - seeds: `c2`, `c3`
- `s4` — `colleague/senses_loop.py (710 lines) + presence_engine.py + senses_moves.py`: the 'loop to remove' = senses' bounded coordination loop (prompted-JSON moves over tools-off completions, default rung 'loop' when armed); it becomes dormant when config.senses is None — code stays, path disappears
  - seeds: `c3`, `c11`
- `s5` — `colleague/config.py _deepthink_lobes_fallback (muse→deepthink rung, l.992-1025)`: muse (Gemma-4-31B) would fill deepthink when ready; today ready:false so nothing dials it, but a rig change would silently re-arm a Gemma seat — the default must not discover it either
  - seeds: `c4`
- `s6` — `CLAUDE.md v1 scope line: increments (2)(3)(4)(5)(7) + 'presence default on all fronts, closes #300'`: senses-by-default is a recorded sanctioned increment; flipping it is a recorded convention change (the fifth), documented alongside the four already listed — not a silent breach, not a deletion
  - seeds: `c5`, `c11`
- `s7` — `tests/ (55 files matching senses|presence|frontdoor|talk|realtime|voice|lobes; test_presence_pin_breaks.py; #422's 3 env-dependent tests)`: tests arm senses via fixtures/env so they survive a default flip; the byte-identical-unarmed pins become the default path; #422 fixes fold in
  - seeds: `c6`
- `s8` — `lobes-cli/lobes/roles.py ROLES/ROLE_BACKEND + ~/git/lobes.1 compose files (no gemma literal; senses→multimodal backend)`: role removal is declared irreversible upstream; rig-side serving is an operator action outside colleague — the arc is consumption-side
  - seeds: `c8`
- `s9` — `colleague/agents/profile.py fallback_from_role + tae_control.py senses seat`: \#411 already records a cortex fallback when senses role is missing; TAE/agents are independent opt-ins whose behaviour with senses absent is already specified — out of this arc
  - seeds: `c12`
- `s10` — `colleague/config.py voice/realtime fallbacks + realtime.py (ears-only senses lane) + voice.py`: voice/realtime are senses consumers (tts speaks senses replies, realtime feeds the senses talk lane); with senses off by default they go dormant unless senses is re-armed — no re-plumb onto cortex here
  - seeds: `c9`
- `s11` — `issue #424 evidence + memory complexity-is-a-problem-doctrine (2026-08-20)`: off 24s / xhigh 88s / medium 129s, Talker ack 22 vs 141 tok; solo cortex 100% vs three-tier 0% — cortex-direct is the measured simpler topology
  - seeds: `c13`
- `s12` — `colleague/cli/_commands/{config,lobes,doctor} show surfaces`: they print resolved senses/lobes state but have no 'advertised-but-not-consumed' line; needed so the retirement is visible
  - seeds: `c7`
- `s13` — `ask-colleague explore 01a3550cae28 (colleague as explorer, 17 steps, graded 4): session.py/talk.py/work.py/_presence_sink.py/appserver.py/livecheck.py/frontdoor.py guard map`: every senses call site in the seven fronts is guarded by config.senses is None or `resolve_presence_rung`()=='off'; NONE dials senses when unarmed — the only behavioural change of the flip is the lobes-discovery fallback at config.py l.3438-3440 (+ the muse twin). Verified by re-reading session.py l.3205-3292 and appserver.py l.956-1083
  - seeds: `c2`, `c3`
- `s14` — `colleague explore's flagged 'surprise' at session.py l.3214 + appserver.py l.975 (SensesBlock(mode=split) init), re-read by me`: FALSE POSITIVE: `_finalize_split_run` runs only when `senses_mode`=='split' and appserver's `_speakback_and_finalize` only when `senses_active`; BUT session.py l.3290 records SensesBlock(mode='cortex-only') when senses was resolved and bypassed — so the default path (never resolved) ≠ --cortex-only artifact; c21/h18 corrected
  - seeds: `c21`
- `s15` — `tests named by the explore: test_config_senses.py (l.178-421 'senses is not None' ladder), test_config_lobes.py (l.212-448 discovery arms SensesConfig), test_presence_config.py (:91/:102 armed→loop), test_senses_all_engines.py, test_config_evaluation_mode.py (('front','senses') seat, :520)`: the discovery-arming pins in `test_config_lobes.py` + `test_presence_config.py` flip meaning (armed by declaration, not discovery); `test_config_evaluation_mode.py`'s TAE front seat must still resolve senses BY ROLE when TAE is opted in — TAE keeps its own resolution (c12)
  - seeds: `c6`, `c12`
- `s16` — `challenge pass / failure-mode lens: session.py _talk_senses (l.~2790) + _handle_talk_input + _dispatch_talk_line`: unarmed session returns on pair is None — mid-run operator lines are dropped, not parked; c15 needs NEW work on the session front (talk.py verb already degrades to raw guide)
  - seeds: `c28`, `c15`
- `s17` — `challenge pass / adjacent-systems lens: session.py _act_model + config context_budget_tokens (l.1170) + lobes RoleInfo.context`: `_act_model` mutates only the model id; budget/effort stay at the previous seat's values — a gemma switch would overrun its 32K window; seeded c29
  - seeds: `c29`, `c26`
- `s18` — `challenge pass / rollback lens: config.py _resolve_senses (explicit declaration inherits main base_url/api_key) + _same_origin`: explicit declaration already works with only a model id on the gateway origin — the opt-in/rollback is a one-liner; seeded c30
  - seeds: `c30`, `c2`
- `s19` — `challenge pass / adjacent-systems lens: colleague/media.py + SensesConfig.multimodal (config.py l.2745)`: media.py has no senses reference — images/audio ride to the main model; SensesConfig.multimodal only arms a senses-side bridge; clean pass for the default flip (cortex Qwen3.8 advertises image/video understanding)
  - seeds: `c3`
- `s20` — `challenge pass / lifecycle lens: colleague/continuation.py + chain.py (no senses reads) ; configs in the wild (~/git/*/.colleague/config.json, ~/.colleague/config.json: none carry presence/senses/deepthink keys)`: continuation rehydrates without reading senses blocks — a pre-flip artifact continues under the new default; no operator config on this machine relies on the discovery rung; clean pass
  - seeds: `c2`, `c6`
- `s21` — `challenge pass / overlooked-actors lens: .claude/skills/ask-colleague/scripts/ask-colleague.sh (--seat-effort accepts senses), background.py, resident/appserver.py senses_active gate, doctor.py (no senses ref)`: ask-colleague only names senses in --seat-effort validation (harmless when unarmed); appserver gates every senses beat on `senses_active`; background/doctor untouched; the #424 '70 stale wrapper copies' broadcast is separate
  - seeds: `c3`, `c7`
- `s22` — `challenge pass / security + concurrency lens: the flip removes a seat and a proxied hop (orin) — no new key, thread, subprocess, or socket; the OwnedInputLine reader thread stays the session's only thread`: clean pass; residual: the talk-lane guidance write (c28) must stay file-based (flight.py), never a new thread
- `s23` — `challenge pass / counter-evidence lens: livecheck.py run_cortex_senses_check (SKIP when unarmed), media.py, oilcheck/`: no gate in the default path requires senses; seeded c31
  - seeds: `c31`
- `s24` — `ask-colleague explore dfb91549b5c5 (colleague as explorer, 36 steps, graded 4): lobes.py fetch_served_model_ids l.501-557 + config.py resolve_lobes_gateway_url l.801 / l.1870 precedent; config.py EngineConfig reasoning_effort(_seats) l.3023 + reasoning_effort_effective property l.3247; effort.py effort_of l.193-213 / validate_effort l.95; session.py SlashSpec l.3383, _CONFIG_ACTIONS l.3745, _act_model l.3653, _slash l.1618, _resolve_view l.3758; tests/test_session_autocomplete.py:151-156 + test_session_cockpit.py:554-605`: every seam for c25/c26 exists; runtime mutation of s.config is live via the property; None-vs-\[\] and catalog/help drift pins are the traps; seeded c32/c33
  - seeds: `c32`, `c33`, `c25`, `c26`
- `s25` — `challenge pass / colleague-reviewer lens, attempt 1 (review 127ea28dfe05 over main...HEAD)`: STALLED: step 4 entered a silent model turn, heartbeat stopped for 15 min (the #415 stall shape — the diff carried the large .devague frame JSON); SIGTERM'd, no findings; attempt 2 re-dispatched reading ONLY docs/specs/2026-08-22-qwen-direct-no-gemma.md at --effort low, max-steps 12
- `s26` — `challenge pass / colleague-reviewer lens, attempt 2 (daee8a957fe9: spec-only read, --effort low, max-steps 12)`: STALLED IDENTICALLY: step 4 entered a silent model turn, heartbeats stopped, `COLLEAGUE_TIMEOUT`=300 did not cut it (445s+); killed. Two-for-two on the same step suggests the spec file's fourth 120-line chunk (the long Scope-exploration section) triggers a pathological generation at low effort — a rig/loop observation for #415/#409, not a spec finding. The reviewer lens is therefore UNAVAILABLE for this pass; the explorer lens (s13/s24) and my own six lenses (s16–s23) stand

## Decisions

- q1: cortex-only is the default-equivalent. Each model is an agent; 1 colleague instance = 1 model = 1 agent that can spawn itself as subagents. Turning senses on later = adding a second main agent we can talk to that can trigger subagents (not this arc).
- q2: no more front door — we speak only with the main agent; speaking to it parks the message on the next possible window and cortex answers directly. voice/realtime dormant for now; later a colleague feature regardless of model (or the realtime API, model irrelevant to colleague).
- q3: muse = cortex at xhigh effort with temperature 0.4 and its own prompts — a configuration, not a Gemma seat; no adjustment now but the config allows it. colleague is the explorer, including during scope/think/challenge.
- Operator intent (2026-08-22): the single-model default is the default, but /model and /effort must show the options and the current default for the current agent/role and let the operator change them — in all modes, from TUI/TAUI and CLI; an explicit choice is the only way a second model (e.g. gemma) gets dialled.

## Hard questions

- Is switching the MAIN seat to gemma via /model a routing policy? No — it is an explicit operator choice per session, never automatic; record that in the v1-scope paragraph alongside the increment.

## Open parks

- [unknown_nonblocking] Whether the dormant senses/presence code (`senses_loop`, `presence_engine`, frontdoor, `senses_stream`, realtime, voice ~3k lines) should be DELETED in a later arc once the opt-in sits unused — a separate re-spec; not decidable until the opt-in has lived a while
- [unknown_nonblocking] Live measurement: cortex-direct session latency for ack/narration with senses off on this rig (Qwen3.8, medium) vs today's senses:off-effort Talker (22 tok ack) — #421's pre-registered arm could add a session-shaped brief
- [unknown_nonblocking] Residual surprise risk: a mesh peer or an older vendored ask-colleague.sh might have learned to expect senses: lines in piped session output (the one recorded break of increment (4)); default-off removes them — any consumer parsing 'senses:' lines is unknown
- [unknown_nonblocking] Residual: no independent (colleague) review of the exported spec landed — both attempts stalled at step 4; the plan leg should open with an ask-colleague review of the PLAN (smaller surface) instead, and the stall itself should be recorded under #415 (silent turn not cut by the 300s timeout)
