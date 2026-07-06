# Experiment — detached `sloth` training runs, driven from the operator front

> Tracking: [colleague#295](https://github.com/agentculture/colleague/issues/295)
> (S5) · spec: [`docs/specs/2026-07-06-colleague-integration-front.md`](../specs/2026-07-06-colleague-integration-front.md)
> (requirement R5) · plan: [`docs/plans/2026-07-06-colleague-integration-front.md`](../plans/2026-07-06-colleague-integration-front.md)
> (task t23).

## Where this sits in the flywheel

`colleague-integration-front` (issue #291) frames colleague as the operator
front for a small AI-coworker organism (see [`docs/organs.md`](../organs.md)).
The **flywheel** this closes: a graded work item's artifact + feedback →
`colleague feedback export` → data-refinery's refine pipeline → a
sloth-validatable training dataset → **`colleague experiment`** trains the
next local adapter → the exported adapter is served by lobes → colleague's
own minds get better, and the loop repeats. This feature is the "train"
step — the one leg of the flywheel that touches a GPU.

## What it does

`colleague experiment` drives unsloth-cli's `sloth` CLI via a curated
allow-listed shell-out (`colleague/experiment.py`; allow-list exactly
`sloth`) — the same integration pattern as the `culture`/`devague`/`memory`
tools. The long-run problem is solved **job-shaped**, not daemon-shaped:

- **`experiment start --config run.toml`** — reads the run's `dataset`/
  `output` straight out of the `[run]` TOML table (stdlib `tomllib`;
  colleague never imports `sloth.tune.config`, let alone torch/unsloth),
  runs `sloth validate --dataset <dataset> --json` **before any GPU work**
  (mirroring `sloth train`'s own host-side preflight), and — only on success
  — detaches `sloth train --config <toml>` **exactly the way
  `colleague/background.py` detaches a background work item**:
  `subprocess.Popen(..., start_new_session=True)`, stdio redirected to
  `.colleague/experiments/<id>/train.log`, stdin `DEVNULL`, no
  `.wait()`/`.poll()` anywhere. Returns immediately with a machine-readable
  start payload: `{id, pid, config, output_dir, log_dir, started}`.
- **`experiment status <id>`** — a fresh `os.kill(pid, 0)` liveness probe, the
  last ~20 lines of `train.log`, and a best-effort correlation against
  sloth's own run registry (`sloth runs list`/`show --json`) — degrading to
  `sloth_run: None` when sloth is unreachable or the registry hasn't been
  written yet (never blocking the status query).
- **`experiment list`** — every detached experiment under
  `.colleague/experiments/`, newest-first, each with a fresh `alive` probe.
- **`experiment summarize <id> [--remember]`** — `sloth summarize
  <output_dir> --json` (an existing output directory always resolves
  directly, per `sloth.tune.registry.resolve_target`), joined with a
  `remembered: bool` key. With `--remember`, a compact record is upserted
  into eidetic via `colleague.memory.remember()` **reused as-is** — never
  re-implemented — so the memory scope convention (`--scope colleague
  --visibility public`, see `tests/test_memory_convention.py`) can never
  drift between this noun and the runtime's own recall/remember calls.
- **`colleague clean`** reaps dead-pid experiment residue (see below).
- An experiment id is a valid feedback `task_id`:
  `colleague feedback record <exp-id> --rating N` — the ROI loop covers
  experiments too.

## Why job-shaped, never a scheduler

The plan's own risk register names this directly: *"Wrong abstraction:
colleague drifting into a training-job daemon — the job surface must stay
one-shot detach + file-based status (the `work --background` precedent),
never a resident scheduler."* `colleague/experiment.py` has no daemon, no
socket, no polling loop, no process registry — a dedicated boundary test
(mirroring `test_background_module_confined_to_one_shot_detach`) pins that
the module never calls `.wait()`/`.poll()`, and `tests/test_boundary.py` pins
that colleague imports no `torch`/`unsloth` anywhere.

## Reap semantics — stricter than `work --background`

`colleague clean` reaps a dead-pid `.colleague/experiments/<id>/` dir only
once it has **also** aged past a day (`colleague.experiment.reap_experiments`,
`_REAP_MIN_AGE_SECONDS`). This is deliberately stricter than
`colleague/background.py`'s reap (which removes a dead-pid log dir the
instant the pid is gone): a background work item's durable result lives in a
**separate** artifact file, so its log dir is disposable the moment the child
exits. An experiment's `start.json` + `train.log` **are** the durable record
(there is no separate artifact) — reaping the instant the pid exits would
delete a successfully-finished, not-yet-summarized experiment out from under
the operator. The day-long grace window gives the operator time to
`experiment status`/`summarize` it first. A genuinely live pid is never
touched, same as the background reap.

## Honest limits

- Missing `sloth` (unsloth-cli) degrades to a structured error with
  remediation (`uv tool install unsloth-cli`), never a traceback — the same
  degrade-never-raise convention as every other organ integration.
- `experiment status`'s `sloth_run` correlation is best-effort: it matches on
  `output_dir` string equality against sloth's own registry record, and
  degrades to `None` when sloth is unreachable, the registry doesn't exist
  yet, or nothing matches — never a hard failure.
- Job-shaped, never a scheduler — see above. There is no `experiment cancel`
  verb in v1 (an operator kills the pid directly, then `colleague clean`
  reaps the residue after the grace window); a documented follow-up.
- `colleague experiment` never bypasses unsloth-cli's own scope guard
  (`sloth/tune/scope.py`'s `check_scope`, which hard-refuses full
  fine-tuning of a large dense model) — it drives `sloth train` as-is and
  surfaces whatever the guard decides.

## See also

- [`docs/organs.md`](../organs.md#sloth-unsloth-cli) — the sloth organ's full
  writeup: owns/seam/contract/spec-issue/respected-non-goal
- [`docs/features/background.md`](background.md) — the `work --background`
  one-shot detach precedent this feature's `start` verb mirrors
- [`docs/features/memory.md`](memory.md) — the eidetic recall/remember
  convention `summarize --remember` reuses as-is
- [`docs/features/coherence-gate.md`](coherence-gate.md) — the sibling S3
  organ integration landed in the same colleague-integration-front arc
