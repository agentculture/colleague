# Graceful degradation — context budgets

> Colleague work items degrade instead of hard-failing when a task exceeds a
> model's context window. The loop proactively windows its message history to
> a configurable token budget and, if an overflow OR a request-timeout error is
> detected, reactively trims and retries a bounded number of times. If the work
> item still cannot finish, the caller gets a readable partial result instead of
> empty stdout.

## The problem (issue #76)

Multi-file repo tasks can exceed a small-context model's window. During a
16-file audit on a ~32k-window model, the loop accumulated an unbounded message
history and vLLM returned HTTP 400: "maximum context length is 32768 ... prompt
contains 32769". The partial artifact landed in a throwaway worktree, but the
operator saw only "colleague produced no result on stdout" — silent failure,
opaque to the caller.

This made outsourcing multi-file work to diverse/smaller models unreliable. A
routine task that overflowed was indistinguishable from a complete failure.

## The solution — two-part

**Proactive windowing:** Before each model turn, the loop measures the running
message history and trims the oldest tool-result history to fit a configured
token budget, preserving OpenAI message validity (no orphaned assistant
tool_calls without matching tool replies, always keeping the system prompt and
first user task message).

**Reactive trim-and-retry:** If the model responds with a context-overflow
error (phrase-match on "maximum context length", "context window", "too many
tokens", etc.), the effective budget shrinks by 40% (`_OVERFLOW_SHRINK_FACTOR =
0.6`) and the history is re-windowed and retried — up to a small fixed cap
(`_MAX_OVERFLOW_RETRIES = 3`) per turn. Once the floor (system + task + most
recent turn) still overflows, the loop stops.

A REQUEST TIMEOUT (the server accepted the request but did not answer within
`COLLEAGUE_TIMEOUT`, default 120s) is now degraded the same way — a bloated
context makes each completion slow, so trimming can let the next one beat the
timeout — but capped LOWER at `_MAX_TIMEOUT_RETRIES = 1`, because each timeout
attempt costs a full timeout window whereas an overflow 400 is instant. The loop
classifies which signal fired via `classify_degradable` (overflow vs timeout)
and, on an exhausted give-up, the floored budget is carried into the next turn
so the injected auto-split / INCOMPLETE recommendation runs against the small
window.

**Preserved partial result:** If the loop cannot finish, it returns the partial
`TaskResult` (status=error, non-empty steps, usage, changed files) to stdout via
the `--json` work path — not empty output plus an opaque error.

## How the knob works

| Setting | Source | Notes |
|---------|--------|-------|
| `COLLEAGUE_CONTEXT_BUDGET` | Environment variable | Tokens; overrides config default. |
| `--context-budget-tokens` | CLI flag (future) | Not yet a flag; config only today. |
| `EngineConfig.context_budget_tokens` | Config object | Default: 131,072 tokens (131072, 128K) — a **moderate raise, not a max-out**, of the reference rig's actually-served window, sized after the 2026-08-20 rollover to `unsloth/Qwen3.8-27B-NVFP4` serving a 1,048,576-token (1M) YaRN context (issue #404; `_DEFAULT_MAX_OUTPUT_CHARS` was rescaled to the same ~13% fraction). Adaptive prefill — letting the agent size the budget per task — is a parked follow-up, not this default. |

The budget is resolved via the standard precedence: explicit value (code) >
environment > default. It must be a positive integer in **tokens** — the exact
unit the server counts. Off by default would be 0 or missing; any value > 0
enables the feature.

## `COLLEAGUE_TIMEOUT` for long-context runs (decision c11)

`_DEFAULT_TIMEOUT` stays **120.0 seconds** — the qwen38-pin rollover did not
raise it. A long-context run (a large budget, deep history, or a
reasoning-heavy model prefilling for minutes before its first token) can
legitimately take longer than that default, so operators running against the
wider 1M-context rig should raise `COLLEAGUE_TIMEOUT` explicitly (e.g.
`COLLEAGUE_TIMEOUT=300`) rather than expect the built-in default to cover it.

Two landed features carry the degrade story instead of a bigger default:

- **Headless streaming is default-on** ([#393](engines.md)) — the socket
  timeout applies per read, not to the whole generation, so a long completion
  no longer races the timeout on its own; only a genuine stall does (see the
  non-goals note below).
- **Timeout-survival** (#268) preserves the partial result instead of losing
  the run outright when a bounded retry still exhausts.

So the guidance for long-context runs is: raise `COLLEAGUE_TIMEOUT` for the
expected prefill depth, and rely on streaming + timeout-survival for the rest —
not a change to `_DEFAULT_TIMEOUT` itself.

## How token counting works — the `count_tokens` seam

The loop takes an injected `count_tokens(messages) -> int` callable. This is a
pluggable seam, like the `complete` function itself.

### vLLM backend — one exact `/tokenize` probe, then `usage`-anchored estimates

Since the adopt-from-qwen-code arc (t12, spec c5/h3) the vLLM engine's
`_make_count_tokens` returns a `colleague.tokenestimate.TokenEstimator`:

- **Run start — one exact probe.** The first count a run asks for POSTs the
  candidate messages to `{base_url-root}/tokenize` with `{"model": model,
  "messages": messages}` and reads the integer `count`. The reply's
  `max_model_len` is the **window-discovery rung** — it feeds
  `outputclamp.resolve_window` (precedence: lobes-advertised context →
  `/tokenize` `max_model_len` → `COLLEAGUE_CONTEXT_BUDGET`) and is recorded as
  `(window, window_source)` on the estimator.
- **Every later turn — an estimate, never a network call.** The engine feeds
  the estimator each completion's `usage.prompt_tokens` (`tokenestimate.observe`);
  a candidate list that still starts with that snapshot costs
  `prompt_tokens + chars/4` of whatever was appended; a trimmed candidate
  (windowing) is scaled by the calibrated tokens-per-char ratio, floored at
  `chars/4`. The estimate is a conservative lower bound on room: windowing and
  the fill-line may over-trigger, never skip (qwen-code's stated rule —
  adapted-from `packages/core/src/services/tokenEstimation.ts`).
- **`COLLEAGUE_EXACT_TOKENS=1`** restores the exact `/tokenize` count on every
  turn (the pre-arc behaviour: one extra blocking POST per model turn).

The artifact's token fields never come from the estimate — `usage` stays the
only source (CLAUDE.md: tokens are exactly what `usage` reports).

### Fallback — char heuristic

If the run-start `/tokenize` returns a 404 (non-vLLM server), any network
error, decode error, or malformed response, the probe returns `None`: the
window falls to the next rung and the count falls to `count_tokens_chars` (a
zero-dependency estimate: `sum(message text) / 4`) until the first `usage`
calibrates the estimator.

This fallback is **why retargeting a non-vLLM OpenAI-compatible server stays a
config change**. Correctness is unchanged, only precision downgrades. So:

- vLLM with `/tokenize` → one exact probe + `max_model_len` window → tight budget.
- vLLM without `/tokenize` (if it ever existed) → char fallback → looser budget.
- Non-vLLM OpenAI (llama.cpp, proxies, etc.) → char fallback → looser budget.

All three are valid configurations; only the precision varies.

### Mock engine

The mock engine uses the char heuristic directly (`count_tokens_chars`).

## Why no tokenizer library is bundled

The zero-deps convention (`dependencies = []` in pyproject.toml) means no
`tiktoken` or `transformers` library is added. The vLLM `/tokenize` endpoint
reuses the existing `urllib`-based HTTP client (the same stdlib path the chat
completions use) — zero new runtime dependency. The char fallback is pure stdlib
arithmetic.

The trade-off is acceptable:

- Exact counting is **available** when the server provides it (vLLM).
- Approximate counting **always works** and is **honest** (measured, not
  guessed).
- Retargeting other servers stays **a config change**, never a code change.

## Non-goals (honest limits)

- **Windowing is the floor, not the whole story (v0 line superseded):** The
  v0 rule "no LLM-generated rolling summary" was superseded by the recorded
  v0→v1 graduation: the [fill-line](capacity-standard.md) `compact` move is a
  model-authored summary, now offered **per crossing** (bounded by a per-run
  compaction cap) and **validated deterministically** before it replaces
  history — an empty summary is rejected, never applied
  ([indefinite-run](indefinite-run.md)). Lossy windowing — dropping the oldest
  history with the placeholder note `[earlier steps elided to fit the context
  budget]` — remains the documented floor whenever compaction is declined,
  capped, or rejected.
- **Not a context router or multi-model fallback:** An overflow never
  auto-switches to a bigger model. That is the out-of-scope
  router / routing policy (multi-backend automatic routing). Degradation is about
  making the chosen backend work, not picking a different one.
- **Not unbounded retries:** Trim-and-retry is capped (`_MAX_OVERFLOW_RETRIES =
  3`) so the loop's termination guarantee still holds. No new exit path, no
  daemon, no new runtime dependency. Once retries exhaust or the floor is
  reached, the loop stops and preserves the partial result.
- **`COLLEAGUE_TIMEOUT` measures silence, not generation, under streaming:**
  with SSE armed by default (#393, [`engines.md`](engines.md)) the socket
  timeout applies per read, so a long generation no longer races it — only a
  genuine stall does. That stall still classifies as a request timeout
  (`is_request_timeout` matches, because the streaming path re-raises through
  the same `_raise_legible_timeout` as the blocking one), so this whole
  degradation path is unchanged; see
  [`backpressure.md`](backpressure.md) for the recorded decision to keep the
  #255 thresholds and the #268 escalation as-is.
- **Request timeout against a dead server:** A request timeout against a
  genuinely unreachable or stuck server still wastes up to `_MAX_TIMEOUT_RETRIES`
  bounded retries (each a full `COLLEAGUE_TIMEOUT` window) before the partial is
  preserved — shrinking the context only helps a context-bloat timeout, not a
  dead server, which is why the timeout cap is deliberately low.

## Runtime-owned (all-engines rule)

The feature lives in `colleague/loop.py` and `colleague/context.py`:

- `_complete_with_degradation` — proactive windowing + reactive trim-and-retry
  logic.
- `window_messages` — trim a message list to a budget, preserving system +
  first-user + recent turns as matched OpenAI-valid units.
- `is_context_overflow` / `is_request_timeout` / `classify_degradable` — detect
  overflow vs request-timeout error phrases.
- `count_tokens_chars` — zero-dep char estimator.

Both backends (`mock` and `vllm-openai`) inherit the feature identically via
`run(..., context_budget=config.context_budget_tokens, count_tokens=...)`. The
engine does not re-implement windowing; it only supplies the counter. The
all-engines rule applies: if a change makes `mock` and `vllm-openai` diverge in
how history is windowed or how overflows are handled, that is a bug.

The e2e shape test (`tests/test_e2e_mock.py`) guards this: the artifact shape is
unchanged even with the feature enabled.

## Usage in practice

```bash
# Explicit budget (tokens):
COLLEAGUE_CONTEXT_BUDGET=16000 colleague work "read all files" --engine vllm-openai

# Default budget (131,072 tokens, a moderate raise for the rig's served 1M YaRN window):
colleague work "read all files" --engine vllm-openai

# Turn off (0 disables proactive windowing; reactive retry still engages on overflow):
COLLEAGUE_CONTEXT_BUDGET=0 colleague work "read all files" --engine vllm-openai

# From ask-colleague skill (inherits the budget):
ask-colleague write "refactor parser" --pr
```

On an overflow, the loop logs the shrink + retry to stderr and continues. On
final give-up, the partial result is returned.

## Key files

- `colleague/context.py` — windowing primitives, overflow detection, char
  counter.
- `colleague/loop.py` — `_complete_with_degradation`, `_MAX_OVERFLOW_RETRIES`,
  `_MAX_TIMEOUT_RETRIES`, `_OVERFLOW_SHRINK_FACTOR`.
- `colleague/config.py` — `context_budget_tokens`, `_DEFAULT_CONTEXT_BUDGET`,
  `COLLEAGUE_CONTEXT_BUDGET` env resolution.
- `colleague/engines/vllm_openai.py` — `_make_count_tokens`, `_tokenize_count`,
  `_tokenize_url`; `_post_json` wraps a read-phase timeout legibly (keeping
  "timed out", surfacing `COLLEAGUE_TIMEOUT`).
- `colleague/tokenestimate.py` — `TokenEstimator` (the run-start probe +
  `usage`-anchored estimate), `observe`, `attach`, `COLLEAGUE_EXACT_TOKENS`.
- `tests/test_e2e_degradation.py` — end-to-end tests (overflow recovery, partial
  result on stdout).
- `tests/test_zero_deps.py` — guards `dependencies = []` (context module has no
  third-party imports).

## See also

- [stats-and-feedback.md](stats-and-feedback.md) — how a partial work item's
  cost/quality is recorded.
- [work-and-loop.md](work-and-loop.md) — the loop lifecycle and termination
  guarantees.
- [model-selection.md](model-selection.md) — configuring the model and server.

## Specification & plan

- Specification: `docs/specs/2026-06-02-colleague-drives-degrade-gracefully-when-a-task.md`
- Build plan: `docs/plans/2026-06-02-colleague-drives-degrade-gracefully-when-a-task.md`
