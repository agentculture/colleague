# #387 exp-2 — the #378 correction-diff ablation: FINAL COMPARISON

Both arms executed in full on 2026-08-08 (UTC): 8 identical game tasks each
(byte-identical brief files), worker `unsloth/Qwen3.6-35B-A3B-NVFP4` on every
leg (verbatim from WorkStats, 32/32 artifacts), separate throwaway repos +
eidetic stores, ON arm first (c32), one loop at a time, every task landed via
a real PR + squash merge + immediate grade, every capture sidecar fired.

## Verdict on the pre-committed c20 bar

**FALSIFYING.** The bar: equal-or-worse ON on the primary metric
(integrator-correction lines) is falsifying, never softened. Measured:

| metric | ON (learning armed) | OFF (COLLEAGUE_MEMORY=0) |
|---|---|---|
| **correction lines (primary)** | **57** | **38** |
| per-task series | 0, 0, 10, 17, 1, 2, 27, 0 | 0, 2, 0, 11, 9, 12, 0, 4 |
| mean grade (fixed rubric) | 3.75 | 3.75 |
| grades | 5,5,3,3,3,3,3,5 | 5,3,5,3,3,2,5,4 |
| worker steps (verbatim) | 661 | 601 |
| model turns (verbatim) | 503 | 493 |
| chain legs | 16 | 16 (incl. one 0-step flap casualty) |
| duration (reported, NEVER load-bearing) | 26,806 s | 19,892 s |

The ON arm required MORE integrator-correction lines than the OFF arm. The
#378 success signal ("learning ON reduces integrator-correction volume") is
**falsified on this run**. Secondary metrics are near-parity.

## Purity + arming evidence (read from artifacts, not assumed)

- OFF: `memory: null` on **16/16** artifacts — zero recall blocks (h4/h16).
- ON: memory armed on 16/16; recall fired on 15/16 (g1's cold-store 0 is the
  honest exception); store grew to 8 code-lessons + work-lessons/distills.
- Store isolation: `EIDETIC_DATA_DIR=<arm>/.eidetic/memory` on every dispatch
  AND grade (the t6 finding: eidetic 0.13 recall otherwise merges + migrates
  `$HOME` records — reproduced in throwaway probes before any arm ran).

## What the falsifying number does NOT say (recorded texture, per-task files)

1. **Class-level transfer in the ON arm was real and observable.** The
   input-plumbing correction class (g3 latch 10 lines, g4 key-naming 17)
   never recurred once its lessons stored: g5 `x→KeyX` and g6 `e→KeyE`
   applied BOTH stored patterns unprompted, commented (verifier-cited
   file:line). ON's residual corrections shifted class each time.
2. **The OFF arm compensated through code-as-memory.** Its g3 worker
   rediscovered the discrete-press defect in-run (verbatim trace), dead-ended
   on a nonexistent webglass `evaluate` verb, then self-built an 8-frame
   latch — at the cost of the run's longest chain (4 legs / 195 steps vs ON
   g3's 3 / 137 + 10 corrected lines). Its g7 reused its own g5 `struckIds`
   dedup for enemies (0 lines vs ON g7's 27). The codebase itself is a memory
   channel the ablation cannot remove; recorded as a design insight, not an
   excuse.
3. **Same-cell defects differed in kind.** g4: both arms shipped a dead jump —
   ON via key naming, OFF via landing-snap physics; zero shared correction
   lines. g6: both arms shipped a lever unreachable behind its own door; OFF
   added a scope-bug crash cluster (its grade-2 worst cell).
4. **ON's 27-line g7 dominates its total.** Combat semantics (static patrol,
   single-swing kill, 1-hit-per-life + falsy resurrection) — a task-complexity
   spike, not an input-class regression.
5. **N=8 per arm, one run.** Ordering confounds: ON ran first (integrator
   familiarity accrues to OFF per c32 — conservative for the hypothesis, and
   the hypothesis still lost); thor-peer flaps hit both arms (2 ON-era /
   3 OFF-era, all absorbed by `--continue`); backpressure context-tightening
   fired in both arms under peer slowdown. #394 tracks the streaming rerun
   that removes the timeout-pressure confound.

## Memory-default decision (required on a falsifying outcome)

**Recommendation: KEEP, with the lesson-specificity re-design (the row-34
next-delta) as the condition.** Rationale: the mechanism is cheap and now
verifiably alive end-to-end (post-#391/#392); class-level transfer was
directly observed; the falsifying delta is dominated by one task-complexity
spike and offset by an un-removable code-as-memory channel in the control
arm. Both this run and exp-1 (row 34) point at the same variable: lesson
SPECIFICITY (answer-level transforms, process-level doesn't). Disarming
would discard a working lane on a metric its own control contaminated;
fixing means making distills/code-lessons more answer-shaped. The operator
decides; this record only recommends.

## Instrument fixes this run (separately-recorded commits, defects named)

- #391 (`386517e`): the rung-2 distill sidecar shadowed slugged artifacts in
  `find_artifact` — grade-time capture reported "no artifact found" on every
  armed run since v1.56.0.
- #392 (`81f9352`): `build_code_lesson_record` emitted no eidetic-required
  `text` key — every code-lesson store silently failed since v1.56.0; the
  #378 lane had never stored a lesson in production before this run.

Both were found live by this experiment's own capture path — the dogfooding
argument for running the ablation at all, independent of its verdict.

## Deliverable

The commissioned game shipped twice over: both arms' repos hold a complete,
winnable Transformer platformer (ON: timed boot→won 35.9s; OFF: 55.8s),
zero uncaught errors, agent-drivable via the documented state contract.
Repos: OriNachum/transformer-arm-on PRs #1–#8, OriNachum/transformer-arm-off
PRs #1–#8 (all squash-merged; worker branches + tips preserved in the PRs).
