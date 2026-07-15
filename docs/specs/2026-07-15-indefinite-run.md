# indefinite-run

> colleague work items no longer die at their budgets: when the step budget exhausts mid-task, colleague automatically continues from the persisted artifact — carrying the prior episode's actual tree state — and when the context fills, it compacts with a validated summary that provably preserves the goal and the work done so far; a big task keeps going until it is done or honestly cannot progress, and the operator can stop it at any moment
> instruction: the mock e2e chain test + the dormant byte-identity test are the executable form of the announcement

## Audience

- operators who hand colleague tasks bigger than one budget (Ori's rig first), on every front: work CLI, session, --background — and both engines, mock + vllm-openai
  - instruction: check the exported spec names all three fronts and both engines

## Before → After

- Before: today a big task dies at max_steps (~40 steps in live work-lessons) with incompletion reason budget-exhausted and waits for a MANUAL work --continue that restarts on a fresh worktree at HEAD without the prior episode's edits; the fill-line fires at most once, and the compaction summary is applied unvalidated
  - instruction: verify each stated limit against loop.py/_fillline_offered, worktrees.py isolation_worktree_add, fillline.py apply_compaction
- After: an armed run chains bounded episodes automatically: budget-exhausted episodes re-seed via resolve_continuation onto a worktree based on the prior episode's branch tip; each context crossing can compact again with a validated summary; the chain ends with the deliverable (ok) or an honest non-ok when progress stalls — stoppable via the flight plane at any boundary
  - instruction: the mock e2e chain test is the executable form of this claim

## Why it matters

- recurring live evidence (eidetic work-lessons: 5+ items 'incomplete: step budget exhausted' at steps 38-49) shows real tasks outgrow one episode; chaining turns colleague from a per-episode tool into a task-completer without weakening the honesty rules that make its results trustworthy
  - instruction: cite at least one work-lesson id in the spec rationale

## Requirements

- episode chaining lives OUTSIDE the bounded loop: _work_loop keeps its max_steps budget and _EXIT_BUDGET exit (loop.py:2262-2321); auto-continue is a driver at the work-dispatch layer that re-seeds a new episode via resolve_continuation, never an in-loop budget extension
  - honesty: max_steps semantics and the _EXIT_BUDGET exit are untouched; no code path extends a live episode's step budget
- the fill-line re-arms after a resolved compact: _fillline_offered (loop.py:627-631, 'at most once per work item' per capacity-standard.md:32) becomes per-crossing so a long run can compact repeatedly, with a per-run compaction cap against thrash
  - honesty: a second threshold crossing after a resolved compact offers the decision again (test), and a per-run compaction cap bounds the total number of compaction turns
- compaction gets deterministic validation: apply_compaction (fillline.py:137-147) today accepts any text — empty becomes '(no summary produced)' and the run continues with amnesia; the compacted note must be checked against the run's own evidence (goal text, changed-file paths from the step trace) with missing facts repaired deterministically, lossy windowing remaining the floor
  - honesty: the validator is deterministic (goal text + changed-file paths from the run's own trace); a summary missing facts is repaired deterministically or rejected — an empty summary NEVER replaces history; lossy windowing remains the floor when validation cannot produce a usable note
- auto-continue reuses resolve_continuation verbatim (continuation.py:25-97): the wrong-run guard and ok-guard stay; the chain driver re-dispatches only a non-ok episode whose exit reason is budget-shaped, and stamps lineage via the existing TaskResult.continued_from
  - honesty: the ok-guard holds inside the chain: an episode that finishes ok is never re-dispatched; ContinuationError surfaces as a clean chain halt, not a crash
- a chained episode carries the prior episode's TREE, not just its 1.3K-token seed: today a continued run dispatches through the ordinary work path onto a fresh worktree at HEAD (worktrees.py isolation_worktree_add: 'at HEAD on *branch*') while the prior WIP sits committed on colleague/<prior-id> (#222); the chain must base episode N+1's worktree on episode N's branch tip so edits accumulate instead of being re-derived
  - honesty: a file committed by episode N's WIP commit is present in episode N+1's worktree (test); when the prior branch is missing (reaped/crashed) the chain degrades to today's HEAD base with a recorded warning, never a crash
- an indefinite run stays stoppable and observable: the flight plane's cooperative stop (flight.py write_stop, checked at every turn boundary via _flight_stop_requested) plus the heartbeat (#308) must hold ACROSS episodes — the chain driver checks stop between episodes and the flight feed shows episode transitions, so 'indefinite' never means 'unattended and unstoppable'
  - honesty: flight write_stop between episodes prevents the next episode from starting (test); each episode keeps its own in-episode stop checks and heartbeat unchanged
- runtime-owned, all-engines: chaining, re-armed fill-line, and compaction validation land in loop.py/work.py/fillline.py — never in an engine — so mock and vllm-openai behave identically; mock exercises the whole chain in tests (the existing seams: test_fillline.py, test_continuation.py, test_cli_work_continue.py, test_capacity*.py)
  - honesty: the chain e2e runs on the mock engine in CI; TaskResult shape (incl. lineage + chain view) is identical across mock and vllm-openai per the all-engines guard
- session parity (all-fronts): whatever arms auto-continue on 'colleague work' is reachable from 'colleague session' too (the /continue SlashSpec already rides the same resolve path; session-continue-heal.md) — a session-dispatched big task benefits identically
  - honesty: the session front can arm the same chaining with the same semantics (shared dispatch path, no session-only fork); off a colour TTY the behavior is unchanged
- knobs ride the existing config resolution (flag > env > config.json > default, config.py resolve()): an episode cap (e.g. COLLEAGUE_MAX_EPISODES / --max-episodes), the auto-continue arm, and a compaction-validation toggle land as ordinary resolved knobs with strict-no-op defaults preserving today's single-episode behavior for untouched configs
  - honesty: every new knob rides resolve() precedence (flag > env > config.json > default) and its unset default reproduces today's single-episode behavior exactly
- docs record the new line honestly: capacity-standard.md ('fires at most once per work item'), continue-working.md, session-continue-heal.md, graceful-degradation.md, honest-incompletion.md and CLAUDE.md architecture bullets all state the once-per-run and text-only-carry limits today and must be updated with the superseding behavior plus its honest limits
  - honesty: each doc that states a limit this feature removes is updated in the same PR, and the doc-test-alignment check passes
- between-episode accounting is first-class: each episode remains one work item with its own artifact; the chain stamps continued_from lineage episode-to-episode and the final artifact carries a chain view (episode count, total steps/tokens) so WorkStats stay exact per-episode, never merged estimates
  - instruction: check artifact.py stats stay per-episode; chain summary is additive from real per-episode usage
  - honesty: tokens/steps in the chain view are sums of per-episode exact usage — never estimated (the tokens-are-exact rule)

## Honesty conditions

- with chaining DORMANT (no flag, no env, no config key) every existing test passes unmodified and a bare work item behaves byte-identically to v1.46 — the indefinite behavior is armed, never ambient
- a chain that makes no progress (no new commits on the episode branch AND no new artifact evidence) halts and the final artifact reports non-ok with an incompletion reason — verified by the chain-halts-honestly test
- test_boundary.py's sanctioned subprocess/thread lists are unchanged by the feature; no new socket/daemon/scheduler code; the rig-budget slot is re-acquired per episode (never held across the gap)
- no front is second-class: work, session, and --background all reach the armed behavior in the shipped PR (all-fronts), not a follow-up
- each stated current limit is verified against the named code line before build starts (they are the baseline the tests must break)
- the mock e2e chain test enacts this narrative end-to-end (>=3 episodes, tree carry, validated compact, honest halt) — the after-state is demonstrated, not asserted
- the spec cites real work-lesson evidence; if the live rig proof shows chaining does NOT reduce babysitting (e.g. the 27B loops without progress), that result is reported honestly in the delivery summary
- all three named tests exist and fail on main before the feature lands (TDD baseline)

## Success signals

- a mock-engine e2e task sized to need >= 3 episodes (deliberately small max_steps) lands its deliverable with status ok and a continued_from lineage chain of length >= 3 with zero operator interventions; a deliberately no-progress task halts within 2 episodes reporting non-ok; a validated compaction test shows an empty/uncoverable summary NEVER silently replaces history
  - instruction: three named tests: chain-completes, chain-halts-honestly, compaction-validated

## Scope / boundaries

- honest incompletion (#313, incompletion.py reasons incl. 'budget-exhausted'/'no-progress-zero-steps') is never weakened: a chain halts on a no-progress episode (no new changed files AND no substantive advance) and the final artifact still reports non-ok with reason + evidence — auto-continue must never become an infinite no-progress loop or a way to launder incompletion
- no daemon, no router: the chain is a foreground loop inside the existing work dispatch (or a c17 background one-shot child) — no new process, socket, scheduler, or task->model routing; each episode re-acquires the rig-budget slot cooperatively rather than holding it across episodes

## Non-goals

- compaction and its validation stay on the MAIN model: the compaction prompt IS the main model's own windowed history, which structurally cannot fit the 64K deepthink window (recorded decision, dual-model-deepthink 2026-07-01) — no deepthink/second-model escalation for summaries, and no LLM-judge validation lane; validation is deterministic-first

## Scope exploration

- `s1` — `colleague/loop.py _work_loop (_EXIT_BUDGET, bounded turn loop)`: the loop is bounded by design (max_steps, budget exit at loop.py:2321); indefinite running must chain bounded episodes, not unbound the loop
  - seeds: `c2`
- `s2` — `colleague/fillline.py + loop.py _maybe_offer_fillline/_fillline_offered`: fill-line decision fires at most once per work item today (single-element _fillline_offered cell); a second crossing gets only silent lossy windowing — the core context gap for long runs
  - seeds: `c3`
- `s3` — `colleague/fillline.py apply_compaction + _compact_history (loop.py:1143-1173)`: the model-authored compaction summary is applied unvalidated; a bad or empty summary silently destroys working context — this is the 'validated compression' gap
  - seeds: `c4`
- `s4` — `colleague/continuation.py resolve_continuation`: the resume seam already exists (artifact -> 5-section record + original request, ok/corrupt guards); auto-continue is a driver over it, not new resume machinery
  - seeds: `c5`
- `s5` — `colleague/worktrees.py isolation_worktree_add + work.py _build_continued_task`: continuation today is text-only state carry; the prior episode's actual edits do NOT reach the next episode's tree — chained continuation would re-do work every episode
  - seeds: `c6`
- `s6` — `colleague/incompletion.py (#313 honest incompletion)`: budget-exhausted is already a first-class incompletion reason; the chain driver consumes it as its continue signal but must preserve honest non-ok reporting when progress stalls
  - seeds: `c7`
- `s7` — `colleague/flight.py (piloting #307-#311: stop/guidance, heartbeat)`: in-episode stop already works at turn boundaries; the between-episode gap is the chain driver's to cover — flight is the operator's safety valve that makes indefinite acceptable
  - seeds: `c8`
- `s8` — `CLAUDE.md v1 scope (no-daemon line, c17, rig-budget)`: indefinite running must not become a resident daemon; chaining inside the existing one-shot dispatch keeps the daemonless line intact and the rig slot cooperative
  - seeds: `c9`
- `s9` — `all-engines rule + tests/ (test_fillline, test_continuation, test_cli_work_continue, test_capacity*)`: every touched mechanism is already runtime-owned with an established test seam per surface; the feature extends those seams rather than minting new layers
  - seeds: `c10`
- `s10` — `colleague/cli/_commands/session.py /continue + docs/features/session-continue-heal.md`: session /continue shares the CLI resume path verbatim; parity for auto-continue is a wiring concern, not new machinery
  - seeds: `c11`
- `s11` — `docs/features/deepthink.md + eidetic decision dual-model-deepthink-window-asymmetry`: the window-asymmetry decision already settles where compaction runs; validated compression must be designed within the main model + deterministic checks
  - seeds: `c12`
- `s12` — `colleague/config.py resolve() + configdir precedence`: config plumbing for new knobs is established (max_steps/context_budget precedents at config.py:1521,2209); nothing new to invent — only which defaults arm what, which is a user decision
  - seeds: `c13`
- `s13` — `docs/features/{capacity-standard,continue-working,session-continue-heal,graceful-degradation,honest-incompletion}.md + CLAUDE.md`: five feature docs + CLAUDE.md currently document the exact limits this idea removes; doc drift here would contradict the trim-discipline rule
  - seeds: `c14`

## Decisions

- arming is an opt-in flag: work --until-done (+ --max-episodes N, default 5 when armed, 0 = unlimited); unarmed behavior byte-identical to today
- the no-progress guard halts the chain when an episode lands no new commits on its branch AND adds no new artifact evidence
- an unrepairable compaction note triggers finish-with-handoff when chaining is armed (chain re-seeds cleanly); the lossy-windowing floor stays for unarmed runs
