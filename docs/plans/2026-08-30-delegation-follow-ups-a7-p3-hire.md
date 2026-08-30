# Build Plan — delegation-follow-ups-a7-p3-hire

slug: `delegation-follow-ups-a7-p3-hire` · status: `exported` · from frame: `delegation-follow-ups-a7-p3-hire`

> Delegation follow-ups: the raw-vs-purpose fair fight (A7) and a size-trigger prose arm with a clean control (P3) run as one pre-registered matrix on the large-surface brief, and `hire_colleague` — cortex hires a run-scoped employee with an agreed purpose and a when clause, then assigns it work — is scoped as a twelfth sanctioned increment that keeps a byte-identical off-state and never becomes a router

## Tasks

### t1 — Add-knob: `COLLEAGUE_ACTING_ADD_TOOLS` at the depth-0 seam

- instruction: Files: colleague/actingsurface.py (`ACTING_ADD_ENV` beside `ACTING_DROP_ENV`, `acting_add_set`(), the depth-0 branch of `curate_for_depth`), tests/`test_acting_add_knob.py`. Add = dataclasses.replace(role, `tool_allowlist`=role.`tool_allowlist` + tuple(new names)); refuse silently nothing — an unknown name is ignored and recorded nowhere (the knob is an arm instrument, spec c3/D3). Do not touch roles.`_writer_allowlist`. Write the tests first.
- covers: c42, h26
- acceptance:
  - actingsurface.`acting_add_set`() reads `COLLEAGUE_ACTING_ADD_TOOLS` (comma-separated, order-preserving, de-duplicated; unset/blank = ()) and `curate_for_depth` applies it at depth 0 AFTER the drop knob, adding only names that exist in tools.SCHEMAS
  - a depth-1 child never gains the added names (`strip_child_forbidden_tools` still removes subagent/subagents)
  - with the knob unset every existing test in tests/`test_acting_drop_knob.py` and tests/`test_purpose_tools_byte_identical.py` passes unchanged; tests/`test_acting_add_knob.py` mirrors the drop-knob suite

### t2 — Persist `offered_tools` on TaskResult for both engines

- instruction: Files: colleague/contract.py (field + serialization next to `prompt_digest`, contract.py:1726/1897/1997), colleague/engines/`vllm_openai.py` (around :1320 where `offered_tools` is computed), colleague/engines/mock.py, tests/`test_contract_offered_tools.py`. Mirror exactly how `prompt_digest` is threaded (omit-when-None). All-engines rule: mock and vllm must not diverge in shape.
- covers: c34, h18
- acceptance:
  - TaskResult.`offered_tools` (Optional\[list\[str\]\], omit-when-None, serialized beside `prompt_digest`) round-trips through `to_dict`/`from_dict` and the artifact JSON
  - `vllm_openai`.work() sets it to the depth-0 `curated_schemas` names in schema order; the mock engine sets the same field the same way (tests/`test_e2e_mock.py` shape parity extends to it)
  - a pre-field artifact loads with `offered_tools` None

### t3 — Stage the P2-0 control and P3 trigger overlays

- instruction: Files: docs/live-testing/overlays/P2-0/writer.md, docs/live-testing/overlays/P3/writer.md, tests/`test_overlays_p3.py`. Trigger sentence (verbatim, spec c7): 'When the survey does not fit in one pass, hand parts of it to `code_survey` and review the digests before you act.' Overlays are staged instruments, never shipped defaults; markdownlint excludes the overlays dir.
- covers: c7, h4
- acceptance:
  - docs/live-testing/overlays/P2-0/writer.md == the 'effort: medium' line + P2's first paragraph, byte-for-byte (a test asserts head-equality with P2)
  - docs/live-testing/overlays/P3/writer.md diffs against P2-0 by exactly one added sentence carrying an explicit size trigger naming `code_survey`; a test asserts the unified diff has exactly one '+' content line
  - tests/snapshots/`prompttext_v1`.txt and `BUILTIN_ROLES`\['writer'\].`prompt_fragment` are unchanged

### t4 — Surface both new knobs in config show and the config digest

