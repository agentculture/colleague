# Post-run addendum — code review, field-play, and the longer-horizon outlook

Added before merge (2026-08-09), after the operator played both games and
commissioned a full-codebase comparison. Extends `final-comparison.md`; the
falsifying verdict there stands unchanged.

## Operator field-play (the verification rung the harness lacked)

The operator played both builds: simple textures, buggy, single screen; the
OFF build not smooth; the ON build's sword barely usable (could not win);
hard to tell which is better. Every complaint traced to a recorded-but-
uncorrected anomaly or to scope: the ON swing animation is clobbered every
frame by the run-idle animation plus a stale keyup-timer race; the OFF
8-frame input latch ignores keyup (133 ms of motion, dead stop, auto-repeat
stutter); one level and primitive art were the commissioned boundary.
"Hard to tell which is better" matches the measured run (identical mean
grades). All CLI playthroughs were discrete key dispatches — held-key feel,
camera scale, and feedback visibility are structurally invisible to that
method. The NEBULA ladder gains a rung: static checks < browser automation
< human hands.

## Full-codebase review (identical rubric, one reviewer per repo)

| dimension | ON | OFF |
|---|---|---|
| Architecture/modularity | 5 | 3 |
| Correctness | 3 | 2 |
| Physics/input | 4 | 4 |
| State contract | 5 | 4 |
| Extensibility | 4 | 4 |
| Hygiene | 5 | 3 |
| Human playability | 3 | 2 |
| **total** | **29/70** | **22/70** |

ON is the better codebase on the bones: it kept its 4-module structure
across all 8 tasks (OFF grew a 1003-line monolith whose physics function
spans 363 lines), better hygiene, and a state element free of the OFF
build's serialized-THREE-mesh bloat. OFF wins per-enemy state visibility
(ON exposes enemies as a bare count — combat is undrivable from state).
Cross-reviewer calibration caveat: two reviewers, identical prompts —
totals are directional; the qualitative findings are the trustworthy part.

**The finding that outranks the scores: both arms shipped the SAME
cross-cutting defect classes**, invisible to every per-task acceptance bar
in both arms — a jump apex unable to reach any platform (both from the same
thickness-vs-spacing unit confusion; the ON level is completable only via
its own head-snap collision bug), walls rendered but never collided (OFF:
un-signaled infinite-fall softlock), no terminal-state gating (negative
lives / falsy-trap resurrection), fall damage punishing the levels' own
designed descents, and input tuned for synthetic taps at held-key expense.
Same worker, same briefs, same blind spots — regardless of memory arming.
**The binding constraint on artifact quality was criteria design, not the
memory lane.** The three criteria changes this implies are recorded on
issue #394 (standing cross-cutting invariants, a human-hands leg, a
state-contract lint).

## The longer-horizon hypothesis (operator addendum, both directions)

The ON arm would potentially perform better as work continues — the store
compounds, and the input-trap class already stopped recurring within this
run — with a risk of DECLINING if learning is not done correctly, on two
failure modes: too much context, and difficulty finding the right lesson.
The run's own artifacts show the leading edge of both: ON recall injections
grew monotonically 0 → 141 → 1570 → 2333 → 3149 → 3838 chars,
near-saturating the 4000-char cap by g7 at fixed top-k=5 — from which point
selection quality, not store size, is the binding constraint (no relevance
threshold, consolidation, or supersedes-driven pruning exists in the
recall-before path today). Rerun instruments recorded on #394: measure the
curve (per-task corrections vs store size), score retrieval precision per
task from the recorded recalls, and treat store hygiene as an experimental
knob.

## Program advice (the integrator's opinion, recorded as such)

1. The verdict falsified the claim as formulated, not the mechanism: the
   lane had never stored a production lesson before this run (#391/#392),
   and once alive, class-level transfer appeared within two tasks. Keep it;
   stop expecting volume-level effects from process-shaped lessons — both
   experiments now converge on lesson SPECIFICITY as the variable.
2. The bigger lever is the acceptance bar, not the memory machinery: better
   bars produce more meaningful corrections, which produce better lessons —
   that is the flywheel worth building.
3. Sequence: merge this PR → land #393 (streaming; removes the timeout
   confound and most chain legs) → lesson-specificity redesign + retrieval-
   precision instrumentation → benchmark criteria redesign per #394 → THEN
   rerun. NEBULA (#377) waits until the redesign proves out.
4. Bank the quiet wins as standing practice: the continuation lane rode out
   five peer flaps with zero lost work; capture sidecars and honest
   incompletion told the truth throughout; the experiment found four real
   pipeline bugs as a side effect. One falsifiable dogfooding experiment
   per arc, with this run's ledger discipline, is the cheapest QA colleague
   has.
