# Background one-shot — `colleague work --background`

**Spec:** `docs/specs/2026-07-02-colleague-is-now-the-colleague-you-always-wanted-i.md`
(R4, c12/h10; boundary c6/h6; decision c17) · **Plan:** task t12.

A delegated work item no longer occupies a foreground terminal. `colleague
work "<task>" --background` detaches the run as a **one-shot session-leader
child** and returns immediately with a machine-readable start payload; the
caller folds the result back later through the artifact, the flight plane,
and the feedback loop — the same three surfaces as any other run.

## How it works

- **`colleague/background.py`** is the ONE sanctioned detach module:
  `subprocess.Popen(argv, start_new_session=True)` with stdio redirected to
  `.colleague/background/<id>/` (`stdout.log` / `stderr.log`), plus a
  `meta.json` (`{id, pid, flight, started_at}`) so a *later, separate*
  process can judge liveness with `os.kill(pid, 0)` — no daemon, no polling,
  no process registry. A dedicated boundary test pins that the module never
  calls `.wait()`/`.poll()`.
- The parent pre-mints the handle id, reconstructs the child's CLI invocation
  (same flags minus `--background`, `--watch` force-appended), and prints
  `{"background": true, "id", "pid", "log_dir", "flight"}` — composing with
  `--json` since the payload *is* the JSON.
- The child reads `COLLEAGUE_BACKGROUND_ID`, adopts the parent-minted id (so
  artifact + flight files match the printed handle), and runs the completely
  ordinary foreground work path — gates, isolation worktree, handoff and all.
- **Pilot it** like any flight: `colleague flight status/guide/stop <id>`
  (`--watch` is auto-armed).
- **Crash residue is reapable, never wedging:** a `kill -9`'d child leaves
  its log dir + partial state; `colleague clean` reaps dead-pid background
  dirs and never touches a live one.

## Batch semantics (the upstream hard question)

agent-lifecycle's spec asks whether batch agents need a run-to-completion
lifecycle mode or whether restart-policy `never` suffices. Colleague's
answer, recorded here and in the module docstring: **a detached one-shot
needs no supervisor at all** — the child runs one work item to completion
and exits; artifact + exit semantics already belong to the work path.

## Honest limits

- Detach is POSIX (`start_new_session`); Windows behavior is untested.
- The parent does not wait, so a child that dies *before* writing its
  artifact is only discoverable via the log dir + `clean` (by design — the
  flight feed is the live view, the artifact the durable one).
