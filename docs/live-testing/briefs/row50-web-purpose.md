# Row 50 brief — web-survey purpose tool on the associate seat (eidetic store present)

Pre-registered for `docs/live-testing.md` row 50 (plan t12, spec
`docs/specs/2026-08-28-purpose-tools-associate-seat.md`, covers c11/h11).
The row-47 web brief adapted to the purpose-tool arm: cortex holds
`web_survey` and NO raw `web` tool (replace, not add), so the seat that
fetches is the scout child — which has no `run_command`, so the row-47
re-run's host-reconnaissance drift (d15) cannot recur.
Run this verbatim in a throwaway repo WITH an `.eidetic` store (eidetic CLI
0.13.0) so the distill seat can fire, with the associate seat armed
(`COLLEAGUE_ASSOCIATE_MODEL=lobes`) and `webglass` on PATH.

## Pass bar (committed BEFORE the run)

- the scout child runs on the associate seat — the child's artifact records
  `served_model` = the associate's served model
- the scout's digest cites WebGlass evidence ids (the `evidence_refs` /
  `operation_id` from the `web_survey` result, verbatim)
- cortex's final answer cites those same evidence ids
- zero `run_command` steps outside the repo (no host probing — the d15
  drift cannot recur because the seat holding web has no `run_command`)
- delegation is observed, never forced — a run with zero delegation is
  recorded as a miss, not spun

## The brief (paste into `colleague work`)

```text
Survey these three upstream docs, then change one module.

1. Read the three upstream references below with the web_survey tool, one
   at a time, and keep each one's WebGlass evidence id (operation_id +
   evidence_refs) as you go:
   - https://docs.example.com/api/overview
   - https://docs.example.com/api/auth
   - https://docs.example.com/api/errors

2. If the survey is large, hand the read-only web survey to a scout child
   (web_survey) and review its digest before acting — or do it yourself;
   the choice is yours.

3. Then change exactly one module in this repo so it matches what the three
   docs say about the auth error shape. Make the smallest edit that does it,
   and in your final answer cite the WebGlass evidence ids (operation_id /
   evidence_refs) that back each claim you relied on.
```

## After the run — record (never fill before)

delegation count, the scout's served model, the evidence ids cited in
cortex's final answer, `run_command` steps outside the repo (bar: 0),
wall-clock and turns; the memory distill counters (attempts/validated/
detached) and the distill child's served model from the artifact. A miss is
written as a miss.
