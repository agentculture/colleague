# Delivery — prove-self-learning #387, the arm runs (t2, t6–t9)

Continues `docs/deliveries/2026-08-07-prove-self-learning-387.md` (waves 0–1 +
exp-1). This record covers the held tasks executed 2026-08-08 after webglass
0.6.0 shipped. The confirmed plan
(`docs/plans/2026-08-07-prove-self-learning-387.md`) is the contract.

## Planned vs actual

| task | planned | actual |
|---|---|---|
| t2 webglass usable-bar | 7 items verified on fixtures; hold if 1–4 fail | **DONE** — 7/7 PASS on local fixtures (record: `docs/experiments/…/t2-webglass-verification.md`); findings posted on webglass-cli#9; arms unheld. Beyond-bar boundary found (post-navigation console capture) → mitigated pre-arm via `state.lastError` in the template (commit `15eb0b9`; frozen correction rules untouched) |
| t6 arm scaffolding | two repos, same template commit, separate stores, empty diff (h21) | **DONE** — both arms at the SAME scaffold commit `5e60888` (h21 empty by construction); store-isolation finding: eidetic 0.13 recall merges + migrates `$HOME` records → `EIDETIC_DATA_DIR` per arm on every dispatch AND grade |
| t7 ON arm | 8 tasks, PR+squash+grade each, capture fired each | **DONE** — 8/8 merged (arm-on #1–#8), 57 correction lines, grades 5,5,3,3,3,3,3,5, capture fired 8/8, 8 code-lessons stored |
| t8 OFF arm | identical briefs, COLLEAGUE_MEMORY=0, zero recall blocks | **DONE** — 8/8 merged (arm-off #1–#8), 38 correction lines, grades 5,3,5,3,3,2,5,4, `memory:null` 16/16 artifacts |
| t9 metrics + ledger + flips + close | verbatim tabulation, rows 32/33, claim flips, docs-only PR | **THIS PR** — row 32 EXECUTED+FALSIFYING; #378 claim flipped to falsified; row 33/#377 stays honestly unverified (NEBULA not run); #387 closes on merge |

## The verdict, unspun

**FALSIFYING on the pre-committed c20 bar**: ON 57 vs OFF 38 correction lines
(equal-or-worse ON = falsified), mean grades identical (3.75). Full table +
texture in `docs/experiments/2026-08-08-prove-self-learning-387-arms/final-comparison.md`.
Memory-default decision recorded there: KEEP, conditioned on the
lesson-specificity re-design (converging with exp-1/row 34's next-delta).

## Mid-run decisions and deviations (all recorded when made)

- Pre-arm template amendment (`state.lastError`) driven by the t2 boundary
  finding — applied before any arm cloned, identical for both.
- Sandbox posture: host AppArmor userns restriction → `WEBGLASS_ALLOW_UNSANDBOXED=1`
  (webglass's sanctioned trusted-harness opt-in; session records carry the
  marker; local fixtures + own game only). Proper AppArmor profile needs sudo
  — offered to the operator, pending.
- g1-ON instrument intervention: handoff's `gh pr create` failed on the
  `--base` default (`main` vs the arms' `master`) — the PR was opened by the
  integrator for the worker's untouched branch/tip and `pr_url` recorded
  post-hoc; all later dispatches passed `--base master`.
- g3-ON capture intervention: sidecar deleted + grade re-recorded once to
  re-fire capture through the #392 fix (rating unchanged).
- Operator mid-run: #393 (headless SSE streaming) + #394 (post-streaming arm
  rerun) filed; deliberately NOT applied mid-series.
- Subagent fanout (operator direction): per-task field verification ran as
  subagents; correction approval/merge/grade/dispatch stayed at the
  integrator gate.

## Instrument fixes (separately-recorded commits naming their defects)

- **#391** `386517e` — `find_artifact` resolved the rung-2 distill sidecar
  instead of the artifact; grade-time capture dead on all armed runs since
  v1.56.0. Test-first fix + regression test.
- **#392** `81f9352` — code-lesson records lacked the eidetic-required `text`
  key; every code-lesson store failed silently since v1.56.0 (CI mocks
  remember; no test asserted the contract). Test-first fix; the #378 lane
  stored its first-ever production lesson in this run.

## Reliability record

Five thor-peer flaps (2 ON-era, 3 OFF-era) — all absorbed by `work --continue`
chains with zero lost work (one 0-step leg recorded as a flap casualty);
backpressure tightened context in both arms under peer slowdown (recorded as
a confound; #394 is the de-confounded rerun). 32 chain legs total across 16
task cells; every cell ended status ok with a merged PR.

## What is NOT claimed

- Nothing about #377 (NEBULA/strive) — not run.
- No claim that memory "doesn't work": class-level transfer was directly
  observed in the ON arm; the falsified claim is the specific #378
  correction-VOLUME signal on this benchmark, with the code-as-memory
  control-arm channel and N=8 recorded as limits.
- The g8 verifier caught the ON worker's own delivery-time verification claim
  being syntax-only (NEBULA pattern) — the invariant held when checked, but
  the worker's claim preceded the check; recorded, not repeated here as if
  the worker had proven it.
