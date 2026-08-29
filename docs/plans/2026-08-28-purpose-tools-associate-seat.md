# Build Plan — purpose-tools-associate-seat

slug: `purpose-tools-associate-seat` · status: `exported` · from frame: `purpose-tools-associate-seat`

> Colleague's cortex delegates BY PURPOSE: `web_survey` / `code_survey` (and review) are typed loop tools that run a scout (or reviewer) child on a FIXED seat — the associate when armed — and return a digest with evidence ids; cortex no longer holds the raw web tool (replace, not add); on the associate side effort is split per seat (scout off, distill low), the multi-turn scout keeps its thinking history, and measurement arms run in a memory-armed repo — the same enumerated seats addressed by purpose instead of by mechanism, never a per-turn model choice

## Tasks

### t1 — t1 effort tables: `ASSOCIATE_SEAT_TABLE` + `PURPOSE_TABLE` + `PURPOSE_STEPS` in a NEW module, with env/config overrides for the two new groups

- instruction: Ratchet: effort.py/config.py cannot grow — put the three tables + the two override readers in NEW colleague/efforttables.py (stdlib only; 'config imports effort, never the reverse' still holds) and wire them with net-zero hunks. Keep `SEAT_TABLE`/`ROLE_TABLE` untouched. docs/features/thinking-effort.md rendering is t11's; you only add the tables and pins.
- covers: c8, h8, c16, h16, c37
- acceptance:
  - colleague/efforttables.py defines `ASSOCIATE_SEAT_TABLE` == {scout: off, compact: off, synthesis: off, digest: off, distill: low}, `PURPOSE_TABLE` == {`web_survey`: off, `code_survey`: off, review: low, validate: low, plan: medium, `handover_to_colleague`: medium} and `PURPOSE_STEPS` == {`web_survey`: 12, `code_survey`: 12, review: 16, validate: 16, plan: 10, `handover_to_colleague`: None}; tests/`test_effort.py` pins every row and the exact key sets
  - `resolve_reasoning_effort_overrides` (or a sibling in the new module) reads `COLLEAGUE_ASSOCIATE_REASONING_EFFORT_`<SEAT> / `reasoning_effort_seats`\['associate.<seat>'\] and `COLLEAGUE_`<PURPOSE>`_REASONING_EFFORT` / `reasoning_effort_purposes`\[<purpose>\], each value through `validate_effort` (invalid → the same refusal message); config.json keys round-trip through EngineConfig.resolve
  - a precedence test: kill-switch 'default' > explicit override > associate.<seat> override > associate row override > `ASSOCIATE_SEAT_TABLE`; `PURPOSE_TABLE`\['`code_survey`'\] == `ASSOCIATE_SEAT_TABLE`\['scout'\] == 'off' is pinned
  - effort.py and config.py net line count unchanged (tests/`test_file_length_ratchet.py` passes); unset knobs → every existing resolve path byte-identical (tests/`test_effort.py` existing cases untouched and green)

### t2 — t2 associate seat builders consume the sub-seat rung

- instruction: Thread the seat NAME into the existing builders (a keyword with a default so unarmed callers are byte-identical). DistillAuthor gains 'effort: Optional\[str\] = None' — t3 consumes it. Do not touch distill.py here.
- depends on: t1
- covers: c15, h15
- acceptance:
  - `associate_engine_config`(config, seat=<name>) (or `resolve_associate_seat_config`) resolves the rung on the associate row with `ASSOCIATE_SEAT_TABLE`\[<seat>\] as the table default and the associate.<seat> override above it; `scout_child_config` passes seat='scout'; `make_associate_complete` passes its seat name; `distill_author` carries the resolved 'distill' rung on DistillAuthor (new optional field, default None)
  - git diff main -- colleague/associate.py colleague/`associate_seats.py` contains only effort-resolution hunks; `ASSOCIATE_SEATS` is still the five-tuple; tests/`test_associate_seats.py` AST guard + five-tuple pin pass unchanged; new tests assert distill resolves 'low' and scout/compact/synthesis 'off' with nothing set, and 'default' yields None everywhere