- instruction: Files: colleague/config.py (the resolve() knob table + config events, follow the `COLLEAGUE_AGENTS` pattern at config.py:2181 and :1389), colleague/cli/`_commands`/config.py (show table), tests/`test_config_hire_knobs.py`. Only the RESOLUTION lands here — no tool behaviour; the hire tools are later tasks and read config.hire.
- covers: c42, h26
- acceptance:
  - colleague config show --json lists `COLLEAGUE_ACTING_ADD_TOOLS` and `COLLEAGUE_HIRE` with their value or unset
  - EngineConfig resolves a boolean hire flag (`COLLEAGUE_HIRE` env > config.json 'hire' > False) and both knobs emit config events, so two otherwise-identical runs differing only in `COLLEAGUE_HIRE` have different `config_digest` values (test asserts inequality)
  - with both unset, existing config-show and config-digest tests pass unchanged

### t5 — Pre-register rows 59-61 (A7, P2-0, P3) before any run

- instruction: Files: docs/live-testing.md only. Copy row 57's cell contract verbatim and add the two new cells (`offered_tools`, raw-call histogram). Arms: A7 = arm-large-surface brief, no overlay, `COLLEAGUE_ACTING_ADD_TOOLS`=subagent,subagents; P2-0 = same brief + overlays/P2-0 as .colleague/agents/writer.md; P3 = same brief + overlays/P3. Baseline for A7 ratios is A5 (row 57); baseline for P3 is row 60. Write the promotion rule and the qualification sentence BEFORE any artifact exists.
- depends on: t1, t2, t3, t4
- covers: c5, h3, c9, h5, c10, h6, c25, h14, c23, h12
- acceptance:
  - docs/live-testing.md gains rows 59 (A7), 60 (P2-0 control), 61 (P3) in the rows 52-58 shape: brief path, fixture per-file line/byte counts, tip SHA pin rule, n=3, pass bars (A7: `offered_tools` carries both halves in 3/3 else VOIDED; P3: q3 rule with the three numbers vs row 60), the qualified-verdict wording of h20, the raw-call (role, effort, engine, model) histogram cell of h19, and '`compare_arms.py` diff empty at each run SHA'
  - the rows cite the four before-state surfaces of h14 (row 56, row 58, prompttext.py:131-145, `purpose_schemas`.dispatch) and the spec names both audiences (h12)
  - git diff main -- scripts/`compare_arms.py` is empty; the row commit predates every artifact (verified in t6)

### t6 — Run the 9-arm matrix and fill the cells from artifacts

- instruction: Rig: lobes armed, cortex Qwen3.8-27B-NVFP4, associate not consumed; runs sequential (GPU serializes); `COLLEAGUE_TIMEOUT`=300; ~586 s/run expected. Build the fixture repo fresh per arm from the generator; pin the SHA per run; use scripts/`compare_arms.py` --bar-wall 1.2 --bar-turns 1.0 for the ratios. A gateway stall is a rig failure — void and re-run, never average in.
- depends on: t5
- covers: c2, h2, h20, c27, h16, c24, h13
- acceptance:
  - 9 artifacts exist (3 per arm) on the fixture from scripts/`make_large_surface_fixture.py`; each row lists its 3 artifact ids, tip SHA, and every cell read from stats/steps/`offered_tools` — 0 figures from prose
  - A7 rows paste `offered_tools` (both halves present or VOIDED) and the per-raw-call argument histogram or 'no raw call occurred'; the A7 verdict sentence contains the h20 qualification verbatim
  - row 61's verdict applies the q3 rule against row 60 with delegation rate, mean turns and mean reasoning chars stated; a null is written as a null

### t7 — Record the arc conclusion and apply the q3 promotion decision

- instruction: Files: docs/features/purpose-tools.md, CLAUDE.md, and ONLY on promotion colleague/prompttext.py + tests/snapshots/`prompttext_v1`.txt + colleague/engine.py (gate `_PURPOSE_TOOLS` on actingsurface.`is_top_level`). Record the deviation with /deviate before regenerating the snapshot. Never promote on a confounded comparison.
- depends on: t6
- covers: c26, h15
- acceptance:
  - docs/features/purpose-tools.md's arc section cites rows 59-61 as closing #456 gaps 1 and 2 and states each result whichever way it fell; CLAUDE.md's purpose-tools bullet gains one sentence pointing there
  - if row 61 meets the q3 rule: the trigger sentence lands in prompttext.`_PURPOSE_TOOLS` AND that section is gated to the top-level acting seat (decision D4), tests/snapshots/`prompttext_v1`.txt regenerated under a recorded deviation, `test_roles`/`test_layers_roles` updated; if not: no prompt literal changes and the row says 'does not promote'

