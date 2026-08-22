# Build Plan — qwen-direct-no-gemma

slug: `qwen-direct-no-gemma` · status: `exported` · from frame: `qwen-direct-no-gemma`

> Colleague works Qwen-direct in every mode: Gemma is retired from the served roles colleague consumes — senses is no longer resolved or dialled by default, the senses presence loop is gone from the default path, cortex (Qwen3.8) answers the operator directly; one mind, one hop, less plumbing.

## Tasks

### t1 — t1 config: senses + muse lobes-discovery OFF by default; explicit declaration is the opt-in

- instruction: ONLY colleague/config.py + the four test files. In EngineConfig.resolve(): the senses block near l.3437-3441 calls `_senses_lobes_fallback`(...) when `_resolve_senses` returned None — REMOVE that fallback call from the default path (keep the function; it is still reachable ONLY when an explicit opt-in sentinel config.json senses: {"model": "lobes"} or `COLLEAGUE_SENSES_MODEL`=lobes asks for discovery — implement that sentinel: model == 'lobes' → use `_senses_lobes_fallback`). Do the SAME for the muse→deepthink rung (`_deepthink_lobes_fallback` call near l.3415-3425; sentinel `COLLEAGUE_DEEPTHINK_MODEL`=lobes). Update the docstrings of both fallbacks to say 'opt-in only'. Keep every other rung (stt/tts/voice/realtime/worker/agents) untouched. Use sed -n to read ONLY the cited line ranges — config.py is 3600+ lines, never read it whole.
- covers: c2, h2, c4, h4, c30, h24
- acceptance:
  - EngineConfig.resolve() with lobes armed (fake gateway advertising cortex+senses+muse ready) and no `COLLEAGUE_SENSES_`\*/`COLLEAGUE_DEEPTHINK_`\* declaration yields config.senses is None and config.deepthink is None
  - `COLLEAGUE_SENSES_MODEL`=<id> alone (no `base_url`/`api_key`) resolves senses with `base_url` == main `base_url` and `api_key` == main key; the same for an explicit deepthink pointing at the cortex model with `reasoning_effort`=xhigh
  - tests/`test_config_senses.py` + tests/`test_config_lobes.py` + tests/`test_config_lobes_deepthink.py` + tests/`test_presence_config.py` updated: discovery-arming pins flip to 'armed only by declaration'; uv run pytest tests/`test_config_senses.py` tests/`test_config_lobes.py` tests/`test_config_lobes_deepthink.py` tests/`test_presence_config.py` -q green

### t2 — t2 session: unarmed talk lane PARKS the operator line to cortex via flight guidance (no front door on the default path)

