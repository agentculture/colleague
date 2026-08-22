# Delivery Summary — per-seat thinking effort (#416)

plan: `per-seat-thinking-effort-416` · run: `complete` · date: `2026-08-21`
baseline: `devague summary skeleton`

## Intent

Deliver the #416 increment — colleague sends a per-seat thinking setting
(`chat_template_kwargs`: `enable_thinking:false` for off, `reasoning_effort`
for a rung) from a fixed v3 table resolved where each seat is built, never per
turn; operator overrides + a kill-switch; a ladder-400 graceful degrade; effort
as trace data; a retroactive split-next-time record; docs, live proof and a
release — executed as the 12-task / 6-wave plan
`docs/plans/2026-08-21-per-seat-thinking-effort-416.md` via
`/assign-to-workforce` on branch `spec/per-seat-thinking-effort-416`, with
colleague as the intended ~90% doer and Claude (Fable) as the TDD gate owner.
The run log is `docs/experiments/2026-08-22-per-seat-thinking-effort-416-workforce-ledger.md`.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Effort model: colleague/effort.py (NEW) — ladder enum, seat/role/design tables (v3), `resolve_effort` precedence, payload fragment
- `t2` — Config wiring: EngineConfig.`reasoning_effort` + per-seat overrides (env/config.json), `to_dict`, config show
- `t3` — Wire: `_build_chat_payload` emits `chat_template_kwargs` from the seat's effort; ladder-400 retry-once + warning; byte-identical when unset
- `t4` — Main seats carry their table effort: deepthink.py, senses.py (+frontdoor), `tae_loop.py`, agents/runtime.py seat builders
- `t5` — Roles + children: Role.effort field (v3 rows), subagent child builds key on the CHILD role/purpose, explicit parent override recorded, top-level --role rule (explorer low, others = acting seat)
- `t6` — Design call-site: `DESIGN_CALL_SITES` constant; plan `spec_stage` xhigh / `plan_stage` high / workforce xhigh; auto-split + fill-line split + subagent decomposition at xhigh on the cortex seat
- `t7` — Observability: effort as trace data on the #411 ledger invocation record and the OTel work span
- `t8` — Retroactive split-next-time record: too-hard/too-long signals → eidetic lesson on remember-after; recall-before surfaces the split recommendation
- `t9` — Guards + all-engines pins: unset byte-identical across mock and vllm-openai; no per-turn effort writes; result-shape parity
- `t10` — Docs: feature doc with the v3 table + honest limits (#417, probes, n=1), CLAUDE.md (THREE carve-outs + architecture bullet), engines/deepthink/config-resolution/roles docs, doc-test alignment
- `t11` — Live arm + success signals: tests/`test_vllm_live_thinking_effort.py` (gated) and the in-session live run on explorer/reviewer/validator/planner children
- `t12` — Release: version bump (minor), CHANGELOG, PR via cicd, address review

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `colleague/effort.py` (ladder, v3 tables, `resolve_effort`, `to_chat_template_kwargs`, `validate_effort`) + `tests/test_effort.py` — commit `4fc649a` (sonnet, d1) |
| `t2` | delivered | `EngineConfig.reasoning_effort` / `reasoning_effort_seats` / `reasoning_effort_effective` (property) / `too_long_min`; `config show` effort table; `to_dict` keys — commits `3434337` `e3b920b` `325b8e4` (sonnet, d1) |
| `t3` | delivered | `vllm_openai._build_chat_payload` emits `chat_template_kwargs`; `_effort_for`; `_is_ladder_400` + retry-once + warning, disjoint from the 404 refresh — commit `7652e47` (sonnet, d1); **note:** the default acting seat now sends `medium` by design (spec c35/c36), so "byte-identical" holds under the kill-switch, not under "nothing configured" |
| `t4` | delivered | deepthink/senses/tae_loop/agents-runtime seat builders set `reasoning_effort_seat` — commits `7149bad` `27347c0` (**colleague @ medium**, 18 min) |
| `t5` | delivered | `Role.effort` (v3 rows, overlay), child builds key on the child, `SubagentSpec.effort` override recorded, tool schema `effort` — commit `1e8efdd` (sonnet, d2) |
| `t6` | partial | `colleague/design.py` + plan spec/plan stages wired end-to-end (xhigh / high) — commit `4b91456` (sonnet, d5); auto-split, fill-line split, decomposition and the workforce stage pinned at the builder level only — no dedicated completion exists (d6) |
| `t7` | delivered | `effort.effort_of`, `InvocationRecord.reasoning_effort` (omitted when unset), OTel `work_span(reasoning_effort=…)` — commit `e55aa5a` (sonnet, d4) |
| `t8` | delivered | `memory.should_record_split` / `build_split_record` / `maybe_remember_split`, recall renders the split recommendation first — commit `1cb8927` (sonnet, d3) + gate-owner wiring `04113ed` (call site in the remember-after lane; `too_long_min` threaded via `ContextControls` → `_Work` → `run()`) |
| `t9` | delivered | `tests/test_thinking_effort_boundary.py` (AST guard) + `tests/test_thinking_effort_payload_fixture.py` — branch `colleague/196386eda99b-…` (**colleague @ medium**, 18 min) |
| `t10` | delivered | `docs/features/thinking-effort.md`, CLAUDE.md bullet + THREE carve-outs, engines/deepthink/config-resolution/subagent-roles docs, `tests/test_thinking_effort_docs.py` — branch `colleague/452a40222413-…` (**colleague @ medium**, 20 min) |
| `t11` | delivered | `tests/test_vllm_live_thinking_effort.py` (3 passed LIVE), `docs/live-testing.md` row 39 (a–d) — commits `46640f2` `8cdc9a5` (Claude); the in-session live fan-out `ad5c5a1a76ae` + final run `7968b1281593` (colleague children by role) |
| `t12` | delivered | v1.62.0 + CHANGELOG — branch `colleague/834b6a20f73d-…` (**colleague @ medium**, 2 min); the PR is opened by the gate owner via `cicd` |

## Mid-work Decisions

- `d1` — t1, t2 (slices a/b/c) and t3 move from colleague to Claude sonnet subagents: colleague cannot send a thinking knob until this very feature lands, so every colleague dispatch runs at the rig's xhigh default (t1 attempt 1: 52 min, no deliverable). Once t1+t2+t3 merge, `uv run colleague` runs the branch code and dispatches resume on colleague at the medium acting-seat default — Ori: "Why is t1 on xhigh? If we can avoid it, let's do. Can use sonnet or opus until we can change default effort."
- `d2` — t5 (both slices) moves to a Claude sonnet subagent after two failed colleague attempts at medium (09e58827e8db: 19-min silent turn; 77217458648f: 8 exploratory steps then write-no-changes) — split-plan blocker rule.
- `d3` — t8 moves to a Claude sonnet subagent after two stalled colleague attempts at medium — blocker rule.
- `d4` — t7 moves to a Claude sonnet subagent after two stalled attempts (medium, then the measured **low** arm — low did not bound the silent turns) — blocker rule.
- `d5` — t6 moves to a Claude sonnet subagent after ONE stalled attempt, on pattern evidence (every existing-module edit brief stalled) and because t10/t12 gated on it — blocker rule + time.
- `d6` — t6 honest limit: only the plan stages have a dedicated completion; auto-split / fill-line split / decomposition / workforce sites are builder-level only — follow-up.
- Not covered by a record: the gate owner (Claude) wired t8's after-run lane into `loop.py` (the task's file constraint forbade it) — `04113ed`; conflict-free merges were done directly by the gate owner rather than via colleague merge work items, to keep the two GPU slots for task work (the split plan said "even merges" — recorded here honestly); t10 was dispatched before t6 merged (docs-only, no code overlap); `COLLEAGUE_MAX_STEPS=80` + a 6-step exploration cap were added to later colleague briefs; the `low` arm (t7b) was run as a measured experiment.
- Two repo-level findings filed: colleague#418 (`--continue` + `--background` drops the continue id) and two data-point comments on #415 (small requests land; module-sized existing-file briefs stall at medium and at low).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t1` (`d1`) | colleague cannot send a thinking knob until this very feature lands, so every colleague dispatch runs at the rig's xhigh default (t1 attempt 1: 52 min, no deliverable) | acceptable |
| `t2` (`d1`) | same as above — sonnet until t1+t2+t3 merged | acceptable |
| `t3` (`d1`) | same as above — sonnet until t1+t2+t3 merged | acceptable |
| `t5` (`d2`) | two failed colleague attempts at medium (19-min silent turn; write-no-changes) | acceptable |
| `t8` (`d3`) | two stalled colleague attempts at medium (zero edits in 42 min; 17-min silent turn) — plus gate-owner wiring outside the task's file list | acceptable |
| `t7` (`d4`) | two stalled colleague attempts (medium; the low arm) | acceptable |
| `t6` (`d5`) | one stalled colleague attempt; pattern evidence + t10/t12 gated on it | acceptable |
| `t6` (`d6`) | only plan.spec_stage/plan.plan_stage have a dedicated completion; the four split/decompose sites are builder-level pins — no request carries their effort today | needs-follow-up |
| `t12` | colleague did the bump + CHANGELOG; the PR is opened by the gate owner (the split plan's own assignment) | acceptable |
| all merges | conflict-free merges performed by the gate owner, not by colleague merge work items (GPU slots reserved for task work) | acceptable |

## Evidence

- tests: `uv run pytest -n auto -q` on `7ab34c4` — `9098 passed, 23 skipped` plus 3 pre-existing env-dependent failures (`tests/test_cli_lobes.py::test_lobes_show_unarmed_*`, `tests/test_config_lobes.py::test_config_show_no_lobes_key_when_unarmed`) caused by this machine's `.colleague/config.json` arming lobes — they fail identically on the pre-run commit `0ac58e3`
- tests (live, rig): `tests/test_vllm_live_thinking_effort.py` — 3 passed (`COLLEAGUE_VLLM_E2E=1`, Spark cortex via the lobes gateway)
- lint: `uv run black --check colleague tests` / `isort --check-only` / `flake8` / `bandit -c pyproject.toml -r colleague` — clean; `uv run teken cli doctor . --strict` — PASS; `markdownlint-cli2` on every touched doc — 0 errors; doc-test-alignment — aligned
- commits: `0ac58e3..7ab34c4` (59 commits on `spec/per-seat-thinking-effort-416`)
- run log: `docs/experiments/2026-08-22-per-seat-thinking-effort-416-workforce-ledger.md`; live proof: `docs/live-testing.md` row 39
- PRs / issues: #416 (feature), #417 (rig evidence), #415 (two data-point comments), #418 (bug found during the run); PR: opened via `cicd` after this artifact

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| every vllm-openai request carries the seat's thinking setting (`enable_thinking:false` / `reasoning_effort`), per the v3 table | high | `tests/test_vllm_thinking_effort.py`, `tests/test_effort.py::test_default_table`; live: row 39 (a),(d) — 5 acting requests at `medium` + 2 senses at off in the final run |
| the kill-switch restores the byte-identical pre-#416 wire | high | `tests/test_thinking_effort_payload_fixture.py`; `tests/test_vllm_thinking_effort.py` (unset/kill-switch shape) |
| a ladder-400 is retried once without the key, disjoint from the 404 refresh | high | `tests/test_vllm_thinking_effort.py` (ladder-400, non-ladder-400, 404→400→200) |
| senses/Talker seat runs thinking-off with `reasoning_tokens == 0`; deepthink runs xhigh | high | `tests/test_vllm_live_thinking_effort.py` (live, 3 passed) |
| subagent children run at their role's effort (explorer off, reviewer/validator low, planner/writer medium) and never inherit the parent's value implicitly | high | `tests/test_subagent_thinking_effort.py`; live fan-out `ad5c5a1a76ae` (18 requests = 6 off / 6 low / 6 medium) |
| effort is trace data on the #411 ledger record + OTel span only when set | high | `tests/test_agents_runtime.py`, `tests/test_telemetry.py` (commit `e55aa5a`) |
| a too-hard/too-long run leaves a split-next-time record that recall surfaces first | high (unit) / medium (live) | `tests/test_memory_split_record.py`, `tests/test_loop_memory.py::test_split_next_time_record_written_when_steps_hit_the_cap`; no live run exercised the record yet |
| plan spec/plan stages run at xhigh/high on the cortex seat | high | `tests/test_design_call_site.py` (commit `4b91456`) |
| auto-split / fill-line split / decomposition / workforce run at the design effort | unverified | d6 — builder-level pins only; no request carries it (not claimed done) |
| colleague's own workforce dispatches moved from xhigh to medium the moment t1–t3 merged | high | ledger rows t4/t9/t10/t12 (`COLLEAGUE_DUMP_REQUEST` payloads) |
| the `low` rung bounds long silent turns on existing-module briefs | unverified → refuted (n=1) | ledger row t7b: a 15-min silent turn at low |
| v1.62.0 + CHANGELOG | high | `pyproject.toml`, `CHANGELOG.md` (merge `7c49009`) |

## Remaining Work / Follow-up

- `t6` (d6) — wire the four builder-level design sites (auto-split, fill-line split, subagents.decompose, plan.workforce) through a dedicated completion threaded via the engine adapter, or re-spec them as "acting-turn decisions" — follow-up issue after the PR.
- Spec claims c18/c20 (after-state / success-signal wording) predate the v2/v3 re-decision (they still say "deepthink/main unset", "'high' never reaches the wire") — the Decisions c35–c40 supersede them; reword on the next frame edit.
- Effort × tool-calling is measured n=1 per cell (live row 39 + the workforce ledger); the v1 "many small requests" experiment (#415) is the next bed.
- #418 (`--continue --background`) — fix in `colleague/background.py`.
- The 3 lobes-unarmed tests are env-dependent on machines whose repo `.colleague/config.json` arms lobes — consider a conftest guard.
- Reconcile memory: `docs/features/thinking-effort.md`'s "split-next-time" section has only unit evidence; a live run that exhausts its budget should be recorded in `docs/live-testing.md` when it happens.
