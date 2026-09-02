# Build Plan — measure-effort-spikes-484

slug: `measure-effort-spikes-484` · status: `exported` · from frame: `measure-effort-spikes-484`

> colleague measures the #484 effort-spike surface: arms A (low + feedback) / B (+ barrier at low) / C (+ barrier at medium) run on the row-69 recorded brief, each a docs/live-testing.md row with a miss written as a miss, and the pre-registered C-beats-B rule decides whether any spike arms by default — the #484 disposition posts to the issue

## Tasks

### t1 — t1 barrier smoke on a throwaway repo (DONE: artifact 2db5bb0ae410, row 70)

- instruction: already executed; the row is written on branch measure/effort-spikes-484
- covers: c3, h3, c12, h11
- acceptance:
  - row 70 in docs/live-testing.md quotes `effort_spikes` \[{barrier.`pre_mutation`, medium, cortex}\], the barrier Step, zero warnings and the per-turn reasoning sizes

### t2 — t2 arm A — low, spikes OFF, `MAX_STEPS` 90, TIMEOUT 600, fresh dispatch from row-69 `task_text`; verify the result branch

- instruction: scratchpad/`run_arm.sh` A (running as 26d71865aeee); then scratchpad/`verify_branch.sh` <id>; save outputs to scratchpad/arm-A.verify
- covers: c1, h1, c2, h2, c7, h5
- acceptance:
  - artifact `task_text` sha256 == 815f5c3f…1ac9 (brief.txt); effort {main: low}; `max_steps` 90; correctness verified via `verify_branch.sh` (import, 6 pins, suite) with outputs saved; spend figures read off the artifact; the row states whether the run FINISHED and quotes `importcheck_report` + the affected-tests warning

### t3 — t3 arm B — spikes ON, barrier pinned low, gate/fillline pinned low; verify

- instruction: scratchpad/`run_arm.sh` B after A finishes (GPU serializes); `verify_branch.sh`; record the step index of the barrier.`pre_mutation` Step
- depends on: t2
- covers: c4, h4
- acceptance:
  - artifact carries exactly one `effort_spikes` entry {barrier.`pre_mutation`, low, cortex} (extra pinned-low entries quoted); no effort-spike-barrier warning else VOID + one rerun; barrier fire step index recorded; same correctness + spend procedure as t2

### t4 — t4 arm C — spikes ON, barrier medium from the table, gate/fillline pinned low; verify

- instruction: scratchpad/`run_arm.sh` C after B finishes; `verify_branch.sh`; record the fire step index
- depends on: t3
- covers: c4, h4
- acceptance:
  - artifact carries {barrier.`pre_mutation`, medium, cortex}; no effort-spike-barrier warning else VOID + one rerun; fire step index recorded; same correctness + spend procedure as t2

### t5 — t5 rows 71-73 in docs/live-testing.md + effort-spikes.md Honest-limits pointer + memory update

- instruction: mirror row 69's shape; a miss is written as a miss; quote verify outputs; cite rows 67-69
- depends on: t4
- covers: c11, h10, c13, c14
- acceptance:
  - three rows each with a correctness verdict, four spend figures, env, brief source (39661f2af608), budget, barrier fire position, n=1 stated; effort-spikes.md 'Honest limits' cites rows 70-73; markdownlint clean

### t6 — t6 patch version bump + PR via cicd (docs-only diff)

- instruction: version-bump skill patch (v1.75.1); cicd skill pr open; do not touch effortspikes.py / `loop_barrier.py`
- depends on: t5
- covers: c8, h6, c9, h9, h12
- acceptance:
  - git diff 4405d07b -- colleague/ is empty except colleague/`__init__.py` version; tests/`test_effortspikes_boundary.py` passes; PR opened via the cicd skill and CI green

### t7 — t7 #484 disposition comment applying the pre-registered rule

- instruction: gh issue comment 484 signed '- colleague (Claude)'; C beats B only by lower spend at equal correctness (q4)
- depends on: t5
- covers: c14, h13, c13
- acceptance:
  - the comment quotes the three arms' verdicts and spend figures verbatim from rows 71-73, names exactly one of #482's three readings (close #484 / #484 proceeds / reframe), and files the barrier-trigger follow-up if any arm fired at step <=2

## Risks

- [unknown_nonblocking] Rig availability + GPU serialization: three 90-step arms at ~1-1.5 h each may span sessions
- [unknown_nonblocking] n=1 per arm at temperature 1.0 — spend differences may be noise; rows state it, disposition must not overclaim