### t3 — t3 distill child: effort plumbing, raised `max_tokens` when a rung is on, 'length' failure reason

- instruction: distill.py is ratchet-pinned (803): put fragment/argv/`max_tokens`/failure-reason helpers in colleague/distilleffort.py and call them with net-zero hunks. Mirror `vllm_openai`.`_maybe_retry_ladder_400`'s rule (one retry, one warning) — do not import the adapter. The child stays a raw urllib POST (the boundary test's sanctioned list is unchanged).
- depends on: t2
- covers: c9, h9, c38, h36
- acceptance:
  - `make_distill_fn`/`_build_child_argv` pass the author's rung to the detached child (argv --effort or env `COLLEAGUE_DISTILL_EFFORT`); `child_main` parses it; `_openai_completion` sends `chat_template_kwargs` via effort.`to_chat_template_kwargs` (absent for None/'default')
  - a ladder-400 on the distill POST retries ONCE without `chat_template_kwargs` and the outcome marker records the warning; `max_tokens` is 4096 when the rung is off/None and ≥ 12288 for low/medium/high/xhigh; `finish_reason`='length' with no lesson JSON writes failure reason 'reasoning exhausted `max_tokens`' (not 'no lesson extracted')
  - tests with a fake HTTP server (the existing distill child test harness) cover: body carries the fragment at low; 400 → retry without it; length → marker reason; distill.py net line count unchanged (helpers live in NEW colleague/distilleffort.py)

### t4 — t4 `purpose_schemas.py`: the six purpose tool schemas, `PURPOSE_ROLE`, hidden-state rule, brief templates

- instruction: Model on colleague/`web_schemas.py` + `search_schemas.py` (offered/`hidden_names`, dispatch shape). Descriptions: one line each, steer multi-file/multi-page surveys to the tool and single reads to `read_file` — no numbers, no prompt section (c12). Do NOT touch tools.py here (t5 splices).
- depends on: t1
- covers: c2, h2, c24, h27, c31, h31
- acceptance:
  - colleague/`purpose_schemas.py` exports `PURPOSE_SCHEMAS` (six OpenAI function schemas: `web_survey`{question, urls\[\]}, `code_survey`{question, paths\[\]}, review{`diff_ref`}, validate{scope}, plan{goal}, `handover_to_colleague`{task, acceptance\[\]}), `PURPOSE_ROLE` == {`web_survey`: scout, `code_survey`: scout, review: reviewer, validate: validator, plan: planner, `handover_to_colleague`: writer}, offered(name, allow) and `hidden_names`() (`web_survey` hidden exactly when `web_schemas`.`hidden_names`() contains 'web'), and `brief_for`(name, arguments) rendering a fixed template ('find X, cite `operation_id`/`evidence_refs`' for `web_survey`)
  - no schema has an 'effort', 'model', 'engine' or 'role' property (schema test); tools.SCHEMAS is unchanged (pin its names); every `PURPOSE_ROLE` value satisfies roles.`is_read_only` except `handover_to_colleague` (writer)
  - unit tests for `brief_for` per tool (verbatim question/urls/paths land in the brief; untrusted-data sentence present for `web_survey`)

### t5 — t5 surface curation: cortex/worker offer purposes, lose web + subagent + subagents; tool profiles

