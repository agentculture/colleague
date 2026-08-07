# Build Plan — prove self-learning (#387)

slug: `prove-self-learning-387` · status: `exported` · from frame: `prove-self-learning-387`

> Colleague provably learns: the self-taught warm-vs-cold and the #378 correction-diff ablation both ran in a healthy session, and the results — supporting or falsifying — are recorded in the live-testing ledger and close the two unverified delivery claims

## Tasks

### t1 — t1: Preconditions + one clean baseline run on the 35B worker

- instruction: Pin the model explicitly (`COLLEAGUE_MODEL`=unsloth/Qwen3.6-35B-A3B-NVFP4 or the lobes worker role via `three_tier` config); run one real small task in a throwaway repo; check rig quiet first (no senses/voice sessions, no other colleague loops, no training jobs); keep the artifact — it is the healthy-backend evidence every later run cites
- covers: c2, h2, c29, h20
- acceptance:
  - Baseline artifact shows steps > 0, a substantive non-meta finish, and WorkStats naming the 35B worker model
  - Rig-quiet condition (no other loops/sessions/jobs) verified and recorded alongside the baseline; a #346-style zero-step collapse aborts the session with the abort recorded

### t2 — t2: Verify the webglass usable-bar (the 7 items of webglass-cli#9) and pin consumption to `run_command`

