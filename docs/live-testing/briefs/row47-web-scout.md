# Row 47 brief — web-scout on the associate seat (eidetic store present)

Pre-registered for `docs/live-testing.md` row 47 (plan t7, spec
`docs/specs/2026-08-28-web-scout-associate.md`, covers c14/h11/c32/h21).
Run this verbatim in a repo that HAS an eidetic store (`.eidetic/` present)
so the distill seat can fire, with the associate seat armed
(`COLLEAGUE_ASSOCIATE_MODEL=lobes`) and `webglass` on PATH.

## Pass bar (committed BEFORE the run)

- the scout child runs on the associate seat — the child's artifact records
  `served_model` = the associate's served model
- the scout's digest cites WebGlass evidence ids (the `evidence_refs` /
  `operation_id` from the `web` tool result, verbatim)
- cortex's final answer cites those same evidence ids
- `associate_calls` > 0 (at least one delegation step/seat served by the
  associate)
- delegation is observed, never forced — a run with zero delegation is
  recorded as a miss, not spun

## The brief (paste into `colleague work`)

```text
Survey these three upstream docs, then change one module.

1. Read the three upstream references below with the web tool (search / page
   read), one at a time, and keep each one's WebGlass evidence id
   (operation_id + evidence_refs) as you go:
   - https://docs.example.com/api/overview
   - https://docs.example.com/api/auth
   - https://docs.example.com/api/errors

2. If the survey is large, hand the read-only web survey to a scout child
   (subagent) and review its digest before acting — or do it yourself; the
   choice is yours.

3. Then change exactly one module in this repo so it matches what the three
   docs say about the auth error shape. Make the smallest edit that does it,
   and in your final answer cite the WebGlass evidence ids (operation_id /
   evidence_refs) that back each claim you relied on.
```

## After the run — record (never fill before)

delegation count, the scout's served model, `associate_calls` (> 0), the
evidence ids cited in cortex's final answer, wall-clock and turns. A miss is
written as a miss.
