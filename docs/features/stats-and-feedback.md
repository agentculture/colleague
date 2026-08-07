# Work statistics & feedback — the ROI loop

**The headline:** you can calculate the *ROI of delegating* to colleague.
Every work item's artifact records, always-on, what the work item **cost**; a feedback
record says how **good** it was. Together — time + tokens + bytes written + a
quality grade — they let a caller (human or agent) retro a delegated task and
decide whether to delegate again, and to which backend.

This is the **Run report** (stats) and a new sibling, **Feedback**, working
together. Both are runtime-owned (the all-engines rule): identical for `mock`
and `vllm-openai`.

## Part A — always-on work statistics

Every `TaskResult` carries a `stats` block (`colleague/contract.py`
`WorkStats`), serialized into the artifact JSON on **every** work item (no flag, no
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
`_work_loop`; the rest are filled by `_finalize_stats` on every exit path
(model finish / empty turn / step budget / mid-loop abort), so even a partial
work item carries populated stats. `ToolExecutor` (`colleague/tools.py`)
accumulates `bytes_written`. The vLLM engine (`colleague/engines/vllm_openai.py`)
captures `message.reasoning` (and `reasoning_content` as an alias) into
`ModelResponse`. The optional OTel path mirrors two new metrics —
`colleague.generated.chars` (attr `kind`=reasoning|answer) and
`colleague.bytes_written` — as a strict no-op when telemetry is off.

## Part B — the feedback loop

`colleague/feedback.py` is a stdlib JSON store. A **single record per
`(work item, author)` pair** (re-grading the SAME author overwrites) lives at
`.colleague/<task_id>.feedback.json` beside the artifact:

```json
{"task_id": "9f2c1ab0", "rating": 4, "notes": "correct but verbose", "by": "ori", "at": "2026-05-31T..."}
```

**Author provenance (c17/h14).** `author` defaults to `"operator"` (a human
grade) and is omitted from the persisted shape at that default — byte-identical
to the pre-author record above, so a legacy on-disk record with no `author` key
still loads as `"operator"`. The only other sanctioned author is `"cortex"` (a
self-grade the acting mind records for its own work item); its record lands at
the sibling file `.colleague/<task_id>.cortex.feedback.json` — **beside** the
operator's record, never overwriting it. `feedback record --author cortex` /
`feedback show --author cortex` write/read that sibling. `--by` (who, a free-text
name) and `--author` (operator vs. cortex, the grade's provenance) are
independent fields.

A per-repo `last_work` pointer (written by `execute_work` after each work item)
lets you grade the most recent work item without quoting its id. An ungraded work item
reads back as a clean "no feedback yet" state — never an error.

**`last` resolves to the most recent *consequential* work item (#132).** `ask-colleague
explore` / `review` run read-only in a throwaway worktree and **preserve** their
artifact but **do not move** `last` — so a later read-only probe can never steal
a grade meant for a write. Grade a probe by its printed `task_id` (every work item
echoes `task:` + a `grade:` hint). Whenever you ask for `last`, the resolved
work item's id + request is echoed to stderr, so a mis-resolve is never silent.

Forgotten the id? **`feedback list`** shows every recorded work item — newest-first,
by request, status, and grade — the durable way to find the right one. It reads
the authoritative `task_id` from each artifact's contents, so the filename
scheme doesn't matter.

> Artifacts and the work branch carry a **request slug** for legibility —
> `.colleague/<task_id>.<slug>.json` and `colleague/<task_id>-<slug>` — so a
> work item is recognisable in an `ls` / `git branch` listing. `task_id` stays the
> key; reads resolve both bare and slugged names (back-compat).

### CLI

```bash
colleague feedback record last --rating 4 --notes "correct but verbose"
colleague feedback record 9f2c1ab0 --rating 5 --repo . --json
colleague feedback record 9f2c1ab0 --rating 4 --author cortex --repo .  # a self-grade, beside the operator's
colleague feedback show last --repo .
colleague feedback show 9f2c1ab0 --author cortex --repo .  # read the cortex record, not the operator's
colleague feedback list --repo .          # every work item by request + grade
colleague feedback overview
```

`record`/`show` take a work item id or the literal `last`. `list` takes neither —
it lists every work item. `--rating` must be an integer 1–5. `--by` defaults to
colleague's resolved identity; `--author` defaults to `operator` (the other
sanctioned value is `cortex`, c17/h14) and is refused outside that set. Results
go to stdout, diagnostics to stderr; every verb supports `--json`.

### From the `ask-colleague` skill

The agent-facing entry is the `ask-colleague feedback` verb — close the loop right
after a delegated work item:

```bash
ask-colleague feedback last --rating 4 --notes "good, but missed an edge case"
ask-colleague feedback <task_id>          # no --rating → show existing feedback
ask-colleague feedback list               # find a past work item by its request
```

Because read-only probes don't move `last`, prefer grading a probe by the
`task_id` it printed (or `ask-colleague feedback list`); `ask-colleague feedback last`
grades the most recent **write**.

## Reading ROI off one work item

```bash
colleague work "refactor the parser" --engine vllm-openai --no-pr --json > result.json
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
- Feedback is a **single record per `(work item, author)` pair** (re-grade of the
  SAME author overwrites). Only two sanctioned authors exist today
  (`operator`/`cortex`, c17/h14) — a full multi-grader append-log (arbitrary
  named graders, a history per work item) is a possible follow-up, not built.
  `feedback export`'s filtering is not yet author-aware (a separate follow-up).
- Stats are **per top-level work item**; a subagent's cost stays in its own
  `SubResult.usage` (nested-only, matching the existing usage rule). Rolling
  sub-results into a parent total is a parked follow-up.
- Reasoning **text** is not persisted in v0 — only its char/byte length (size +
  privacy). Persisting the full chain-of-thought is a parked follow-up.
