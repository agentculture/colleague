# Arm brief — large surface, where in-seat reading provably does not fit

Pre-registered for the `purpose-tools-get-chosen` arm matrix (plan t10, spec
`docs/specs/2026-08-29-purpose-tools-get-chosen.md`, covers c47/h35). The row
number is assigned by plan t14; the row cites this file by path, in the rows
47-50 shape.

## Why this brief exists

Row 49's own recorded reading is "on a three-small-file brief cortex reads
the files itself" — which describes RATIONAL behaviour. Three small files are
cheaper to read than to delegate, so every arm run only on the decomposable
brief measures how hard the levers can push the model into a WORSE decision.
Spec c47/h35 therefore requires at least one brief whose non-delegating
baseline demonstrably cannot finish in-seat, so the levers are also tested
where delegation is the correct choice.

## The repo fixture (build before the run, same fixture on every arm)

A throwaway repo with an `.eidetic` store (eidetic CLI 0.13.0, so the distill
seat can fire) containing **twelve modules** under `src/`, named `mod_a`
through `mod_l`, each **~1,500 lines / ~60,000 characters** (~40 chars per
line). Each module defines 8-12 public functions with docstrings — bulk comes
from module-level data tables and long bodies, not from extra functions. Four
pairs of modules contain the SAME algorithm under DIFFERENT function names,
parameter names, local variable names and docstrings (so the duplication
cannot be found by grepping one identifier), and the four pairs implement four
GENUINELY DIFFERENT algorithms — interval coalescing, decay-ranked ordering, a
rolling 32-bit checksum, even partitioning — so "four pairs" is a well-defined
answer rather than one eight-way duplicate. Each module imports two neighbours
and bridges to BOTH of them, so the call graph between modules has two
outgoing edges per module and is only visible from the import lines plus the
call sites in the bodies.

Generate it deterministically and commit the generator alongside the row so
the fixture is reproducible; record the exact per-file line and byte counts
in the row.

## Why the non-delegating baseline cannot fit (the arithmetic)

Both arithmetic paths are computed from shipped defaults, not from
guesswork; the pilot below is what turns them into evidence.

- **Step budget.** `read_file` pages at 25,000 chars per call
  (`colleague/truncation.py` `DEFAULT_TOOL_MAX_CHARS`, applied by
  `colleague/readpage.py`; `COLLEAGUE_MAX_OUTPUT_CHARS` is a CEILING only, so
  its 68,000 default does not widen the page). A ~60,000-char module is
  therefore 3 `read_file` calls; twelve modules are **36 calls** before a
  single `list_dir`, `grep_search`, `edit_file` or `finish`. The default step
  budget is **40** (`colleague/config.py` `_DEFAULT_MAX_STEPS`). Reading the
  surface in-seat consumes 90% of the budget and leaves 4 steps for the
  survey write-up plus the edit.
- **Context budget.** ~757,000 characters of module text is roughly
  **189,000 tokens** at ~4 chars/token, against a default context budget of
  **131,072** (`_DEFAULT_CONTEXT_BUDGET`). The fill-line threshold is 0.8
  (~104,858 tokens), crossed somewhere around the seventh module, so an
  in-seat read of all twelve crosses the capacity decision at least once and
  cannot hold the whole surface at once regardless of how the crossing
  resolves.

A delegating run does not pay either cost in the acting seat: the child reads
and returns a digest, and only the digest lands in cortex's history.

## Pilot run — to be recorded before the arm (OPERATOR's job, not the brief author's)

Plan t10's acceptance criterion 2 ("the large-surface brief's non-delegating
baseline provably hits a budget or context limit, evidenced by a recorded
pilot run") is **explicitly reassigned to the rig operator** for this arc: the
brief author authored the brief and the arithmetic above and did NOT run
colleague. This section states exactly what the pilot must demonstrate so
criterion 2 can be discharged before any arm runs.

**What the pilot must demonstrate.** ONE run of the brief below on the
baseline arm (no lever armed), on the arc's current tip, against the fixture
above, with the acting seat holding no delegation tool it would not hold in
the baseline. The pilot passes if the run hits **at least one** of the three
limits — and the row must say WHICH one, never a bare "it struggled":

