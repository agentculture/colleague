# delegation-follow-ups-a7-p3-hire

> Delegation follow-ups: the raw-vs-purpose fair fight (A7) and a size-trigger prose arm with a clean control (P3) run as one pre-registered matrix on the large-surface brief, and `hire_colleague` — cortex hires a run-scoped employee with an agreed purpose and a when clause, then assigns it work — is scoped as a twelfth sanctioned increment that keeps a byte-identical off-state and never becomes a router
> instruction: verify: grep the arms PR and the hire spec for a runtime-side task->tool or task->hire decision; there must be none — only presentation + explicit calls

## Audience

- Two audiences: the operator who pre-registers and reads the arm rows (docs/live-testing.md) and decides promotion; and cortex on the acting seat, who is offered the raw pair (A7), the trigger sentence (P3) or the hire/assign pair (hire) and calls or ignores them explicitly
  - instruction: verify: grep the exported spec for 'operator' and 'cortex' audience lines

## Before → After

- Before: Before: the raw pair has never been offered beside the purpose tools on a brief that delegates (A4 ran the small brief), the large brief has no prose control so A6-vs-A5 is confounded, the shipped prompt has permission + brake but no trigger, and every delegation is one-shot — nothing persists a purpose or a prompt across two assignments
  - instruction: verify: the four citations resolve on daedbc6
- After: After: (arms) rows 59-61 answer 'does cortex prefer `code_survey` over subagent when offered both' and 'does a size trigger move delegation on a clean control' with measured numbers, and one promotion decision is taken on the q3 rule; (hire) a `COLLEAGUE_HIRE`=1 run can hire a run-scoped employee with an agreed purpose + when clause, assign it work, and the artifact records the hire, its authored prompt digest and every assignment — unarmed runs unchanged
  - instruction: verify: the rows' cell contract (six cells) is complete; the hire spec's h-list includes the off-state condition

## Why it matters

- Why: the arc's headline ('cortex was right not to delegate', c46) rests on two inference gaps that ~1.5 h of rig closes; and hiring is the first increment where a model authors another seat's prompt, so getting its authority story (describes, never grants) right on a run-scoped first cut is what keeps the router excluded when persistence follows
  - instruction: verify: grep docs/features/purpose-tools.md for '#456' after the PR

## Requirements

- A7: run docs/live-testing/briefs/arm-large-surface.md with BOTH the raw subagent/subagents pair AND the six purpose tools on the acting seat, n=3, baseline A5 (row 57, 2/3 delegating, wall mean ~586 s); the row is pre-registered before the first run and its delegation cell is broken down BY TOOL NAME, read off artifact step tool names, never prose
  - instruction: verify: per run, paste loop.`curated_schemas`' offered names at depth 0 (the gap row 56 recorded) and the tool-name histogram over steps
  - honesty: For every A7 run the artifact's offered-tools list contains both subagent/subagents AND the six purpose tools, and the delegation cell names each called tool with its count read from Step.tool; a run whose offered list lacks either half is VOIDED, not averaged
- P3: a NEW staged overlay docs/live-testing/overlays/P3/writer.md (the shipped-off precedent of P0/P1/P2, all 'effort: medium' + a writer `prompt_fragment` replacement) carrying an explicit size TRIGGER sentence — e.g. 'when the survey does not fit in one pass, hand parts to `code_survey` and review the digests' — run on the large-surface brief, n=3, against a NEW control arm on the SAME brief, n=3 (the large brief has no control today, which is what made A6-vs-A5 unreadable)
  - instruction: verify: diff -u overlays/P2-0/writer.md overlays/P3/writer.md shows one + line; head of P2-0 == head of P2
  - honesty: The P3 overlay diffs against P2-0 by exactly one added sentence, and P2-0 equals P2's first paragraph byte-for-byte after the effort line — so the trigger sentence is the ONLY moving contrast
