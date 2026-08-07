# prove self-learning (#387)

> Colleague provably learns: the self-taught warm-vs-cold and the #378 correction-diff ablation both ran in a healthy session, and the results — supporting or falsifying — are recorded in the live-testing ledger and close the two unverified delivery claims
> instruction: the session transcript + artifacts must show both arms executed live; verify no arm ran under #346 (steps=0) before accepting any comparison

## Audience

- The operator + the colleague development loop itself: the proof's consumers are issue #387, the two unverified claims in docs/deliveries/2026-08-07-self-learning-arc.md, and every future arc deciding whether memory stays armed by default
  - instruction: check the exported spec names #387 + the delivery doc as consumers

## Before → After

- After: Colleague's learning claim is evidence-backed either way: ledger rows 32/33 carry measured arms, the delivery claims flip to verified-or-falsified, #387 closes — and a falsifying outcome is a first-class result, not a failure to explain away
  - instruction: verify rows 32/33 status markers changed from ⏳ and the delivery-claims table no longer says 'unverified'

## Why it matters

- An unproven learning loop is dead weight: every run pays recall/remember cost on faith; only a measured behavioral delta justifies default-armed memory — and a falsification is equally actionable (disarm, or fix the link)
  - instruction: a falsifying outcome must trigger a recorded decision about the memory default, not silence

## Requirements

- Precondition gate: ONE clean baseline run on a step-executing backend before either arm starts — the live lobes /capabilities probe (2026-08-07) shows the 35B worker role (unsloth/Qwen3.6-35B-A3B-NVFP4) ready=true, the backend issue #387 names; a #346 zero-step collapse in the baseline aborts the session (unattributable), never gets explained around
  - honesty: The baseline artifact shows steps > 0 and a substantive non-meta finish on the 35B worker BEFORE either arm starts; a collapsed baseline aborts the session
