# Live-testing ledger

The unit suite (1700+ test functions) proves the **contract** against the `mock`
backend and fixtures. It does **not** prove the runtime works end-to-end against a
real served model. Two layers stay invisible to unit tests:

1. **Tools the model must *choose* to invoke** — `subagent`/`subagents`,
   `culture`, `devague`. A drive only exercises them if the live model decides to
   call them. Across every real drive trace captured so far, the live model has
   invoked **only the base five** (`read_file`, `write_file`, `list_dir`,
   `run_command`, `finish`).
2. **Config surfaces that must be *present* to fire** — `approvals.json`,
   `hooks.json`, `neighbours.json`, per-model AGENTS/skills layers, the `[otel]`
   extra. None are present in this repo, so none have ever fired in a live drive.

This ledger tracks that second layer: **live validation against the reference
rig**, with a commit+date stamp per feature so staleness is detectable.

## Reference rig

| Field | Value |
|-------|-------|
| Provider `base_url` | `http://localhost:8001/v1` |
| Model | `sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP` |
| Readiness check | `colleague doctor --probe` (must report `provider_reachable` + `provider_model_available` → passed) |

A served model that exposes tool calling is required: the vLLM rig must run with
`--enable-auto-tool-choice` plus a model-appropriate `--tool-call-parser`
(e.g. `hermes` or `qwen3_coder`).

## How to use this ledger

