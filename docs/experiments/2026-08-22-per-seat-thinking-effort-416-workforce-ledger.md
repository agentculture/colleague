# Workforce ledger — per-seat thinking effort (#416)

Run log for the `/assign-to-workforce` execution of
`docs/plans/2026-08-21-per-seat-thinking-effort-416.md` (spec
`docs/specs/2026-08-21-per-seat-thinking-effort-416.md`). Kept at a 15-minute
cadence during the session; every row is read from the run artifact
(`.colleague/<id>.json` — `WorkStats`: steps, tokens exact from `usage`,
reasoning measured by length) or from the shell clock. Colleague does ~90% of
the work; Claude (Fable) TDD-gates merges and runs the t11 live arm.

**Effort note:** until this very feature lands, every colleague request runs at
the served checkpoint's template default (`reasoning_effort=xhigh`, #417) — the
"effort" column records what the seat *actually* ran at, so early rows are all
`xhigh (rig default)`.

| task | who | seat model | effort | brief chars | dispatched | wall | steps | prompt tok | completion tok | reasoning chars | outcome | notes |
|------|-----|------------|--------|-------------|------------|------|-------|------------|----------------|-----------------|---------|-------|
| t1 (attempt 1) | colleague | unsloth/Qwen3.8-27B-NVFP4 | xhigh (rig default) | 2286 | 21:50Z (61f99a4c8030, SIGTERM'd at 0 steps by the 10-min foreground cap; resumed 21:56Z as 2025e232a209) | 52m (stopped 22:48Z) | 22 of 40 | — | — | 22,989 (completed turns only; a final ~45k-token turn was in flight) | STOPPED — no deliverable | 14 model turns of exploration (read_file/run_command), then ONE reasoning turn ran 42 min at ~23 tok/s without reaching a tool call; flight guidance never got a boundary. #418 (--continue+--background) found here. Re-dispatched as two smaller requests (t1a module, t1b tests) per #415. |