- Experiment 1 (self-taught warm-vs-cold): fail -> rung-2 self-distill (nothing hand-seeded; the arc's own pipeline authors the lesson) -> rerun the SAME task in the same repo -> compare steps/tokens/outcome via the always-on WorkStats, mirroring the h3/h14 methodology in docs/features/memory.md (which measured 5x fewer steps with a HAND-seeded lesson) including its honest-cold footnote discipline
  - honesty: The warm arm's lesson was authored by the rung-2 pipeline from the failed run's own record — store record origin=model + the distill.json done marker prove it; nothing hand-seeded
- Experiment 2 (#378 correction-diff ablation) runs exactly the row-32 recipe: one repo, N sequential REAL tasks, learning ON vs OFF with `COLLEAGUE_MEMORY`=0 as the OFF arm (gate verified live at colleague/config.py:1705 `_resolve_memory_enabled`, reading `COLLEAGUE_MEMORY`/`CONVERTIBLE_MEMORY`), integrator-correction-diff lines per task (colleague/correction.py) as the primary metric
  - honesty: Both arms run the IDENTICAL task list with only `COLLEAGUE_MEMORY` differing; correction-diff lines are counted by the same colleague/correction.py capture on every task in both arms
- Acceptance recording: both arms' artifacts + WorkStats + a ledger row land in docs/live-testing.md rows 32/33, and the two 'unverified' delivery claims in docs/deliveries/2026-08-07-self-learning-arc.md (learning-ON-reduces-corrections #378; recall-reduces-strive-attempts #377) flip to verified-or-falsified — equal-or-worse outcomes are recorded as FALSIFYING the memory link, never explained away
  - honesty: Rows 32/33 + the delivery-claim flips land in the SAME PR as the arm artifacts; an equal-or-worse result lands in FALSIFYING wording, never softened
- The #378 ablation workload is the 'Transformer' game build: a 2D Prince-of-Persia-style classic platformer with a robot hero — three.js + nodejs, browser-run, stunning graphics, lives, sword, puzzles, doors — agent-accessible AND human-beautiful; its task list, run as N sequential real tasks per arm, IS the ablation's task list (q1)
  - instruction: before the arms start: commit the game's own plan (task list with acceptance criteria); each arm replays that exact list via colleague work on the worker model
  - honesty: The game's task list exists as its own committed plan BEFORE the arms start; every task is real repo work (the game runs in a browser at each step's acceptance), gradeable via feedback
- Work dispatches in every arm go to the worker role (35B) — worker always works, for speed; cortex deep-thinks, gives feedback, configures, and designs worker/senses improvements (q2) — so the behavioral delta is attributed to what the WORKER learns, and lesson/feedback authorship sits with cortex
  - instruction: pin work dispatches to the worker (Qwen3.6-35B) model id; pin the distillation author to the served cortex model; verify both from artifact WorkStats + store record authorship
  - honesty: Every work-arm artifact's WorkStats names the 35B worker as the executing model; lesson/feedback records name cortex (or the operator) as author — both verifiable from the artifacts
- Workload 1 (enabling, colleague repo): the playwright arm — colleague gains a browser-driving/verification capability so it can actually run and test the game it builds; per the v1 scope line this is a NEW tool surface + a new sanctioned-subprocess consumer, so it needs its own scope/spec leg (re-spec, ninth-increment discipline) and is sequenced BEFORE the game workload
  - honesty: The playwright arm lands via its own scope/spec/plan cycle with tests/`test_boundary.py`'s allow-list updated deliberately — never as an unreviewed side effect of the game arc
- Every ablation task in BOTH arms lands via a real PR with a squash merge and integrator corrections committed before merge: `maybe_capture_correction` requires `pr_url` AND `tip_sha` from the artifact (probe: colleague/feedback.py:784-830); a no-PR task yields outcome=skipped and NO metric for that task
  - honesty: Every counted task's capture sidecar shows outcome=fired in both arms; a skipped capture removes that task from BOTH arms' metric and is recorded
- The two ablation arms run in SEPARATE fresh repos with SEPARATE stores: memory.remember is UNGATED (colleague/memory.py:133 — the memory gate is loop-side ctx.`memory_enabled`, colleague/loop.py:2199), so the grade-time correction capture stores code-lessons even under `COLLEAGUE_MEMORY`=0; OFF-arm purity therefore means NO RECALL (loop-gated), and store separation keeps OFF-arm writes from ever reaching the ON arm
  - honesty: The OFF arm's N artifacts show zero memory.recalled blocks — checked, not assumed
- Experiment 1's warm rerun is gated three ways: (a) the detached distill child's marker reads status=done (the row-31 round-2 artifact race), (b) a store probe shows the distilled lesson present, (c) post-run, the warm artifact's memory.recalled block contains that lesson (h7 diagnosability) — any miss ABORTS/invalidates the comparison; a vacuous warm arm is never compared
  - honesty: An aborted warm arm is recorded as aborted — never quietly rerun until the numbers look right
- Both experiment-1 runs start from the IDENTICAL repo state — same base commit SHA, each in a fresh isolation worktree; the failed run's worktree/branch must not leak into the rerun; only the store differs between the runs
  - honesty: Both experiment-1 artifacts record the same base commit SHA — verifiable from the artifacts
- Measured runs are serialized on a quiet rig: one work loop at a time, no concurrent rig consumers (no senses/voice sessions, no other colleague loops, no training jobs) during either arm; each run's record notes the rig-quiet condition
  - honesty: Each measured run's record names the rig-quiet status; a contaminated run is invalidated and rerun, never averaged in
- Both arms' repos are scaffolded IDENTICALLY: same .colleague/approvals.json tokens (node/npm/webglass — the game tasks need `run_command` through the approval gate), same hooks/templates, same task briefs + acceptance criteria, same immediate-grading discipline (the grade-time trigger fires the capture); the ONLY difference is `COLLEAGUE_MEMORY`
  - honesty: A scaffolding diff of the two arm repos (excluding the `COLLEAGUE_MEMORY` setting) is empty at arm start — captured as evidence
- Integrator corrections are rule-bound and pre-committed: correct each task ONLY to its pre-committed acceptance criteria (no opportunistic polish), diff measured mechanically by colleague/correction.py; the integrator's arm-awareness is an acknowledged validity threat mitigated by the written rule, not denied
  - honesty: The correction-rules text is committed BEFORE arm 1 task 1 and its SHA is unchanged at experiment end

## Honesty conditions

- Both experiments actually ran in a healthy session window — the spec is falsified if either arm was simulated, hand-seeded, or run under a #346 zero-step collapse
- The session's ledger additions cite the existing row-31/CI evidence instead of re-running it — zero rig hours spent re-proving transmission or lesson production
- The proof PR's diff touches docs + experiment records/scripts only; any pipeline-blocking instrument fix is a separately-recorded commit naming the defect (t17 precedent)
- The spec names its consumers concretely (#387, the delivery doc's claims table) rather than a generic audience
- \#387 closes ONLY when both arms' evidence is committed — never on recipes or intentions alone
- A falsifying outcome triggers a recorded decision about the memory default (keep / disarm / fix), not silence
- All compared numbers are read verbatim from artifact WorkStats and correction-capture sidecars — no estimation, no hand-computation, no dropped runs
- A discarded too-easy task is recorded in the ledger with its artifact — never silently swapped for a harder one

## Success signals

- Experiment 1: `steps_warm` < `steps_cold` AND `tokens_warm` < `tokens_cold` on the same task with a self-taught lesson (the hand-seeded precedent measured 5x fewer steps / 5.5x fewer tokens); Experiment 2: mean correction-diff lines per task ON < OFF across the identical N-task list. Equal-or-worse on either = recorded as FALSIFYING the memory link
  - instruction: read both numbers from the artifacts' always-on WorkStats and the correction-capture sidecars verbatim — never hand-computed or estimated

## Scope / boundaries

- Do NOT re-prove what CI and row 31 already carry: transmission (tests/`test_e2e_selflearning.py`::`test_second_run_recalls_first_runs_lesson_verbatim`, verbatim first-turn recall) and live lesson production (ledger row 31, four-round probe, anti-fabrication held) — issue #387 lists both under 'what is already proven'
- The instruments stay unchanged: no production code changes to memory.py/distill.py/correction.py/strive.py/artifact.py during the proof — a pipeline-blocking defect discovered mid-proof may be fixed and recorded (the t17 probe precedent: 3 defects found+fixed live), but never a change that shapes the metric itself

## Non-goals

- The 'experiment' CLI noun is NOT the recorder for these ablations — colleague/experiment.py is the detached sloth QLoRA-training runner (#291 S5, allow-list exactly 'sloth'); the ablation record is the live-testing.md ledger row plus the work artifacts, as row 32's recipe already states
- The #377 NEBULA strive ablation (row 33) is the companion, not a gate: it runs only if the nebula-run benchmark repo + rig hours allow within the session — strive's mechanics are already CI-proven end-to-end, so skipping row 33 leaves its claim honestly unverified without blocking #387's close

## Assumptions

- The distillation author must be PINNED to a served model for experiment 1: colleague/distill.py resolves deepthink/muse first (precedence c16/c32), muse advertises ready=false yet lingers in /capabilities (discovery ignores 'ready' — the known lobes-cli advert bug), and row 31 round 3 died at exactly this 404; round 4's served-author pin is the working recipe
- Experiment 1 runs in a throwaway/fixture repo that IS the run's operator repo — keeps colleague's committed in-repo .eidetic store unpolluted by probe lessons, and honors the day-one lesson that recall/remember resolve against `memory_root` (the operator repo), not the isolation worktree
- The game gets its own spec/plan (its own devague frame or colleague plan) whose task list becomes the ablation's N — identical across the ON and OFF arms, each arm building from a fresh repo state per the row-32 recipe; #387's frame does not design the game, it consumes the game's task list as the benchmark
- Honoring q2 mechanically: the distillation/lesson author pins to the served CORTEX model (the row-31 round-4 served-author pin), never the unserved muse — cortex authors feedback and lessons, the worker's runs consume them via recall
- Experiment 1 needs a task that reliably FAILS cold yet is winnable warm — the spec is silent on construction; candidate shape: a hidden-fact repo-spelunking task in the h3/h14 fixture style, sized past the cold step budget; a run-1 unexpected success means select/adjust and record the discarded attempt honestly, never silently swap

## Scope exploration

- `s1` — `lobes /capabilities (live probe, localhost:8001)`: worker=Qwen3.6-35B ready=true tools=true, cortex=27B ready=true, muse=Gemma-4-31B ready=FALSE but still advertised — the healthy-backend precondition is satisfiable today via the worker role; the muse lingering-advert risk persists
  - seeds: `c2`
- `s2` — `docs/features/memory.md (warm-vs-cold section + day-one lessons)`: the h3/h14 measurement methodology already exists (same task, cold vs warm store, WorkStats compare, honest footnote that cold merges the $HOME store); day-one lesson: isolated runs write lessons to the OPERATOR repo (`memory_root`) — so the experiment repo must BE the operator repo of the run
  - seeds: `c3`
- `s3` — `colleague/config.py:1705-1713 + docs/live-testing.md row 32`: the OFF-arm switch exists and is spelled `COLLEAGUE_MEMORY` (with `CONVERTIBLE_MEMORY` back-compat) in `_resolve_memory_enabled`; row 32 records the recipe as executable-pending with both arms scripted and equal-or-worse explicitly falsifying
  - seeds: `c4`
- `s4` — `docs/deliveries/2026-08-07-self-learning-arc.md (Delivery Claims table)`: exactly two claims sit at confidence 'unverified' — the #378 and #377 success signals — with the ablations recorded as pending recipes (ledger rows 32/33); closing them is the issue's acceptance, and only docs change to record results
  - seeds: `c5`
- `s5` — `tests/test_e2e_selflearning.py + docs/live-testing.md row 31`: 6 behavior e2e tests incl. verbatim lesson transmission to run 2's first turn; row 31 is ALREADY GREEN (live 4-round distillation probe, status done, doctor 4-attempts-1-validated) — the proof session measures behavior change, it does not re-run these
  - seeds: `c6`
- `s6` — `docs/features/self-learning.md (the instrument map)`: all five instruments the proof leans on are landed and documented: strive four-phase ledger, rung-2 distillation with refuse-whole schema, correction-diff capture, the grade-time/work-start auto-trigger lane, and the doctor alive-counter — the proof session consumes them, it does not extend them
  - seeds: `c7`
- `s7` — `colleague/experiment.py (module docstring + CLI registration)`: the experiment noun drives 'sloth train' detached with job handles — a training-run runner, not an A/B measurement recorder; using it for the ablations would be a category error
  - seeds: `c8`
- `s8` — `colleague/distill.py (resolve_distill_author precedence) + ledger row 31 rounds 3-4`: author resolution prefers the deepthink/muse target before the armed-lobes main; with muse unserved this 404s honestly (dead marker) — the self-taught leg needs the round-4 author pin or the lesson never exists and the warm arm is vacuous
  - seeds: `c9`
- `s9` — `issues #377/#378 (the falsifiable criteria) + docs/live-testing.md row 33`: \#378 defines the correction-diff-volume-declines metric; #377 defines attempts-to-success on the NEBULA crucible and needs an external benchmark repo colleague does not contain — row 33 marks it pending-benchmark explicitly
  - seeds: `c11`
- `s10` — `CLAUDE.md v1 scope line + tests/test_boundary.py _SUBPROCESS_ALLOWED`: adding a playwright arm means a new loop tool + a new entry in the sanctioned subprocess allow-list — exactly the kind of addition the scope line requires an explicit re-spec for; it cannot ride into #387's proof session as a side effect
  - seeds: `c14`
- `s11` — `../webglass-cli (README.md, repo tree)`: WebGlass = the guarded web operations + evidence plane for agents; status pre-implementation — agent-first contracts + explain catalog ship today, zero third-party deps, the planned page/action/session/evidence verbs exist only in the issue #1 brief; workload 1 is therefore a webglass-repo build, not a colleague-repo one
  - seeds: `c21`
- `s12` — `webglass-cli#9 (filed this session)`: the consumer requirements are now a tracked artifact on the supplier repo — the proof's webglass dependency is pinned to an issue with acceptance criteria instead of an assumption in colleague's head
  - seeds: `c22`
- `s13` — `challenge pass / adjacent-systems lens: colleague/feedback.py maybe_capture_correction`: the metric instrument's preconditions read live: `pr_url` + `tip_sha` both required, honest skipped/failed outcomes, idempotent re-fire short-circuit — the ablation recipe must therefore include per-task PR + merge or the metric never exists
  - seeds: `c23`
- `s14` — `webglass-cli#9 acknowledgment (operator relay)`: the supplier dependency is no longer an assumption: the seven load-bearing items are a committed M0-M2 slice with fixture tests mirroring colleague's acceptance criteria
  - seeds: `c24`
- `s15` — `challenge pass / adjacent-systems lens: colleague/memory.py remember + colleague/loop.py memory gate`: the OFF switch gates the loop's recall/remember, NOT the feedback-lane remember — read live at memory.py:133 (no gate) and loop.py:2199 (ctx.`memory_enabled`); the naive one-repo-two-arms reading of the row-32 recipe would contaminate
  - seeds: `c25`
- `s16` — `challenge pass / failure-mode lens: distill detached child (ledger row 31 round 2) + memory.md h7 recall-diagnosability`: the pipeline's own history documents the race and the diagnosable-recall block; the spec's experiment-1 text assumed the sequence without gating it
  - seeds: `c26`
- `s17` — `challenge pass / unstated-assumptions + operations lenses: exported spec experiment-1 section + the serializing GPU`: the spec fixed WHAT to measure but not the run-state hygiene (identical HEAD, fresh worktrees) nor the rig-quiet condition; steps/tokens are contention-robust but duration is not, and a contaminated run must be invalidated, not averaged
  - seeds: `c28`, `c29`
- `s18` — `challenge pass / overlooked-actors lens: the integrator as a measurement actor`: the metric IS the integrator's own output (correction-diff lines), and the integrator knows which arm is which — an unexamined bias channel in the spec; mitigation is a pre-committed correction rule, with the residual acknowledged
  - seeds: `c30`, `c31`
- `s19` — `challenge pass / security lens: proof-session surfaces`: clean pass — the proof adds no colleague code or attack surface; webglass rides `run_command` through the existing approval gate (policy gate, not sandbox, per the documented gap); no new sanctioned subprocess, no new tool; residual risk unchanged from baseline
- `s20` — `challenge pass / reversibility lens: durable mutations of the proof`: clean pass — all execution happens in throwaway repos/worktrees + colleague/\* branches; the durable mutations are docs (ledger rows, delivery-claim flips) and eidetic records in throwaway stores, all PR-reviewed; nothing hard-to-reverse

## Decisions

- The playwright arm lives in the sibling webglass-cli repo (operator: 'there is ../webglass-cli'): the browser-driving substance is webglass's own build brief (webglass-cli issue #1 — surface specified, not yet built; Playwright as a declared extra behind a replaceable adapter); colleague consumes it as a curated allow-listed shell-out to the operator-installed 'webglass' CLI (the agtag/devex/sloth pattern), so colleague's own re-spec shrinks to the integration tool + boundary allow-list entry
- Operator 2026-08-07: assume webglass-cli IS implemented (being handled now in its own repo) — the proof plans against a working operator-installed webglass CLI; colleague's concrete needs (localhost policy, console/page-error evidence, selector extract, action press, screenshot, session reuse, agent-first contract) are communicated as webglass-cli#9 with acceptance criteria; items 1-4 there are load-bearing, the rest degradable
- webglass folded colleague#9 in (operator, 2026-08-07): all seven acceptance items adopted verbatim into the M0-M2 slice as fixture-based M2 tests; action press pulled forward from M5 for declared apps-under-test; sessions reattach across one-shot CLI subprocess invocations; console/page-error evidence is a first-class observation surface; CLI-shell-out-only consumption recorded as a webglass decision (library provider deferred in webglass#8) — acknowledged on #9, pull-forward note on #8
- Arm order: ON first, then OFF (q3) — the conservative ordering; integrator-familiarity advantage, if any, accrues to the OFF arm

## Open parks

- [unknown_nonblocking] NEBULA benchmark repo availability + remaining rig hours this session — not discoverable from the colleague repo; determines whether row 33 runs now or stays a recorded recipe
- [unknown_nonblocking] Statistical power at small N: the operator's bar records equal-or-worse as falsifying, but a near-tie at small N is weak evidence in either direction — the raw per-task numbers are recorded so a future larger-N rerun can extend the series
- [unknown_nonblocking] Warm-run duration confound: server warm-up/KV-cache makes the second run's DURATION incomparable; steps/tokens are the primary metrics and are contention-robust — duration is reported but never load-bearing
