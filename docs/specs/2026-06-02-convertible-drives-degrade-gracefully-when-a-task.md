# Convertible drives degrade gracefully when a task outgrows the model's context window: the loop trims its running history to fit and keeps going, and any drive that still cannot finish returns a readable partial result to the caller instead of empty stdout.

> Convertible drives degrade gracefully when a task outgrows the model's context window: the loop trims its running history to fit and keeps going, and any drive that still cannot finish returns a readable partial result to the caller instead of empty stdout.

## Audience

- Operators and agents who outsource multi-file repo tasks to convertible against small-context models (e.g. the served ~27B at a 32k window) via 'convertible drive' / the outsource skill.

## Before → After

- Before: The loop accumulates an unbounded message history (only per-tool-result truncation at 20k chars, tools.py:30). During the #72 audit a ~16-file read overflowed the 32k window; vLLM returned HTTP 400 'maximum context length is 32768 ... prompt contains 32769'. The partial artifact landed in a throwaway worktree and the caller saw only 'convertible produced no result on stdout' (outsource.sh:222).
- After: A multi-file drive that would overflow the context window trims its oldest tool-result history to fit and continues; if it still cannot finish, the caller receives the partial TaskResult (steps/usage/changed_files, status=error) on stdout, not empty output plus an opaque error.

## Why it matters

- Outsourcing repo work to diverse/smaller models is convertible's whole value; if a routine multi-file task silently dies on a small model, the harness is unreliable for its core use case.

## Requirements

- The loop enforces a configurable context budget (env/config, conservative default) and windows the running message list before each model turn, preserving OpenAI message validity (no orphaned assistant tool_calls / tool replies).
  - honesty: Windowing always keeps the system prompt + the original task message + the most-recent turns, and never sends a message list with an assistant tool_calls turn missing its matching tool replies (OpenAI-valid).
  - honesty: The budget is read from config/env with a conservative default and expressed in TOKENS; it is counted exactly via the server's /tokenize when reachable and approximated by the char fallback otherwise — documented as best-effort-exact (degrades to approximate), never silently wrong.
- On a detected context-overflow error from 'complete', the loop trims history and retries the same turn a bounded number of times before giving up; on final give-up it preserves the partial result (the existing #37 DriveAborted path).
  - honesty: trim-and-retry is capped at a small fixed number of attempts per turn; once the floor (system+task, no droppable history) is reached and it still overflows, the loop stops and preserves the partial result — termination guarantee h3 still provable.
- The CLI --json drive path emits the partial TaskResult JSON to stdout even on the failure/overflow path, so a caller (outsource.sh) gets a parseable result instead of empty stdout; exit code still reflects failure.
  - honesty: After the change, 'convertible drive --json' on an overflow exits non-zero AND prints a JSON object with status=error and non-empty steps to stdout; outsource.sh print_result parses it instead of reporting 'no result on stdout'.
- Degradation lives in the chassis (convertible/loop.py) and fires identically for mock and vllm-openai (all-engines rule); the artifact shape is unchanged (e2e shape test stays green).
  - honesty: tests/test_e2e_mock.py still passes unchanged (artifact shape identical) and the new degradation behavior is exercised through the engine-agnostic loop, not engine-specific code.

## Honesty conditions

- A reproduced overflow scenario that fails today returns a non-empty, status=error TaskResult on stdout after this change (provable by a test).
- The overflow is reproducible for a multi-file drive on a ~32k-window model via 'convertible drive' / outsource — i.e. this audience actually hits it today, not a hypothetical.
- After the change the same overflowing drive either finishes, or yields a status=error result whose steps/changed_files reflect the work done up to the limit — verifiable in a test.
- The cited failure is real and current: today's loop sends the full unbounded history with no proactive trim — confirmable by reading loop.py _drive_loop + tools.py:30 (only per-result truncation exists).
- A multi-file task on a small model is a normal, intended use of convertible (not abuse), so silent failure is a genuine reliability gap.
- No third-party tokenizer LIBRARY/dep is added (exact counting reuses the existing stdlib HTTP path to the server's /tokenize; the fallback is char-based) — tests/test_zero_deps.py stays green.
- When /tokenize is absent or errors (non-vLLM OpenAI server), the drive still runs unchanged on the char fallback — so retargeting any OpenAI-compatible server stays a config change, never a code change (h2 preserved); only budget precision degrades, never correctness.
- There is a concrete runnable test that reproduces an overflow and asserts the post-change outcome (completes, or status=error with non-empty steps on stdout).
- Both tests run engine-agnostically (no live server) by injecting a 'complete' callable, so CI exercises the degradation path deterministically.

## Success signals

- A drive that previously overflowed (the 16-file audit on a 32k model) now either completes, or returns a readable partial result with status=error and non-empty steps on stdout.
- An engine-agnostic test injects a 'complete' that raises a context-overflow error once then succeeds, and asserts the loop trimmed history and retried; a second test asserts the --json drive path emits the partial result JSON to stdout on the failure path.

## Scope / boundaries

- Token-based budget via a PLUGGABLE counter, no new library dependency: the loop measures the running prompt in tokens through an injected count_tokens seam. The vLLM engine counts exactly via the server's /tokenize endpoint (reusing the same stdlib urllib/OpenAI-style connection — zero new dep); when a server does not expose /tokenize (llama.cpp/proxies/mock) the seam falls back to a zero-dep char heuristic. No third-party tokenizer library (tiktoken/transformers) is added.

## Non-goals

- No LLM-generated rolling summary in v0: windowing drops/elides the oldest tool results and leaves a short placeholder note; a model-based summarization pass is a parked follow-up.
- Not a context router or multi-model fallback: an overflow never auto-switches to a bigger model — that is the out-of-scope 'gearbox'.
- Not unbounded retries: trim-and-retry is bounded so the loop's termination guarantee (h3) still holds; no new exit path, no daemon, no new runtime dep.

## Decisions

- Overflow detection (resolves v2): match known overflow phrases first ('maximum context length', 'context window', 'too many tokens', 'reduce the length'); if unmatched, treat any HTTP 400 from 'complete' as a possible overflow and attempt one bounded trim+retry. Worst case on an unrelated 400 is a single harmless retry before the partial-result path.
- Token-counter seam: the loop takes an injected count_tokens(messages)->int (like complete/progress/spawn). The vLLM engine supplies one that POSTs the candidate messages to {base_url-root}/tokenize (vLLM extension) for an exact count; on 404/any error it returns None so the loop uses the zero-dep char-heuristic fallback. The mock engine uses the heuristic. At most a small constant number of /tokenize calls per turn (count, proportional pre-trim, one verify).

## Open / follow-up

- Detection wording across OpenAI-compatible servers (DECIDED, see c16): match known overflow phrases first, else treat any HTTP 400 as a possible overflow and try one bounded trim+retry. Residual follow-up: extend the phrase list if a new server surfaces an unanticipated overflow wording.
