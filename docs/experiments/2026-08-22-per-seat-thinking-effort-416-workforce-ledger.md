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
| t1a (attempt 2) | colleague | unsloth/Qwen3.8-27B-NVFP4 | xhigh (rig default) | 2.9k | 22:50Z (87c66296e57a) | 2m (stopped 22:53Z by operator) | 0 | — | — | — | STOPPED — deviation d1 | Ori: avoid xhigh; t1/t2/t3 go to Claude sonnet subagents until the knob lands, then colleague resumes at medium. |
| t1 (attempt 3) | Claude sonnet subagent (d1) | claude-sonnet | n/a (Claude) | 2286 + shape hints | 22:55Z | 2m00s | 19 tool uses | — | 70,320 subagent tokens total | — | MERGED 4fc649a → integration (no-ff) | 25 tests; full suite 8873 passed, 3 failures are pre-existing env-dependent lobes-unarmed tests (pass with a clean HOME) — not from t1. Gate: before = tests absent (new), after = pass. |
| t2 (a+b+c) | Claude sonnet subagent (d1) | claude-sonnet | n/a (Claude) | ~4.2k | 22:58Z | 16m01s | 120 tool uses | — | 200,110 subagent tokens total | — | MERGED 3434337/e3b920b/325b8e4 → integration | 34 new tests + to_dict pins updated; config.py 4284→4369 (ratchet baseline regenerated via the sanctioned path); acting-seat logic pushed into effort.resolve_acting_effort. |
| t3 | Claude sonnet subagent (d1) | claude-sonnet | n/a (Claude) | ~3.9k | 23:09Z | 11m53s | 73 tool uses | — | 190,608 subagent tokens total | — | MERGED 7652e47 → integration | 23 tests; vllm_openai.py 1101→1260 (ratchet baseline bumped); two payload-key pins extended (default acting seat now sends medium by design — c35/c36; byte-identical holds under the kill-switch). From here colleague dispatches send medium. |
