# Drive statistics & feedback — the ROI loop

**The headline:** you can calculate the *ROI of outsourcing* to colleague.
Every drive's artifact records, always-on, what the drive **cost**; a feedback
record says how **good** it was. Together — time + tokens + bytes written + a
quality grade — they let a caller (human or agent) retro a delegated task and
decide whether to outsource again, and to which backend.

This is the **Run report** (stats) and a new sibling, **Feedback**, working
together. Both are runtime-owned (the all-engines rule): identical for `mock`
and `vllm-openai`.

## Part A — always-on drive statistics

Every `TaskResult` carries a `stats` block (`colleague/contract.py`
`DriveStats`), serialized into the artifact JSON on **every** drive (no flag, no
opt-in). It sits beside `usage`, which holds the exact token counts.

| Field | Meaning |
|-------|---------|
| `request` | the originating task instruction |
| `started_at` | ISO-8601 UTC start of the loop |
| `duration_seconds` | wall-clock loop duration (monotonic) |
| `model_turns` | number of model turns (`complete` calls) |
| `step_count` | number of tool-call steps |
| `tool_counts` | per-tool call counts (e.g. `{"write_file": 1, "finish": 1}`) |
| `files_changed` | distinct files written |
| `bytes_written` | exact UTF-8 bytes written to files via `write_file` |
| `reasoning_chars` / `reasoning_bytes` | size of all `message.reasoning` (the "thought" not saved to a file) |
| `answer_chars` / `answer_bytes` | size of all `message.content` (the final answer) |

Tokens live on `usage` (`prompt_tokens` / `completion_tokens` / `total_tokens`).

### Honest token model

Tokens are **exactly** what the model response `usage` reports — never estimated.
Colleague has **no tokenizer** (zero runtime deps), so it cannot produce a
reasoning- or written-*token* count. Concretely, the reference server
(`model-gear`, Qwen3.6-27B) reports only `prompt`/`completion`/`total` tokens —
no `completion_tokens_details`, so no reasoning-token breakdown — but it returns
the chain-of-thought as a separate `message.reasoning` field. So colleague
measures "thought vs written" as exact **chars/bytes**, not tokens:

- "thought" → `reasoning_chars`/`reasoning_bytes` (the `message.reasoning` text,
  which the vLLM engine previously **discarded**).
- "written" → `bytes_written` (exact UTF-8 bytes that landed in files).

There is no `bytes/4` heuristic. If you need token-level reasoning accounting,
that needs a tokenizer dependency — a deliberate non-goal in v0.

### Where it's populated

Runtime-side, in `colleague/loop.py`: per-turn fields accumulate in
`_drive_loop`; the rest are filled by `_finalize_stats` on every exit path
(model finish / empty turn / step budget / mid-loop abort), so even a partial
drive carries populated stats. `ToolExecutor` (`colleague/tools.py`)
accumulates `bytes_written`. The vLLM engine (`colleague/engines/vllm_openai.py`)
captures `message.reasoning` (and `reasoning_content` as an alias) into
`ModelResponse`. The optional OTel path mirrors two new metrics —
`colleague.generated.chars` (attr `kind`=reasoning|answer) and
`colleague.bytes_written` — as a strict no-op when telemetry is off.

## Part B — the feedback loop

`colleague/feedback.py` is a stdlib JSON store. A **single record per drive**
(re-grading overwrites) lives at `.colleague/<task_id>.feedback.json` beside
the artifact:

```json
{"task_id": "9f2c1ab0", "rating": 4, "notes": "correct but verbose", "by": "ori", "at": "2026-05-31T..."}
```

A per-repo `last_drive` pointer (written by `execute_drive` after each drive)
lets you grade the most recent drive without quoting its id. An ungraded drive
reads back as a clean "no feedback yet" state — never an error.

### CLI

```bash
colleague feedback record last --rating 4 --notes "correct but verbose"
colleague feedback record 9f2c1ab0 --rating 5 --repo . --json
colleague feedback show last --repo .
colleague feedback overview
```

`record`/`show` take a drive id or the literal `last`. `--rating` must be an
integer 1–5. `--by` defaults to colleague's resolved identity. Results go to
stdout, diagnostics to stderr; every verb supports `--json`.

### From the `outsource` skill

The agent-facing entry is the `outsource feedback` verb — close the loop right
after an outsourced drive:

```bash
outsource feedback last --rating 4 --notes "good, but missed an edge case"
outsource feedback <task_id>          # no --rating → show existing feedback
```

## Reading ROI off one drive

```bash
colleague drive "refactor the parser" --engine vllm-openai --no-pr --json > result.json
# cost: result.json → .stats.duration_seconds, .usage.{prompt,completion}_tokens, .stats.bytes_written
colleague feedback record last --rating 4 --notes "clean, a bit slow"
# quality: .colleague/<task_id>.feedback.json → .rating
```

Time + tokens + bytes written + rating — everything a retro needs, from one
artifact plus its feedback record, with no external data.

## Honest limits

- **No tokenizer** → no reasoning/written *token* counts; chars/bytes only.
- **Tokens are verbatim** from the model's `usage`; a server that reports nothing
  yields zeros (colleague does not fabricate them).
- Feedback is a **single record** per drive (re-grade overwrites). A multi-grader
  append-log is a possible follow-up, not built.
- Stats are **per top-level drive**; a subagent's cost stays in its own
  `SubResult.usage` (nested-only, matching the existing usage rule). Rolling
  sub-results into a parent total is a parked follow-up.
- Reasoning **text** is not persisted in v0 — only its char/byte length (size +
  privacy). Persisting the full chain-of-thought is a parked follow-up.