- P3's promotion rule is the spec's q3, written into the row before the first run: delegation rate up AND turns + reasoning chars not up versus the control (`compare_arms` --bar-wall 1.2 --bar-turns 1.0 as rows 52-58 did); a miss or a null is written as such (c46). Until promotion the trigger lives ONLY in the overlay: tests/snapshots/`prompttext_v1`.txt and `BUILTIN_ROLES`\['writer'\].`prompt_fragment` are untouched by the arm
  - instruction: verify: git log -1 --format=%cI on the row commit vs the artifacts' `started_at`
  - honesty: The q3 rule and its three numbers are written into the P3 row at a SHA that predates the first P3/P2-0 artifact timestamp; promotion is taken only if delegation rate(P3) > rate(P2-0) AND mean turns(P3) <= mean turns(P2-0) AND mean reasoning chars(P3) <= control's
- A7 + P3 + the P2-0 control run as ONE matrix (9 runs) on the EXISTING fixture — scripts/`make_large_surface_fixture.py` + docs/live-testing/briefs/arm-large-surface.md (13.7 KB), rows 57-58 precedent — on the tip that ships the add-knob and the P3 overlay, with every row (59+) pre-registered in docs/live-testing.md before the first run; cost ~9 x 586 s ≈ 1.5 h of rig, arms sequential because the local GPU serializes
  - instruction: verify: row commit timestamp < earliest artifact; fixture counts pasted per row
  - honesty: Rows 59-61 exist in docs/live-testing.md, with their pass bars, at a SHA earlier than any of their artifacts; all 9 artifacts cite the SAME fixture generator output (per-file line/byte counts match the row) and the SAME tip SHA family
- Prompt describes, never grants: a hire is a runtime overlay on a BUILTIN role — replace(`BUILTIN_ROLES`\[base\], `prompt_fragment`=authored), exactly the shape roles.`load_role` gives an operator .colleague/agents/<role>.md overlay (prompt replaced, allow-list kept). Cortex picks base from the builtin names only (scout/reviewer/validator/planner/writer), never a tool list; the child's surface is the base allow-list minus actingsurface.`strip_child_forbidden_tools` (children never hold purpose, hire or raw delegation tools), so authority ⊆ hirer holds by construction; the authored text and its digest land on TaskResult
  - instruction: verify: tests/`test_hire.py`::`test_prompt_never_grants` over `BUILTIN_ROLES`
  - honesty: A parametrised test proves, for every builtin base and for an authored prompt that explicitly names write/delegation tools, that the hire's rendered surface == base allow-list minus `PURPOSE_TOOL_NAMES` minus `CHILD_FORBIDDEN_TOOLS` minus {`hire_colleague`, `assign_to_colleague`} — the prompt text changes nothing about the surface
- Byte-identical off-state by opt-in knob: `COLLEAGUE_HIRE`=1 (the `purpose_schemas`.`hidden_names` precedent that hides `web_survey` without webglass) is what puts the two schemas on the seat; unarmed = zero wire change, pinned by the tests/`test_purpose_tools_byte_identical.py` pattern. Armed + empty roster differs from unarmed by exactly the two schemas and one prompt sentence — an armed run that never calls hire is otherwise identical
  - instruction: verify: extend tests/`test_purpose_tools_byte_identical.py` with a `COLLEAGUE_HIRE`=1 no-call case that diffs the offered list and prompt
  - honesty: With `COLLEAGUE_HIRE` unset the byte-identical suite passes unchanged against its reference fixture; with it set and no hire call, the offered-tools list differs from unarmed by exactly {`hire_colleague`, `assign_to_colleague`} and the composed prompt by exactly one sentence
- Negotiation is bounded: one tools-off candidate completion (same cortex model, effort from the seat table) per round, at most 2 rounds; the candidate returns accept / amend (purpose + when) / decline; a failed agreement is the tool RESULT 'not hired' with no roster entry, costing the caller one step like a refused purpose (h30) — never a crashed drive
  - instruction: verify: tests/`test_hire.py`::`test_negotiation_bounded`
  - honesty: A mock-engine test drives two candidate declines and asserts: tool result starts with 'not hired', roster length 0, exactly 2 candidate completions were made, and the caller's `step_count` advanced by 1
- Caps: hires per run <= `MAX_SUBAGENT_FANOUT` (4); an assignment spawns through subagents.`run_subagent` under `MAX_SUBAGENT_DEPTH` 4 / `MAX_SUBAGENT_TOTAL` 24 with `charges_budget` by base role (read-only bases exempt, c34); `hire_colleague`/`assign_to_colleague` join `_NOT_INHERITABLE` and `strip_child_forbidden_tools` so a hire can never hire
  - instruction: verify: tests/`test_hire.py` caps + a depth-1 `curate_for_depth` assertion
  - honesty: A 5th `hire_colleague` call in one run returns a readable refusal (no exception) and the roster stays at 4; a depth-1 child's offered tools contain neither `hire_colleague` nor `assign_to_colleague`; an assignment whose base is writer decrements the same `MAX_SUBAGENT_TOTAL` budget a manual subagent would
