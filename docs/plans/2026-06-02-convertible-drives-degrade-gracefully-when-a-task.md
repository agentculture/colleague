# Build Plan — Convertible drives degrade gracefully when a task outgrows the model's context window: the loop trims its running history to fit and keeps going, and any drive that still cannot finish returns a readable partial result to the caller instead of empty stdout.

slug: `convertible-drives-degrade-gracefully-when-a-task` · status: `exported` · from frame: `convertible-drives-degrade-gracefully-when-a-task`

> Convertible drives degrade gracefully when a task outgrows the model's context window: the loop trims its running history to fit and keeps going, and any drive that still cannot finish returns a readable partial result to the caller instead of empty stdout.

## Tasks

### t1 — Context windowing + overflow-detection core (new pure-stdlib module convertible/context.py)

- covers: c12, c6, h2, h11
- acceptance:
  - window_messages(messages, budget_tokens, count_tokens) keeps the system message + the first user task message + the most-recent turns, and drops the oldest tool/assistant pairs as matched units so no assistant tool_calls turn is ever left without its matching tool replies (OpenAI-valid)
  - the running size is measured via the INJECTED count_tokens callable; the module ships a zero-dep default counter (char/4 estimate) used when no exact counter is available; under budget the list is returned unchanged, over budget oldest droppable history is elided with one short placeholder note (no LLM call)
  - windowing makes at most a small constant number of count_tokens calls per pass (proportional pre-trim then one verify, never one-per-pair); is_context_overflow(text) phrase-matches known overflow errors; module is stdlib-only so tests/test_zero_deps.py stays green

### t2 — Context-budget config knob (tokens) on EngineConfig (convertible/config.py)

- covers: c12, h3
- acceptance:
  - EngineConfig gains context_budget_tokens with a conservative default (sized with headroom below the served model's window, e.g. under 32k) resolvable via CONVERTIBLE_CONTEXT_BUDGET; precedence explicit > env > default, matching the existing _pick pattern
  - EngineConfig.to_dict() includes the budget; a docstring/comment documents the unit as TOKENS, counted exactly via the server's /tokenize when reachable else the char-fallback estimate (best-effort exact, never silently wrong)

### t3 — CLI --json drive path surfaces the preserved partial result to stdout on the failure path (convertible/cli/_commands/drive.py)

- covers: c14, h5
- acceptance:
  - on an engine failure carrying a partial TaskResult (the #37 DriveAborted path), 'convertible drive --json' prints the partial result JSON (status=error, non-empty steps) to stdout while still exiting non-zero; the human-readable diagnostic stays on stderr
  - stdout stays clean JSON so outsource.sh print_result parses a result instead of reporting 'no result on stdout'; the success-path output is byte-identical to today (regression-guarded by a test)

### t4 — Loop windows each turn + bounded reactive trim-and-retry on overflow, wired for every engine (convertible/loop.py + both engines)

- depends on: t1, t2
- covers: c1, c3, c12, c13, c15, h1, h4, h8
- acceptance:
  - run() accepts a context_budget (tokens) and a count_tokens callable; _drive_loop windows the running messages via window_messages(.., count_tokens) BEFORE each complete() call
  - the vllm-openai engine builds count_tokens by POSTing the candidate messages to {base_url-root}/tokenize (vLLM extension, stdlib urllib) for an exact count, returning None on 404/any error so the loop uses the char fallback — retargeting a non-vLLM server stays a config change; the mock engine uses the default counter; both engines forward config.context_budget_tokens (all-engines rule)
  - on a detected context-overflow error from complete(), the loop trims harder and retries the same turn up to a small fixed cap; once the floor (system+task) still overflows it stops and preserves the partial result via the existing DriveAborted path — termination stays guaranteed; tests/test_e2e_mock.py artifact shape unchanged

### t5 — End-to-end degradation success-signal tests, engine-agnostic (tests/test_e2e_degradation.py)

- depends on: t3, t4
- covers: c2, c4, c10, c11, h7, h9, h12, h13, h6, h14
- acceptance:
  - a test injects a complete() that raises a context-overflow once then succeeds, and asserts the loop trimmed history (via an injected fake count_tokens) and retried, then completed (status=ok)
  - a test reproduces a non-recoverable overflow and asserts a status=error TaskResult with non-empty steps is preserved AND emitted to stdout via the --json drive path
  - a test covers the vLLM /tokenize counter with a mocked POST (exact count) and its fallback-to-None-on-error -> char heuristic; all tests run without a live server; tests/test_e2e_mock.py and tests/test_zero_deps.py remain green

### t6 — Document the context-budget chassis surface + honest limits (CLAUDE.md + docs/features/graceful-degradation.md)

- depends on: t4
- covers: c5, c6, h10, h14
- acceptance:
  - CLAUDE.md gains a chassis bullet describing token-budget windowing + bounded reactive retry as loop-owned (all-engines rule), the CONVERTIBLE_CONTEXT_BUDGET knob, the pluggable count_tokens seam (vLLM /tokenize primary, char fallback), and honest limits (no third-party tokenizer lib; /tokenize is a vLLM extension that degrades gracefully; no LLM summary in v0; no multi-model router; bounded retries)
  - a docs/features note explains the behavior, the /tokenize exception to the OpenAI-surface rule (graceful fallback preserves retarget-by-config), and references the spec + plan

## Risks

- [unknown_nonblocking] The default context_budget_tokens value (and the fallback char->token ratio used when /tokenize is unavailable) need measuring against the served model; ship a conservative configurable default rather than a hardcoded guess. (task t2)
- [follow_up] Detection phrase list may miss an unanticipated overflow wording from a future OpenAI-compatible server; the generic-400 fallback covers it with one harmless retry, but the phrase list may need extending. (task t1)