1. **step budget exhausted** — `incompletion.reason == "budget-exhausted"`
   (`colleague/incompletion.py` `REASON_BUDGET_EXHAUSTED`) with a non-`ok`
   status and `stats.step_count` at the configured `max_steps`;
2. **context budget crossed** — `capacity_decision` present on the artifact
   (the fill-line offered its one decision), and/or `capacity_warning` set,
   and/or `stats.counts.results_blanked` > 0 (microcompaction blanked older
   tool results) or `stats.counts.outputs_spilled` > 0 (a tool output spilled
   to `.colleague/tool-output/`);
3. **web budget consumed** — `stats.web_calls` at `COLLEAGUE_WEB_MAX_CALLS`
   (default 20, `colleague/webbudget.py`). Not expected on this fixture,
   which is repo-local with no upstream references; listed because the spec's
   honesty condition names it as one of the three admissible limits, and
   because it is the limit row 50 actually hit.

**What voids the pilot.** A stall rather than a budget (a `step-stall`
warning / `stats.counts.stream_guard_trips` > 0, the #438 lane) is NOT
evidence for criterion 2 — it is a rig failure and the pilot must be re-run.
A pilot that finishes `ok` well inside both budgets means the fixture is too
small: enlarge it (more modules, or longer modules) and re-pilot, and record
each attempted size. If no size can be found at which the non-delegating
baseline provably struggles — for instance because the model consistently
finds a cheap `grep_search` path that answers the brief without reading
bodies — then per spec c47's instruction the arc RECORDS that it could not
construct such a brief, and every subsequent arm result is reported as
measuring small briefs only. That outcome is a legitimate finding, not a
failure of this file.

**Record where.** The pilot's run id, tip, fixture counts, and the artifact
field that evidenced the limit go into the arm's row in `docs/live-testing.md`
(plan t14) before the first arm run, provable by git log order.

### Pilot result — RECORDED 2026-08-29 (criterion 2 discharged as a NEGATIVE finding)

Three attempts on tip `1d49c54`, fixture generated by
`scripts/make_large_surface_fixture.py` (deterministic; 12 modules, 17,996
lines, 708,496 chars — per-module 1,496–1,507 lines / ~58,800–59,500 chars).

| # | Fixture | Run | Outcome |
|---|---------|-----|---------|
| 1 | shared pair doclines; algorithm at a fixed top offset | `eeb7f261f87d` | `ok` in 18 steps — **no limit hit**; all four pairs found correctly |
| 2 | per-side doclines; algorithm still at top | `75b0c4a23087` | `incomplete` — **VOID**: stream-lifetime stall at 1800 s, `stats.counts.stream_guard_trips == 1` |
| 3 | algorithms scattered to per-module offsets (194–597) | `b7b2c91748f9` | `error` — interrupted by SIGTERM at 5 steps under external GPU contention; not a result, but see the mechanism below |

**The finding: the baseline does not struggle, and the reason is the tool
surface, not the fixture size.** The acting seat never used `read_file` for
the survey. It built a symbol index in ONE call —
`grep -nE '^(def |class |import |from )'` across all twelve modules — and then
read only the ranges that mattered with `sed -n 'START,ENDp'`. Attempt 3
proves scattering does not defeat this: the grep index *hands the model the
offsets*, and it read lines 194, 229 and 264 directly in a single command.

The brief's arithmetic above assumes `read_file`'s 25,000-char paging, and
**paging only binds on `read_file`**. `run_command` reads whatever range it
likes, so 708 KB of surface is never traversed and neither budget is
approached.

**Consequence for the arm matrix — DECIDED (operator, 2026-08-29, spec c55).**
Per spec c47's own instruction this is recorded rather than engineered around:
at this size, on this surface, no brief was constructed whose non-delegating
baseline provably hits a limit. The operator has **accepted "small briefs
only" as the reported scope of every arm** — the h35 branch the spec
authorises explicitly. The acting seat is NOT narrowed further: dropping
`run_command` would be a far larger surface change than plan t8's
`grep_search`/`glob` drop and would alter what the arm measures.

Every arm row must therefore carry this scope line verbatim:

> measures small briefs only (large-surface pilot refuted the cannot-fit
> premise; see `arm-large-surface.md`)

This brief still runs as the matrix's larger-surface arm — it is a bigger
brief, just not one that provably forces a limit. Its results are read under
the same scope line as the rest.

**The pilot ran against a superseded generator.** The three attempts above
used the generator as it stood on tip `1d49c54`. A Qodo review of PR #450
(comments 3887387011 / 3887387013 / 3887459533) then found three defects in
it — all four pairs rendered the *same* implementation (an eight-way
duplicate, so "four pairs" was not well defined), the filler loop emitted
dozens of public functions per module instead of the 8-12 specified here, and
the bridge selector `calls[i % 2]` under an `i % 4 == 0` guard could only ever
pick the first neighbour, so the second call edge was missing. The generator
is fixed; the fixture it now produces is **12 modules, 18,362 lines, 757,130
chars** (per-module 1,518–1,539 lines / 62,654–63,369 chars, 10–11 public
functions each, both call edges present, the four algorithms behaviourally
distinct). The counts in the table above are left as recorded because they
describe the runs that actually happened — they are not reproducible from the
current generator. The pilot's *finding* (the acting seat builds a grep symbol
index and does ranged `run_command` reads, so neither budget is approached) is
about the tool surface, not the fixture's internals, and is unaffected; a
re-pilot on the corrected fixture is nonetheless the honest way to re-confirm
it if the arm is re-run.

