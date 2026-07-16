# indefinite-run — colleague works until it's done

> An **armed** run (`--until-done`) no longer dies at its step budget: when an
> episode exhausts its budget mid-task, colleague automatically continues from
> the persisted artifact — carrying the prior episode's **actual tree state** —
> and hands off exactly once, at the end of the chain. Independently, two
> **ambient** (default-on) loop improvements land with it: the fill-line
> re-arms per crossing, and a compaction summary is validated before it
> replaces history.

## Why it matters (live evidence)

Real tasks outgrow one episode. The recorded eidetic work-lesson
`work-lesson-54ead8272f22` is the canonical example: *"TASK t4 (TDD, work
test-first …) … steps=46 … Signals: step budget exhausted"* — a legitimate,
progressing work item cut at its `max_steps` budget, waiting for a **manual**
`work --continue` that would restart on a fresh worktree at HEAD without the
prior episode's edits. The pattern recurs across the work-lesson ledger
(multiple items incomplete at steps ~38–49). Chaining turns colleague from a
per-episode tool into a task-completer — without weakening the honesty rules
(#313) that make its results trustworthy.

## The split, stated honestly

The feature ships in two deliberately different postures:

- **ARMED (opt-in): episode chaining.** Everything under `--until-done` below.
  Unarmed behavior is byte-identical to v1.46 — chaining is armed, never
  ambient.
- **AMBIENT (default-on): loop improvements.** The fill-line re-arm and the
  compaction validator are **not** flag-gated — every run gets them. They
  change default behavior (a long run can compact more than once; an empty
  compaction summary is rejected instead of silently replacing history) and
  are recorded as such in the CHANGELOG.

## ARMED — episode chaining (`--until-done`)

### Arming and knobs

`colleague work --until-done` and `colleague session … --until-done` (both
fronts share the flag; `--background` forwards it to the detached child via
the forwardable-flags table). Standard precedence — flag > env > config.json >
default:

| Knob | Env | config.json | Default |
|------|-----|-------------|---------|
| arm | `COLLEAGUE_UNTIL_DONE` | `{"until_done": true}` | off (dormant, byte-identical) |
| `--max-episodes N` | `COLLEAGUE_MAX_EPISODES` | `{"max_episodes": N}` | 5 when armed; `0` = unlimited |

`--until-done` is arm-only (no `--no-until-done`), so a config-armed chain
stays armed.

### The chain loop

`execute_work_chain` (`colleague/cli/_commands/work.py`) is the single
implementation on **both** fronts — the CLI adapts parsed argv onto it and the
session's armed dispatch calls it directly, so the session can never fork the
semantics. Each episode is an ordinary bounded work item with its own
`max_steps` budget, `_EXIT_BUDGET` exit, and artifact — chaining lives at the
work-dispatch layer, **outside** the loop; no code path extends a live
episode's step budget.

Decisions are pure verdicts in `colleague/chain.py`:

- **Continuable-exit allow-list** — `CONTINUABLE_REASONS` is exactly
  `{"budget-exhausted"}`, an explicit enumeration, never a `status != ok`
  catch-all: `ok`, `error`, pilot-stop, `tool-protocol-broken`,
  `no-progress-zero-steps`, `write-no-changes`, and `empty-deliverable` are
  each a deliberate halt with its own meaning. Because the #313 **soft rule**
  suppresses the incompletion record when a budget exit already changed files
  (delivered-so-far is not absence), `exit_reason` also maps the persisted
  `not_finished` flag to `budget-exhausted` — the headline chaining case.
- **No-progress guard** — an episode that lands no new commits on its branch
  (`git rev-list --count`, where the #222 WIP commit counts) AND adds no new
  changed-file evidence to the chain's ledger halts the chain. Chaining never
  becomes a way to launder incompletion: a halted chain returns its last
  episode's honest non-ok result.
- **Episode cap** — default 5 armed, `0` = unlimited.

### Tree carry

Episode N+1's isolation worktree bases on episode N's `colleague/<id>` branch
tip (`isolation_worktree_add` `base_ref`, verified with `git rev-parse`
first), so edits accumulate instead of being re-derived from a 1.3K-token text
seed. The carry mechanism is #222's WIP sweep, which is **best-effort**
(`suppress(Exception)`): a missing/reaped prior branch degrades to today's
HEAD base with a recorded warning on the outcome — never a crash.

### Handoff once, at chain end

Every episode dispatches with push/PR suppressed. A **completed** chain
(ok-finish) performs the arming invocation's handoff choice exactly once: the
final episode's branch carries the cumulative diff (each episode based on the
prior tip), and the intermediate `colleague/<id>` branches are reaped
(ancestors of the kept final branch only — a degraded-base episode's unique
work is never destroyed; artifacts keep the evidence). A **halted** chain
never pushes and keeps every episode branch as inspectable WIP. Read-only
verbs stay handoff-free.

### Verbatim config inheritance

Every episode re-dispatches with the SAME resolved options — engine, config
(resolved once; the mode profile applied once at arming), `--no-pr`,
`--allow-dirty`, budgets, attachments. Nothing re-reads env or
`.colleague/config.json` mid-chain (the background-child forwardable-flags
precedent).

### Accounting, lineage, and `--continue`

`continued_from` stamps episode-to-episode; each chained artifact carries a
running `ChainView` (`colleague/contract.py`, the `"chain"` key,
omit-when-None so non-chained artifacts serialize byte-identically) whose
totals are **sums of per-episode exact usage** — never estimated.
`--continue` composes: episode 1 is the continued task (dispatched at HEAD,
exactly like an unchained `--continue`), and a cut chained run's accounting
resumes via `read_chain_view`.

### Piloting and observability

On a watched chain the driver checks the just-finished episode's flight
control **between** episodes — a cooperative `stop` landing in the boundary
window halts the chain (`pilot-stop`) before the next episode dispatches. Each
boundary appends a `type="episode-transition"` marker to the prior episode's
feed (`episode N of <cap>: continuing <id>`) and announces the same text on
the progress sink, so a pilot tailing episode 1 can follow the chain hop by
hop. In-episode stop checks and the heartbeat (#308) are unchanged.

### Chain-aware feedback

`feedback record` on a chain tail traverses the `continued_from` lineage and
stamps the grade on **every** episode (`grade_chain`), each record carrying an
omit-when-False `chain` marker. A lineage cycle (visited-set) or a missing
artifact terminates the walk cleanly — never a loop, never a crash.

### Unrepairable compaction → finish-with-handoff

When chaining is armed (`until_done` threaded onto the loop's
`ContextControls.chain_armed`) and a compaction turn produces an unrepairable
(empty) summary, the loop injects the deterministic FINISH-WITH-HANDOFF
instruction instead of grinding on: the model finishes with a continuation
summary and the chain re-seeds cleanly. Unarmed runs keep the
lossy-windowing floor.

## AMBIENT — default-on loop improvements

- **Fill-line re-arms per crossing** (supersedes v1's "fires at most once per
  work item", #156): a resolved offer re-arms once the run drops back under
  the line, so a long run can compact repeatedly. Total compaction turns are
  bounded by the compaction cap (`COLLEAGUE_COMPACTION_CAP` env >
  `config.json` top-level `compaction_cap` > default `DEFAULT_COMPACTION_CAP = 4`
  in `colleague/fillline.py`; `0` or any non-positive = unlimited; shown in
  `colleague config show`); the cap reached suppresses further
  offers and is recorded once on `TaskResult.capacity_warning` plus a phase
  notice — never silent.
- **Deterministic compaction validation** (`validate_compaction`): the MAIN
  model's summary is cross-checked against the run's own evidence — the goal's
  first line and every changed-file path from the step trace; anything missing
  is appended as one deterministic evidence block (idempotent repair). An
  empty/whitespace summary is **rejected** — the `(no summary produced)`
  silent-amnesia path is gone from the loop. On rejection, an unarmed run
  keeps the lossy-windowing floor; an armed run takes finish-with-handoff (see
  above).

Both are runtime-owned (all-engines): they fire identically for `mock` and
`vllm-openai`.

## Honest limits

- **The WIP sweep is best-effort** (`suppress(Exception)` in
  `_preserve_isolated_wip`; an empty diff is a no-op): tree carry can find the
  prior branch missing and degrades to a HEAD base with a recorded warning —
  the chain never assumes the sweep succeeded.
- **Crawl risk under `--max-episodes 0`**: a chain making trivial-but-real
  progress each episode (one new commit or one new changed file) never trips
  the no-progress guard and never halts. That is explicit operator intent —
  `0` means unlimited — and the flight-plane stop plus the heartbeat are the
  brakes.
- **Pre-finish gate deferral** (#335): a chain-dispatched episode whose exit is
  continuation-shaped (budget-exhausted, or a declared finish-with-handoff)
  skips the four pre-finish gates (lint #200, coherence #294, test-integrity
  #203, affected-tests #213) and stamps a typed marker `TaskResult.gates_deferred`
  on its artifact; the chain accumulates deferring episode ids on
  `ChainView.deferred_gate_episodes` (omit-when-empty). The final finish-shaped
  episode runs all four gates over the union of its own changed files plus every
  prior episode's changed files that still exist in its worktree. Honest limits:
  a HALTED chain (no-progress / cap / error) keeps its skipped gates — recorded,
  never backfilled; its outcome line names the deferring episodes and the kept
  WIP branches. A COMPLETED chain whose final episode deferred (ok-finish +
  declared fill-line handoff, #340) warns on the outcome line and carries the
  warning in the handoff PR body. Detection-only stance: halted chains keep
  ungated WIP by design; `work --continue` is the remedy (its finishing episode
  re-gates over the inherited union). The union paths the gate existence filter
  removes are recorded once per run on `capacity_warning`
  ("N prior-episode path(s) no longer exist and were not graded", #342). The skip
  keys on the chain-dispatch marker, never `config.until_done`, so subagent
  children of an armed run still run their gates.
- **Read-only chains bypass the commit-evidence half of the no-progress
  guard**: a read-only role structurally cannot commit or change files, so the
  guard's evidence inputs don't apply (`progressed=None`); the episode cap
  bounds a read-only chain instead.
- **Boundary stop and transition markers are watch-gated**: a `--no-watch`
  chain ignores flight at episode boundaries too (matching the in-episode
  unwatched semantics). The transition marker recreates the prior episode's
  already-reaped feed file with the marker as its only record — marker-only
  feeds are ordinary residue for `colleague clean`.
- **The compaction cap is operator-tunable** via `COLLEAGUE_COMPACTION_CAP` env
  > `config.json` top-level `compaction_cap` > default
  `DEFAULT_COMPACTION_CAP = 4` (`colleague/fillline.py`); `0` or any non-positive
  value means unlimited; visible in `colleague config show`.
- **Compaction validation runs on the MAIN model only** — the compaction
  prompt is the main model's own windowed history, which structurally cannot
  fit the deepthink window (the recorded window-asymmetry decision,
  dual-model-deepthink 2026-07-01); no second-model lane, no LLM-judge
  validation.
- **Chain grading traverses lineage best-effort**: a cycle or missing artifact
  terminates the walk cleanly — episodes beyond the break simply keep their
  existing (or no) grade.
- **#313 is never weakened**: a halted chain reports its last episode's honest
  non-ok status with reason and evidence; the allow-list plus no-progress
  guard exist precisely so auto-continue can't become an infinite no-progress
  loop.

## Key files

- `colleague/chain.py` — the pure decision layer: `CONTINUABLE_REASONS`,
  `exit_reason`, `should_continue`, `episode_progressed`, `ChainState`,
  `resolve_chain_seed`.
- `colleague/cli/_commands/work.py` — `execute_work_chain` (the chain loop,
  both fronts), `_resolve_chain_arming`, `_chain_should_start_next`,
  `_chain_progress`, `_chain_finalize`.
- `colleague/worktrees.py` — `isolation_worktree_add(…, base_ref=…)` +
  `IsolationAddOutcome` (tree carry + degrade).
- `colleague/fillline.py` — `DEFAULT_COMPACTION_CAP`, `cap_reached`,
  `validate_compaction`, `build_handoff_instruction`.
- `colleague/loop.py` — per-crossing `_maybe_offer_fillline`, cap recording,
  validator consumption, `chain_armed` handoff policy.
- `colleague/flight.py` — `append_episode_transition`,
  `transition_announcement`, `read_stop`.
- `colleague/contract.py` / `colleague/artifact.py` — `ChainView` +
  `read_chain_view`.
- `colleague/feedback.py` — `grade_chain`.
- `colleague/config.py` — `until_done` / `max_episodes` resolution.
- `tests/test_chain_e2e.py` — the executable form of the announcement
  (chain-completes, chain-halts-honestly, compaction-validated, dormancy).

## Spec + plan

- [`docs/specs/2026-07-15-indefinite-run.md`](../specs/2026-07-15-indefinite-run.md)
- [`docs/plans/2026-07-15-indefinite-run.md`](../plans/2026-07-15-indefinite-run.md)
