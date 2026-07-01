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

- **Claims** are proposed in **focused calls**: the mandatory kinds first
  (announcement / audience / after_state / boundary / success_signal +
  before_state | why_it_matters), then requirement claims, then a **dedicated
  honesty-only pass** (#215, see below) — splitting honesty out of the combined
  call the weak model was dropping.
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

## Honesty conditions: a dedicated pass (#215)

The single biggest wall on the reference 27B (v1.20.0) was *not* unparseable
JSON — the mandatory-kinds call now gets through. It was the **combined
requirements+honesty call returning claims but zero honesty conditions**, so
every confirmed spec-affecting claim failed the convergence rule and the spec
could never converge (filed as the new wall in #215).

`make_propose_claims` now recovers honesty in two bounded steps **after** the
claim calls, all routed through `robust_simple_complete`:

1. **A dedicated honesty-only call** (`CLAIMS_HONESTY_SYSTEM_PROMPT`) — lists
   every spec-affecting claim still missing a condition and asks for a single
   `{"honesty": [...]}` array. One output shape, one focused ask — the kind a
   weak model handles best.
2. **A bounded per-claim fallback** (`ONE_HONESTY_SYSTEM_PROMPT`, cap
   `_MAX_HONESTY_FALLBACK = 8`) — for any claim the batch call still left
   uncovered, one tiny focused call each.

The fill keys on **`claim_id`** (the convergence rule binds honesty to a
*claim*) and **mints a fresh unique id** for each accepted condition — the
dedicated/per-claim calls often reuse `"h1"`, which the id-dedup of the normal
claims path would have silently dropped. A strong model that already returned
honesty in the combined call skips the whole pass (no claims missing → no
extra call); an empty/unparseable honesty chunk is tolerated, never a crash.
Honesty conditions still land `state="proposed"` — the operator/gate confirms
them; the convergence rule is **unchanged** (honesty stays mandatory).

> **A deliberate non-choice:** a deterministic *synthetic* honesty condition
> (auto-generating "verify X is achievable" per claim) would *guarantee*
> convergence but make it vacuous — a rubber-stamp passing a gate whose entire
> purpose is genuine pressure-testing. Plan mode instead gives the model
> multiple focused shots and, if it still cannot produce honesty, **fails
> honestly** with the #224 reason — never a synthetic pass.

## Plan-only mode: `--no-workforce` (#215)

A caller who says "plan this" usually wants the **spec + plan**, not the long,
side-effecting implementation fan-out (Wall 2: the workforce's big-context
implementation turns time out at the 120s default on the 27B). `colleague plan
run --no-workforce` stops right after the plan items are proposed (and gated, in
`--quick` mode): **no wave is computed, `batch_spawn` is never called, and no
subagent worktree is created.** `OrchestratorResult` keeps its shape (empty
`waves`/`sub_results`/`conflicts`), so the default (workforce on) is
byte-identical. Surfaced through `ask-colleague plan --no-workforce` too.

## Honest non-convergence reporting (#224)

When the spec gate fails, the CLI now names the **real** gap. The convergence
result carries two failure lists — `missing_kinds` and `claims_missing_honesty`
— but the CLI surfaced only the first, so a run that failed *solely* on missing
honesty reported `missing: (none)` (human) or `{"missing_kinds": []}` (`--json`):
the gate knew the answer and dropped it. Both `_render_run` and `_run_payload`
now surface `claims_missing_honesty`, and a non-converged result **never**
renders a silent `(none)` (a defensive line covers the unreachable both-empty
case). A drift test pins the invariant: `converged is False` ⇒ at least one
failure list is non-empty on each surface.

## Spec-less `--quick` path (#199)

`colleague plan run --quick "<request>"` (alias `--no-spec`) skips the per-claim
spec-convergence micro-cycle and proposes plan items **directly from the
request** — the middle ground between the full devague arc and a one-shot
`colleague work`. It is **still operator-gated at the plan level** (confirm the
task split; `--yes` auto-confirms); only the spec stage is skipped. The default
(non-quick) path is unchanged.

## Cross-invocation resume: `plan continue` (#t17)

`colleague plan continue` resumes an interrupted `plan run` (killed, crashed,
closed terminal) from its persisted checkpoint
(`.colleague/plan/<frame>.json`, `--frame <slug>` to target a non-default one)
— **without re-asking the gates it already resolved**. It is a thin wrapper
over the same orchestrator entry (`run_plan_mode`): the checkpoint now also
stores the originating `request` text (`Checkpoint.request`, `checkpoint.py`),
so `continue` can rebuild the frame without the caller re-typing it. It reads
back the resolved-gate count and reports `resuming '<frame>': N gate(s)
already resolved` to stderr, then drives the orchestrator in the
already-shipped `quick=True` mode — which never calls `decide` for spec
claims/honesty at all, so those resolved gates are **structurally** never
re-asked (not merely best-effort id-matching against a freshly re-proposed,
possibly different, set of claims). `continue` **refuses cleanly** (a
`CliError` with a remediation hint, never a traceback) when there is no
checkpoint to resume from, or the checkpoint predates this feature and has no
stored request — that refusal is exactly what distinguishes it from `run`.
Accepts the same `--repo`/`--engine`/`--model`/`--yes`/`--review`/
`--no-workforce`/`--json` flags as `run`; there is no `--quick` on `continue`
(resuming is always the quick/skip-spec-stage path) and no `--timeout` (`run`
has none either — the per-request timeout is env-only, `COLLEAGUE_TIMEOUT`).

**Honest limits:** the checkpoint does not persist the full frame (claim/
honesty text, kind, or per-item confirm/reject decisions) — only gate *ids*
and the request text — so a genuinely fine-grained "replay exactly what the
operator confirmed, claim by claim" resume is not what this builds. Instead
`continue` trusts that a checkpointed spec stage already ran to a decision and
moves straight to plan-item proposal from the original request (the same
mechanism `--quick` already uses for a fresh run), which is honest about *what*
it skips (the whole spec-stage gate cycle) without pretending to reconstruct
per-claim state it never stored. This never invents a confirm/reject decision
the operator did not make — no per-item auto-confirmation, no gate-semantics
change.

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
- **No convergence guarantee on a weak model (#215)** — the dedicated honesty
  pass gets the 27B *further* (focused single-claim asks are what it handles
  best) but cannot *guarantee* it produces honesty. If it doesn't, the spec
  **fails honestly** with the #224 reason — honesty is never synthesized to
  force a pass. `--no-workforce` only sidesteps Wall 2 (the workforce timeout),
  not a genuine spec non-convergence.
- **`plan continue`'s resume is checkpoint-id-level, not full-frame** — it
  persists gate ids + the request text, not full claim/honesty content or
  per-item decisions, so it resumes by skipping the whole spec stage (via
  `quick=True`) rather than precisely replaying each prior confirm/reject.

## Conventions

Runtime-owned and all-engines (fires identically for `mock` and `vllm-openai`),
zero new runtime deps (stdlib `json`), no socket/daemon. Gate semantics are
unchanged — the operator still gates; LLM proposals stay proposed.

Spec + plan: `docs/specs/2026-06-17-colleague-plan-mode-now-drives-smaller-degradation.md`,
`docs/plans/2026-06-17-colleague-plan-mode-now-drives-smaller-degradation.md`.

The honesty-pass + `--no-workforce` + honest-reporting layer (#215 / #224 / #226):
`docs/specs/2026-06-19-colleague-plan-mode-gets-the-served-27b-further-an.md`,
`docs/plans/2026-06-19-colleague-plan-mode-gets-the-served-27b-further-an.md`.

`plan continue` (R6, task t17):
`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`,
`docs/plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`.