- Measurement pre-registered before the build: the hypothesised winning brief shape — repeated, similar sub-tasks across one long run, where one hire amortises over many assignments — has NO brief under docs/live-testing/briefs/ today, so a new brief + deterministic fixture generator is a prerequisite; the comparison arm is one-shot purpose tools on the same brief; hiring is strictly heavier than `code_survey` so the live risk is 0/N calls, and a null is publishable (c46)
  - instruction: verify: the three paths exist at the row's SHA; the row's pass bar contains a numeral
  - honesty: Before the first hire-arm run the tip carries: the new brief under docs/live-testing/briefs/, its deterministic fixture generator under scripts/, and a pre-registered row naming the comparison arm (one-shot purpose tools, same brief), n, and a pass bar with a delegation count

## Honesty conditions

- Exactly two deliverables come out of this frame — the arms PR (A7 + P3 + P2-0, v1.69.0) and the hire-increment spec — and neither contains any code path where the runtime picks a tool, model or hire on cortex's behalf
- git diff main -- scripts/`compare_arms.py` is empty at every SHA any of the 9 runs executed on
- The spec has a 'who reads what' line for each of the two audiences and no claim in it describes the runtime deciding for cortex
- Rows 59-61 have every cell filled from artifacts, and the hire spec contains a confirmed honesty condition for the byte-identical off-state
- The four 'before' facts are each traceable to a cited surface: row 56 (A4 small brief), row 58 (no large control), prompttext.py:131-145 (no trigger), `purpose_schemas`.dispatch (one-shot spawn)
- purpose-tools.md's arc section, after the arms PR, cites the new rows as closing gaps 1 and 2 of #456 and states the result whichever way it fell
- Every number in the three rows has an artifact id beside it; a figure without one is a defect in the row, not a rounding
- The four hire signals are each a test or a row cell: byte-identical suite, offered-list diff == 2, depth-1 surface == 0 of 2, hire arm row with a delegation count

## Success signals

- Arms signal: 9 runs land with 0 voided (or each void named), A7's delegation cell splits by tool name for 3/3 runs, and the P3-vs-P2-0 verdict is written under the q3 rule with the three numbers (delegation rate, mean turns, mean reasoning chars) — all read from artifacts, 0 figures from prose
  - instruction: verify: each row lists 3 artifact ids and the numbers are reproducible with `compare_arms.py` on those ids
- Hire signal: the byte-identical suite is green with `COLLEAGUE_HIRE` unset (0 bytes of wire/prompt/schema difference vs the reference fixture); armed + no call differs by exactly 2 schemas; a depth-1 child lists 0 of {`hire_colleague`, `assign_to_colleague`}; the hire arm's row records its delegation count — including 0/N as a publishable null
  - instruction: verify: name the test ids and the row number in the hire spec

## Scope / boundaries

- scripts/`compare_arms.py` is NOT modified for A7/P3 (the rows-52-58 contract: a modified comparator voids the matrix); its delegations column already counts subagent/subagents OR any `PURPOSE_TOOL_NAMES` step but does not split by tool name, so the per-tool breakdown is read off the artifact steps in the row (or by a new sibling script), never by editing the comparator
  - instruction: verify: record the diff check beside each run's SHA in the row

## Non-goals