Each feature has a row in the [matrix](#validation-matrix) and a procedure below.
A row records **Last validated** as `<commit> · <date>` — the commit the code was
at when the procedure was last run and passed.

**Staleness check.** A row is stale when its source files have commits newer than
the recorded SHA. To check one feature:

```bash
# compare the feature's source files against the row's "Last validated" SHA
git log -1 --format='%h %cs' -- colleague/subagents.py colleague/worktrees.py
```

If that SHA differs from the ledger's recorded SHA for the row, the live
validation is stale: re-run the procedure and update the row (commit, date,
status, evidence). A row whose code moved but whose stamp did not is **lying** —
treat ❌-by-staleness the same as never-validated.

**Status legend:** ✅ validated live · ⚠️ partial / flaky · ❌ not yet validated live

## Validation matrix

| # | Feature | Source | Status | Last validated | Issue |
|---|---------|--------|--------|----------------|-------|
| — | Base loop (5 tools), drive | `colleague/loop.py`, `colleague/tools.py` | ✅ | `83fe6aa` · 2026-06-04 (17 live drives) | — |
| — | `outsource explore` | `.claude/skills/outsource/` | ✅ | `83fe6aa` · 2026-06-04 (drive `d2dc294f3c41`, `f9f17b0d924f`) | — |
| — | `outsource review` | `.claude/skills/outsource/` | ✅ | `83fe6aa` · 2026-06-04 (drive `782a90785b30`, rated 4) | — |
| — | `feedback` record/show | `colleague/feedback.py` | ✅ | `83fe6aa` · 2026-06-04 (graded drives present) | — |
| — | `doctor` / `doctor --probe` | `colleague/cli/_commands/doctor.py` | ✅ | `83fe6aa` · 2026-06-04 | — |
| — | Command templates | `colleague/commands.py` | ✅ | `83fe6aa` · 2026-06-04 (`doc-review`) | — |
| — | Drive stats | `colleague/loop.py`, `colleague/contract.py` | ⚠️ | present in artifacts; not field-audited live | — |
| — | Step-budget termination | `colleague/loop.py` | ✅ | `83fe6aa` · 2026-06-04 (drive `99d1a4ee9572`, `901e9d61bf31`) | — |
| 1 | `outsource write` reliability | `.claude/skills/outsource/`, `colleague/handoff.py` | ⚠️ | flaky — drive `1bcabd9095d3` rated 1 | [#121](https://github.com/agentculture/colleague/issues/121) |
| 2 | Subagents (`subagent`/`subagents`) | `colleague/subagents.py`, `colleague/worktrees.py` | ❌ | — (0 live calls) | [#122](https://github.com/agentculture/colleague/issues/122) |
| 3 | Gated configs (approvals / hooks / per-model layers) | `colleague/policy.py`, `colleague/hooks.py`, `colleague/layers.py` | ❌ | — (no config present) | [#123](https://github.com/agentculture/colleague/issues/123) |
| 4 | Loop tools: `culture` + `devague` | `colleague/culture.py`, `colleague/devague.py` | ❌ | — (0 live calls) | [#124](https://github.com/agentculture/colleague/issues/124) |
| 5 | Neighbours read-only clones | `colleague/neighbours.py` | ❌ | — (no `neighbours.json`) | [#125](https://github.com/agentculture/colleague/issues/125) |
| 6 | Telemetry end-to-end | `colleague/telemetry/` | ❌ | — (never run w/ collector) | [#126](https://github.com/agentculture/colleague/issues/126) |
| 7 | Context-overflow graceful degradation | `colleague/context.py`, `colleague/loop.py` | ❌ | — (only step-budget seen live) | [#127](https://github.com/agentculture/colleague/issues/127) |

Tracking epic: [#128](https://github.com/agentculture/colleague/issues/128).

## Procedures

Every procedure ends by updating this file's matrix row (status + `Last
validated` SHA/date + evidence drive id) and closing the linked issue.

### 1. `outsource write` reliability

**Why it matters.** `explore`/`review` are read-only and validated. `write
--apply` lands a drive branch; `write --pr` opens a PR. The drive's
commit/summary can drop or misreport edits, and a stale base or silent `mock`
fallback can produce a no-op.

**Evidence of the gap.** Drive `1bcabd9095d3` (rated 1): branched from an old
base, produced a stray `colleague-mock.md` with the doc-review command template
as the commit message, never touched the target file. Counter-example
`8cc1b4528a34` succeeded on the same task — so `write` is **flaky**, not broken.
`write --pr` has never opened a PR end-to-end.

**Procedure.**

1. Pick a small, well-scoped change with a clear target file.
2. `outsource write "<task>" --apply` (live backend).
3. **Verify by diff, not by the drive summary:** `git diff main...HEAD --stat`
   and inspect — confirm the target file changed and no stray files (e.g.
   `colleague-mock.md`) appeared.
4. Re-run the affected tests; confirm green.
5. Repeat 1–4 three times on different tasks.
6. Run `outsource write "<task>" --pr` once; confirm a real PR opens against the
   correct base.

**Acceptance.** 3 consecutive `write --apply` runs verified clean by diff + tests;
one `write --pr` opens a correct PR; the stale-base / mock-fallback root cause is
understood (and filed separately if it recurs).

### 2. Subagents end-to-end live

**Evidence of the gap.** Across all live drive traces the model invoked only the
base five tools; `subagent`/`subagents` were never called. Worktree isolation and
the sequential merge child are unexercised against a real model.

**Procedure.**

1. Craft a task that *invites* delegation, e.g. "make two independent edits in
   parallel: rename X in file A and add a helper in file B."
2. `COLLEAGUE_SUBAGENT_CONCURRENCY=2 colleague drive "<task>" --repo . --no-pr`.
3. Confirm in the trace/artifact: ≥1 `subagent`/`subagents` call; children ran on
   `sub/<id>` branches in throwaway worktrees; the merge child integrated them;
   `sub_results` folded into the artifact.
4. Force a merge conflict (two children edit the same lines) and confirm the merge
   child **surfaces** the conflict rather than force-merging.
5. Confirm caps: `MAX_SUBAGENT_DEPTH=2` and `MAX_SUBAGENT_FANOUT=4` hold.

**Acceptance.** A live drive shows subagent delegation, worktree create+cleanup,
conflict surfaced, caps enforced, and `sub_results` in the artifact.

### 3. Gated configs enforcement live (approvals / hooks / per-model layers)

**Evidence of the gap.** No `approvals.json` / `hooks.json` / AGENTS layers in the
repo; `doctor` reports `0 AGENTS layer(s), 0 skill(s)`; none has fired live.

**Sub-checks (tick individually).**

- **3a Approvals — `run_command`:** add `.colleague/approvals.json` denying a
  program token (e.g. `curl`); run a drive that would call it; confirm
  `_deny_by_policy` blocks it. Then approve and confirm it runs.
- **3b Approvals — hooks/commands by checksum:** approve a hook script, then edit
  it; confirm the checksum mismatch voids the approval (denied).
- **3c Hooks fire:** add `.colleague/hooks.json` with a `pre_tool` hook that
  **rewrites** and another that **denies** a tool call; confirm both take effect
  live (first-deny / rewrite-wins).
- **3d Per-model hooks overlay:** add `.colleague/<sanitized-model>/hooks.json`;
  confirm per-model-first precedence over the base entries.
- **3e Per-model AGENTS/skills:** add `AGENTS.colleague.<model>.md` and a
  `.colleague/<model>/skills/*.md`; confirm both land in the system prompt
  (`colleague agents` / `colleague skills`, and a drive reflects them).

**Acceptance.** Each sub-check observed live; all config removed afterward (this
repo ships none by default — keep it that way).

### 4. Loop tools live — `culture` + `devague`

**Evidence of the gap.** 0 live calls to either tool.

**Sub-checks.**

- **4a `culture`:** a task that should reach for `agtag`/`devex`; confirm the tool
  shells out with `COLLEAGUE_IDENTITY` injected and the allow-list holds (a
  non-allow-listed CLI is rejected).
- **4b `devague`:** a vague/new task; confirm the model can `new`/`capture`/
  `converge`/`status`, and that `confirm`/`reject`/`export` are structurally
  **absent** from the allow-list. Confirm `destination`/`announcement` land in the
  artifact when set.

**Acceptance.** A live drive invokes each tool; identity injection + allow-list
exclusions verified; artifact carries the destination when one is set.

### 5. Neighbours read-only clones live

**Evidence of the gap.** No `neighbours.json`; the feature has never run.

**Procedure.** Add `.colleague/neighbours.json` with one `{name, url}`; run a drive
that reads a neighbour file; confirm a shallow clone appears under
`.colleague/neighbours/<name>/`, is gitignored, and is cleaned up on drive finish.

**Acceptance.** Clone-on-demand + cleanup observed; empty-config default still a
no-op.

### 6. Telemetry end-to-end live

**Evidence of the gap.** Off by default; never run against a collector.

**Procedure.** `uv sync --extra otel`; run an OTLP collector (or point at a
file/debug exporter); `COLLEAGUE_OTEL_ENABLED=1
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 colleague drive … --no-pr`;
confirm root + per-tool + handoff spans and the metrics
`colleague.generated.chars` / `colleague.bytes_written`. Re-confirm that with the
flag off there are no spans and no SDK import (strict no-op).

**Acceptance.** Spans + metrics observed when on; verified no-op when off.

### 7. Context-overflow graceful degradation live

**Evidence of the gap.** Step-budget termination has been seen live (drives
`99d1a4ee9572`, `901e9d61bf31`), but the **context-overflow trim+retry** path in
`colleague/context.py` has never triggered against a real model.

**Procedure.** Set a small `COLLEAGUE_CONTEXT_BUDGET` (e.g. a few thousand tokens)
and a multi-file task; confirm history windowing drops oldest turns with a
placeholder note, and that an induced overflow triggers a harder trim + bounded
retry, preserving a readable partial result instead of hard-failing.

**Acceptance.** The trim+retry path is exercised live and a partial result is
preserved; bound on retries holds (termination).