### t8 — Arms PR: version 1.69.0, CHANGELOG, PR, review triage

- instruction: Use /version-bump minor then the cicd skill. Leave .eidetic recall-counter churn out of the PR. Sign as '- colleague (Claude)'.
- depends on: t7
- covers: c1, h1
- acceptance:
  - pyproject/`__init__`/CHANGELOG bumped to 1.69.0 (version-bump skill); PR opened via the cicd skill with rows 59-61 + the knob + `offered_tools` + overlays; CI green, Sonar gate OK, Qodo threads triaged
  - grep of the PR diff finds no runtime-side task->tool decision: the add knob only changes what is OFFERED (h1)

### t9 — colleague/hire.py: the Hire record, roster and prompt-never-grants role builder

- instruction: New file colleague/hire.py + tests/`test_hire.py`. Pure stdlib, no loop imports (mirror agents/profile.py's discipline). `base_role` must be a `BUILTIN_ROLES` key or HireError. Use actingsurface.`strip_child_forbidden_tools` for the surface (it will learn the hire pair in the next task; import lazily).
- depends on: t8
- covers: c14, h7
- acceptance:
  - Hire dataclass (`agent_id`, `hirer_id`, `base_role`, purpose, when, `prompt_fragment`, `prompt_digest`, status in {live, expired}, `task_id`, `created_step`) with `to_dict`/`from_dict`; Roster caps at `MAX_SUBAGENT_FANOUT` (4) and refuses a 5th with a readable HireError
  - `hired_role`(hire) == replace(`BUILTIN_ROLES`\[base\], `prompt_fragment`=authored) with the allow-list unchanged from the base; a parametrised test over every `BUILTIN_ROLES` base and an authored prompt naming write/delegation/hire tools proves the surface equals base minus `PURPOSE_TOOL_NAMES` minus `CHILD_FORBIDDEN_TOOLS` minus {`hire_colleague`, `assign_to_colleague`}
  - prompt > 2000 chars or when > 200 chars raises HireError; `prompt_digest` == contract.`prompt_digest_for`(`prompt_fragment`)

### t10 — `hire_schemas`: the two tool schemas, the `COLLEAGUE_HIRE` hidden rule and the surface splice

- instruction: Files: colleague/`hire_schemas.py` (new; model on `purpose_schemas.py`'s offered/`hidden_names` shape), colleague/tools.py (the splice at :627), colleague/roles.py (`_writer_allowlist` + `HIRE_TOOL_NAMES`), colleague/prompttext.py (one armed-only sentence via the `SECTION_TABLE` opt-in path so the v1 snapshot stays untouched), tests/`test_hire_schemas.py` + an added case in tests/`test_purpose_tools_byte_identical.py`. `hidden_names` reads the resolved config.hire flag threaded like `purpose_schemas`.`_thread_effort_config`.
- depends on: t8
- covers: c17, h8
- acceptance:
  - colleague/`hire_schemas.py` defines `HIRE_TOOL_NAMES` = ('`hire_colleague`', '`assign_to_colleague`'), their OpenAI schemas (hire: purpose, when, `base_role` enum of builtin names, prompt; assign: `agent_id`, task, acceptance; no effort/model/engine/role property), and `hidden_names`() returning both names unless config.hire is armed
  - `curate_schemas` appends them exactly as it appends purpose schemas; roles.`_writer_allowlist` includes them; prompttext gains ONE sentence that renders only when armed
  - the byte-identical suite passes with `COLLEAGUE_HIRE` unset; a new case with `COLLEAGUE_HIRE`=1 and no hire call shows `offered_tools` differing by exactly the two names and the composed prompt by exactly one sentence

### t11 — Confinement: children, agents-mode tool sets and the batch pool never hold the hire pair

- instruction: Files: colleague/actingsurface.py (extend the forbidden set), colleague/agents/tools.py (:88 and :161-166, knob-guarded), tests/`test_hire_confinement.py`, additions to tests/`test_agents_tools.py` and tests/`test_toolbatch`\*.py. No change to toolbatch.py itself is expected — `CONCURRENCY_SAFE_TOOLS` is an allow-list; the test pins exclusion.
- depends on: t8
- covers: c41, h25, c37, h21, c19, h10
- acceptance:
  - actingsurface.`strip_child_forbidden_tools` strips `HIRE_TOOL_NAMES` at depth >= 1; a depth-1 `curate_for_depth` test shows neither name
  - under `COLLEAGUE_AGENTS`=1 + `COLLEAGUE_HIRE`=1 agents/tools.`THINKER_CODER_TOOLS`/`ASSOCIATE_TOOLS` contain both names; under `COLLEAGUE_AGENTS`=1 alone neither; both names are in `_NOT_INHERITABLE`; `validate_profile_tools` refuses a talker holding either
  - neither name is in toolbatch.`CONCURRENCY_SAFE_TOOLS` and a mixed batch \[`read_file`, `assign_to_colleague`, `grep_search`\] runs the hire/assign step outside the pool in request order

### t12 — `hire_colleague` handler: the bounded two-round negotiation, on mock and vllm

- instruction: Files: colleague/`hire_dispatch.py` (new; the `hire_colleague` handler ONLY — assign lives in `hire_assign.py`, t13; bind like `purpose_schemas`.dispatch and register where tools.py registers purpose handlers at :738), colleague/engines/mock.py (candidate rule), tests/`test_hire_negotiation.py`. Locate the tools-off completion seam the senses loop / deepthink already use (grep 'tools-off' in colleague/) and reuse it — never a new transport. Effort for the candidate turn: the seat's `ROLE_TABLE` row for the base role.
- depends on: t9, t10
- covers: c18, h9, c40, h24
- acceptance:
  - `hire_colleague` runs at most 2 candidate rounds, each ONE tools-off completion on the cortex seat (the existing tools-off completion seam), parsing accept | amend(purpose, when) | decline; accept or amend-then-accept mints a Hire on the roster; two declines or a malformed second reply return the tool result 'not hired: <reason>' with roster unchanged and exactly 2 completions made
  - the mock engine's candidate rule is deterministic and documented: accept unless the proposed purpose contains 'decline'; amend when it contains 'amend'
  - a refused hire (cap, caps on length, unknown base) is a readable tool result, never an exception (h30); the caller's `step_count` advances by 1 per hire call

### t13 — `assign_to_colleague` handler + TaskResult.hires block

- instruction: Files: colleague/`hire_assign.py` (NEW — the assign handler lives here, NOT in `hire_dispatch.py`, so t12 and t13 stay file-disjoint in the same wave; tools.py registers both modules' handlers), colleague/contract.py (hires block next to `sub_results` serialization), tests/`test_hire_assign.py`. Reuse `purpose_schemas`.`_record`/`_render` rather than duplicating the fold. The hires block carries the authored prompt TEXT — the ledger (next task) carries only its digest.
- depends on: t9, t10, t11
- covers: c38, h22
- acceptance:
  - `assign_to_colleague`(`agent_id`, task, acceptance) spawns ONE child through executor.`_spawn` with role=`hired_role`(hire), purpose='`assign_to_colleague`', effort=`ROLE_TABLE`\[base\], `charges_budget`=not `is_read_only`(base), `web_calls_remaining` folded exactly as `purpose_schemas`.`_record` does; the result renders like a purpose result including the 'urls fetched:' block
  - an unknown or expired `agent_id` returns 'no live hire: <id>' as the tool result; TaskResult.hires (omit-when-empty) records every Hire plus its assignments (child `task_id`, status, changed files) and round-trips through the artifact; `test_e2e_mock` shape parity covers it
  - a 2001-char prompt at hire time is refused readably (h22 caps re-tested end-to-end)

### t14 — Ledger refs-not-payloads event and hires dead at the cut

- instruction: Files: colleague/agents/state/ledger.py (a new closed-vocabulary kind 'hire' if `EVENT_KINDS` is closed — bump additively), colleague/`hire_dispatch.py` (emit when ctx.agents is not None), colleague/continuation.py + colleague/chain.py (mark expired on seed), tests/`test_hire_ledger.py`, tests/`test_hire_continuation.py`. Decision D43: dead at the cut.
- depends on: t13
- covers: c38, h22
- acceptance:
  - under `COLLEAGUE_AGENTS`=1 a hire appends one task-ledger event {`agent_id`, `hirer_id`, `base_role`, `prompt_digest`, `when_digest`, `artifact_ref`} with NO prompt text, under 4096 bytes; unarmed appends nothing
  - work --continue and an --until-done episode load the prior artifact's hires with status=expired; `assign_to_colleague` on an expired id returns 'no live hire'; hires are never rehydrated as live

### t15 — `compare_arms.py`: hires / assignments columns (versioned, before the hire row)

- instruction: Files: scripts/`compare_arms.py`, tests/`test_compare_arms.py`. Keep the delegations column definition unchanged (raw pair OR `PURPOSE_TOOL_NAMES`) — assignments are a separate column by decision D44.
- depends on: t8
- covers: c21, h11
- acceptance:
  - scripts/`compare_arms.py` prints two new columns: hires (len(artifact\['hires'\])) and assignments (count of `assign_to_colleague` steps), 0 for pre-field artifacts; existing columns and bars unchanged; tests/`test_compare_arms.py` covers both
  - the change is its own commit, landed before row 62 is written (t16), and the arms matrix rows 59-61 note that their comparator SHA predates it

### t16 — Hire arm: the repeated-sub-tasks brief, fixture generator and pre-registered row 62

- instruction: Files: docs/live-testing/briefs/arm-repeated-subtasks.md, scripts/`make_repeated_subtasks_fixture.py`, docs/live-testing.md (row 62). Model the brief on arm-large-surface.md's 'why the baseline cannot fit' arithmetic — here the argument is amortisation, not surface size.
- depends on: t7, t13, t15
- covers: c21, h11
- acceptance:
  - docs/live-testing/briefs/arm-repeated-subtasks.md describes a brief with >= 6 similar independent sub-tasks across one long run (the shape where one hire amortises); scripts/`make_repeated_subtasks_fixture.py` generates it deterministically with recorded per-file counts
  - row 62 is pre-registered before any run: arm H (`COLLEAGUE_HIRE`=1) vs control (one-shot purpose tools, same brief, knob unset), n=3 each, pass bar with a numeric hire/assignment count, and the accept/amend/decline counts per hire as a cell; a 0/N result is declared publishable in the row
  - the brief text cites row 61's P3 verdict as the input to its trigger hypothesis

### t17 — Run the hire arm and record row 62

- instruction: Same rig discipline as t6. Void gateway stalls. Do not tune the brief after the first run.
- depends on: t16, t14, t12
- covers: c28, h17, c24, h13
- acceptance:
  - 6 artifacts (3 H, 3 control); row 62 cells read from artifacts: hires, assignments, delegations, accept/amend/decline per hire, task success, wall/turns ratios; the verdict names the pass bar and is written as a null if 0 hires occurred
  - the four hire signals of h17 are each named as a test id or a row cell in docs/features/hire-colleague.md

### t18 — Hire docs, CLAUDE.md twelfth increment, version 1.70.0, PR

- instruction: Mirror docs/features/purpose-tools.md's structure. Record the two challenge parks (self-negotiation theatre, A7 generality) under honest limits with the row-62 accept/amend/decline counts.
- depends on: t17
- covers: c1, h1, c23, h12
- acceptance:
  - docs/features/hire-colleague.md exists in the feature-doc template (what/before-after/why/shipped/measurement/honest limits/knobs/provenance) naming both audiences; CLAUDE.md gains the hire bullet and the twelfth-increment entry stating it is presentation + explicit calls, never dispatch
  - version 1.70.0, CHANGELOG, PR via cicd, CI/Sonar/Qodo green; grep of the diff finds no runtime-side task->hire decision (h1)

## Risks

- [unknown_nonblocking] Which existing tools-off completion seam the candidate turn reuses (senses loop vs deepthink path) is undetermined until t12 reads them; a wrong pick is a rework, not a design change (task t12)
- [unknown_nonblocking] Self-negotiation on the same cortex model may be theatre (frame park); t17's accept/amend/decline counts decide whether the 2-round bound is cut to 1 later (task t17)
- [unknown_nonblocking] A7's result may not generalise beyond the one brief shape where delegation occurs (frame park); no second delegating brief exists (task t6)
- [unknown_nonblocking] P3 promotion (t7) is conditional on row 61 and, if taken, regenerates the v1 prompt snapshot + gates a shared section to depth 0 — a deviation must be recorded before the regen (task t7)
- [unknown_nonblocking] Rig availability: 15 sequential runs (~2.5 h) plus gateway-stall voids (lobes-cli#220 precedent) can stretch t6/t17 across days; never average a voided run (task t6)
