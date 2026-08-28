# Delivery Summary — purpose-tools-associate-seat

plan: `purpose-tools-associate-seat` · run: `partial` · date: `2026-08-28`
baseline: `devague summary skeleton`

## Intent

Deliver the purpose-tools arc (issues #443 + #442): replace raw `web` /
`subagent` / `subagents` on cortex's acting surface with six typed purpose
tools — `web_survey` / `code_survey` (a scout child, on the associate seat
when armed), `review` / `validate` / `plan` (reviewer / validator / planner
children on cortex) and `handover_to_colleague` (a writer child on cortex) —
each a fixed purpose → fixed role → fixed seat + rung; split the associate
seat's effort per sub-seat (`distill` = `low`); plumb a real rung into the
detached distill child; and measure delegation on pre-registered live rows
49/50. The plan executed is `docs/plans/2026-08-28-purpose-tools-associate-seat.md`
(14 tasks / 8 waves, plus `t15` added mid-run for deviation `d14`), fanned out
by `/assign-to-workforce` on `spec/purpose-tools-associate-seat` from base
`8fc8b5e`. The run is `partial` because every code task merged but the
measured hypothesis (row 49 delegation bar, row 50 final-answer clause)
**missed** — written as a miss, per the pre-registration.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — t1 effort tables: `ASSOCIATE_SEAT_TABLE` + `PURPOSE_TABLE` + `PURPOSE_STEPS` in a NEW module, with env/config overrides for the two new groups
- `t2` — t2 associate seat builders consume the sub-seat rung
- `t3` — t3 distill child: effort plumbing, raised `max_tokens` when a rung is on, 'length' failure reason
- `t4` — t4 `purpose_schemas.py`: the six purpose tool schemas, `PURPOSE_ROLE`, hidden-state rule, brief templates
- `t5` — t5 surface curation: cortex/worker offer purposes, lose web + subagent + subagents; tool profiles
- `t6` — t6 purpose executor: spawn with fixed role/rung/`max_steps`; budget-exhausted marker; arithmetic exemption
- `t7` — t7 parent-side reporting + one work-item web budget across purpose children
- `t8` — t8 armed-agents ⊆ exemption for purpose delegations
- `t9` — t9 `compare_arms`: purpose steps in delegations + `associate_calls`
- `t10` — t10 delegation prose + config show / /effort render the three rung groups
- `t11` — t11 docs: purpose-tools.md feature doc, thinking-effort tables, web-scout q3 superseded, adopt doc scout=off, CLAUDE.md increment (1) clause
- `t12` — t12 pre-register live rows 49/50 + briefs BEFORE any run
- `t13` — t13 guards + byte-identical suite + all-engines e2e
- `t14` — t14 live proof: baseline re-run + rows 49/50 + `compare_arms`

Added mid-run (recorded on the plan as `t15`, proposed — see `d14`):

- `t15` — t15 (d14): the bare top-level acting seat + TAE worker get the purpose-tool swap; children never hold purpose tools; handover writer child loses web/subagent too

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `colleague/efforttables.py` (`ASSOCIATE_SEAT_TABLE`, `PURPOSE_TABLE`, `PURPOSE_STEPS`, override readers, precedence resolvers); `config.py` `reasoning_effort_purposes` + `associate.<seat>` keys; pins in `tests/test_effort.py` — merge `477504b` (sonnet, after the colleague lane stalled: `d2`) |
| `t2` | delivered | `associate_engine_config(config, sub_seat=None)`; `scout_child_config` / `make_associate_complete` / `distill_author` resolve the sub-seat rung; `DistillAuthor.effort` — merge `cfbb0e4` (colleague: red tests `ae21579f3f9a` + continuation `b9cb1dcb5cd2`, `d5`) |
| `t3` | delivered | `colleague/distilleffort.py`; distill child `--effort` argv, `chat_template_kwargs` on the raw POST, one ladder-400 retry, `max_tokens` 4096→≥12288 when a rung is on, `reasoning exhausted max_tokens` failure reason — merge `2cc26ec` (sonnet, after the colleague lane stalled: `d11`) |
| `t4` | delivered | `colleague/purpose_schemas.py`: six schemas (no effort/model/engine/role property), `PURPOSE_ROLE`, `offered`/`hidden_names`, `brief_for` — merge `0870988` (colleague `72540eb07edd`) |
| `t5` | delivered | writer allow-list + `WORKER_TOOLS` / `THINKER_CODER_TOOLS` swap; `TOOL_PROFILES` for the six; `CONSEQUENTIAL_TOOLS` + `handover_to_colleague`; `loop.resolve_role` narrowing-guard fix (`d6`) — merge `4674377` (sonnet). The swap did NOT reach the bare run (`d14`) — completed by `t15` |
| `t6` | delivered | `purpose_schemas.dispatch`: fixed role/rung/`max_steps` spawn, budget-exhausted marker, `charges_budget` exemption, `served_model` on the parent step — merge `3474234` (opus). Finding `d9`: no `sub/<id>` worktree on the single-child path |
| `t7` | delivered | one work-item web budget across purpose children (`ChildSpec.web_calls_remaining`, counters fold back), parent-side `urls fetched:` block + report line, purpose override seam via `make_spawn.parent_config` (`d12`) — merge `d4e5e1a` (sonnet) |
| `t8` | delivered | `DelegationRequest.purpose`; purpose delegations exempt from `requested_tools ⊆ parent`, manual superset still refused; web-scout honesty line 33 marked superseded — merge `593b221` (sonnet) |
| `t9` | delivered | `compare_arms.py` counts the six purpose names in `delegations` / `associate_calls`; pre-landed the `purpose_schemas.py` stub (`d4`) — merge `3864152` (colleague `d12408b86b6d`) |
| `t10` | delivered | armed-facts sentence on `web_survey`/`code_survey` (not `handover_to_colleague`, `d8`); `config show` + session `/effort` render seats / `associate.<seat>` / purposes (`_effort_groups.py`) — merge `af8a211` (sonnet, after the colleague lane stalled: `d7`) |
| `t11` | delivered | `docs/features/purpose-tools.md` (colleague `6963eccfb210`); CLAUDE.md increment (1) clause + Web scout bullet; `thinking-effort.md` two new tables; adopt doc `scout=off` — merge `3b1d4e3` |
| `t12` | delivered | rows 49/50 pre-registered + briefs + `tests/test_live_rows_49_50_preregistration.py` — merge `e458cac` (colleague `a8da10e42059`, incomplete-but-delivered, parser fix by the integrator: `d3`) |
| `t13` | delivered | `tests/test_purpose_tools_boundary.py`, `tests/test_purpose_tools_byte_identical.py` + `e589451` fixtures, all-engines purpose-step shape, review fixes (marker keyed on reason; handover scope sentence) — merge `95520cb` (sonnet) |
| `t14` | partial | main baseline re-run n=3, branch n=3, row 50 run; rows 49/50 filled (commit `0598396`). **Row 49 MISS** (0/3 purpose calls, turns 1.18×); **row 50 MISS on the bar** — mechanism proven (`web_survey` ×3 on the associate seat, zero `run_command`), cortex stalled before the final answer; served model recorded as the wire alias only |
| `t15` | delivered | `colleague/actingsurface.py` + `child_depth` stamp: bare top-level seat + TAE worker offer the six purposes and never the three raw tools; children never hold purposes — merge `80b4138` (sonnet); resident peer turns withhold `web_survey` too — `36a04cb` (`d15`) |

## Mid-work Decisions

All fifteen deviation records were proposed via `/deviate` during the run and
are **pending operator confirmation** (`devague deviate --list`); they are
quoted here as recorded, not re-litigated.

- `d1` — the confirmed announcement/after-state still say "the multi-turn scout keeps its thinking history" — dropped by q8 / non-goal c41 (#446); the plan does not build it
- `d2` — t1 colleague lane stalled (0 files, turns averaging 369 s) → reassigned to sonnet — a config.py-class large-file edit
- `d3` — t12 colleague run ended INCOMPLETE but had delivered the whole deliverable; the integrator fixed the test's own parser (5-column matrix)
- `d4` — t9 pre-landed `colleague/purpose_schemas.py` as a 26-line stub exporting `PURPOSE_TOOL_NAMES` so the script imports one list
- `d5` — t2 colleague run stalled after writing the 7 red tests; retried once as a narrowed "make them pass" continuation lane (worked)
- `d6` — t5 fixed a latent bug: `loop.resolve_role`'s strict-subset narrowing guard would silently fall through to the full surface once purpose names exist
- `d7` — t10 colleague lane through the gateway stalled (1089 s turn past the 900 s guard, #438) → SIGTERM'd, sonnet; the unscoped dogfood review also step-stalled at step 3
- `d8` — the brief/plan said to splice the armed-scout sentence onto `handover_to_colleague`; the spec (c12) names only `web_survey`/`code_survey` — reverted before merge
- `d9` — spec c28/h26 assumed a `sub/<id>` worktree per purpose child; `run_subagent` creates none (stale docstring) — documented, no behaviour change
- `d10` — t6 left the per-purpose override seam unset; t7 threaded it
- `d11` — t3 colleague lane stalled as the SOLE lane (read-heavy brief) → sonnet
- `d12` — t7 threaded the overrides via `make_spawn`'s closure because `loop.py`'s default `ToolExecutor(` site is unreachable in production
- `d13` — the scoped dogfood review (`0e9fdacaba63`) returned BLOCK on the kill-switch seam — true on the reviewed tip, already fixed by t7; its two minor findings went to t13
- `d14` — the swap never reached the BARE run (t5 changed only the writer role's allow-list); new task t15 fixed it — classified **risky**
- `d15` — t15 broke the resident web-trust pin (operator seat now holds `web_survey`, not `web`); the integrator applied park v6's default (peer turns withhold `web_survey` too)
- Not covered by a record: the wave-1+2 `ask-colleague review` was re-run **scoped to two modules** after the unscoped one stalled — the scoped form delivered a cited verdict in 16 steps.
- Not covered by a record: the row-49 main baseline ran through the lobes gateway with cortex served on two machines, so wall spread 119–628 s across hosts — recorded on the row as a confound on the wall column.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t1` (`d2`) | the brief mixes a new module with net-zero hunks in config.py — the large-file edit class colleague times out on | acceptable |
| `t12` (`d3`) | honest-incompletion soft rule: a substantive non-meta finish = delivered; the parser fix is a 6-line test-only touch-up | acceptable |
| `t9` (`d4`) | the t9 brief said 'import the purpose names, no duplicate list' and t4 had not landed yet; the stub is the agreed single source | acceptable |
| `t2` (`d5`) | TDD red half delivered; the implementation is small and now fully specified by the tests | acceptable |
| `t5` (`d6`) | the surface change exposed the guard; leaving it would have made worker/thinker_coder narrowing a no-op in agents mode | acceptable |
| `t10` (`d7`) | under 3-4 concurrent lanes every colleague turn runs 5-18 min; the gateway did not help; the stream-lifetime guard does not fire on this path (#438) | acceptable |
| `t10` (`d8`) | plan/brief drift from the spec, caught by the sonnet agent's flag | acceptable |
| `t6` (`d9`) | the spec cited a docstring, not the code path; no behaviour change made | needs-follow-up |
| `t6` (`d10`) | t6's brief scoped the executor, not the loop wiring; c37/h35 need the override to reach the child | acceptable |
| `t3` (`d11`) | read-heavy brief spanning distill.py + associate_seats + loop.py seam; contention was NOT the cause this time | acceptable |
| `t7` (`d12`) | the brief's suggested wiring point was dead code; the agent chose the live seam and proved it | acceptable |
| `t13` (`d13`) | review of a moving tip; findings verified before acting | acceptable |
| `t5` / `t13` (`d14`) | spec c4/c23/h1 name the bare 'colleague work' surface; the plan's t5 wording let the role-less default path slip through | risky |
| `t15` (`d15`) | the swap reached the resident front through the shared top-level seat; the security property is preserved and now covers the purpose path | acceptable |
| `t11` (`d1`) | the exported spec's headline carries a claim the plan does not build — the feature doc states it is out of scope (#446) | acceptable |
| `t14` | the pre-registered bars missed: row 49 turns 1.18× and 0/3 purpose calls; row 50 no final answer (cortex step-stall, #438) and the served model recorded as the wire alias only (in-process children persist no artifact) | needs-follow-up |

## Evidence

- tests: full suite `uv run pytest -n auto -q` on `36a04cb` — **10363 passed, 26 skipped, 0 failed** (per-merge gates: 10124 → 10136 → 10165 → 10188 → 10200 → 10232 → 10269 → 10275 → 10314 → 10317 → 10345 → 10363; every merge suite-green before and after)
- tests: `tests/test_actingsurface.py`, `tests/test_purpose_tools_byte_identical.py`, `tests/test_purpose_tools_boundary.py`, `tests/test_purpose_executor.py`, `tests/test_purpose_web_budget.py`, `tests/test_purpose_schemas.py`, `tests/test_distilleffort.py`, `tests/test_effort_groups.py`, `tests/test_agents_delegation.py`, `tests/test_resident_web_trust.py`, `tests/test_live_rows_49_50_preregistration.py` — pass
- tests: `tests/test_file_length_ratchet.py` — pass on every merge (`tools.py` 1508, `loop.py` 5281, `subagents.py` 1694, `effort.py` 280, `distill.py` 804 unchanged)
- lint: `black --check`, `isort --check-only`, `flake8`, `bandit -c pyproject.toml -r colleague`, `teken cli doctor . --strict`, `markdownlint-cli2` — clean on `36a04cb`/`ff332ce`
- commits: `8fc8b5e..ff332ce` on `spec/purpose-tools-associate-seat` (16 `--no-ff` task merges + 3 integrator commits)
- live rows: `docs/live-testing.md` rows 49–50; artifacts main `70eb4ddcb69c` `1abb0335ad27` `df76184e7eca`, branch `78b0f0f90855` `480b6d6ea857` `59fb72435645`, row 50 `0780c75e2519`, smoke `6ce1ed9bd8fe`; `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` → branch wall 0.271 / turns 1.176 MISS
- dogfood: `ask-colleague review` `de61d945192e` (unscoped, stalled step 3) and `0e9fdacaba63` (scoped, BLOCK verdict, graded 4/5 in the feedback store); colleague lanes `2efba884e43f` `a8da10e42059` `d12408b86b6d` `72540eb07edd` `ae21579f3f9a` `b9cb1dcb5cd2` `09a4292aa7df` `5db5e4b35a5e` `6963eccfb210`
- PRs / issues: #443, #442, #435, #436, #439 (closed), #446 (opened: thinking continuity), #438 (comment: 7-run stall table)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| a bare `colleague work` offers exactly the six purpose tools and never raw `web`/`subagent`/`subagents`; children are never offered a purpose tool | high | commit `80b4138` · file `colleague/actingsurface.py` · test `tests/test_actingsurface.py` |
| purpose tools spawn a fixed role at a fixed rung with a fixed step cap; read-only purposes do not charge `MAX_SUBAGENT_*`; `handover_to_colleague` does | high | commit `3474234` · test `tests/test_purpose_executor.py` |
| a purpose child's rung comes from `PURPOSE_TABLE` (operator-overridable), never the parent's rung or the global rung; the `default` kill-switch still wins | high | commits `477504b` `d4e5e1a` · tests `tests/test_effort.py`, `tests/test_purpose_web_budget.py::test_reasoning_effort_kill_switch_overrides_the_purpose_table` |
| the associate seat resolves per sub-seat (`distill` = `low`) and the detached distill child sends a real rung, raises `max_tokens`, retries once on a ladder-400, and records `length` as its own failure reason | high | commits `cfbb0e4` `2cc26ec` · tests `tests/test_associate_seats.py`, `tests/test_distilleffort.py` |
| one work-item web budget spans purpose children and the parent reports every URL the child fetched | high | commit `d4e5e1a` · test `tests/test_purpose_web_budget.py` · row 50 `web_calls` 20 across three children |
| purpose delegations are exempt from the armed-agents `⊆ parent` check; manual supersets are still refused | high | commit `593b221` · test `tests/test_agents_delegation.py` |
| the unset-knob run is byte-identical to `e589451` except the named cortex surface carve-out | high | test `tests/test_purpose_tools_byte_identical.py` · fixtures `tests/fixtures/e589451_baseline/` |
| with raw `web` absent, cortex delegates web reading via `web_survey` to scout children on the associate seat and never probes the host | high | row 50 artifact `0780c75e2519` (`web_survey` ×3, 0 `run_command`, children `served_model`=`associate`) |
| purpose tools make cortex delegate a three-module code survey (row 49 bar) | unverified | row 49: 0/3 purpose calls, turns 1.18× — MISS, not claimed |
| the scout child's served Nemotron id is recorded on an artifact | unverified | in-process purpose children persist no artifact; the parent records the wire alias `associate` only |
| the distill seat fires at `low` on a memory-armed run | unverified | rows 49/50 wrote no lesson (no failure substance / stalled run) — counters not exercised live |
| thinking continuity for the multi-turn scout | (not claimed) | dropped by q8 / `d1`; tracked in #446 |

## Remaining Work / Follow-up

- `t14` — the measured hypothesis missed on the code-survey bar (row 49) and on the final-answer clause (row 50). Next: re-run row 50 once #438's stall recovery lands (the cortex stall, not the tools, cost the answer), and design a row-49 brief whose survey cannot be done by reading three small files — the doctrine (#435) says nothing forces delegation, and this run confirms cortex delegates exactly where the raw tool is absent.
- served-model evidence for purpose children — persist an artifact (or at least the reply's served id) for in-process purpose children so row 50's "served model = the associate's" clause can be verified from the parent. Follow-up issue.
- `d9` — spec c28/h26 and the stale `subagents.py:834` docstring: fix the docstring; decide in a follow-up whether `handover_to_colleague` should get a worktree (today: parent's tree, as manual `subagent`).
- park v5 — manual typed children still inherit the parent's cortex seat override above their `ROLE_TABLE` row; purpose children do not. Follow-up reorder (a non-byte-identical change to #416's pin).
- park v6 — the resident webtrust confirmation still fires on the child's raw `web` call; gating it at the `web_survey` call is undecided (peer turns now withhold `web_survey`, `36a04cb`).
- park v7 — whether `flight stop` reaches a running purpose child is unverified.
- park v2 — purpose tools are not batch-safe; parallel purpose calls serialize.
- #438 — 5 of 10 colleague task lanes and both unscoped reviews stalled in long model turns; the concurrency evidence is on the issue. Only small new-file briefs (t4, t9, t11-doc) and the "red tests exist, make them pass" continuation (t2b) landed on colleague lanes.
- #446 — thinking continuity on the associate scout (carried out of this arc).
- operator confirmation of deviations `d1`–`d15` (`d14` is marked risky) and of plan task `t15`.