- instruction: One splice in tools.`curate_schemas` (like `search_schemas`/`web_schemas`.offered) + one dispatch entry per purpose pointing at `purpose_schemas`.dispatch(self) (t6 fills the executor). roles.`_writer_allowlist`: drop web/subagent/subagents, add the six purposes; keep `_READONLY_TOOLS` as is. `WORKER_TOOLS`: replace subagent/subagents with the six purposes. Update the conftest webglass fixture expectations if a pin references web on cortex.
- depends on: t4
- covers: c4, h4, c5, h5, c25, h23, h37
- acceptance:
  - `curate_schemas`('writer') and the `thinker_coder`/worker purpose surfaces contain the six purpose schemas and NOT web/subagent/subagents; `curate_schemas` for scout/explorer/reviewer/validator/planner contain NO purpose schema and still contain web (read-only roles unchanged); byte-identical when purposes are not offered? — N/A: purposes are always offered to cortex/worker; pin the new offered list as the fixture
  - agents/tools.`TOOL_PROFILES`: five read-only purposes = ToolProfile(class='read', `required_approval`=False, inheritable=False); `handover_to_colleague` = class 'write', inheritable=False; `tae_loop`.`CONSEQUENTIAL_TOOLS` gains exactly '`handover_to_colleague`' (the subagent it replaces) and none of the read-only purposes; `assert_purpose_surface` still refuses a talker holding `handover_to_colleague`
  - tools.py/roles.py/agents/tools.py hunks are net-zero (ratchet green); tests/`test_role_curation.py`, `test_search_schemas.py`, `test_deepthink_tool.py` fixtures updated deliberately (the diff names each removed/added name)

### t6 — t6 purpose executor: spawn with fixed role/rung/`max_steps`; budget-exhausted marker; arithmetic exemption

- instruction: The spawn callable is already threaded (ToolExecutor.`_spawn` → subagents.`make_spawn`); add '`max_steps`' to `make_spawn`'s signature → ChildSpec.`max_steps` (exists). For the arithmetic exemption add a '`charges_budget`: bool' on ChildSpec honoured by `_enforce_delegation_bounds`/`_AgentBudget`.charge — net-zero hunks in subagents.py (pinned 1692): move the exemption logic into `purpose_schemas` or a tiny new module if needed. Budget-exhausted marker: read the child's TaskResult.status/incompletion; never raise.
- depends on: t5
- covers: c3, h3, h30, c28, h26, c34, h33, c40
- acceptance:
  - `purpose_schemas`.dispatch(executor) handlers call executor.`_spawn`(brief, engine=None, model=None, role=`PURPOSE_ROLE`\[name\], effort=`PURPOSE_TABLE` rung, `max_steps`=`PURPOSE_STEPS`\[name\]) — a parametrised test asserts role/effort/`max_steps` per tool and that a parent at `reasoning_effort_seats`={'cortex':'medium'} yields child rung low for review, off for `code_survey`
  - a child that exhausts `max_steps` returns a NON-empty tool result prefixed '\[purpose budget exhausted: N steps\]' with its partial; a read-only purpose call does NOT charge `MAX_SUBAGENT_FANOUT`/TOTAL (25 sequential `code_survey` calls all run on mock) while `handover_to_colleague` does (depth/total refusal text returned as the tool result, no exception)
  - the child runs through `run_subagent` unchanged (sub/<id> worktree created and removed — e2e mock test); `purpose_schemas.py` imports no worktrees/subprocess (grep guard); `handover_to_colleague`'s `changed_files` reach the parent's changed-file set; tests/`test_e2e_mock.py` shows mock and vllm-openai produce the same `sub_results` shape

### t7 — t7 parent-side reporting + one work-item web budget across purpose children