- instruction: webglass committed the seven items to its M0-M2 slice (ack on webglass-cli#9); build a tiny fixture page (one that logs keydowns + one that throws on load) in scratch space and drive each verb; if any load-bearing item (1-4 of #9) fails, post on the #9 thread and HOLD the game arms — degrade only per that thread's agreement
- covers: c14, h8
- acceptance:
  - All seven acceptance items from webglass-cli#9 pass against a local fixture page: localhost open, console/page-error evidence (a throwing page yields error text, a clean page yields an explicitly empty list), selector-scoped extract, action press key sequence, screenshot-to-file, session reattach across one-shot CLI calls, --json/stdout-stderr/exit-code contract
  - Colleague-side consumption in this proof is `run_command` through the approval gate only — zero colleague code diff; the colleague-native webglass tool is recorded as a future own-cycle arc

### t3 — t3: Experiment-1 setup — throwaway operator repo, fail-cold task, cortex-pinned distill author

- instruction: Construct a hidden-fact repo-spelunking task in the h3/h14 fixture style (docs/features/memory.md), sized past the cold step budget so the cold run reliably fails; pin the distill author per the row-31 round-4 recipe; if the cold run later succeeds unexpectedly, record the discard honestly and adjust (assumption c27)
- covers: c28
- acceptance:
  - A throwaway repo (the run's operator repo) committed at a recorded base SHA; the experiment task brief committed; the store verified cold (no task-specific lesson)
  - The distillation author resolves to the SERVED cortex model — verified via config/distill resolution output, never the unserved muse

### t4 — t4: Experiment-1 execution — cold fail, distill, gated warm rerun, WorkStats comparison

- instruction: Sequence strictly: cold run -> wait on distill.json (bounded, the row-31 round-2 race) -> eidetic store probe -> warm run -> verify recall in the artifact -> compare; both artifacts must record the same base commit SHA; nothing is hand-seeded at any point
- depends on: t1, t3
- covers: c3, h3, c26, h17, h19
- acceptance:
  - Cold run artifact recorded (steps > 0, failed/incomplete); the detached distill child's marker reads status=done; a store probe shows the lesson with origin=model
  - Warm rerun starts from the same base SHA in a fresh isolation worktree; its artifact's memory.recalled contains the distilled lesson; any gate miss ABORTS with the abort recorded as aborted
  - steps/tokens cold-vs-warm read verbatim from the two artifacts' WorkStats into the comparison record; equal-or-worse recorded as FALSIFYING

### t5 — t5: Author the Transformer game plan + pre-commit the integrator correction rules

- instruction: Author the game plan as its own devague frame/plan in a game template repo; size tasks for the worker model (small, one-PR-each, browser-verifiable via webglass); target N in the 6-10 range; every task brief names its webglass verification step; the rules doc is the h22 evidence — hash it
- covers: c12, h9, c31, h22
- acceptance:
  - The game repo's own committed plan exists BEFORE the arms: N tasks, each with acceptance criteria under which the game runs in a browser at that step (three.js + nodejs, robot hero, lives, sword, puzzles, doors, an agent-readable state element, human-beautiful visuals)
  - The correction-rules doc (correct ONLY to each task's pre-committed acceptance criteria, no opportunistic polish) is committed BEFORE arm 1 task 1 and its SHA recorded

### t6 — t6: Scaffold the two arm repos identically from the game template

- instruction: memory.remember is UNGATED (memory.py:133) so store separation is what keeps OFF-arm writes from ever reaching the ON arm — never share a repo or store between arms; capture the diff output as the h21 evidence before any task runs
- depends on: t2, t5
- covers: c25, c30, h21
- acceptance:
  - Two fresh repos cloned from the SAME template commit with SEPARATE .eidetic stores; a scaffolding diff excluding the `COLLEAGUE_MEMORY` setting is EMPTY and captured as evidence
  - Both repos carry identical .colleague/approvals.json (node/npm/webglass `run_command` tokens), hooks/templates, task briefs and acceptance criteria

### t7 — t7: Run the ON arm first — N game tasks, learning armed

- instruction: ON arm runs FIRST (decision c32 — conservative: integrator familiarity accrues to the OFF arm); serialize one loop at a time; grade each task immediately so the grade-time trigger fires the correction capture; the code-lessons stored between tasks ARE the learning lane under measurement — do not prune the store mid-arm
- depends on: t1, t6
- covers: c13, h10, c23, h15
- acceptance:
  - N tasks run sequentially on the worker model with memory armed; every task lands via a real PR with squash merge, rule-bound integrator corrections committed before merge, and an immediate grade; every capture sidecar shows outcome=fired (a skip is recorded and removes that task from BOTH arms' metric)
  - Every artifact's WorkStats names the 35B worker; lesson/feedback authorship shows cortex (or operator); rig-quiet recorded per run

### t8 — t8: Run the OFF arm — the identical task list with `COLLEAGUE_MEMORY`=0

- instruction: Same worker model, same briefs, same integrator rules doc (verify its SHA unchanged); the OFF arm's store WILL still receive lesson writes from grade-time capture (ungated remember) — that is expected and harmless under store separation; what must be zero is RECALL
- depends on: t7
- covers: c4, h4, h16
- acceptance:
  - The IDENTICAL task list runs in the OFF repo with `COLLEAGUE_MEMORY`=0; the same PR + squash-merge + rule-bound correction + immediate-grade discipline applies to every task
  - Zero memory.recalled blocks across all N OFF-arm artifacts — checked from the artifacts, not assumed

### t9 — t9: Metrics, adjudication, recording — rows 32/33, delivery-claim flips, close #387

- instruction: This is the accountability task: read every number from artifacts/sidecars verbatim (h14); the healthy-session condition h1 is certified here from the baseline + per-run rig-quiet records; sign the ledger rows with the artifact paths so a reviewer can re-derive every cell
- depends on: t4, t8
- covers: c1, h1, c5, h5, c6, h6, c7, h7, c17, h11, c18, h12, c19, h13, c20, h14
- acceptance:
  - Correction-diff lines per task tabulated verbatim from both arms' capture sidecars; experiment-1 steps/tokens tabulated verbatim from WorkStats; mean ON vs OFF compared; equal-or-worse on either experiment lands in FALSIFYING wording, never softened
  - docs/live-testing.md rows 32/33 updated and the two unverified delivery claims in docs/deliveries/2026-08-07-self-learning-arc.md flipped to verified-or-falsified, in the SAME PR as the arm artifacts; row 33 recorded honestly as run or still-recipe per NEBULA availability; the ledger cites row-31/CI evidence for transmission and lesson production instead of re-running them
  - The proof PR's diff touches docs + experiment records only (any instrument fix is a separately-recorded commit naming its defect); a falsifying outcome triggers a recorded memory-default decision (keep/disarm/fix); #387 closes only on this committed evidence

## Risks

- [unknown_nonblocking] webglass M0-M2 slice timing: the seven usable-bar items are committed but not yet delivered; t2 is the gate — if a load-bearing item (1-4 of webglass-cli#9) is late, the game arms hold and the session runs experiment 1 + records the hold honestly (task t2)
- [unknown_nonblocking] NEBULA row 33 (the #377 strive ablation) runs only if the benchmark repo + rig hours materialize; otherwise it stays a recorded recipe and its delivery claim stays honestly unverified (task t9)
- [unknown_nonblocking] Statistical power at small N: a near-tie is weak evidence either way; raw per-task numbers are recorded so a larger-N rerun can extend the series (task t9)
- [unknown_nonblocking] Warm-run duration confound (server warm-up/KV cache): duration is reported but never load-bearing; steps/tokens are the primary metrics (task t4)
- [unknown_nonblocking] The 35B worker has never collapsed but N sequential runs are unproven at this volume; a mid-arm zero-step collapse invalidates that run per h20 (invalidated and rerun, never averaged) (task t7)
