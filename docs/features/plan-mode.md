# Plan mode — degradation-aware proposals + the spec-less `--quick` path

`colleague plan` makes colleague the *planning mind* for a complex task — the
same `/think` → `/spec-to-plan` → `/assign-to-workforce` arc, but driven by a
**different mind** than the requester (the diversity is the point). The verb
proposes spec **claims**, runs the convergence-gated spec stage, proposes
**plan items**, and fans the dependency waves out to the workforce.

This document covers the **robustness** layer that makes plan mode work on a
smaller or *reasoning* served backend (issues #210 / #199 / #204).

## The problem (#210)

The proposal seams (`colleague/plan/cli_driver.py`) used to ask the model for
**everything in one shot** and read `resp.content` only. On the reference 27B
reasoning model (`Qwen3.6-27B`) that failed two ways:

- The model emits its answer into the **`reasoning`** channel and returns an
  **empty `content`** → `parse_claims` raised `no JSON object found in model
  output`. Plan mode was *non-functional* on a reasoning backend.
- A big single JSON blew the request timeout, and any truncation failed the
  whole stage.

## The robust proposal path

Plan proposals now route through `robust_simple_complete` instead of the thin
`to_simple_complete`. For each proposal call it:

1. **Forced no-thinking follow-up** — when `resp.content` is empty/whitespace,
   it appends a `"Respond with ONLY the JSON object now. Do not think step by
   step."` turn and completes again (the loop's `_maybe_force_synthesis`
   pattern, applied to the proposal seam).
2. **Reasoning-channel recovery** — if content is still empty, it returns
   `resp.reasoning` so the parser can recover the JSON the model placed in its
   thinking.
3. **Degradation retry** — a `classify_degradable`-classified timeout/overflow
   error is retried bounded (timeout ×1, overflow ×3), mirroring the loop's
   `_MAX_TIMEOUT_RETRIES` / `_MAX_OVERFLOW_RETRIES`.

### Smaller "jumps"

- **Claims** are proposed in **two calls**: the mandatory kinds first
  (announcement / audience / after_state / boundary / success_signal +
  before_state | why_it_matters), then requirements + honesty conditions
  conditioned on the first set.
- **Plan items** are proposed in **bounded batches** (≤5 items, ≤4 batches),
  each conditioned on the prior set. The loop stops when a batch adds nothing
  new — and **dedups by id**, so a model that re-proposes prior items cannot
  inflate the set or break `validate_items`.
- A single bad chunk is **tolerated** (skipped, not fatal); a *total* parse
  failure still surfaces the clean `"unusable plan proposal"` error.

### Tolerant JSON extraction

`_extract_json_object` gained two robustness behaviors, both driven by live 27B
failure modes:

- **Prefer the expected key** — it scans successive top-level objects and
  returns the first carrying `"claims"` / `"items"`, so a stray `{...}` in the
  model's prose (e.g. an inline schema example) cannot shadow the real payload.
- **Repair truncation** — when the model stops *before the closing brace*
  (`{"items": [ … ]` with the final `}` missing — observed live), it walks the
  unclosed `{`/`[` stack, appends the implied closers, and parses; on a
  mid-token cut it retreats to the last complete element and retries once.

A well-formed, balanced response is **byte-identical** through all of the above.

## Spec-less `--quick` path (#199)

`colleague plan run --quick "<request>"` (alias `--no-spec`) skips the per-claim
spec-convergence micro-cycle and proposes plan items **directly from the
request** — the middle ground between the full devague arc and a one-shot
`colleague work`. It is **still operator-gated at the plan level** (confirm the
task split; `--yes` auto-confirms); only the spec stage is skipped. The default
(non-quick) path is unchanged.

## `Engine.make_complete` (#204)

The public one-shot completion seam (`Engine.make_complete(config) -> CompleteFn`)
that plan mode drives the model through is on the `Engine` base: live backends
override it; `mock` inherits the default `NotImplementedError` (plan mode needs a
live backend). Landed and pinned by `tests/test_engine_make_complete.py`.

## Live validation

On the reference 27B that previously failed at the claims stage, an end-to-end
proposal run now produces **11 claims + 8 honesty conditions** and **4 plan
items** (with a valid dependency order) — no `no JSON object found` raise. The
claims path closed cleanly; the plan-items path needed the truncation repair
(the model dropped its final `}`).

## Honest limits

- **Still needs a live backend** — `mock` inherits `make_complete`'s
  `NotImplementedError`; plan mode is a no-op there.
- **Latency tradeoff (#210 q1)** — chunking adds model calls; the batch count is
  bounded (≤4) and each call is smaller, but on a serializing server total
  wall-clock can exceed the old monolith. The bound is the mitigation.
- **JSON repair is best-effort** — it recovers a structurally-truncated object,
  not arbitrary malformed JSON; an unrecoverable fragment still degrades to the
  clean `"unusable plan proposal"` error.
- **Cross-invocation `plan continue` resume** remains a documented follow-up.

## Conventions

Runtime-owned and all-engines (fires identically for `mock` and `vllm-openai`),
zero new runtime deps (stdlib `json`), no socket/daemon. Gate semantics are
unchanged — the operator still gates; LLM proposals stay proposed.

Spec + plan: `docs/specs/2026-06-17-colleague-plan-mode-now-drives-smaller-degradation.md`,
`docs/plans/2026-06-17-colleague-plan-mode-now-drives-smaller-degradation.md`.