- instruction: ONLY session.py (the `_talk_senses` method near l.2790-2840 and, if needed, a tiny helper next to it) + the two test files. Find how colleague/cli/`_commands`/talk.py writes raw guidance when senses is unarmed (grep 'guide' in talk.py and colleague/flight.py) and reuse that exact call; the session already holds the flight id for the running work item (grep '`_flight`' in session.py). Read session.py ONLY by line range with sed -n; it is 4000+ lines.
- covers: c3, h3, c15, h11, c28, h22
- acceptance:
  - In colleague/cli/`_commands`/session.py `_talk_senses`: when `_senses_engine`() returns None the typed/voiced line is written VERBATIM as flight guidance (the same seam colleague talk's raw-guide degrade uses) and a line 'parked for cortex at the next boundary' is logged — no return-and-drop
  - tests/`test_session_talk_lane.py` gains a default-path case: config.senses None + typed mid-run line → exactly one guidance record with the verbatim text, zero senses calls; tests/`test_session_frontdoor.py` gains a default-path case asserting `run_frontdoor` is never called when config.senses is None
  - uv run pytest tests/`test_session_talk_lane.py` tests/`test_session_frontdoor.py` tests/`test_session_senses.py` -q green

### t3 — t3 session /model: no-arg lists served models + current per-seat default; switch re-derives context budget

- instruction: ONLY session.py (`_act_model` near l.3653, the SlashSpec entry near l.3446, `_HELP_TEXT`) + new tests/`test_session_model.py`. Precedent for the roster call: colleague/config.py l.1870; `resolve_lobes_gateway_url` is already imported in session.py (l.95). Budget derivation: reuse the ratio helper `_senses_budget_from_window` style or min(window, current) — state which in the confirmation line. Read by line range only.
- depends on: t2
- covers: c26, h20, c29, h23, c33, h26
- acceptance:
  - /model with no argument prints: every id from lobes.`fetch_served_model_ids`(gateway, `api_key`=s.config.`api_key`) (Bearer attached), one 'role → model' line per role from lobes.`resolve_roles`, and the current acting model marked; roster None → 'roster unavailable' + current model; lobes unarmed → 'lobes not armed' + current model; never raises
  - /model <id> sets s.config.model AND re-derives s.config.`context_budget_tokens` from the matching role's advertised context window when known (print 'model → X · budget N'); SlashSpec catalog + `_HELP_TEXT` updated so tests/`test_session_autocomplete.py` and tests/`test_session_cockpit.py` drift pins pass
  - tests/`test_session_model.py` (new) covers: listing with a fake roster, None roster, unarmed, switch + budget; uv run pytest tests/`test_session_model.py` tests/`test_session_autocomplete.py` tests/`test_session_cockpit.py` -q green

### t4 — t4 session /effort: show per-seat effort via `effort_of`, switch live (session-only), validated rungs

- instruction: ONLY session.py (new `_act_effort` beside `_act_model`, SlashSpec + `_HELP_TEXT` + `_CONFIG_ACTIONS` entries) + new tests/`test_session_effort.py`. colleague/effort.py is ~280 lines — read it whole; it has `SEAT_TABLE`/`ROLE_TABLE`/`validate_effort`/`resolve_effort`/`effort_of`. config.py l.3023 defines `reasoning_effort` + `reasoning_effort_seats`; l.3247 `reasoning_effort_effective` is a property (live).
- depends on: t3
- covers: c25, h19, c32, h25
- acceptance:
  - /effort (no arg) prints one line per seat (cortex, worker, deepthink, evaluator, senses, design + the acting role) using colleague.effort.`effort_of` / `resolve_effort` — what is actually sent, incl. 'unset' under the default kill-switch
  - /effort <rung> \[seat\] (default seat cortex) validates via effort.`validate_effort` (CliError → ValueError message for the slash dispatcher), mutates s.config.`reasoning_effort_seats`\[seat\] (or `reasoning_effort` for 'all'), prints 'effort <seat> → <rung> (session-only)'; the next request's `chat_template_kwargs` reflects it
  - tests/`test_session_effort.py` (new): golden no-arg table, switch + request-dump assertion via the mock engine's recorded config, bad rung error; catalog/help drift tests green

### t5 — t5 visibility: config show / lobes show / doctor print advertised-but-not-consumed roles

- instruction: ONLY colleague/cli/`_commands`/config.py, colleague/cli/`_commands`/lobes.py, colleague/cli/`_commands`/doctor.py + tests. The roles payload comes from colleague/lobes.py `resolve_roles` (LobesRoles has .senses/.muse RoleInfo with .model). Keep existing output lines byte-identical; ADD lines only.
- covers: c7, h7
- acceptance:
  - colleague config show and colleague lobes show each print one line per gateway-advertised role colleague does not consume by default (senses, muse) naming the served model, e.g. 'not consumed (opt-in): senses → unsloth/gemma-4-12B-it-qat-w4a16'; doctor's lobes/provider group mentions it too
  - golden-output tests on a fake /capabilities payload advertising cortex+senses+muse in tests/`test_cli_lobes.py` + tests/`test_config_lobes.py` (or a new tests/`test_cli_not_consumed.py`); --json carries a `not_consumed` list; uv run pytest on those files green

### t6 — t6 CLI flags: --model / --effort with no value print the list/table instead of refusing

- instruction: ONLY colleague/cli/`_commands`/work.py (+ the rendered-flag table near l.2294 / `add_argument` near l.2697) and the new test file. Put the two list/table renderers in a NEW small module colleague/cli/`_commands`/`_listing.py` so t3/t4 (session) can import them later — keep them pure (take roster/roles/config, return text + dict).
- covers: c25, c26
- acceptance:
  - colleague work --model (no value) prints the served-model list (same content as session /model no-arg) and exits 0 without running; --effort (no value) prints the per-seat effort table (same as session /effort no-arg); --json shapes for both
  - tests in tests/`test_cli_flags_listing.py` (new) with a fake gateway; existing work/session flag tests green

### t7 — t7 voice/realtime: honest 'senses not armed' line on the default path

- instruction: ONLY session.py voice/realtime slash handlers (grep '/voice', '`_start_realtime`', '`_speak_only`' by line range) + voice.py/realtime.py guards + the two tests.
- depends on: t4
- covers: c9, h9
- acceptance:
  - /voice, --voice, /speak and the realtime lane on a session whose config.senses is None print one honest line 'senses not armed — voice/realtime dormant (opt in with `COLLEAGUE_SENSES_MODEL`)' and never raise; colleague/voice.py and colleague/realtime.py change ONLY by None-guards (no cortex plumbing)
  - tests/`test_session_voice.py` + tests/`test_session_realtime_byteident.py` default-path cases green; git diff of voice.py/realtime.py shows guards only

### t8 — t8 docs: CLAUDE.md fifth convention change + 1-model-1-agent principle; feature docs mark senses opt-in

- instruction: Docs only. CLAUDE.md is ~330 lines: edit the architecture list and the v1-scope paragraph with targeted sed/Edit, do not rewrite. Cite docs/specs/2026-08-22-qwen-direct-no-gemma.md and the memory doctrine by name. Keep every existing fact (trim discipline c17/h4): mark superseded, never delete.
- covers: c5, h5, c8, h8, c14, c20, h16, c22, h13, c23, h14
- acceptance:
  - CLAUDE.md: the v1-scope paragraph lists the FIFTH recorded v0→v1 convention change (senses/muse discovery opt-in; increment (4) presence-default-everywhere superseded), a new architecture bullet '1 colleague instance = 1 model = 1 agent' placed BEFORE the senses bullets, the hard-question note that /model switching is explicit operator choice not routing, and the lobes boundary (lobes-cli untouched, still advertises)
  - docs/features/{presence-default-everywhere,cortex-senses,talking-to-one,talking-to-one-teammate,session-streaming-voice,realtime-speech,senses-live-presence,deepthink}.md each open with an 'Opt-in since v1.63 (qwen-direct)' note citing `COLLEAGUE_SENSES_MODEL` / the lobes sentinel; grep -rn 'default on every front\|default state on every front' CLAUDE.md docs/features/ returns only superseded-marked lines; new docs/features/qwen-direct.md links the spec + cites s2/s3 + the doctrine/evidence files
  - markdownlint-cli2 on the touched files clean

### t9 — t9 tests: single-model default guard, #422 hermetic lobes tests, unarmed artifact = default path

- instruction: Tests only (plus conftest if a fixture is the cleanest #422 fix). tests/conftest.py already scrubs `COLLEAGUE_`\* and isolates `COLLEAGUE_HOME` — extend it to point the repo-level config loader at `tmp_path`. Run the three #422 tests locally first to see them fail on this checkout.
- depends on: t1
- covers: c6, h6, c14, h10, c21, h18
- acceptance:
  - tests/`test_single_model_default.py` (new): with lobes armed (fake gateway cortex+senses+muse) and no declarations, every seat EngineConfig.resolve() builds (main, deepthink, subagent child configs via roles, evaluator/design seats) reports the SAME model id; an AST/text guard asserts no default-path code resolves a model from a role name other than cortex
  - \#422 fixed: tests/`test_cli_lobes.py`::`test_lobes_show_unarmed_`\* and tests/`test_config_lobes.py`::`test_config_show_no_lobes_key_when_unarmed` pass on a checkout whose .colleague/config.json arms lobes (monkeypatch the repo-config loader or chdir to a tmp repo)
  - tests/`test_presence_pin_breaks.py` + tests/`test_senses_all_engines.py`: the default-path artifact (no senses key) is pinned as the default; uv run pytest -n auto fully green on this checkout

### t10 — t10 live proof: the four c24 checks on this rig + evidence row

- instruction: Run on this rig (lobes at localhost:8001, cortex unsloth/Qwen3.8-27B-NVFP4). Use a throwaway repo for the session run; unset `CONVERTIBLE_MODEL` first. This task is executed by the integrator (needs the live rig + piped session), not a colleague child.
- depends on: t1, t2, t3, t4, t5, t6, t7, t8, t9
- covers: c1, h1, c24, h15
- acceptance:
  - docs/live-testing.md gains row 40 with: (1) `COLLEAGUE_DUMP_REQUEST`=1 piped session → 0 requests to non-cortex ids, (2) uv run pytest -n auto green on this checkout, (3) the three #422 tests green here, (4) colleague config show prints the not-consumed lines; plus wall time of a session ack/answer at cortex medium vs the pre-arc 22-tok senses ack (h17 measurement, recorded even if unfavourable)
  - docs/evidence/2026-08-22-qwen-direct-no-gemma-results.md holds the raw outputs; a failed check is recorded as failed

### t11 — t11 release: version bump minor + CHANGELOG entry

- instruction: Use the version-bump skill (minor). Do it last, after all merges, on the integration branch.
- depends on: t10
- acceptance:
  - pyproject.toml + colleague/`__init__.py` at 1.63.0; CHANGELOG.md top entry names the fifth convention change, /model + /effort, the opt-in sentinel, and links the spec + plan

## Risks

- [unknown_nonblocking] v4: no independent colleague review of the SPEC landed (two stalls); mitigation — colleague reviews the PLAN (this artifact) before wave 1 and each merged wave's diff via ask-colleague review
- [unknown_nonblocking] session.py (4000+ lines) and config.py (3600+ lines) are hot files colleague times out on when read whole — t1-t4/t7 must stay line-anchored; if a colleague child stalls twice the integrator does the edit and records a deviation
- [unknown_nonblocking] t2/t3/t4/t7 all touch session.py — serialized by deps (waves 1→2→3→4), never same-wave; t1 and t9 share `test_config_lobes.py` — serialized by t9's dep on t1
- [unknown_nonblocking] h17 (cortex-direct ack ≤ 2x the senses ack) is measured in t10; an unfavourable result ships recorded, it does not block
