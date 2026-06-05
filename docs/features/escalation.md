# Escalation — agtag continuation issues

> When a work item hits a wall, colleague files one tracked agtag issue carrying
> what it finished, what is still outstanding, and a concrete suggested split —
> so the work is continuable, not silently dropped.

Escalation turns a partial work item result into an **actionable, continuable
artifact** that a human or agent can pick up. It is the outward signal of the
graceful-degradation layer: the loop already preserves a partial `TaskResult`
and `WorkStats` when it aborts; escalation converts those into a tracked issue
in the AgentCulture mesh via `agtag`.

This feature serves **whoever outsourced the task**: the operator or agent that
delegated work to colleague and needs to know it hit a limit and how to restart.

## When it fires

Escalation fires on exactly two branches of `colleague/loop.py`:

1. **`WorkAborted` branch** — a timeout, context-overflow, or engine error
   caused the loop to abort mid-work. The exception is caught, the partial
   result is finalized, and escalation is attempted before re-raising the abort.

2. **`not_finished` branch** — the step budget was exhausted without the model
   calling `finish`. The `not_finished` flag on `TaskResult` is set to `True`,
   and escalation fires.

On both branches, the call is wrapped in `contextlib.suppress(Exception)` — a
failure to escalate (network down, `agtag` absent, gate denied) **never masks
the work item result**. The work item artifact is always written first; escalation is
best-effort and observe-only.

## The opt-in / gating model

Escalation is **OFF by default**. It only fires when every one of these five
gates is open:

| Gate | Condition |
|------|-----------|
| **Opt-in** | `COLLEAGUE_ESCALATE` env var is set to a truthy value (legacy `CONVERTIBLE_ESCALATE` honored as fallback). Values `""`, `"0"`, `"false"`, and `"no"` are falsy. |
| **Online** | `handoff.has_remote(repo)` is `True` (a git remote is configured) AND `handoff.gh_available()` is `True` (`gh` is on `PATH`). |
| **Main checkout** | `(repo / ".git")` is a **directory**, not a file. A linked git worktree (colleague's subagent worktrees, `ask-colleague explore/review` throwaway worktrees) has `.git` as a file; escalation is skipped there. |
| **Approval gate** | The policy loaded from `.colleague/approvals.json` (and any per-model overlay) must allow the `agtag` program token. Absent or non-configured policy is a strict no-op (deny by default for the gate). |
| **Idempotency** | No escalation marker (`<task_id>.escalation.json`) already exists for this task id. A prior successful escalation prevents a duplicate issue on a retry. |

With the env flag unset — the default — all of the above is short-circuited
immediately: CI runs, offline runs, worktree runs, and tests are escalation-free
by construction.

### Enabling escalation

```bash
# Enable for one work item:
COLLEAGUE_ESCALATE=1 uv run colleague work "<task>" --repo . --engine vllm-openai

# Also approve agtag in the repo policy first (escalation requires it):
uv run colleague hooks approve .colleague/approvals.json --algo sha256 --repo .
# Or add the agtag token to .colleague/approvals.json run_command allow-list:
# { "run_command": { "allow": ["agtag"] } }
```

Like the live vLLM end-to-end test, the agtag post is not exercised in CI
(no live network or agtag daemon in the test environment).

## The idempotency marker

When a successful escalation is posted, `mark_escalated(repo, task_id,
issue_url)` writes `.colleague/<task_id>.escalation.json`:

```json
{
  "task_id": "9f2c1ab0e3c1",
  "issue_url": "https://github.com/…/issues/42"
}
```

The marker lives beside the work item artifact and feedback record. A second work item
of the same task (retrying after a failure) finds the marker and skips posting
— one issue per task, never duplicates. If the agtag post fails, the marker is
NOT written, so a future work item may retry.

## The continuation issue body

The issue title is: `colleague: continuation needed for work item <task_id>`

The body is produced by `build_continuation(result, stats)` in
`colleague/escalation.py` — a pure function with no I/O. It renders five
`##`-headed sections from the live `TaskResult` and `WorkStats`:

### Section 1 — Continuation State

What the work item actually completed. Includes:

- **Task ID**, **start time** (ISO-8601 UTC), and **wall-clock duration**.
- **Model turns** and **steps completed** (tool-call count).
- **Files changed** — a count and a list of up to five filenames (truncated
  with `…` when there are more than five).
- **Bytes written** — exact UTF-8 bytes written to files via `write_file`.
- **Tool breakdown** — per-tool call counts, sorted by tool name (e.g.
  `finish: 0, read_file: 4, write_file: 2`).
- **What the work item finished** — the model's `summary` field, or
  `_No summary produced._` when the work item produced none.

### Section 2 — Remaining Work

How far the work item got versus the original request. Built from `stats.request`
(the originating instruction) and `result.summary`. If both are identical the
section says to retry the full task; otherwise it shows the original request and
the point reached, and prompts a follow-up work item.

### Section 3 — What's Needed

A resource or configuration suggestion for unblocking the next work item. The
section inspects `result.error` for known keywords and generates targeted
advice:

| Error pattern | Advice |
|---------------|--------|
| `"context"` / `"window"` | Reduce `COLLEAGUE_CONTEXT_BUDGET`, split the task, or use a larger-context model. |
| `"timeout"` or `duration_seconds >= 600` | Increase the per-work-item timeout or break into shorter sub-tasks. |
| `"step"` / `"budget"` | Increase `COLLEAGUE_MAX_STEPS` or split the task. |
| _(none of the above)_ | Generic fallback: review the raw error, consider more steps, larger budget, longer timeout, or a task split. |

### Section 4 — Suggested Split

A concrete decomposition strategy built from step and turn counts. If the work item
was large (≥ 20 steps or ≥ 10 model turns) the split is labelled by feature
area or file group; smaller work items are split by scope. The section names files
already changed in the work item as "Part A (done)" and frames the continuation as
"Part B", finishing with an integration step.

### Section 5 — Why It Hit the Wall

A prose explanation of the exact stopping reason, drawn from
`result.error` keyword matching and the work stats. Covers context-window
exhaustion (with turn/step and char counts), timeout (elapsed time and steps),
step-budget exhaustion, and a generic fallback for other errors. Appended with
the bytes-written total when non-zero.

## Why runtime-auto instead of model-judged escalation

The escalation seam fires from the finalize path in `colleague/loop.py` — a
deterministic runtime hook, not a model tool call. The local model (Qwen3.6-27B)
unreliably calls tools at the wall (`#109`/`#104`): when context is nearly full
or the step budget is exhausted, the model's ability to emit a structured tool
call degrades. A runtime-auto hook is deterministic: it fires on the two
well-defined terminal branches regardless of what the model managed to produce.

The output is an **actionable, continuable artifact** — not a mere failure
notification. The five sections give the next work itemr (human or agent) exactly
what it needs to continue: the state checkpoint, the remaining scope, the
resource prescription, a concrete split plan, and the root-cause explanation.

## Honest limits

- **Best-effort, observe-only.** Both call sites are wrapped in
  `contextlib.suppress(Exception)`. Any failure in the escalation path
  (network error, `agtag` not found, policy denial, filesystem error) is
  silently swallowed and **never surfaces to the caller**. the work item result is
  always written before escalation is attempted.
- **Not the prompt-level INCOMPLETE seed.** The `doc-review` command template
  ships a prompt-level `INCOMPLETE:` section format (`#104`) for partial
  in-report continuations. That mechanism is separate — it posts no outward
  issue and is not gated by `COLLEAGUE_ESCALATE`.
- **No CI coverage of the agtag post.** The live network call to `agtag issue
  post` is not exercised in automated tests, exactly like the vLLM live
  end-to-end test (`COLLEAGUE_VLLM_E2E=1`). Tests inject a fake `run`
  callable to avoid subprocess/network calls.
- **Gate is a policy gate, not a sandbox.** The approval gate for `agtag` uses
  the same `run_command` allow/deny mechanism as the rest of the loop — it is
  bypassable by `sh -c` or pipelines (documented gap in the approval gate spec).

## Source pointers

| Module | Role |
|--------|------|
| `colleague/escalation.py` | `build_continuation` (pure renderer), `should_escalate` (5-gate predicate), `mark_escalated` (idempotency marker), `escalate` (orchestrator) |
| `colleague/loop.py` | Two finalize call sites (aborted branch + not-finished branch), each wrapped in `suppress` |
| `colleague/contract.py` | `TaskResult.not_finished` flag, `WorkStats` fields consumed by `build_continuation` |
| `.colleague/<task_id>.escalation.json` | Idempotency marker (beside the artifact and feedback record) |

Spec: `docs/specs/2026-06-03-colleague-escalates-via-agtag-when-it-can-t-withst.md`  
Plan: `docs/plans/2026-06-03-colleague-escalates-via-agtag-when-it-can-t-withst.md`

## See also

- [graceful-degradation.md](graceful-degradation.md) — the context-budget
  and overflow-retry layer that produces the partial result escalation reads.
- [stats-and-feedback.md](stats-and-feedback.md) — the `WorkStats` fields
  (`duration_seconds`, `step_count`, `bytes_written`, etc.) consumed by
  `build_continuation`.
- [mesh-member.md](mesh-member.md) — the `culture` tool and `run_culture`
  subprocess launch path that `escalate` uses to shell out to `agtag`.
- [audit-fanout.md](audit-fanout.md) — the operator-driven fan-out pattern for
  tasks that are too large for a single work item.
