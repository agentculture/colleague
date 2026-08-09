# Self-Learning — colleague learns from its own runs

Colleague learns from its own work: lesson-grade feedback records,
repo-anchored code-lessons derived from correction diffs, and a bounded
strive loop that iterates hypotheses toward a goal. The self-learning arc
closes the ROI loop — feedback grades say how *good* a work item was,
correction diffs say *what changed* between the agent's output and the
final merge, and strive drives bounded hypothesis-ledger iteration when
the goal is measurable. Together they turn every run into material the
next run can recall.

## The pieces

| Piece | Where | What |
|-------|-------|------|
| Strive | `colleague/strive.py` + `colleague/cli/_commands/strive.py` | Four-phase bounded-attempt iteration: (1) declare delta and hypothesis BEFORE dispatch, (2) run the attempt via `Engine.work` on branch `sub/strive-<goal-slug>` inside an episode worktree, (3) run the measure command through the approval-gate policy in the episode worktree cwd, (4) record the result (supported/refuted) in the schema-enforced ledger. The ledger schema (`_LEADER_KEYS`) refuses whole entries with missing or extra keys. Novelty stall detection at `K=3` (default `DEFAULT_NOVELTY_STALL_K`): K consecutive refuted attempts with the same normalized hypothesis = a recorded stall. Real per-attempt episodes via `Engine.work` — no fabricated progress. |
| Rung-2 distillation | `colleague/lessons.py` validator + `colleague/distill.py` author-by-role + detached child | A gated pattern→constant→reason pass at remember time (answer-shaped since #396): the distillation author is resolved BY ROLE (deepthink/muse > lobes cortex > none, guarded against a declared evaluator seat auto-authoring without a distinct distiller authority — spec c38/h30, forward-compat for the evaluation arc's t12 arming) via `distill.resolve_distill_author_from_config`. Raw model text must pass the strict `{pattern, constant, reason}` schema in `lessons.validate_lesson` — refuse-whole on any deviation, including a `constant` that reads as generic prose rather than a repo anchor. An invalid distillation leaves the rung-1 record with an honest `no-lesson-extracted` marker. Production runs detach a bounded background child (`distill.make_distill_fn`, the sanctioned one-shot pattern via `background.spawn_background`) — the child validates-then-upserts and writes an outcome marker (`distill.json`); the run's return is never blocked. Kill switch: `COLLEAGUE_MEMORY_DISTILL=0` / config `memory_distill` — independent of the memory gate, rung-1 stands. |
| Code-lessons + correction diff | `colleague/correction.py`, `colleague/memory.py` builders | Repo-convention records (`type=code-lesson`, own id namespace, `{area, convention, evidence, confidence}` with verbatim evidence) grown from teachers: the integrator-correction diff (`colleague/correction.py` — tip SHA vs the PR's squash commit, scoped to `changed_files`, honest no-diff when any fact is missing), lint-gate fixes, in-run test failures, and ROI grades. `correction.build_code_lesson` builds an answer-shaped `CodeLesson` (`{pattern, constant, reason}`, `constant` defaulting to the hunk's file path) from a `DiffHunk` with the hunk text as verbatim evidence and `origin="model"`; the call site maps those fields onto `memory.build_code_lesson_record`'s own `{area, convention, evidence, confidence}` record shape (unchanged) before it's packaged for the eidetic store. |
| Auto-trigger lane | `colleague/feedback.py` grade-time + work-start, observable sidecar | ONE shared best-effort primitive (`maybe_capture_correction`) fires from TWO triggers: (1) grade time — wired into `write_feedback`, (2) work-start — `capture_uncaptured_predecessor` catches the prior ungraded work item. The capture outcome is an observable sidecar (`<task_id>-correction-capture.json`) beside the artifact — never blocking the grade. A capture failure is a no-op, never an error. |
| Doctor's distillation alive-counter | `colleague/oilcheck/distillation.py` | Armed is not evidence the tier is alive — a counter that increments is. Scans `.colleague/` and `.convertible/` for `*.distill.json` outcome markers, counting attempts (any recognisable status) and validated (status `done` with a non-empty lesson dict). When `attempts > 0` and `validated == 0`, emits a `warning` — the distillation pipeline is armed but not alive. `doctor` surfaces attempts-vs-validated across recent runs. |

## Honest limits

- Strive's ledger is local (`.colleague/strive/<goal-hash>.json`), not yet
  eidetic-synced. The ledger persists per-goal as a JSON list of
  schema-checked dicts; cross-repo sharing is a future lane.
- Novelty detection v1 uses normalized exact match (`_normalize` — lowercase,
  collapse whitespace). Semantic matching is parked with the embedder lane.
- The detached distillation child's outcome is not in the launching run's
  artifact by design: the child writes `distill.json` markers and the doctor
  check carries the signal. The artifact's `distill_validated` count is
  honest-at-return, never a false positive.
- `chain.CONTINUABLE_REASONS` is untouched — it remains
  `{"budget-exhausted"}`. Strive's retry policy lives in `strive.py`, not
  in the chain module.
- The flywheel exclusion default: cortex-authored feedback is excluded from
  `feedback export` unless `--include-cortex-authored` is passed (c30/h25).
  Self-grades in the export would create a feedback flywheel where the model
  reinforces its own biases.

## Cross-links

- [Memory](memory.md) — the eidetic store that self-learning records feed into.
- [Artifact](artifact.md) — where outcome markers and correction-capture
  sidecars live beside work-item artifacts.
- [Approval Gate](approval-gate.md) — the policy gate that strive's measure
  commands route through.
- [Organs](docs/organs.md) — the living architecture map that places
  self-learning in the colleague system.
