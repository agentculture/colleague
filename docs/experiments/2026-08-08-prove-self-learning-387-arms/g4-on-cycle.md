# g4 ON-arm cycle record

- work: 2-leg chain — df098d598ba3 (budget-exhausted, 51 steps; recall 5
  records/1570 chars — the compounding store incl. g3's latch code-lesson) →
  2c07759d0da9 (ok, 42 steps, PR #4)
- model: unsloth/Qwen3.6-35B-A3B-NVFP4 both legs
- PR: <https://github.com/OriNachum/transformer-arm-on/pull/4> → squash 1092baa
- verification (subagent): HUD hearts + zero-error invariant PASS; Space jump
  DEAD at runtime — worker keyed the input map on 'Space' but browsers deliver
  e.key ' ' (24 y-samples across 3 press attempts all grounded; ArrowRight
  control moved exactly per the g3 latch, proving dispatch alive). Fall
  predicate source-verified; runtime fall unreachable while the jump was dead.
  NOTE the transfer shape: the g3 latch lesson DID transfer (worker extended
  the latch to Space unprompted); the key-NAMING trap was a new, unlearned
  failure — now stored as lesson 2.
- INTEGRATOR CORRECTION (rule-bound, acceptance 1+2): normalize e.key ' ' →
  'Space' in both listeners; empirically re-verified pre-merge — single press
  arc y 0 → 0.8 → 1.111 → 0 (analytic apex 1.225u = 2.45 platform-heights,
  airtime 0.70s, both inside the bar; sampling cadence too coarse to bound
  airtime tighter, recorded honestly). Fall path now reachable; a bounded
  slab-mount+walk-off probe did not trigger a runtime fall (recorded).
  Correction lines (tip 72cd9a89 vs squash 1092baa, mechanical): 17
- grade: 3; capture outcome=fired, 1 hunk, 1 lesson stored (store: 2
  code-lessons)
- anomalies: leaked worker server (killed); landing-predicate quirk +
  falsy-zero lives flagged for later criteria, not corrected
