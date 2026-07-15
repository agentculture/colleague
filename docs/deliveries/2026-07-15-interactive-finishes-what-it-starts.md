# Delivery Summary — interactive-finishes-what-it-starts

plan: `interactive-finishes-what-it-starts` · run: `complete` · date: `2026-07-15`
baseline: `devague summary skeleton`

## Intent

Colleague's interactive session finishes what it starts: a cut work item
continues with one flag, a dirty tree heals with one explicit choice instead
of a refusal, and the PR a run just opened is one glance away (#167 / #168 /
\#169, closing #170 as the interactive-redesign increment per frame decision
c15). Executed as an 8-task / 5-wave plan by a mixed Claude + colleague
workforce with TDD-gated merges; all waves merged; the final PR (#331) is open
at the human gate.

## Planned Work

Quoted verbatim from the `devague summary` skeleton (plan task ids; the
summaries' embedded "tN:" prefixes are the authoring labels and drifted from
the assigned ids at creation — the ids are authoritative):

- `t1` — t1: TaskResult.continued_from lineage field (contract)
- `t2` — t2: NEW colleague/continuation.py — resolve + guard + seed
- `t3` — t5: NEW heal choice model (pure) — 3 choices with consequence+undo copy
- `t4` — t4: work --continue/-c CLI flag
- `t5` — t5: session heal wiring — dirty-blocked dispatch offers the choice
- `t6` — t6: session /continue slash + free-text affordance
- `t7` — t7: PR link on the session surface
- `t8` — t8: docs + boundary grep gate + acceptance sweep

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `TaskResult.continued_from` (omit-when-None, round-trips) — commit `98bd85a`, by Claude after deviation `d1` |
| `t2` | delivered | `colleague/continuation.py` + 11 tests (wrong-run guard, corrupt/missing artifact guards, AST import-constraint test) — commit `138b3b3`, colleague drive `1aab84aec80a`, graded 5/5 |
| `t3` | delivered | `colleague/heal.py` + 31 tests (verbatim consequence+undo copy, empty-input-aborts) — commit `d82f40d`, colleague drive `d939304b9033`, graded 4/5 (WIP-on-stop finish; work complete and verified) |
| `t4` | delivered | `work --continue/-c` seeding + explicit validation + lineage stamped on success AND failure artifact writes — commit `1f03519`, by Claude after deviation `d2`, colleague's TDD test file salvaged (fixture paths corrected to the real slugged-artifact layout) |
| `t5` | delivered | session heal wiring: 3-choice prompt before a doomed dispatch, one-run commit waiver, stash with named recovery, off-TTY/allow-dirty fall-through pinned, runtime #149 guard pinned untouched — commit `4cb1467` + `handoff.heal_stash` |
| `t6` | delivered | `/continue [id\|last]` SlashSpec + handler on the same resolve path, CLI-identical error shape, per-dispatch lineage-cell consumption pinned — commit `5d399f8` |
| `t7` | delivered | `Ledger.pr_url` reconciled verbatim; Last-run PR row + post-run `· PR: <url>` line only when real; local-only output pinned byte-identical — commit `d213643` |
| `t8` | delivered | `docs/features/session-continue-heal.md` (honest limits + executed boundary grep gate + acceptance sweep) + CLAUDE.md bullet — commit `ff15260`, by Claude after deviation `d3` |

## Mid-work Decisions

- `d1` — t1 reassigned colleague→Claude mid-wave-1 — the colleague drive
  finished 'ok' with zero changes and a COMPACT meta-note as its summary
  (artifact `17cb439d5c02`) — a live classifier gap now filed as colleague#330;
  Claude rebuilt t1 to the same acceptance criteria (41 tests green incl. the
  e2e shape pin)
- `d2` — t4 reassigned colleague→Claude mid-wave-2 — the colleague drive spent
  all 45 steps writing the TDD test file and exhausted its budget before
  implementing (artifact `54ead8272f22`, honest budget exhaustion); Claude took
  over the implementation, salvaging the drive's test file from its branch
- `d3` — t8 reassigned colleague→Claude at wave 5 — the acceptance-sweep table
  + boundary grep gate need the full arc-diff context the integrator already
  holds; two earlier reassignments (d1/d2) showed the colleague round-trip cost
  under GPU contention outweighs delegation for context-heavy end-of-arc docs
- The `continued_from` kwarg is passed to the session's `work_fn` ONLY when
  set — an ordinary dispatch keeps the exact call shape stable for strict test
  doubles (surfaced by 7 full-suite failures; no deviation record — an
  implementation-level choice inside t6's contract, captured here directly)
- The lineage rides `args._continued_from_resolved` (CLI) / a consumed-per-
  dispatch session cell — the TaskResult field is stamped by `execute_work`,
  mirroring the `mode` precedent, not carried on `Task` (colleague's salvaged
  t4 test assumed `Task.continued_from`; corrected to the landed seam)
- Frame/plan confirmations and the workforce go/no-go were exercised
  in-session under the operator's standing pre-authorization of the full
  /scope→/summarize-delivery chain (operator away); the exported spec, this
  artifact, and PR #331 are the durable human-review surfaces

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t1` (`d1`) | the colleague drive finished 'ok' with zero changes and a COMPACT meta-note as its summary (artifact `17cb439d5c02`) — a live classifier gap now filed as colleague#330; Claude rebuilt t1 to the same acceptance criteria | acceptable |
| `t4` (`d2`) | the colleague drive spent all 45 steps writing the TDD test file and exhausted its budget before implementing (artifact `54ead8272f22`); Claude took over, salvaging the drive's test file | acceptable |
| `t8` (`d3`) | end-of-arc docs need the full arc-diff context the integrator already holds; colleague round-trip cost under GPU contention outweighs delegation | acceptable |

No other task drifted: t2, t3, t5, t6, t7 delivered to their confirmed
acceptance criteria as assigned.

## Evidence

- tests: full suite `uv run pytest -n auto` — **6278 passed, 20 skipped** on `7292761`
- tests (arc-specific): `tests/test_contract_lineage.py` (5) · `tests/test_continuation.py` (11) · `tests/test_heal.py` (31) · `tests/test_cli_work_continue.py` (10) · `tests/test_session_heal.py` (12) · `tests/test_session_continue.py` (6) · `tests/test_session_pr_link.py` (8) — all pass
- lint: `black --check` / `isort --check-only` / `flake8` / `bandit` — clean; `markdownlint-cli2` clean on the new docs
- boundary grep gate (c19/h15): `git diff main...HEAD` touches no `resident/`, `colleague/plan/`, `subagents.py`, and no engine/model-resolution files — executed 2026-07-15, recorded in `docs/features/session-continue-heal.md`
- commits: `a785549..7292761` (spec, plan, 8 tasks, fixups, eidetic fold, version bump — 28 files, +2903/−32)
- PRs / issues: PR `#331` (open, human gate) · closes `#167` `#168` `#169` `#170` · filed `#330` (classifier gap found live) · deviations `d1`–`d3` in `.devague/`

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A cut run resumes with one flag, lineage recorded | high | `tests/test_cli_work_continue.py::TestContinueE2E::test_continue_last_reaches_terminal_state` · commit `1f03519` |
| One session move (`/continue`) resumes the last cut run | high | `tests/test_session_continue.py::test_bare_continue_defaults_to_last` · commit `5d399f8` |
| A completed run is never silently re-run (wrong-run guard) | high | `tests/test_continuation.py` ok-guard cases · `tests/test_session_continue.py::test_continue_ok_run_is_refused_with_the_cli_error_shape` |
| A colour-TTY dirty dispatch offers the 3-choice heal, never the raw refusal | high | `tests/test_session_heal.py` (12 pins incl. off-TTY fall-through + runtime-guard-untouched) · commit `4cb1467` |
| The PR link is one glance away, never synthesized | high | `tests/test_session_pr_link.py` (8 pins incl. local-only byte-identical) · commit `d213643` |
| Non-continued artifacts are byte-identical (all-engines) | high | `tests/test_contract_lineage.py::test_default_is_none_and_key_omitted` · `tests/test_e2e_mock.py` shape pin · `tests/test_result_fidelity.py` |
| The arc diff stays inside the declared boundary | high | the executed grep gate in `docs/features/session-continue-heal.md` |
| A colleague review of the whole arc diff found no issues | unverified | the review drive exhausted its step budget without a verdict (task `74d869128f07`) — not claimed; Qodo + SonarCloud gate PR `#331` |

## Remaining Work / Follow-up

- PR `#331` awaits human review + merge (gate 3); #167/#168/#169/#170 close on merge.
- colleague#330 — the COMPACT/meta-finish classifier gap found live during d1 (filed, open).
- colleague#329 + eidetic-cli#32 — the wrapper dirty-guard `.eidetic` exemption gap and the upstream recall-churn design issue that forced four stash dances this run (both filed, open).
- Big-diff colleague reviews exhaust their step budget (two honest `budget-exhausted` incompletions today, tasks `5746a2d97035` / `74d869128f07`) — consider a chunked-review mode or a raised default review budget; no issue filed yet.
- Parked from the frame: v1 (flight-state continue) and v2 (`last_work` race under two concurrent sessions) — evidence-gated follow-ups, recorded in the spec.
