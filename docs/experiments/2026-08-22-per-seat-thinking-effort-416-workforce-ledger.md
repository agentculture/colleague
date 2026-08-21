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