- A7 never changes the default allow-list regardless of its result: the raw pair does not return to the shipped acting seat (arm 4 rejected on evidence, PR #455 / row 56 addendum); a 'cortex prefers subagent over `code_survey`' finding is recorded and reasoned about in purpose-tools.md, not auto-promoted
- OUT of the first increment: persistence across runs (a repo-scoped .colleague/employees/), firing, hire-to-hire delegation, LLM-judged relevance, any automatic task->hire dispatch, and leaning on colleague/policy.py for containment (a policy gate, not a sandbox — an authored prompt is contained by the allow-list, not by approvals)

## Assumptions

- A7 instrument: issue #456's 'leave `COLLEAGUE_ACTING_DROP_TOOLS` unset' does NOT put the raw pair on the seat on the current tip — roles.`_writer_allowlist` (roles.py:133-160) drops web/subagent/subagents unconditionally since arm 4's revert, and tools.`narrow_role_by_tool_set` has `tool_set`/drop but no add. A7 needs an ADD instrument: a `COLLEAGUE_ACTING_ADD_TOOLS` knob at the SAME depth-0 seam (actingsurface.`curate_for_depth`), unset = byte-identical, reverting by unset (spec s25 reversibility), never reaching a child — `CHILD_FORBIDDEN_TOOLS` keeps stripping the pair at depth >= 1
  - instruction: implement `COLLEAGUE_ACTING_ADD_TOOLS` beside `ACTING_DROP_ENV` in actingsurface.py; add applies at depth 0 after the drop; tests mirror tests/`test_acting_drop_knob.py`; unset = byte-identical pinned
- A7 known confound, pre-registered: the shipped t9 prompt (prompttext.`_PURPOSE_TOOLS`, prompttext.py:131-145) names the six purpose tools and NOT subagent/subagents, so under A7 the raw pair is offered-but-undescribed in prose (schema description only, the inverse of the c2/h10 defect). No prose overlay is added to A7 to correct this — it would confound the surface arm with the prose arm — and the asymmetry is written into the row
- The honest P3 control is NOT the P0 overlay #456 names: A6 (row 58) ran P2, and P2's first paragraph ('a peer seat drawn from the same model family') is the TRUE description on this rig — config show reports lobes armed with senses/muse/associate `not_consumed`, so a scout child runs on cortex itself — while P0's 'runs considerably quicker, reasoning switched off' sentence is untrue here. Control = P2's first paragraph ALONE (P2-0); P3 = P2-0 + the trigger sentence; both lose the builtin fragment identically so the trigger is the only moving contrast, the A3-vs-A1 shape
  - instruction: write overlays/P2-0/writer.md as P2's effort line + first paragraph; P3 = P2-0 + the trigger sentence; both staged, never shipped defaults
- Rig facts at scope time (uv run colleague config show, 2026-08-30): lobes armed at <http://localhost:8001>, cortex = unsloth/Qwen3.8-27B-NVFP4, senses/muse/associate advertised but not consumed, `reasoning_effort` unset, timeout 120, `max_steps` 40; tip main daedbc6 v1.68.0 — every arm row cites the SHA it ran on (deviation d1 precedent)
- agents/profile.py's AgentProfile cannot carry a hire as-is: purpose is a CLOSED set (PURPOSES = talker/worker/`thinker_coder`/associate, refused in `__post_init__`), `SCHEMA_VERSION` 1 with fail-closed readers, and no prompt/when fields. A hire is a NEW typed record (Hire: hirer id, base builtin role, authored `prompt_fragment` + its `prompt_digest_for`, the when clause, lineage, `task_id`) that may REFERENCE an AgentProfile; #411's record stays untouched
- The tool surface and system prompt are fixed ONCE per run (`vllm_openai.py`:1320 `curated_schemas`, :1341 `system_prompt`, :1387 `prompt_digest`), so: `assign_to_colleague` must be on the seat from run start and refuse readably ('no live hire') on an empty roster; and a hire's when-hint cannot be a per-turn system-prompt edit — the only per-turn injection seams are the tool result itself, the flight-guidance user-turn (loop.py ~2293-2319) and #206 phase notices (never advancing `step_count`)
- In the run-scoped first cut the when clause drives no gate: cortex hires for the task at hand, so relevance is trivially true and the whole roster (<= cap) is what exists. when is captured at hire time and recorded (data for the persistence follow-up); the pre-committed rule for that follow-up is DETERMINISTIC relevance (the frontdoor.py classifier shape: enumerated triggers, ambiguous -> SHOW, fail open on presentation), and LLM-judged relevance is excluded by name
- Sequencing — the three join rather than compete: A7 + P3 are cheap (~1.5 h) and inform the hire spec — P3 tests a GENERIC size trigger, the when clause is a SPECIFIC per-hire trigger; if P3 promotes, when's unique value shrinks to persistence; if P3 nulls, when stays the untested specific-trigger hypothesis. Run A7+P3 first (one PR: add-knob + P3 overlay + rows, v1.69.0), then /think the hire increment with P3's result as an input
  - instruction: sequence: arms PR first (add-knob + P2-0 + P3 overlays + rows 59-61, run, record, v1.69.0), then /challenge + /spec-to-plan the hire spec with the P3 verdict cited

## Scope exploration

- `s1` — `colleague/roles.py _writer_allowlist (133-160)`: drops web/subagent/subagents unconditionally since arm 4's revert; unsetting the drop knob cannot restore the raw pair — A7 needs an add instrument
  - seeds: `c2`, `c3`
- `s2` — `colleague/actingsurface.py curate_for_depth + CHILD_FORBIDDEN_TOOLS`: the ONE depth-aware seam; an add knob mirrors the t8 drop knob there and children keep the raw pair stripped regardless
  - seeds: `c3`, `c19`
- `s3` — `colleague/tools.py narrow_role_by_tool_set (634)`: signature is `tool_set`/drop only — no add path exists today
  - seeds: `c3`
- `s4` — `colleague/prompttext.py _PURPOSE_TOOLS (131-145)`: the shipped delegation prose names the six purpose tools, gives permission + brake, no size trigger, and does not name subagent/subagents — A7's raw pair would be offered-but-undescribed
  - seeds: `c4`, `c7`
- `s5` — `scripts/compare_arms.py`: delegations column counts subagent/subagents OR `PURPOSE_TOOL_NAMES` steps without a per-tool split; the arc rule forbids editing it mid-matrix
  - seeds: `c5`
- `s6` — `docs/live-testing.md rows 52-58 + row 56 addendum`: A4 (raw pair, small brief) 0/3; A5 2/3 delegating (3 calls each), A6 12 calls; zero raw-pair calls in 21 runs; large brief has no control; wall ~586 s/run; cells contract and the d1 tip-pin rule
  - seeds: `c2`, `c6`, `c10`, `c11`
- `s7` — `docs/live-testing/overlays/P0,P1,P2/writer.md`: each replaces the builtin writer fragment; P0/P1 claim a quicker reasoning-off seat (untrue on this rig), P2 claims a same-family peer seat (true); P1/P2 add the same imperative paragraph — the clean control for the large brief is P2's first paragraph alone
  - seeds: `c7`, `c8`
- `s8` — `docs/live-testing/briefs/arm-large-surface.md + scripts/make_large_surface_fixture.py`: the 12-module ~60 KB/module fixture and its generator exist and are reproducible; A7/P3 reuse them unchanged
  - seeds: `c10`
- `s9` — `docs/specs/2026-08-29-purpose-tools-get-chosen.md q3 + c46`: the pre-committed promotion rule (delegation up AND turns/reasoning not up) and the null-is-publishable claim carry over verbatim
  - seeds: `c9`, `c21`
- `s10` — `uv run colleague config show (rig, 2026-08-30)`: lobes armed localhost:8001, cortex Qwen3.8-27B-NVFP4, associate not consumed so scout children run on cortex
  - seeds: `c11`, `c8`
- `s11` — `colleague/purpose_schemas.py + colleague/efforttables.py PURPOSE_*`: six static tables keyed by tool name, schemas expose no effort/model/role property, dispatch spawns via executor.`_spawn` with a fixed role/rung/steps — a negotiated purpose has no row here
  - seeds: `c12`
- `s12` — `colleague/agents/profile.py AgentProfile`: purpose is a closed set refused in `__post_init__`, schema v1 fail-closed, no prompt/when fields — a hire needs its own record
  - seeds: `c13`
- `s13` — `colleague/agents/tools.py + messages.py + state/ledger.py (#411)`: typed messages bounded by `MAX_AGENT_MESSAGES`, append-only JSONL ledger, `_NOT_INHERITABLE` already lists the raw pair + deepthink + purposes; all of it is live only when `COLLEAGUE_AGENTS` is armed (loop ctx.agents=None otherwise)
  - seeds: `c19`, `c17`
- `s14` — `colleague/roles.py load_role/_resolve_role_prompt + Role dataclass`: operator overlays replace `prompt_fragment` and keep the builtin allow-list — the exact shape a cortex-authored hire prompt should take
  - seeds: `c14`
- `s15` — `colleague/engines/vllm_openai.py work() 1320/1341/1387`: `curated_schemas` and the system prompt are composed once per run and digested; nothing rebuilds the surface mid-run
  - seeds: `c15`, `c16`
- `s16` — `colleague/loop.py flight control (2293-2319) + #206 phase notices`: the only per-turn injection seams: guidance as a user-role turn, phase notices that never advance `step_count`
  - seeds: `c15`
- `s17` — `colleague/frontdoor.py`: the deterministic enumerated-signal classifier with ambiguous -> the safe default — the precedent for deterministic when-clause relevance
  - seeds: `c16`
- `s18` — `colleague/config.py MAX_SUBAGENT_DEPTH/FANOUT/TOTAL (353-355) + colleague/subagents.py run_subagent`: 4/4/24 and the purpose= spawn kwarg; a hire assignment rides the same spawn path
  - seeds: `c19`
- `s19` — `tests/test_purpose_tools_byte_identical.py + test_purpose_schemas/boundary, test_roles_confinement, test_agents_tools`: the byte-identical pattern to reuse and the six-count / not-inheritable pins a seventh-and-eighth tool would trip
  - seeds: `c17`, `c19`
- `s20` — `docs/live-testing/briefs/ (6 briefs)`: no repeated-similar-sub-tasks brief exists; the hire arm needs a new brief + fixture
  - seeds: `c21`
- `s21` — `colleague/policy.py`: checksum/token policy gate, explicitly not a sandbox — cannot contain an authored prompt
  - seeds: `c20`
- `s22` — `issues #456 + #457 (+ operator comment: roster starts empty, when clause, deterministic relevance)`: the three ideas join: arms first, hire spec after, with P3 as an input to the when-clause hypothesis
  - seeds: `c22`

## Decisions

- `hire_colleague` is a TWELFTH sanctioned increment with its own spec, not a seventh `PURPOSE_TABLE` row: the six purpose tables (`purpose_schemas`.`PURPOSE_TOOL_NAMES`/`PURPOSE_ROLE`/`PURPOSE_SCHEMAS`, efforttables.`PURPOSE_TABLE`/`PURPOSE_STEPS`, agents/tools.`THINKER_CODER_TOOLS`/`_NOT_INHERITABLE`) are static purpose -> role -> seat + rung maps and test-pinned at six; a negotiated purpose has no static row. It must be argued as a fixed enumerated surface (two tools, `hire_colleague` + `assign_to_colleague`, called explicitly), never an automatic task->model dispatch
- P3's control is P2-0: docs/live-testing/overlays/P2-0/writer.md = P2's first paragraph alone (effort: medium); P3 = P2-0 + one trigger sentence (q2)
- A7's instrument is `COLLEAGUE_ACTING_ADD_TOOLS` — a comma-separated add-set applied at depth 0 only in actingsurface.`curate_for_depth`, mirroring the t8 drop knob; unset = byte-identical; children still stripped by `CHILD_FORBIDDEN_TOOLS` (q3)
- A winning P3 trigger promotes into prompttext.`_PURPOSE_TOOLS`, conditional on gating that section to the top-level acting seat in the same PR (it renders for every seat today, incl. children that hold no purpose tool); if the gate is not taken, the writer `prompt_fragment` is the target (q4)
- `hire_colleague` lives on the DEFAULT seat behind `COLLEAGUE_HIRE`=1: roster on the executor, hires + assignments on TaskResult with `prompt_digest_for`(authored); when `COLLEAGUE_AGENTS` is also armed a task-ledger event is emitted too; agents mode is never required (q5)
- Negotiation is at most 2 candidate rounds, each one tools-off completion on the cortex model; unresolved after round 2 = the tool result 'not hired', no roster entry (q6)

## Open parks

- [unknown_nonblocking] Whether flight stop reaches a hire's running assignment — purpose-tools v7 left this unverified for purpose children
- [unknown_nonblocking] Attestation: a roster-bearing seat makes `prompt_digest` vary per run once persistence lands; arm rows over such a seat need a digest-of-the-static-part or must accept per-run digests
- [follow_up] Persistence follow-up: repo-scoped .colleague/employees/, firing, roster cap + staleness when a lobes role vanishes (the c11/h8 same-role refresh analogue), deterministic when-clause gating
