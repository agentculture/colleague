# You can now calculate the ROI of outsourcing to convertible: every drive reports time, tokens spent (read + generated), tokens/bytes written, and an attachable quality grade -- together enough to retro and evaluate whether outsourcing a task to convertible paid off.

> You can now calculate the ROI of outsourcing to convertible: every drive reports time, tokens spent (read + generated), tokens/bytes written, and an attachable quality grade -- together enough to retro and evaluate whether outsourcing a task to convertible paid off.

## Audience

- agents and humans who run 'convertible drive' (incl. via the outsource skill) and want to know what a drive cost and grade its quality

## Before → After

- Before: today the artifact carries only usage (prompt/completion/total tokens) and a steps trace: no elapsed time, no tools-used aggregate, no bytes-written, no request copy, no reasoning capture, and no way to record how good a drive was
- After: every drive's artifact JSON carries rich always-on stats (request, tokens read, total generated tokens, tools used, elapsed time, turns, files changed, bytes written, reasoning vs answer char counts); and a caller can attach feedback to a drive by task-id or 'last', persisted beside the artifact

## Why it matters

- drives become a gradeable, learnable record: stats show what happened, feedback shows how good it was, so callers (and future routing) can compare engines/models on real cost and quality
- the four signals together -- wall-clock time, tokens spent (read+generated), bytes/tokens written, and a 1-5 quality grade -- make outsourcing measurable: a caller can retro a delegated task's ROI from one drive's artifact + feedback alone and decide whether to outsource again and to which engine

## Requirements

- Part A: drive statistics are ALWAYS-ON in the artifact (no flag), captured chassis-side in loop.py/execute_drive/contract and mirrored into optional OTel as a strict no-op when off; holds identically for mock and vllm-openai
  - honesty: with stats disabled-by-absence impossible (always-on), a no-op drive's artifact still round-trips through TaskResult.to_dict/from_dict and the e2e mock-shape test passes after updating its pinned key-set
  - honesty: tests/test_zero_deps.py stays green: no new third-party import is added outside the lazy telemetry/_otel.py
- Part B: a 'convertible feedback' CLI verb records and reads feedback for a drive by task-id or 'last', stored as stdlib JSON beside the artifact with a per-repo last-drive pointer; surfaced as an 'outsource feedback' skill verb; supports --json, overview, and an explain catalog entry
  - honesty: 'convertible feedback' follows agent-first conventions: results to stdout, diagnostics to stderr, --json supported, an 'overview' verb on the noun, and an explain catalog entry added
  - honesty: feedback persists to a stdlib JSON file under the repo artifact dir keyed by task-id, with a 'last' pointer that resolves the most recent drive in that repo; absent store is a clean no-op
- vllm-openai engine captures message.reasoning (currently discarded): per-turn it records reasoning char/byte length and answer char/byte length, threaded ModelResponse -> loop -> stats; mock engine mirrors the same fields for shape parity
  - honesty: for model-gear, a captured drive shows reasoning_chars > 0 and answer_chars matching message.content length; mock yields deterministic non-API values for the same fields so the e2e shape test is engine-agnostic

## Honesty conditions

- after the feature ships, a real model-gear drive's artifact shows populated stats AND 'convertible feedback' can grade that drive by its task-id or 'last'
- both a human (readable artifact JSON) and an agent (the outsource skill) can consume the stats + feedback with no extra tooling
- after a drive the artifact JSON contains a populated stats block, and a feedback record can be attached and read back for that task-id
- today's pre-feature artifact demonstrably lacks elapsed time, tools-used aggregate, bytes-written, request copy, reasoning capture, and feedback (verifiable from current TaskResult.to_dict)
- two drives of the same task on different engines are comparable on cost (time+tokens+bytes) and quality (rating) from their artifacts + feedback alone
- no tokenizer/third-party dep is added (zero-deps test green) and no stats read-noun, router, daemon, socket, or sandbox appears in the diff
- e2e mock-shape + zero-deps tests pass; a live model-gear drive shows reasoning_chars>0; 'convertible feedback last' writes and reads back a record
- writing feedback twice for one task-id overwrites (single record, not a list); 'convertible feedback <id>' / 'last' reads it back; reading a drive with no feedback file returns an explicit 'no feedback' (clean no-op), not an error
- token figures equal exactly what the response usage reports (no derived/estimated tokens); reasoning_chars==len(message.reasoning) and answer_chars==len(message.content) per turn, summed across turns; bytes are UTF-8 byte lengths
- an outsourcing retro/ROI is computable from a single drive's artifact + its feedback record alone (time + tokens + written-bytes + rating), needing no external data

## Success signals

- a real vllm-openai drive against model-gear writes an artifact with populated stats incl. non-zero reasoning chars; 'convertible feedback last --rating ...' writes a feedback record linked to that drive; mock and vllm-openai produce identical result shape; zero-deps + e2e-shape tests stay green

## Scope / boundaries

- not a tokenizer (zero runtime deps): token counts are only what the model API reports; reasoning is measured as chars/bytes, never estimated as tokens. Not a new read-back 'stats' noun, not a router/gearbox, not a daemon/socket/sandbox

## Non-goals

- no token-level reasoning count (model-gear doesn't report reasoning_tokens); no bytes/4 heuristic; no automatic engine->task routing; no persistence of full reasoning TEXT unless converged as in-scope

## Assumptions

- feedback is general to any convertible drive (keyed by task-id), with 'outsource feedback' as the agent-facing entry; not outsource-exclusive

## Decisions

- tokens come from the model API exactly as reported; missing fields default and are flagged to the operator, never estimated. model-gear reports prompt/completion/total only (no completion_tokens_details, prompt_tokens_details=null) but returns a separate message.reasoning field
- surface is artifact-JSON-only for stats (no 'stats' read noun); the only new CLI/skill surface is feedback
- build via /think -> /spec-to-plan, committing spec+plan under docs/ before implementation
- feedback record = a SINGLE object per drive (re-grading overwrites), stored as <task_id>.feedback.json beside the artifact: {rating: int 1-5, notes: free-text, by: actor, at: ISO-ts, task_id}; absent file = no feedback yet
- stats sizing = exact API tokens from the response payload usage (prompt_tokens, completion_tokens, total_tokens), PLUS reasoning-vs-answer measured as BOTH chars and bytes (reasoning_chars/bytes, answer_chars/bytes) from message.reasoning vs message.content; the reasoning TEXT is NOT persisted in v0 (lengths only)

## Open / follow-up

- whether to persist full reasoning TEXT in the artifact (privacy + size) or only reasoning char/byte lengths
- rolling up sub_results stats into a parent total vs keeping nested-only (matches existing usage rule)