- instruction: Pass the remaining budget on ChildSpec (new optional field) and read the child's SubResult stats on return; webbudget.py helpers (`resume_counts` precedent). Keep the child's own cap semantics for manual subagents byte-identical (remaining=None → today's behaviour).
- depends on: t6
- covers: c33, h32, c36, h34
- acceptance:
  - a purpose child inherits remaining web calls (`COLLEAGUE_WEB_MAX_CALLS` − parent.`web_calls`) and on return its `web_calls`/`web_failed` fold into the parent's executor counters; with `COLLEAGUE_WEB_MAX_CALLS`=5 three `web_survey` scouts fetching 2 pages each end with call 6 refused and parent result.stats.`web_calls` == 5
  - the parent's Step.result for `web_survey` ends with a 'urls fetched:' block listing every URL from the child's web steps verbatim, and the parent artifact's web report line (`web_schemas`.`summary_line`) includes them; a .colleague/hooks.json `pre_tool` deny on 'web' fails the child's fetches and the digest says so (e2e mock + fake webglass)

### t8 — t8 armed-agents ⊆ exemption for purpose delegations

- instruction: Add an optional 'purpose' field to DelegationRequest; subagents' armed path sets it from ChildSpec. Find the existing pin test by grepping tests/ for 'receives' + 'web'.
- depends on: t6, t7
- covers: c6, h6, c26, h24
- acceptance:
  - agents/delegation.validate accepts a DelegationRequest flagged purpose=<name> whose `requested_tools` (the role allow-list ∩ environment) exceed the parent's effective tools; an unflagged request with a superset is still refused — both asserted side by side
  - the web-scout spec honesty line 33 pin (child receives web only when the parent holds it) is rewritten to the new rule, not deleted; docs/features/web-scout.md marks it superseded with a pointer to this spec (doc line edit only — the full doc pass is t11)

### t9 — t9 `compare_arms`: purpose steps in delegations + `associate_calls`

- instruction: Import the purpose names from colleague.`purpose_schemas` (or a `PURPOSE_TOOL_NAMES` constant) — no duplicate list. Also count purpose steps in the `web_calls` column? No — web calls stay the CHILD's; t7 folds them.
- covers: c7, h7
- acceptance:
  - `_count_delegations` counts subagent/subagents and the six purpose tools; `_count_associate_calls` matches a purpose step's `served_model` to artifact\['associate'\]\['`served_model`'\]; fixture artifact with one `code_survey` step + `served_model` yields delegations=1, `associate_calls`=1; existing fixtures unchanged

### t10 — t10 delegation prose + config show / /effort render the three rung groups

- instruction: config.py:82 / `_session_actions.py`:89-104 / `harness_cli.py`:34 iterate `SEAT_TABLE` today — iterate efforttables too. Keep --json shapes additive (new keys only).
- depends on: t1, t4
- covers: c12, h12, h35
- acceptance:
  - `delegation_text`.`apply_armed_facts` splices the armed sentence onto `web_survey`/`code_survey`/`handover_to_colleague` descriptions (and subagent/subagents when present); prompttext.`default_system`() output is byte-identical to the committed fixture (no new section)
  - colleague config show and session /effort print three groups — seats, associate.<seat>, purposes — with resolved rungs; an invalid value in any group refuses at resolve() with `validate_effort`'s message (parametrised test per group)

### t11 — t11 docs: purpose-tools.md feature doc, thinking-effort tables, web-scout q3 superseded, adopt doc scout=off, CLAUDE.md increment (1) clause

- instruction: Follow the feature-doc shape of docs/features/web-scout.md. Cite line numbers; never restate numbers from memory — copy from docs/live-testing.md. Reference #446 for thinking continuity (out of scope).
- depends on: t10, t8, t3
- covers: c14, h14, c17, h17, c27, h25, c20, h18, c21, h19, c22, h20
- acceptance:
  - docs/features/purpose-tools.md exists (what/before-after/audience by ROLE/why with rows 45/47/48 + direct-seat numbers quoted with dates and artifact ids/what shipped/knobs/honest limits incl. the manual-child rung leak v5, webtrust v6, flight v7, batch v2); CLAUDE.md: Web scout bullet + increment (1) gain one clause each, the count stays eleven (grep 'twelve' → none); docs/features/thinking-effort.md renders `ASSOCIATE_SEAT_TABLE` + `PURPOSE_TABLE` once (tests/`test_thinking_effort_docs.py` green); adopt-from-qwen-code.md says `ROLE_TABLE`\['scout'\] = 'off'; web-scout.md q3 marked superseded; markdownlint-cli2 clean

### t12 — t12 pre-register live rows 49/50 + briefs BEFORE any run

- instruction: Copy the row-47/48 pre-registration shape exactly. Do this in wave 1 so the bar is committed before any code exists.
- covers: c11, h11
- acceptance:
  - docs/live-testing.md rows 49 and 50 exist with brief pointer, repo ('throwaway repo WITH an .eidetic store, eidetic CLI <version>'), pass bar (49: purpose calls ≥ 1 on ≥ 2/3 runs, turns ≤ 1.0×, wall ≤ 1.2× vs main @ e589451 RE-RUN n=3; 50: scout served model = associate's, evidence ids in the final answer, zero `run_command` steps outside the repo) and 'result: pending'; docs/live-testing/briefs/row49-purpose.md (the row-48 brief verbatim) + row50-web-purpose.md; both name the memory distill counters to record

### t13 — t13 guards + byte-identical suite + all-engines e2e

- instruction: Reuse tests/`test_all_engines_batch.py` fixtures; the 'byte-identical' claim is honest only with the cortex surface change carved out and asserted — say so in the test docstring.
- depends on: t7, t8, t9
- covers: h1, c1
- acceptance:
  - tests/`test_purpose_tools_boundary.py`: AST guards in tests/`test_thinking_effort_boundary.py` and tests/`test_associate_seats.py` list `purpose_schemas.py`/efforttables.py/distilleffort.py with a stated reason and pass; no per-turn path assigns effort; `purpose_schemas` imports no worktrees/subprocess
  - unarmed byte-identical suite: with no associate, `COLLEAGUE_WEB`=0/no webglass, no effort knobs — payload keys, prompt text, step trace vs the e589451 fixtures are identical EXCEPT the recorded offered-tool list change on cortex (web/subagent/subagents → purposes), which the test names explicitly; tests/`test_e2e_mock.py` all-engines shape check covers a purpose step

### t14 — t14 live proof: baseline re-run + rows 49/50 + `compare_arms`

- instruction: Run from the operator's login shell (Brave key; DNS). Detach via setsid, never `run_in_background`. GPU serializes: baseline first, then branch. Record wall vs turns per column (c35).
- depends on: t11, t12, t13
- covers: c13, h13, c23, h21
- acceptance:
  - main @ e589451 re-run n=3 on the row-48 brief (artifact ids recorded); branch n=3 with purposes offered + associate armed in an .eidetic-armed repo; row 49 filled from scripts/`compare_arms.py` --bar-wall 1.2 --bar-turns 1.0 (delegations column = purpose calls); row 50 filled (served model, evidence ids, `run_command` steps outside the repo = 0, memory distill counters, distill child rung/reasoning chars); a miss is written as a miss

## Risks

- [unknown_nonblocking] v2 purpose tools are NOT in toolbatch.`CONCURRENCY_SAFE_TOOLS`; parallel purpose calls from one turn serialize on the main thread — cost unmeasured until row 49; if it dominates wall, a follow-up measures batch-safe purpose calls (nested `worktree_add` under the pool) (task t6)
- [unknown_nonblocking] v6 resident webtrust: whether the per-turn confirmation gate fires on the `web_survey` purpose call or only on the child's raw web call is undecided — t7 must not silently choose; default: gate at the purpose call (the operator-visible boundary) and record it (task t7)
- [unknown_nonblocking] v7 flight reach: 'flight stop' on the parent may not reach a running purpose child (own task id / flight file) — t6 verifies with a mock child and records the finding in the feature doc (t11); if it does not reach, the parent's stop waits for the child's step cap (task t6)
- [unknown_nonblocking] c35 wall vs turns can diverge under purpose tools (each call = a serial child run on a serializing GPU); row 49 is reported per column and a turns-pass/wall-miss is a MISS — the arc must not average it away (task t14)
- [unknown_nonblocking] ratchet friction: tools.py (1508), subagents.py (1692), distill.py (803), effort.py (280), config.py are line-pinned — every wired task must land net-zero hunks or move logic into its new module; a baseline bump is a recorded deviation, never silent
- [unknown_nonblocking] the row-48 brief may not trigger purpose calls at all (row 48: 0 delegations on both arms with subagent offered); purpose tools lower the ask's cost but nothing forces them — a 0-call row 49 is a MISS and evidence for #435, not a bug to fix mid-arc (task t14)
