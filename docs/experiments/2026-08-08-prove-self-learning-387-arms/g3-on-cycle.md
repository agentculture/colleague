# g3 ON-arm cycle record

- work: CHAIN of three legs — 7b8e9ef688e4 (budget-exhausted at 49 steps,
  honest incomplete) → 3f4f3623ef41 (--continue, budget-exhausted at 47) →
  aea233c7fd8b (--continue, ok, 41 steps, handoff PR #3)
- model: unsloth/Qwen3.6-35B-A3B-NVFP4 all legs
- PR: https://github.com/OriNachum/transformer-arm-on/pull/3 → squash 486dfc3
- verification (subagent, live browser): criteria 1+4 PASS (hero primitives +
  emissive eyes standing under gravity; page_errors [], lastError null);
  criteria 2+3 FAIL on the pre-committed 4-press probe — discrete CLI
  keydown/keyup (~1ms apart) fall between 60Hz physics steps: 4 presses = 0.0
  movement (12 presses = 0.3, frame-race lottery, residual vx 1.27e-21
  verbatim)
- INTEGRATOR CORRECTION (rule-bound to acceptance 2+3): ~120ms key latch in
  src/main.js so synthetic taps span physics frames; empirically re-verified
  on the SAME probe before merge: x 2 -> 4.9 (4x ArrowRight), 4.9 -> 3.5
  (2x ArrowLeft), lastError null. Correction lines (tip 4dfd5f1 vs squash
  486dfc3, mechanical count): 10
- grade: 3 (functional corrections); capture outcome=fired, 1 hunk,
  1 code-lesson STORED — the first lesson through the repaired lane
- instrument interventions this cycle (recorded): #392 discovered live (the
  captured hunk stored 0 lessons — build_code_lesson_record emits no 'text'
  key, eidetic rejects every code-lesson since v1.56.0; fixed 81f9352
  test-first) + the g3 capture sidecar deleted and the grade re-recorded to
  re-fire capture through the fixed lane (rating unchanged at 3)
- anomalies: leaked worker server on :8080 (killed); elevated-platform landing
  predicate + README key-map deltas flagged for later tasks' criteria, not
  corrected (no opportunistic polish)
