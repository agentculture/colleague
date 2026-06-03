# Build Plan — A colleague drive never reports an empty-looking success: when the model doesn't call finish, the result still carries the model's actual produced content, and a genuinely empty drive is explicitly signalled rather than disguised as a normal completion

slug: `a-colleague-drive-never-reports-an-empty-looking-s` · status: `exported` · from frame: `a-colleague-drive-never-reports-an-empty-looking-s`

> A colleague drive never reports an empty-looking success: when the model doesn't call finish, the result still carries the model's actual produced content, and a genuinely empty drive is explicitly signalled rather than disguised as a normal completion

## Tasks

### t1 — Add a stable, programmatic 'no result produced' signal to the result shape (colleague/contract.py)

- covers: c10, h10
- acceptance:
  - TaskResult exposes a stable sentinel/flag a caller can branch on to detect 'no output was produced', without string-matching a step-count summary
  - the signal is identical for every backend and adds no runtime dependency

### t2 — Track the last substantive assistant content and use it as the no-finish summary fallback in colleague/loop.py

- depends on: t1
- covers: c1, c3, c4, c6, c7, c9, h1, h3, h4, h6, h7, h9
- acceptance:
  - a last-substantive-content candidate is updated on EVERY turn with non-empty content, including tool-call turns (the loop.py:568 gap)
  - finalize summary precedence is finish_summary > last-substantive content > the t1 empty sentinel; the generic step-count text is only used when truly nothing was produced
  - no extra model request is issued to build the summary; for a fixed transcript the model turn/token counts are unchanged vs today (only the summary string differs)

### t3 — Add a regression test reproducing the empty-summary case and asserting the new fidelity behavior (tests/)

- depends on: t2
- covers: c2, c5, c8, c11, h2, h5, h8, h11
- acceptance:
  - a mock drive that emits content on a tool-call turn then stops WITHOUT finish surfaces that content in result.summary and --json (not a step count)
  - a mock drive that produces no content yields the explicit empty sentinel, programmatically distinguishable
  - the e2e shape test passes: mock and vllm-openai produce the identical result shape; no new runtime dep

## Risks

- [unknown_nonblocking] v0 takes the last non-empty assistant content as 'substantive'; a relevance filter to drop pure tool-call narration ('let me read X next') is a follow-up
