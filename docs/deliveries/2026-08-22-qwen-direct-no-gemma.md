# Delivery Summary — qwen-direct-no-gemma

plan: `qwen-direct-no-gemma` · run: `complete` (PR #426 open, awaiting the human gate) · date: `2026-08-22`
baseline: `devague summary skeleton`

## Intent

Make the single-model default real — 1 colleague instance = 1 model = 1 agent: retire Gemma from the served roles colleague consumes by default (senses + muse lobes discovery become opt-in via the `lobes` sentinel), remove the front door / senses loop from the default path, park mid-run operator lines for cortex, make the retirement visible, and give the operator `/model` + `/effort` (session) and bare `--model` / `--effort` (CLI) to inspect and switch explicitly. Executed plan `docs/plans/2026-08-22-qwen-direct-no-gemma.md` (11 tasks / 6 waves) from spec `docs/specs/2026-08-22-qwen-direct-no-gemma.md`, with colleague (`unsloth/Qwen3.8-27B-NVFP4` via `ask-colleague write --apply`) as the workforce and the integrator TDD-gating every merge.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — t1 config: senses + muse lobes-discovery OFF by default; explicit declaration is the opt-in
- `t2` — t2 session: unarmed talk lane PARKS the operator line to cortex via flight guidance (no front door on the default path)
- `t3` — t3 session /model: no-arg lists served models + current per-seat default; switch re-derives context budget
- `t4` — t4 session /effort: show per-seat effort via `effort_of`, switch live (session-only), validated rungs
- `t5` — t5 visibility: config show / lobes show / doctor print advertised-but-not-consumed roles
- `t6` — t6 CLI flags: --model / --effort with no value print the list/table instead of refusing
- `t7` — t7 voice/realtime: honest 'senses not armed' line on the default path
- `t8` — t8 docs: CLAUDE.md fifth convention change + 1-model-1-agent principle; feature docs mark senses opt-in
- `t9` — t9 tests: single-model default guard, #422 hermetic lobes tests, unarmed artifact = default path
- `t10` — t10 live proof: the four c24 checks on this rig + evidence row
- `t11` — t11 release: version bump minor + CHANGELOG entry

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | colleague's WIP (config.py sentinel on both rungs, test_config_lobes.py) merged 93f4988 + integrator finish b07fbbe (deepthink tests flipped, comments compacted under the ratchet, 4 discovery-by-default pins elsewhere flipped); the sentinel is `resolved.model == "lobes"` |
| `t2` | delivered | colleague branch merged e7a4eb0: `_park_talk_for_cortex` + 2 default-path tests; follow-through d759050 extracted the slash actions to `_session_actions.py` (ratchet) |
| `t3` | delivered | colleague branch merged 0fbe90e: `/model` listing + `min(window, current)` budget rule, `tests/test_session_model.py` (8 tests) |
| `t4` | delivered | colleague branch (WIP committed on stop) merged 710625e + 1-line lint fix: `/effort` table + session-only switch, `tests/test_session_effort.py` (11 tests) |
| `t5` | delivered (integrator) | 34d0bbc: not-consumed lines on `config show` / `lobes show` + `--json not_consumed`, `tests/test_cli_not_consumed.py`; helpers later moved into `_listing.py`. **doctor** does NOT carry the line (the plan's acceptance named it; see Drift) |
| `t6` | delivered (integrator) | d244f5c + 7308446 + eb12b2c: `_listing.py` pure renderers, `--model` / `--effort` nargs="?" on `work`, `tests/test_cli_flags_listing.py`; `apply_operator_effort` lives in `effort.py` |
| `t7` | delivered (integrator) | 76a7108: dormant lines for `/voice`, `/speak`, `--voice` (ANSI only) + 3 tests; `voice.py`/`realtime.py` unchanged |
| `t8` | delivered (integrator) | 6d078fb: CLAUDE.md bullet + fifth convention change; 8 feature docs opt-in notes; `docs/features/qwen-direct.md` |
| `t9` | delivered (integrator) | 1b21696: `tests/test_single_model_default.py` (4 tests incl. the sentinel text guard + artifact pin); #422 trio hermetic |
| `t10` | delivered (integrator, as planned) | 0c412f1: `docs/live-testing.md` row 40 + `docs/evidence/2026-08-22-qwen-direct-no-gemma-results.md` |
| `t11` | delivered | 72007d4: 1.62.1 → 1.63.0 + CHANGELOG |

## Mid-work Decisions

- `d1` — integrator extracted the session slash config actions (`_act_*` + `_CONFIG_ACTIONS`, 115 lines) into `colleague/cli/_commands/_session_actions.py` because merging t2 grew session.py past the file-length ratchet baseline (4029 → 4052) — ratchet test failed post-merge; every later session.py task would fail the same way (approved, acceptable).
- `d2` — t1 child SIGTERM'd after a 15-min silent turn (stderr: backpressure escalation, timeout raised once to 600 s — a long legit request, not a hang); resumed from the salvaged artifact; the continuation sat 15 min at 0 steps → integrator finished from the WIP commit (approved, acceptable).
- `d3` — t5 and t6 taken over by the integrator: t5's child stalled twice, t6's child spent 44 steps reading with zero edits before budget exhaustion (approved, acceptable).
- `d4` — t8 taken over by the integrator: the colleague parent stalled 15 min at step 9; its subagent children's 16 doc edits were reaped with the parent (the #410 SIGTERM salvage commits only the parent's WIP) (approved, needs-follow-up).
- `d5` — t9 taken over by the integrator: child stalled 15 min at step 14 with 0 edits (approved, acceptable).
- `d6` — t7 taken over by the integrator: child stalled 15 min at step 22 with 0 edits (approved, acceptable).
- No record covers: the `lobes` sentinel was realised as `resolved.model == "lobes"` after `_resolve_*` (colleague's WIP used a separate `_pick` of the declared model) — same semantics, fewer lines under the ratchet; `/model` lists **all** served ids (incl. embedder/reranker) rather than chat models only; the h17 comparison arm opted senses in via the sentinel (the pre-arc default no longer exists to measure against).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t2` (`d1`) | ratchet test failed post-merge; every later session.py task would fail the same way | acceptable |
| `t1` (`d2`) | cap-2 slot + the 15-min silent-turn rule from plan risk r2 | acceptable |
| `t5` (`d3`) | plan risk r2 (hot files / stall-twice rule); keeps wave 1 moving | acceptable |
| `t8` (`d4`) | third colleague stall today on this wave; children's work is not salvageable after a parent SIGTERM | needs-follow-up |
| `t9` (`d5`) | stall rule (r2); tests-only task | acceptable |
| `t7` (`d6`) | stall rule (r2) | acceptable |
| `t5` | acceptance named `doctor` too; only `config show` + `lobes show` carry the not-consumed line (h7's contract) — doctor's rubric lives in `colleague/oilcheck/` and was left untouched | needs-follow-up |
| `t3` / `t4` | instructions re-pointed from session.py to `_session_actions.py` after d1 (re-confirmed) | acceptable |
| plan risk r1 | the colleague REVIEW lens never landed: two spec reviews + one code review of the merged diff stalled in a silent first turn (the reviewer child for the PR diff: 0 steps after 20 min, killed) — the TDD gate + Sonar/Qodo are the independent checks on this PR | needs-follow-up |

## Evidence

- tests: `uv run pytest -n auto` at `e67525e` — 9163 passed, 0 failed, 23 skipped (baseline before the run: 9105 passed / 3 failed — the #422 trio)
- tests: `tests/test_single_model_default.py` (4), `tests/test_session_model.py` (8), `tests/test_session_effort.py` (11), `tests/test_cli_flags_listing.py` (6), `tests/test_cli_not_consumed.py` (4), `tests/test_session_voice.py::test_voice_toggle_unarmed_senses_prints_dormant_line_no_dial` + 2 — pass
- lint: `black --check`, `isort --check-only`, `flake8`, `bandit`, `teken cli doctor --strict`, `markdownlint-cli2` — pass locally; SonarCloud's first scan raised 13 issues, fixed in e67525e (re-scan pending at write time)
- commits: `8888db9..e67525e` on `spec/qwen-direct-no-gemma` (53 commits)
- live proof: `docs/live-testing.md` row 40; `docs/evidence/2026-08-22-qwen-direct-no-gemma-results.md`
- workforce ledger: `docs/evidence/2026-08-22-qwen-direct-no-gemma-workforce-ledger.md` (16 ticks)
- PRs / issues: #426 (this PR); #422 (fixed); #415 / #409 (stall data points added); #424 (worklist context)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| With lobes armed and nothing declared, `EngineConfig.resolve()` arms only the cortex model (senses/deepthink/worker None) | high | test `tests/test_single_model_default.py::test_default_path_arms_exactly_one_model`; live: check 1 default arm — 2 requests, both Qwen3.8 |
| The lobes fallbacks are reachable only under the `lobes` sentinel | high | test `tests/test_single_model_default.py::test_lobes_fallbacks_are_reached_only_under_the_sentinel`; commits 93f4988, b07fbbe |
| An unarmed session parks a mid-run line for cortex via flight guidance | high | test `tests/test_session_talk_lane.py::test_talk_senses_unarmed_parks_for_cortex`; commit e7a4eb0 |
| `/model` lists the roster + roles and re-derives the budget on switch; `/effort` shows/switches per seat | high | `tests/test_session_model.py`, `tests/test_session_effort.py`; commits 0fbe90e, 710625e |
| Bare `--model` / `--effort` print the list/table and exit 0 | high | `tests/test_cli_flags_listing.py::test_work_bare_model_and_effort_print_and_exit_zero`; live check 4b |
| `config show` / `lobes show` name advertised-but-not-consumed roles | high | `tests/test_cli_not_consumed.py`; live check 4 output on this rig |
| The default-path artifact carries no senses key (byte-identical to the unarmed floor) | high | `tests/test_single_model_default.py::test_default_path_mock_artifact_has_no_senses_key` |
| cortex-direct answers a non-repo turn ≤ 2× the senses ack (h17) | medium | evidence file: 12.45 s vs 6.81 s = 1.83× (n=1 per arm, same rig, same minute) |
| `/voice`, `/speak`, `--voice` print one honest dormant line when senses is unarmed | high | `tests/test_session_voice.py` (3 new tests); commit 76a7108 |
| CLAUDE.md records the fifth convention change and the feature docs mark senses opt-in | high | commit 6d078fb; `grep -rnE 'default on every front\|default state on every front' CLAUDE.md docs/features/` → only superseded-marked lines |
| SonarCloud quality gate passes on the final tip | unverified | re-scan of e67525e pending at write time — not claimed |
| Qodo / independent review findings addressed | unverified | Qodo summary pending; the colleague reviewer lens stalled — not claimed |

## Remaining Work / Follow-up

- PR #426: wait for the Sonar re-scan + Qodo; triage every comment (FIX/PUSHBACK) and reply; then the human merge gate.
- `doctor` does not yet mention the not-consumed roles (t5 acceptance) — small follow-up in `colleague/oilcheck/`.
- d4 follow-up: a parent SIGTERM drops subagent children's edits — the #410 salvage should commit `sub/*` worktree WIP too (file on colleague).
- Stall data for #415 / #409: colleague stalls on spec-md reads (3/3), on continuations (2/2), and on review-of-diff briefs (3/3) today; the 300 s timeout did not cut those turns.
- Spec parks v1 (delete the dormant senses/presence code later), v2 (session-shaped latency arm for #421), v3 (consumers parsing `senses:` lines), v4 (plan-level colleague review) remain open.
- The ~70 sibling-repo `ask-colleague.sh` copies with a 3.6 model default — the #424 skill broadcast (now also carries the narrate-progress rule).
