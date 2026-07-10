# Delivery Summary — colleague now feels at home on your machine

plan: `colleague-now-feels-at-home-on-your-machine-arm-th` · run: `complete` · date: `2026-07-10`
baseline: `devague plan (colleague-now-feels-at-home-on-your-machine-arm-th)`

## Intent

Three frictions the operator hit while using `colleague session` against the
reference rig, each reproduced live before it was fixed: a lobes gateway that
had to be armed per-repo instead of once per machine; a mid-run update line that
destroyed the operator's in-progress typing ("clears my text, so I have to type
really fast"); and a colleague that could not answer questions about itself
(colleague#306). This run executed the converged plan
`colleague-now-feels-at-home-on-your-machine-arm-th` — 11 confirmed tasks across
four dependency waves — fanned out by `/assign-to-workforce` to a mixed workforce
(opus, sonnet, haiku, and colleague itself), each task built test-first in an
isolated worktree and merged behind a TDD gate.

## Planned Work

Quoted verbatim from `devague plan waves --json` (task ids and summaries; the
plan carries no `t3` — it was rejected at the plan gate, so the confirmed set is
11 tasks, not 12).

<!-- The summaries below are VERBATIM plan text. Leading-underscore identifiers
     (_load_lobes_override, _poll_talk_lane) read as emphasis markers to
     markdownlint; escaping them would break the verbatim-quote rule, so MD037
     is disabled for this section only. -->
<!-- markdownlint-disable MD037 -->

- `t1` — t1 per-key config merge: configdir gains resolve_files (all matches in precedence order); config.py's load_config_file, _load_lobes_override, and the senses/voice/deepthink section loaders merge per top-level key across roots (repo wins, user fills absent keys). TDD: the shadow test (repo config without lobes + user config with lobes => armed) written FIRST as the failing reproduction
- `t2` — t2 lobes show honesty: widen colleague/cli/_commands/lobes.py to the real precedence via resolve_lobes_gateway_url(repo_path), add --repo (default cwd); drop the env-only scope note
- `t4` — Owned-input-line machinery: new module colleague/cli/_commands/_input_line.py — a reader thread owning raw stdin (instant per-key echo into an owned buffer) + a locked print_above(text) helper that repaints the pending line after every print (hand-rolled patch_stdout); bounded join at stop; any failure degrades to cooked mode. Includes the test_boundary.py thread allow-list edit with the recorded rationale (the operator-decided q1 sanction — the module can't land green without it)
- `t5` — Session wiring: the colour-TTY talk lane uses the owned input line — sink/update prints route through print_above; _poll_talk_lane's cooked select path stays as the off-colour-TTY fallback. TDD: the typing-clobber reproduction written FIRST
- `t6` — Record the 4th convention break: CLAUDE.md conventions section documents the sanctioned session reader thread (confinement to the colour-TTY session path, join semantics, degrade path) alongside the three existing recorded breaks
- `t7` — Self-knowledge classifier + guide index: new module colleague/selfknowledge.py — a deterministic stdlib-re classifier (classify_frontdoor sibling; ambiguous => NOT self-knowledge) + build_guide_index() naming the live guide paths (CLAUDE.md architecture bullets, docs/features/*)
- `t8` — Runtime self-facts builder in colleague/selfknowledge.py: build_self_facts(config) renders the RESOLVED state — cortex+senses model ids, armed gateway, active gates — from EngineConfig.resolve output only
- `t9` — Cortex-side wiring in colleague/loop.py: a self-knowledge-classified turn injects ONE advisory message (guide index + self-facts) before the cortex turn; cortex reads the live docs via existing read_file. Pin the #306 acceptance: ordinary turns byte-identical
- `t10` — Senses-side self-facts: the front door's fact-set (colleague/architecture_facts.py + frontdoor/senses path) gains the resolved runtime facts so 'what model are you?' through senses answers with the real ids — replacing the live-proven 'I don't know which model' deferral. TDD: that deferral is the failing reproduction
- `t11` — Live proofs: livecheck classifiers for the three success signals — (a) global-arming shadow proof (zero env vars, repo config without lobes => armed + lobes show agrees), (b) input-line survival (print-above pytest + a recorded live session), (c) self-knowledge answers with exact resolved model ids via senses AND cortex, guide question answered from real docs. Graded from evidence, honest SKIP when the rig is down; rows added to docs/live-testing.md
- `t12` — Feature doc + arc closing: docs/features/at-home-on-your-machine.md (motivation cites the operator complaint verbatim; restates the router-exclusion line; names the guide/docent role follow-up and the config-show contributing-files follow-up), CLAUDE.md architecture bullet, version bump

<!-- markdownlint-enable MD037 -->

## Actual Delivery

Every one of the 11 confirmed plan tasks is accounted for. Ten landed as
TDD-gated worktree merges; `t11` was built by the integrator directly (see Drift).

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `configdir.resolve_files` + `config._merged_config_json`; all four section loaders merge per top-level key. Merge `674b5d3` (sonnet). Added `COLLEAGUE_HOME` + conftest wiring beyond the brief (see Drift). |
| `t2` | delivered | `lobes show` resolves via `resolve_lobes_gateway_url(repo_path)`, gained `--repo`, scope note discharged; drift test vs `config show`. Merge `9053400` (haiku). |
| `t4` | delivered | New `colleague/cli/_commands/_input_line.py` (`OwnedInputLine`: start/stop/print_above, daemon reader thread, bounded join, degrade-never-raise) + the `test_boundary.py` thread allow-list entry with rationale. Merge `5d94b13` (opus). |
| `t5` | delivered | `session.py` `emit()` routes mid-run output through `print_above` while armed; `_poll_talk_lane` retained as the off-colour-TTY fallback. Merge `b973041` (opus). |
| `t6` | delivered | CLAUDE.md conventions bullet records the sanctioned reader thread. Merge `43bd14b` (haiku); ordinal corrected by integrator commit `871877a` (see Drift). |
| `t7` | delivered | `colleague/selfknowledge.py` `classify_selfknowledge` + `build_guide_index`. Merge `dd7758f` (**colleague**, graded 5/5). |
| `t8` | delivered | `build_self_facts(config)` — pure renderer over resolved config. Merge `0e7d4f7` (**colleague**, graded 5/5). |
| `t9` | delivered | `loop.py` `_maybe_inject_self_knowledge`; `EngineConfig.lobes_gateway_url` threaded via `ContextControls.from_config` (all-engines). Merge `5bddab3` (opus), after an integrator-refused first attempt (see Drift). |
| `t10` | delivered | `frontdoor.run_frontdoor(config=, gateway_url=)` appends resolved self-facts to the front-door fact-set; resident wired. Merge `87f118d` (sonnet). |
| `t11` | delivered | `livecheck.classify_at_home_check` + the three graders; live proofs run on the rig and graded; `docs/live-testing.md` rows 27–29. Commits `d17a0ed`, `ae4897b` (integrator, not a worktree merge — see Drift). |
| `t12` | delivered | `docs/features/at-home-on-your-machine.md`, CLAUDE.md architecture bullet, CHANGELOG, v1.44.0. Merge `ce19e2b` (sonnet). Follow-ups drafted, not filed at merge time (see Drift). |

## Mid-work Decisions

- **`COLLEAGUE_HOME` env override added to `configdir`, beyond t1's brief** — the
  suite had 8 pre-existing failures on the developer's machine that CI never saw,
  because tests resolved the *real* `~/.colleague/` through `Path.home()`. Making
  the global-config feature testable required making the user-level root
  injectable; a conftest autouse fixture now points it at a per-test tmp dir.
- **`EngineConfig.lobes_gateway_url` introduced as a runtime-only field** — the
  work loop holds a `ContextControls`, never a full `EngineConfig`, so the
  cortex-side facts block could not otherwise see the armed gateway. Modelled on
  the existing `embed_env` precedent (`compare=False, repr=False`, excluded from
  `to_dict`), so the artifact contract is unchanged.
- **`build_self_facts` is fed the *original* config, never `senses_config`** —
  `senses_engine_config()` returns `dataclasses.replace(config, model=sc.model)`,
  so passing it would have rendered the senses model id as the *cortex* id. Caught
  by the t10 agent itself.
- **The plan's `t3` was rejected at the plan gate**, so the confirmed contract is
  11 tasks. No work was expected or performed for it.
- **Two follow-ups were drafted as committed files rather than filed as issues**
  during the run, because filing public tickets was outside the authorization the
  workforce gates granted. Filed after the run on explicit operator approval
  (see Remaining Work).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t1` | Delivered its contract, and additionally added the `COLLEAGUE_HOME` override + conftest hermeticity fixture, which the plan did not name. The feature's own shadow test could not be written honestly without it. | acceptable |
| `t6` | The agent numbered the new thread sanction "(3)", colliding with CLAUDE.md's existing "third recorded convention change" (the c17 residency re-spec). Corrected before the wave closed by integrator commit `871877a`; the sanction is the **fourth**. | acceptable |
| `t9` | The first attempt satisfied the letter of the brief but rendered `senses: not configured` / `lobes: not armed` **in an armed session** — an honest-looking falsehood, because the loop never sees a full `EngineConfig`. The merge was refused and the task re-run with the `lobes_gateway_url` plumbing. Delivered correct. | acceptable |
| `t11` | Built by the integrator directly (commits `d17a0ed`, `ae4897b`) rather than as an isolated-worktree agent merge. Running the live proofs needs the real rig, a real PTY, and the operator's real `~/.colleague` — none of which exist inside a task worktree. | acceptable |
| `t12` | Its acceptance criterion says the two follow-ups are "filed as issues, not silently dropped". At merge they existed only as committed drafts under `docs/drafts/`. Discharged after the run: both filed (see Remaining Work). Not silently dropped at any point. | acceptable |

No other plan task diverged from its contract. `t2`, `t4`, `t5`, `t7`, `t8`, and
`t10` delivered exactly what they were confirmed to deliver.

## Evidence

Read-only verification. Range: `68f65dc..35fcf37` (28 commits), plus the
post-review fixes described in Remaining Work.

- commits: `68f65dc..35fcf37` — 36 files changed, +4491 / −137
- PRs / issues: PR `#315`; closes `#306`
- plan state: `devague plan status` → `convergence: PASSED ✓` (read-only)
- tests: full suite — **6062 passed, 18 skipped** (baseline before the arc: 5898;
  6060 at the workforce's final merge, plus 2 regression tests from the review fix)
- tests: `tests/test_config_merge.py::test_repo_config_without_lobes_falls_through_to_user_lobes_default` — pass
- tests: `tests/test_config_merge.py::test_repo_lobes_key_wins_over_user_lobes_key` — pass
- tests: `tests/test_cli_lobes.py::test_lobes_show_and_config_show_agree_on_armed_config` — pass
- tests: `tests/test_input_line.py::test_print_above_repaints_pending_input_below_the_printed_line` — pass
- tests: `tests/test_session_input_line.py::test_armed_line_routes_mid_run_output_above_pending` — pass
- tests: `tests/test_loop_selfknowledge.py::test_ordinary_instruction_is_byte_identical_no_injection` — pass
- tests: `tests/test_loop_selfknowledge.py::test_self_knowledge_turn_injects_guide_index_and_self_facts` — pass
- tests: `tests/test_frontdoor_runtime.py::test_resolved_model_ids_reach_the_senses_prompt_when_config_given` — pass
- tests: `tests/test_selfknowledge.py::test_deterministic` — pass
- tests: `tests/test_boundary.py::test_threads_only_in_sanctioned_files` — pass (the allow-list gate)
- lint: `black --check colleague tests` — 504 files unchanged
- lint: `isort --check-only`, `flake8 colleague tests`, `bandit -c pyproject.toml -r colleague` — clean
- lint: `markdownlint-cli2` — 0 errors
- live: `docs/live-testing.md` row 27 (global arming), row 28 (mid-run typing over a
  real PTY), row 29 (self-knowledge on both minds) — all ✅, 2026-07-10, each graded
  by `colleague/livecheck.py` `classify_at_home_check`
- ROI: colleague's own two tasks graded via the feedback loop — `13af07c4cbe0` (t7)
  **5/5**, `b08522bab3a2` (t8) **5/5**
- external review: SonarCloud quality gate **passed** (86.0 % coverage on new code,
  0.0 % duplication, 0 security hotspots); Qodo — 1 bug, 0 rule violations, 0
  requirement gaps

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A user-level `~/.colleague/config.json` `{"lobes": …}` arms a repo whose own `config.json` omits `lobes`; a repo-level key still wins outright | high | test `tests/test_config_merge.py::test_repo_config_without_lobes_falls_through_to_user_lobes_default` · test `::test_repo_lobes_key_wins_over_user_lobes_key` · commit `674b5d3` |
| `lobes show` and `config show` can no longer disagree about the armed state | high | test `tests/test_cli_lobes.py::test_lobes_show_and_config_show_agree_on_armed_config` · commit `9053400` |
| A mid-run update prints *above* the operator's pending input line instead of destroying it, on a real colour TTY | high | test `tests/test_input_line.py::test_print_above_repaints_pending_input_below_the_printed_line` · test `tests/test_session_input_line.py::test_armed_line_routes_mid_run_output_above_pending` · live-testing row 28 (real PTY) |
| Off a colour TTY (piped / `--json` / `--no-tui`) the session is byte-identical | high | test `tests/test_session_input_line.py::test_unarmed_line_full_frame_redraw_has_no_repaint` · test `::test_arm_owned_line_noop_when_not_live_and_no_seam` |
| The reader thread is the 4th sanctioned thread, confined to the colour-TTY session path, and the allow-list enforces it | high | test `tests/test_boundary.py::test_threads_only_in_sanctioned_files` · file `colleague/cli/_commands/_input_line.py` · commit `43bd14b`+`871877a` |
| `stop()` releases stdin promptly; no ghost reader survives it | high | test `tests/test_input_line.py::test_stop_is_prompt_when_the_reader_is_parked_on_an_idle_stream` (post-review fix; see Remaining Work) |
| A self-knowledge turn injects one advisory (guide index + resolved facts); an ordinary turn is byte-identical — the #306 acceptance | high | test `tests/test_loop_selfknowledge.py::test_ordinary_instruction_is_byte_identical_no_injection` · test `::test_self_knowledge_turn_injects_guide_index_and_self_facts` · commit `5bddab3` |
| The classifier is deterministic and ambiguous input never reaches the guide surface (not a router) | high | test `tests/test_selfknowledge.py::test_deterministic` · file `colleague/selfknowledge.py` |
| Senses answers "what model are you?" with both exact resolved model ids instead of the pre-arc deferral | high | test `tests/test_frontdoor_runtime.py::test_resolved_model_ids_reach_the_senses_prompt_when_config_given` · live-testing row 29 · commit `87f118d` |
| Cortex reads its own live guide docs and explained the affected-tests gate correctly (2 steps, `read_file` ×1) | high | live-testing row 29 (`colleague work --mode explore` against the reference rig, graded by `classify_at_home_check`) |
| An unarmed / unreachable gateway degrades to an honest `not armed`, never a fabricated model id | high | test `tests/test_loop_selfknowledge.py::test_self_knowledge_facts_degrade_to_guide_only_without_model` · test `tests/test_frontdoor_runtime.py::test_omitting_config_never_appends_self_facts` |
| The arc adds no new base dependency, no socket, no daemon | high | test `tests/test_zero_deps.py` · test `tests/test_boundary.py` (both green) |
| The three live proofs passed on the reference rig on 2026-07-10 | high | `docs/live-testing.md` rows 27–29, each graded from captured evidence by `classify_at_home_check` |
| The `~/.colleague/config.json` on the operator's machine was created by this arc's tooling | unverified | file appeared 2026-07-09 20:57 with no identified author; colleague's loop is repo-confined, so it was not written by a work item. Content matches the intended global default and was kept. Not claimed as delivered by any task. |
| The owned input line behaves correctly under a terminal resize or a multi-line paste mid-run | unverified | not exercised by any test or live proof — not claimed |

## Remaining Work / Follow-up

No plan task is partial, dropped, or blocked. The items below are follow-ups
discovered during the run and during external review.

- **Qodo review finding — ghost stdin reader (fixed in this PR, post-review).**
  `OwnedInputLine.stop()` set its stop event but the reader was parked in a
  blocking `os.read`, so the bounded join *always* timed out and returned while
  the thread still held stdin — a ghost reader racing the session's cooked reads
  for the next keystroke, plus a ~1 s stall after every work item. Fake in-memory
  streams structurally could not catch it (`StringIO.read(1)` returns at EOF
  immediately). Fixed by polling the fd with `select` so the reader observes the
  stop event within one 50 ms tick; verified on a real PTY (`stop()` 0.040 s,
  thread dead) and regression-pinned by
  `tests/test_input_line.py::test_stop_is_prompt_when_the_reader_is_parked_on_an_idle_stream`.
- **SonarCloud `python:S3776` (fixed in this PR, post-review).**
  `classify_at_home_check` carried cognitive complexity 29 (limit 15); split into
  three per-leg graders behind a dispatch table, behavior unchanged
  (`tests/test_livecheck_at_home.py` green unchanged).
- **colleague#316 — a named guide/docent role.** The advisory guide-index
  injection is deliberately shallow: it points cortex at its own docs rather than
  giving it a curated self-description. If dogfooding shows the advisory is too
  thin, #306's fuller sketch (a named role) is the next increment. Filed; draft
  `docs/drafts/issue-guide-role.md` removed.
- **colleague#317 — `config show` should list every contributing config file.**
  Now that config.json merges per-key across four roots, `config show` reports the
  merged *result* but not *which files contributed*, so a surprising value is hard
  to trace. Filed; draft `docs/drafts/issue-config-show-files.md` removed.
- **Terminal resize / multi-line paste under the owned input line** — unverified
  above; no test or live proof covers it. Worth a proof if an operator reports
  corruption.
- **`docs/skill-sources.md`** — `summarize-delivery` is cited directly from
  devague because guildmaster has not re-broadcast it yet; re-point at
  guildmaster's copy once that broadcast lands.
