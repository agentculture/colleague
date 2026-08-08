# g7 ON-arm cycle record

- work: 3-leg chain — b3401df3209e (cut at 54) → e198eb328c06 (cut at 65;
  narrated completion without handoff; two approval-gate denials on ls probes
  recorded) → fda803f1302c (ok, 26 steps, PR #7)
- PR: https://github.com/OriNachum/transformer-arm-on/pull/7 → squash 07c2293
- verification (subagent, 56 evidence files): engage/chase/defeat/death and
  the zero-error invariant genuinely worked end-to-end; three named-criterion
  failures — (C1) enemy never patrols (edge-only targetVx; byte-identical
  frames + fixed red-pixel centroid), (C3) single-swing kill (per-step latch
  clear re-hits every 60Hz step, ~50ms drain) + counter INCREMENTS from 0
  instead of decrementing from the level count, (C4) 1 hit = 1 life (no
  accumulator) + a falsy (0||3)-1 resurrection cycle live-captured on the
  lost screen + HUD 3-hearts-at-death
- INTEGRATOR CORRECTION (rule-bound to C1/C3/C4, ~27 lines): persistent
  patrol facing; latch cleared at swing end; enemies initialized + decremented;
  hitsTaken%3 accumulator + Math.max floor + HUD ??; encounter reachability —
  with real patrol the y=3.5 spawn's range never intersected any reachable
  hero position (the pre-fix chase rode the bounce artifact), so the guard
  spawns on the ground corridor (y 3.5→0, bounds/platforms untouched).
  Empirically re-verified in ONE live series: engage on approach (hitsTaken=2
  mid-walk), lives drop at hitsTaken exactly 3/6/9, enemies 1→1→1→0 across
  three distinct swings, lives pinned at 0 (no resurrection).
- grade: 3; capture fired, 4 hunks, 4 lessons stored (store: 8 code-lessons)
- observations: heaviest task of the series (3 legs, 145 worker steps); the
  interplay lesson — fixing patrol removed the accidental reachability the
  bounce had provided; corrections must keep criteria JOINTLY reachable
