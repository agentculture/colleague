# Build Plan — You can now calculate the ROI of outsourcing to convertible: every drive reports time, tokens spent (read + generated), tokens/bytes written, and an attachable quality grade -- together enough to retro and evaluate whether outsourcing a task to convertible paid off.

slug: `convertible-records-what-every-drive-cost-and-how` · status: `exported` · from frame: `convertible-records-what-every-drive-cost-and-how`

> You can now calculate the ROI of outsourcing to convertible: every drive reports time, tokens spent (read + generated), tokens/bytes written, and an attachable quality grade -- together enough to retro and evaluate whether outsourcing a task to convertible paid off.

## Tasks

### t1 — Contract: DriveStats dataclass + TaskResult.stats with JSON round-trip

- covers: c8, h1
- acceptance:
  - DriveStats holds request, started_at, duration_seconds, model_turns, step_count, tool_counts(dict), files_changed, bytes_written, reasoning_chars, reasoning_bytes, answer_chars, answer_bytes
  - TaskResult.stats serializes via to_dict and from_dict round-trips to an equal object; from_dict tolerates a missing 'stats' block (back-compat)

### t2 — Engines: ModelResponse reasoning/answer capture + vllm parse + mock parity

- covers: c10, h5
- acceptance:
  - vllm _parse_response reads message.reasoning AND message.content; tokens taken exactly from usage (prompt/completion/total), optional fields default 0
  - unit test parses a model-gear-shaped response (usage without completion_tokens_details) and asserts reasoning length==len(message.reasoning) and answer length==len(message.content)
  - mock engine yields deterministic reasoning/answer values so the e2e shape test is engine-agnostic

### t3 — ToolExecutor: accumulate UTF-8 bytes_written from write_file

- covers: c8
- acceptance:
  - ToolExecutor exposes a bytes_written total summing UTF-8 byte length of write_file content; non-write tools leave it unchanged; unit test asserts the count

### t4 — feedback.py: stdlib JSON store (single record per drive) + last-drive pointer

- covers: c9, h4
- acceptance:
  - write_feedback overwrites <task_id>.feedback.json with {task_id,rating(1-5),notes,by,at}; read returns it or an explicit no-feedback sentinel (not an error) when absent
  - set/get last-drive pointer resolves the most recent drive in the repo; rating outside 1-5 rejected; round-trip unit test

### t5 — Loop: time the drive + aggregate tool_counts + snapshot bytes/reasoning into DriveStats

- depends on: t1, t2, t3
- covers: c8, c3, h1, h11
- acceptance:
  - run() records started_at(ISO) and duration_seconds(monotonic delta); tool_counts aggregated from result.steps; bytes_written snapshotted from the executor; reasoning/answer char+byte lengths summed across turns; TaskResult.stats populated
  - existing loop tests pass; a no-op drive still produces a valid populated stats block

### t6 — CLI: convertible feedback noun (record/show/overview) + register + explain

- depends on: t4
- covers: c9, h3, h6, c1
- acceptance:
  - feedback record <id|last> --rating N --notes ... writes; feedback show <id|last> reads; feedback overview describes the noun; --json on every verb; stdout for results, stderr for diagnostics; bad rating raises CliError (no traceback)
  - verb registered in cli/__init__.py and an explain catalog entry added for feedback

### t7 — execute_drive: capture request + update last-drive pointer after artifact write

- depends on: t5, t4
- covers: c3, h11
- acceptance:
  - stats.request == task.instruction; after write(result) the last-drive pointer is set to result.task_id; session path inherits via shared execute_drive (no parallel code path)

### t8 — Telemetry: mirror reasoning chars/bytes + bytes_written metrics; stay strict no-op

- depends on: t5
- covers: h2, c6, h14
- acceptance:
  - _otel _build_state defines metrics for reasoning chars/bytes and bytes_written, recorded chassis-side; telemetry off = strict no-op (no spans/import, TaskResult shape unchanged)
  - tests/test_zero_deps.py green: no third-party import outside lazy _otel.py; no new read-noun/router/daemon/socket/sandbox in the diff

### t9 — outsource skill: add 'outsource feedback <id|last>' verb over convertible feedback

- depends on: t6
- covers: c2, h10
- acceptance:
  - outsource feedback <id|last> --rating N --notes '...' shells to convertible feedback; SKILL.md documents the verb; test_outsource_skill.py covers the new path

### t10 — Finalize: e2e shape + before/after + ROI comparability + docs + version bump

- depends on: t5, t7, t6, t8, t9
- covers: c4, c5, c7, c18, h6, h9, h12, h13, h15
- acceptance:
  - tests/test_e2e_mock.py pinned key-sets updated for the always-on stats block and pass; mock and vllm-openai produce identical result shape
  - a test asserts ROI inputs (duration, tokens, bytes_written, rating) are all readable from one artifact + its feedback (h9/h13); pre-feature before-state (h12) verified
  - opt-in live model-gear smoke documented: a real vllm-openai drive shows reasoning_chars>0 and 'feedback last' writes+reads (h6/h15)
  - CLAUDE.md chassis bullet + conventions, docs/features entry, CHANGELOG entry, and version bump (version-check CI) present

## Risks

- [follow_up] persist full reasoning TEXT in the artifact (v0 = char/byte lengths only)
- [follow_up] roll up sub_results stats into a parent total (v0 = nested-only, matching usage)
