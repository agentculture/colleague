# Evidence — per-seat thinking effort (#416): did colleague get faster?

Measured 2026-08-22 on the DGX Spark rig via the lobes gateway, cortex
`unsloth/Qwen3.8-27B-NVFP4` (1M YaRN, MTP on), PR #419 tip. Three sources:
a **controlled arm** (same brief, three rungs), the **workforce ledger**
(the PR built itself; confounded by task shape), and **seat-level**
measurements. Short answer first, numbers after.

## Short answer

- **Where the table turns thinking OFF, colleague is dramatically faster and
  cheaper with no loss on shallow calls** — senses acks 22 vs 141 completion
  tokens, explorer/validator children 0 reasoning tokens, and the same small
  coding brief finishing in **24 s at off vs 88 s at xhigh vs 129 s at medium**
  (all three correct).
- **`medium` for the acting seat is NOT a measurable speed-up over `xhigh` on
  small coding briefs** (n=1: medium took one more model turn than xhigh and
  was slower), consistent with colleague#417's "lower rungs are not reliably
  cheaper". Its value is bounded reasoning on *open-ended* turns, which this
  arm does not exercise.
- **No rung rescues the module-sized existing-file brief.** Every such
  dispatch in the workforce stalled — at xhigh (t1: 42-min silent turn),
  at medium (t5, t6, t7, t8) and at low (t7b) — in the same shape:
  10–20 exploratory steps, then one silent turn of 15–42 min. Effort is not
  the lever there; **request size is** (#415). New-file / small / one-line-edit
  briefs landed at medium in 2–20 min (t4, t9, t10, t12, the live runs).

So: better-performing **yes** for shallow seats and small well-specified
requests (off), **unproven** for the acting seat's medium default, **no** for
the hard brief shape. A wider, pre-registered arm (same briefs × rungs × n≥5)
is the next step before touching the table again.

## Controlled arm — same brief, three rungs (n=1 each)

Brief: "Add a function `mul(a, b)` returning a*b to calc.py and a test
`test_mul` in test_calc.py; run `python -m pytest -q` and finish with the
summary line. Keep it to three tool calls." Throwaway repo, `--max-steps 30`,
senses lane armed (off in every arm).

| acting-seat rung | status | steps | model turns | wall | prompt tok | completion tok | reasoning chars | result |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `xhigh` (override) | ok | 6 | 4 | **88 s** | 17,357 | 1,558 | 4,754 | calc.py + test_calc.py, `2 passed` |
| `medium` (the v3 default) | ok | 6 | 5 | **129 s** | 21,808 | 2,750 | 8,756 | same |
| `off` (override) | ok | 6 | 4 | **24 s** | 17,137 | 335 | 0 | same |

Work items: `302be07a81e3` (xhigh), `7968b1281593` (medium), `22d6bc1390ce`
(off). Per-request payloads verified with `COLLEAGUE_DUMP_REQUEST=1`
(acting seat at the arm's rung; senses at `enable_thinking:false`).

## Seat-level measurements (live)

| call | off | medium | xhigh (rig default) |
|---|---:|---:|---:|
| senses-style JSON ack (completion / reasoning tokens) | 22 / 0 | 101 / 77 | 141 / 121 |
| `tests/test_vllm_live_thinking_effort.py` senses seat `reasoning_tokens` | **0** | — | — |
| deepthink seat `reasoning_tokens` | — | — | > 0 |
| child fan-out (`ad5c5a1a76ae`, 4 roles, 18 requests) | 6 req (senses + explorer) | 6 req (acting + planner) | — (reviewer/validator at low: 6 req) |

All four children answered correctly; no file edits. Details: `docs/live-testing.md` row 39.

## Workforce ledger (confounded — task shape varied)

Full rows: `docs/experiments/2026-08-22-per-seat-thinking-effort-416-workforce-ledger.md`.

| brief shape | rung | outcome | examples |
|---|---|---|---|
| NEW files / one-line edits / mechanical | medium | **landed** 2–20 min | t4 18m (4 one-line seat edits + tests), t9 18m (2 new test files), t10 20m (new doc + pointer edits), t12 2m (bump + CHANGELOG) |
| module-sized edits to existing modules | xhigh | stalled (42-min silent turn) | t1 attempt 1 |
| module-sized edits to existing modules | medium | stalled ×5 (15–19-min silent turns / write-no-changes) | t5 (×2), t6, t7, t8 (×2) |
| module-sized edits to existing modules | low | stalled (15-min silent turn) | t7b |

The pattern is independent of rung: 10–20 exploratory `run_command`/`read_file`
steps, then one silent generation turn (vLLM 1 running request @ ~23 tok/s)
that never reaches a tool call. Flight guidance lands only at a tool-call
boundary, so it could not interrupt it. Those tasks were handed to Claude
sonnet subagents (deviations d1–d5 in the delivery summary).

## Honest limits

- n=1 per cell in the controlled arm; one checkpoint, one box, one day; the
  brief is shallow by design (it isolates overhead, not judgement quality).
- `medium` vs `xhigh` is within noise here; #417 measured the same on 4 prompts.
- The ledger compares different tasks; it shows the *shape* effect, not a
  rung effect.
- `high` == `xhigh` on this checkpoint (alias); not measured separately.
- Not measured: effort × long-context (deep in the 1M window), effort ×
  judgement-heavy turns (review, plan), Thor's no-MTP cortex.

## What to do with this

1. Keep the v3 table (off for shallow seats is the proven win).
2. Run a pre-registered arm before changing the acting-seat default:
   3 briefs (shallow edit, multi-file edit, open-ended review) × {off, medium,
   xhigh} × n=5, scoring correctness + wall + tokens.
3. Attack the stall shape with #415 (many small requests) — not with rungs.
