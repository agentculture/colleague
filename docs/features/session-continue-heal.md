# Interactive finishes what it starts — continue, heal, PR-at-a-glance

Three session affordances landed together (spec
[`2026-07-15-interactive-finishes-what-it-starts`](../specs/2026-07-15-interactive-finishes-what-it-starts.md),
plan of the same date; issues #167 / #168 / #169, with #170 closed by this arc
as the interactive-redesign increment):

## 1. A cut work item continues with one flag (#167)

- **CLI:** `colleague work --continue <id|last>` (short `-c`). Resolves the
  reference (`last` via the per-repo `last_work` pointer, else an explicit task
  id), loads the persisted artifact, and seeds the NEW run's instruction with
  the existing five-section continuation record
  (`colleague/escalation.py` `build_continuation`, rendered VERBATIM — probed
  at ~1.3K tokens on a real 29-step artifact) plus the original request.
  Positional text becomes extra guidance appended after the seed;
  `--command` cannot combine with `--continue`.
- **Session:** `/continue [id|last]` (bare `/continue` = `last`) rides the SAME
  resolve path, then dispatches through the ordinary work path — cockpit,
  heal guard, artifact writes all behave like a fresh dispatch.
- **Lineage:** the new run records `TaskResult.continued_from = <old id>`
  (omit-when-None; stamped before every artifact write, success AND failure
  paths). One-way: the old artifact is never mutated.
- **Wrong-run guard:** a status-`ok` artifact is refused with
  `nothing to continue: <id> finished ok` — a SIGKILL-cut run may have written
  no artifact at all, and silently continuing the *previous, completed* run
  would be worse than an error. Missing/corrupt artifacts error naming the id;
  never a silent fresh start (`colleague/continuation.py`).

## 2. A dirty tree heals with one explicit choice (#168)

A colour-TTY session that KNOWS the dispatch would hit the #149 refusal
(`facts.dirty` and not `--allow-dirty`) renders the three-choice heal prompt
BEFORE the doomed run (`colleague/heal.py`, pure copy + parsing):

| choice | consequence (in the prompt verbatim) | undo (also in the prompt) |
|--------|--------------------------------------|---------------------------|
| commit-onto-work-branch | commits your uncommitted tracked edits onto the work branch | `git reset --soft HEAD~1` |
| stash | stashes your uncommitted tracked edits | `git stash pop` (the created ref is named) |
| abort (default — empty input) | aborts — your edits remain untouched | none needed |

The commit choice is a **one-run waiver** (consumed by the next dispatch,
never sticky). The stash runs via `handoff.heal_stash` (the sanctioned
subprocess module) and names `stash@{0}` + the recovery line.

## 3. The PR a run just opened is one glance away (#169)

`Ledger.pr_url` is reconciled verbatim from `TaskResult.pr_url`; the Last-run
panel gains a `PR` row and the post-run line appends `· PR: <url>` — ONLY when
the handoff actually returned one. A local-only run renders exactly the
pre-#169 output (test-pinned). The mid-run observed ledger never claims a PR.

## Honest limits

- **Top-level work items only** (boundary c19): subagent children, plan-mode
  runs, and the resident/talk front keep today's behavior; a follow-up re-spec
  covers them if evidence demands.
- **`last_work` races under two concurrent sessions** (parked v2, risk r2):
  `continue last` may resolve the other session's run — an explicit id is
  exact. No locking until evidence says it's worth the complexity.
- **Off a colour TTY the heal prompt never renders** — a piped/`--json`
  session falls through to today's refusal text byte-identically (a prompt
  must never block a pipe, h12).
- **The runtime #149 guard is untouched** (h9): the heal is a session-surface
  affordance; the bare CLI still refuses a dirty tree.
- **Continue re-runs on the SAME resolved backend** (boundary c6): the seed is
  Task-content composition; no task→model routing rides in.

## Boundary grep gate (c19/h15, executed 2026-07-15)

Run against the full arc diff (`git diff main...HEAD`):

- paths matching `resident/ | colleague/plan/ | subagents.py` touched: **none**
- diff hunks in `colleague/config.py`, `colleague/engines/`,
  `colleague/registry.py` (engine/model resolution): **none**

## Acceptance sweep (h1/h4 — one flag · one choice · zero moves)

| flow | proof (fails on main, passes on this branch) |
|------|----------------------------------------------|
| one flag: `work --continue last` resumes a cut run with lineage | `tests/test_cli_work_continue.py::TestContinueE2E::test_continue_last_reaches_terminal_state` |
| one move: session `/continue` | `tests/test_session_continue.py::test_bare_continue_defaults_to_last` |
| one choice: dirty dispatch heals, never refuses on a colour TTY | `tests/test_session_heal.py::test_commit_choice_is_a_one_run_waiver` (+ abort/stash/off-TTY pins) |
| zero moves: PR link visible after the run | `tests/test_session_pr_link.py::test_last_run_panel_shows_pr_only_when_present` + `test_post_run_line_appends_the_pr_link` |
| wrong-run guard | `tests/test_continuation.py` ok-guard cases + `tests/test_session_continue.py::test_continue_ok_run_is_refused_with_the_cli_error_shape` |
| lineage omit-when-None (all-engines) | `tests/test_contract_lineage.py` + `tests/test_e2e_mock.py` shape pin |
