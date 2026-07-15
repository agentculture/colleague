# interactive-finishes-what-it-starts

> colleague's interactive session finishes what it starts: a cut work item continues with one flag, a dirty tree heals with one explicit choice instead of a refusal, and the PR a run just opened is one glance away
> instruction: acceptance sweep at the end: one flag (--continue last), one choice (heal prompt), zero moves (PR link visible in the Last-run panel) — each demonstrated by a test named in the plan

## Audience

- the interactive operator at the session prompt (human or agent) — the person who just watched a run get cut, hit the dirty-tree refusal, or wants the PR they just shipped
  - instruction: read docs/features/session.md's audience section; the three features are session-surface affordances

## Before → After

- Before: a cut run's work is stranded (restart from scratch or hand-mine the artifact); a dirty tree turns 'go' into an error message the operator must decode; a freshly-opened PR's URL scrolls away in the digest
- After: the session finishes what it starts: 'colleague work --continue last' (or /continue) resumes a cut run from its persisted artifact; a dirty tree becomes one explicit choice (commit-onto-branch / stash / abort) instead of a refusal; the Last-run panel and post-run line carry the PR link

## Why it matters

- interactive trust is colleague's front door: an operator who loses work to a cut run, gets stonewalled by a guard, or has to scroll for their own PR stops delegating — the ROI loop starts at the session prompt

## Requirements