**Honest limit of this pilot.** One fixture size was tested (708 KB). The
mechanism observed is size-independent in principle — a symbol index plus
ranged reads scales with the number of *symbols of interest*, not with file
size — so enlarging the fixture is unlikely to change the outcome while
`run_command` is on the seat. That is an argument, not a measurement: larger
sizes remain untested.

## Pass bar (committed BEFORE the run)

- delegation calls >= 1 on >= 2 of 3 runs, where a delegation call is a step
  naming any tool that spawns a child on the arm's own surface — read off the
  artifact steps, never from prose
- markup count per run recorded beside it (the #360 dropped-call counter,
  plan t6): a zero-delegation run with markup > 0 is INCONCLUSIVE
- **task success recorded beside the delegation rate** (spec c46): status,
  whether exactly one module changed, whether the interface stayed stable,
  and whether the survey named all twelve modules. On this brief the
  non-delegating baseline is EXPECTED to fail that bar — if it succeeds
  anyway, that is the headline result and it is recorded as such
- the limit the baseline hit, quoted from the artifact field that showed it
  (the same three-way choice as the pilot)
- turns <= 1.0x and wall <= 1.2x vs the baseline arm at the same tip, n=3
  (`scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0`, from artifact
  stats, never from prose) — with the honest note that a ratio against a
  baseline that never delivered compares an unfinished run to a finished one
- reasoning chars per run
- a miss is written as a miss

## The brief (paste into `colleague work`)

```text
Survey twelve modules, then remove one duplication.

1. Survey every module under `src/` in this repo — there are twelve, `mod_a`
   through `mod_l`, and each is around 1,500 lines. For each module report
   its public functions and what they do, and say which other modules it
   calls. Then name the pairs of modules that implement the SAME algorithm
   under different function names — the names and local variables differ, so
   matching identifiers alone will not find them.

2. If the survey is too large to hold at once, you may hand parts of the
   read-only survey to helpers and review their digests before acting — or
   do all of it yourself; the choice is yours.

3. Then change exactly ONE module to remove ONE of the duplications you
   found, keeping its public interface stable. Make the smallest edit that
   does it, say which module you changed, which duplicate pair it belonged
   to, and why you picked that one.
```

Note: this brief names no tool, for the reasons recorded in
`docs/live-testing/briefs/arm-decomposable-neutral.md` — the same brief runs
across arms whose surfaces differ, so any tool name would be a steer that
some arm cannot act on.

## After the run — record (never fill before)

Per-run delegation count and which tool was called, markup count, task
success (status / survey completeness / module changed / interface stable),
the limit hit and the artifact field evidencing it, the child's served model
where a child ran, `stats.step_count`, `stats.counts` (all six), turns,
wall-clock and reasoning chars; the delegation-rate column from
`scripts/compare_arms.py`; the prompt digest read off the artifact (a
mismatch with the arm the row claims voids that run); the memory distill
counters (attempts/validated/detached) and the distill child's served model.