- work/session gain a continue move (#167): 'colleague work --continue [id|last]' (alias -c) and a session '/continue' slash resume a cut work item by seeding a NEW work item with the existing continuation record — colleague/escalation.py build_continuation already renders the five-section record from a partial TaskResult, and colleague/feedback.py get_last_work + artifact read resolve 'last'
  - instruction: reuse build_continuation(result, stats) unchanged; add tests for missing artifact, corrupt JSON, and 'last' resolution
  - honesty: continue NEVER fabricates progress: the new run's Task carries the continuation record VERBATIM from build_continuation plus lineage {continued_from: <task_id>}; a missing/corrupt artifact is a clean CliError naming the id, never a silent fresh start
- session self-heals the dirty-tree refusal (#168): session.py:936 already detects dirty-blocked (facts.dirty and not allow_dirty) and renders 'Safest next' TEXT, but still dispatches the doomed run into handoff's #149 refusal — at dispatch time the session instead offers ONE explicit choice (commit-onto-work-branch via --allow-dirty / stash first / abort) and acts on it
  - instruction: test: empty input at the heal prompt aborts; each explicit choice maps to allow_dirty pass-through / git stash / no-op
  - honesty: the heal prompt only ever fires where the SESSION already knows the tree is dirty (facts.dirty), offers exactly three choices, and 'abort' is the default on empty input — no choice is ever inferred
- the session surfaces the PR a run just opened (#169): TaskResult.pr_url exists (contract.py:1170, populated by handoff via work.py:154, printed by the work digest work.py:108) but the session cockpit's Ledger (cockpit_run.py:113 files/commands/commits/publish_state) and the post-run session line never carry it — thread pr_url into the Last-run panel + the post-run line
  - instruction: test: ledger/panel shows pr_url only when TaskResult.pr_url is non-None; local-only run unchanged
  - honesty: pr_url is surfaced only when the handoff ACTUALLY returned one (never a synthesized URL); a local-only run renders the honest 'local commit' state it renders today
- continue refuses to silently continue the WRONG run: a SIGKILL-cut run may have written NO artifact, so 'continue last' can resolve to the previous COMPLETED run — continuing a status-ok artifact requires an explicit distinct flag or errors with 'nothing to continue: <id> finished ok' naming the id it resolved
  - honesty: the guard is testable: a fixture where last_work points at an ok artifact makes bare 'continue last' exit non-zero with the id in the message
- every heal choice states its consequence and its undo in the prompt itself (the cockpit label-state-consequence policy, docs/features/cockpit-ux.md): 'commit onto work branch' names the #149 sweep consequence; 'stash' prints the created stash ref and the 'git stash pop' recovery line
  - honesty: the prompt text itself carries consequence + undo (asserted verbatim in the session test), not a doc reference the operator has to chase

## Honesty conditions

- each of the three affordances is reachable in one move from the session prompt (one flag / one choice / zero moves for the visible link) — 'finishes what it starts' is falsified if any needs a manual artifact dig
- handoff.py's _guard_clean_tree and the bare-CLI refusal are byte-identical on the branch; only the session-side dispatch gains the pre-flight choice
- no code path selects a model/backend from task content anywhere in the diff; continue re-resolves config exactly like a fresh work item
- nothing here requires a human TTY exclusively: an agent driving the session (agent-native default, #234) gets the same three affordances in parseable form
- the before-state is reproducible today on main: a killed work item leaves only the artifact; a dirty tree yields the #149 error verbatim; pr_url appears only in the scrolling digest
- the after-state is demonstrated by tests, not prose: each of the three flows has a test that fails on main and passes on the branch
- the claim stays grounded: no marketing numbers are invented; the ROI argument cites the existing feedback/stats loop (stats-and-feedback.md), not fabricated adoption data
- the lineage field is omit-when-None (byte-identical artifacts for non-continued runs, all-engines)
- off-TTY/piped sessions and --json keep today's behavior (no interactive prompt can block a pipe; dirty-blocked off-TTY dispatch falls back to the current refusal text)
- grep gate: no diff hunk touches resident/, plan/, or subagents.py dispatch — the boundary is enforceable mechanically

## Success signals

- a work item stopped at step N resumes via --continue and reaches a terminal state with >= 1 further step recorded, seeded from the SAME artifact (task id lineage recorded on the new run)
  - instruction: pytest: cut a scripted run mid-flight, run work --continue last, assert the new Task carries the continuation record + lineage field
- 0 dirty-tree refusals reach the operator from a session-dispatched run: 100% of dirty-blocked dispatches surface the 3-choice heal prompt first (the #149 refusal remains only for non-session/direct CLI paths)
  - instruction: pytest: session free-text dispatch on a dirty fixture repo renders the heal prompt and never the runtime error; direct 'colleague work' still refuses

## Scope / boundaries

- the #149 dirty guard's DEFAULT refusal stays: self-heal is an offered, explicit operator choice at the session surface — never an automatic sweep of uncommitted tracked edits (handoff.py _guard_clean_tree and the runtime-side guard are untouched)
  - instruction: pin with a test asserting handoff._guard_clean_tree behavior is unchanged on a dirty fixture repo via the bare CLI path (expect the #149 error verbatim)
- continue re-runs on the SAME resolved backend/model — no automatic task-to-model routing rides in with #167 (the CLAUDE.md router-exclusion scope line); the continuation is a Task-content composition, engine-agnostic per the all-engines rule
  - instruction: grep gate in the task brief: the diff may not touch engine/model resolution; continue calls the same EngineConfig.resolve path a fresh work item uses
- continue targets top-level work items via the EXISTING last_work semantics; subagent children, plan-mode runs, and the resident/talk front are out of this increment (each keeps today's behavior; a follow-up re-spec covers them if evidence demands)

## Non-goals

- no daemon, no socket, no session state that outlives the process: continue reads the PERSISTED artifact (.colleague/<id>.json), not an in-memory session handle — a cut session's work is continuable from a FRESH session
- off-TTY and --json surfaces stay byte-compatible: the heal prompt and PR line are colour-TTY session affordances; 'work --json' output shape only GAINS the already-existing pr_url field it prints today (work.py:108), nothing else changes

## Assumptions

- the continuation record fits any supported context budget: probed 2026-07-15 on a real 29-step artifact, build_continuation renders 5193 chars (~1.3K tokens) against the 48K default budget — no digest/truncation stage needed this increment

## Scope exploration

- `s1` — `colleague/escalation.py (build_continuation, t1)`: a pure five-section continuation-record builder from a partial TaskResult already exists (built for the agtag escalation path); #167 continue can consume it directly instead of inventing a new resume format
  - seeds: `c2`
- `s2` — `colleague/feedback.py + colleague/artifact.py`: get_last_work resolves the per-repo last work item id; find_artifact/read resolve its persisted TaskResult — 'continue last' needs no new state
  - seeds: `c2`, `c7`
- `s3` — `colleague/cli/_commands/session.py:931-946 (_next panel)`: the session already computes dirty-blocked (facts.dirty and not allow_dirty) and renders 'Safest next: commit or stash first' as TEXT ONLY; the dispatch path then lets the run hit the runtime refusal — the detection exists, the ACTION is missing (#168's exact paste)
  - seeds: `c3`, `c5`
- `s4` — `colleague/handoff.py (#149 guard) + docs/features/write-isolation.md`: the runtime-side dirty guard refuses uncommitted TRACKED edits unless --allow-dirty; the session passes allow_dirty through today (session.py:523-531) — the heal choice maps onto existing knobs, no new runtime surface
  - seeds: `c3`, `c5`
- `s5` — `colleague/contract.py:1150-1170 + colleague/cli/_commands/work.py:108,154`: TaskResult.pr_url is populated by the handoff and printed by the work digest; it is dropped on the session floor — no session/cockpit consumer exists
  - seeds: `c4`
- `s6` — `colleague/cockpit_run.py:113 (Ledger) + cli/_commands/_tui_sink.py`: the cockpit Last-run ledger carries files/commands/commits/publish_state but no pr_url; publish_state proves the ledger already distinguishes publish outcomes, so a pr link is a natural field
  - seeds: `c4`
- `s7` — `colleague/cli/_commands/session.py:2506-2565 (SlashSpec catalog)`: slashes are a typed catalog with categories + safety tags; /continue lands as one more SlashSpec entry, and 'colleague plan continue' is the existing verb-shape precedent
  - seeds: `c2`
- `s8` — `CLAUDE.md scope line (router exclusion) + docs/features/session-modes.md`: five sanctioned increments enumerate the only model-choice surfaces; continue must stay a Task-composition on the resolved backend to stay inside the line
  - seeds: `c6`, `c8`
- `s9` — `challenge pass / adjacent-systems lens: colleague/cli/_app.py flag registration (agentfront)`: work's flags are rendered through the imported agentfront App; the known agentfront#38 gotcha (Flag choices= does not validate value-carrying flags) means --continue's value ('last'|id) is validated explicitly in the command, not via choices=
- `s10` — `challenge pass / failure-mode lens: colleague/artifact.py write points + SIGKILL timing`: a hard-killed run can leave no artifact; 'continue last' would resolve to the prior completed run — seeded the wrong-run guard requirement
  - seeds: `c16`
- `s11` — `challenge pass / reversibility lens: git stash semantics at the heal prompt`: a stash the session created but never names is operator data at risk; seeded the consequence+undo requirement
  - seeds: `c17`
- `s12` — `challenge pass / concurrency lens: .colleague/last_work pointer under two concurrent sessions`: two sessions on one repo race the last_work pointer (last-writer-wins today); clean pass otherwise — parked as residual, explicit-id continue is the workaround
- `s13` — `challenge pass / observability lens: TaskResult lineage`: one-way lineage (continued_from on the NEW run) is sufficient; a reverse continued_by marker on the old artifact would mean mutating a written artifact — rejected, artifacts stay immutable

## Decisions

- #170 'redesign' closes on the arc PR's merge, citing the exported spec — the three concrete affordances (#167/#168/#169) ARE the interactive redesign increment; no separate umbrella stays open
