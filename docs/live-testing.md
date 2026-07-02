# Live-testing ledger

The unit suite (1700+ test functions) proves the **contract** against the `mock`
backend and fixtures. It does **not** prove the runtime works end-to-end against a
real served model. Two layers stay invisible to unit tests:

1. **Tools the model must *choose* to invoke** — `subagent`/`subagents`,
   `culture`, `devague`. A drive only exercises them if the live model decides to
   call them. Across every real drive trace captured so far, the live model has
   invoked **only the base five** (`read_file`, `write_file`, `list_dir`,
   `run_command`, `finish`). The newer `edit_file` (partial-edit, #174) has not
   yet appeared in a captured live trace — see its own matrix row below.
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
| — | Drive stats | `colleague/loop.py`, `colleague/contract.py` | ✅ | `d1b4d54` · 2026-06-05 (drive `a6c5f0c1fd13`, `bytes_written` exact); see §0 result | — |
| — | Step-budget termination | `colleague/loop.py` | ✅ | `83fe6aa` · 2026-06-04 (drive `99d1a4ee9572`, `901e9d61bf31`) | — |
| 1 | `outsource write` reliability | `.claude/skills/outsource/`, `colleague/handoff.py` | ✅ | `6eb843d` · 2026-06-04 (apply `b885fbb`,`5bc48e7`,`f51427e` + PR `221b4ce`/#130); see §1 caveats | [#121](https://github.com/agentculture/colleague/issues/121) |
| 2 | Subagents (`subagent`/`subagents`) | `colleague/subagents.py`, `colleague/worktrees.py` | ✅ | `61d15cc` · 2026-06-04 (drive `6c27147eb917`); see §2 caveat | [#122](https://github.com/agentculture/colleague/issues/122) |
| 3 | Gated configs (approvals / hooks / per-model layers) | `colleague/policy.py`, `colleague/hooks.py`, `colleague/layers.py` | ✅ | `304002a` · 2026-06-04 (3a/3c/3d live, 3b/3e deterministic); see §3 result | [#123](https://github.com/agentculture/colleague/issues/123) |
| 4 | Loop tools: `culture` + `devague` | `colleague/culture.py`, `colleague/devague.py` | ✅ | `7a12d1e` · 2026-06-05 (4a `2395f7d5d9b9`, 4b `80cb15c5f9cd`); see §4 result | [#124](https://github.com/agentculture/colleague/issues/124) |
| 5 | Neighbours read-only clones | `colleague/neighbours.py` | ✅ | `64361da` · 2026-06-05 (drive `711505cb4c3f`); see §5 result | [#125](https://github.com/agentculture/colleague/issues/125) |
| 6 | Telemetry end-to-end | `colleague/telemetry/` | ✅ | `d5c9312` · 2026-06-05 (e2e in CI + live drive `eff14af763d4`); see §6 result | [#126](https://github.com/agentculture/colleague/issues/126) |
| 7 | Context-overflow graceful degradation | `colleague/context.py`, `colleague/loop.py` | ✅ | `fcbf4ec` · 2026-06-05 (proactive `36b022abc7f0`, reactive `0323db53b1dd`); see §7 result | [#127](https://github.com/agentculture/colleague/issues/127) |
| 8 | Partial-edit tool (`edit_file`) | `colleague/tools.py` | ✅ | `bf6cf2d` · 2026-07-02 (work items `ede0f61fb28b` ×7, `5ccdf8573cad` ×2, `6422d3224e32` ×11 — real TDD builds on this repo) | [#174](https://github.com/agentculture/colleague/issues/174) |
| 9 | Memory: recall-before / remember-after | `colleague/memory.py`, `colleague/loop.py` | ✅ | `bf6cf2d` · 2026-07-02 (smoke `e082b37e602e` lesson persisted to the durable store; warm-vs-cold `503b0a36c33a` vs `c5774404bc3d` — 10→2 steps, 23.4k→4.3k tokens; see `docs/features/memory.md`) | — |
| 10 | Finish recovery (thin/meta/literal-markup) | `colleague/loop.py` | ⚠️ | `bf6cf2d` · 2026-07-02 (deterministic regression suite on the #248/#231 evidence shapes; a live re-occurrence not yet observed post-fix — the fix removes the trigger) | [#248](https://github.com/agentculture/colleague/issues/248) [#231](https://github.com/agentculture/colleague/issues/231) |
| 11 | Background one-shot (`work --background`) | `colleague/background.py` | ⚠️ | `bf6cf2d` · 2026-07-02 (mock-engine e2e through `main()` incl. kill-reap; a live-model background run not yet exercised) | — |
| 12 | Resident appserver (agent-lifecycle embed) | `colleague/resident/appserver.py` | ⚠️ | `bf6cf2d` · 2026-07-02 (real `agent_lifecycle` 0.9.0 + reference transport e2e; REAL mesh transport PENDING upstream — h15, never claimed) | — |
| 13 | Spontaneous `subagents` delegation | `colleague/subagents.py` | ✅ | `bf6cf2d` · 2026-07-02 (work items `5ccdf8573cad` ×1, `6422d3224e32` ×2 with 7 folded sub_results — UNPROMPTED, superseding §2's "needs an explicit invite" caveat) | — |
| 14 | Substantial decomposed write (h9) | `colleague/loop.py`, `colleague/tools.py`, `colleague/subagents.py` | ⚠️ | `22adbb3` · 2026-07-02 (pre-fix `4c6a96107269` CRASHED on a malformed tool call; post-fix `55859cb1d605` survived to an honest `incomplete` — harness proven, the served 27B couldn't land the full decomposition; see the substantial-write section below) | — |

Tracking epic: [#128](https://github.com/agentculture/colleague/issues/128).

## Procedures

Every procedure ends by updating this file's matrix row (status + `Last
validated` SHA/date + evidence drive id) and closing the linked issue.

### 0. Drive stats field audit

**Why it matters.** `DriveStats` (`colleague/contract.py`) is always-on and
populated runtime-side in `colleague/loop.py` (the all-engines rule), so the unit
suite proves it *exists* in every artifact. What unit tests cannot prove is that
its numbers are *faithful to a real drive*: that `bytes_written` equals the bytes
actually written, that `tool_counts`/`step_count` mirror the live step trace, and
that the token `usage` is the verbatim server count. This audits the block
against ground truth from one live drive.

**Procedure.**

1. Run a live drive that exercises several stat fields (a write + a command over
   several turns) in a throwaway git repo so this repo stays clean:

   ```bash
   WORK=$(mktemp -d); git -C "$WORK" init -q
   git -C "$WORK" config user.email a@b.c; git -C "$WORK" config user.name audit
   git -C "$WORK" commit -q --allow-empty -m init
   uv run colleague drive "Create greet.py with a greet(name) function and a \
     __main__ block that prints greet('world'), then run it with python3." \
     --repo "$WORK" --engine vllm-openai --no-pr
   ```

2. Open the artifact (path is echoed as `artifact:`) and read its `stats` +
   `usage` + `steps` + `changed_files`.
3. **Verify each field against ground truth, not the summary:**
   - `bytes_written` == exact UTF-8 byte size of the written file(s) (read the
     file from the drive branch: `git -C "$WORK" show <branch>:<file> | wc -c`).
   - `tool_counts` / `step_count` == the live `steps` trace; `files_changed` ==
     `len(changed_files)`.
   - `usage` tokens are present (verbatim from the response, never estimated);
     `started_at` is valid ISO-8601 and `duration_seconds` > 0.
   - `reasoning_*` / `answer_*` are char/byte lengths (no tokenizer) — a
     tool-calling model legitimately yields `answer_*` == 0 when it emits only
     reasoning + tool calls.

**Acceptance.** Every `stats` field matches ground truth from the live drive,
with `bytes_written` exact.

**Result — 2026-06-05 (validated).** Live drive `a6c5f0c1fd13` against the
reference rig (a write + a `python3 greet.py` run + finish, 3 turns) produced a
faithful block: `bytes_written` **101 — exact** match to the committed
`greet.py`; `tool_counts` `{write_file:1, run_command:1, finish:1}` mirrored the
`steps` trace; `step_count` 3 == `len(steps)`; `files_changed` 1 ==
`len(changed_files)`; `usage` `{prompt 7105, completion 309, total 7414}`
verbatim; `started_at` valid ISO-8601, `duration_seconds` 18.35. `reasoning`
487 chars/bytes (pure-ASCII CoT) with `answer` 0/0 — the honest tool-calling
shape (all output via `tool_calls`, `message.content` empty), not a bug. Row →
✅. Stats are engine-agnostic (`mock` and `vllm-openai` fill them identically,
pinned by `tests/test_e2e_mock.py`), so this audit confirms the contract the unit
suite already guards, now against a real model.

### 1. `outsource write` reliability

**Why it matters.** `explore`/`review` are read-only and validated. `write
--apply` lands a drive branch; `write --pr` opens a PR. The drive's
commit/summary can drop or misreport edits, so the result must be verified by
diff (and lint), never trusted from the summary.

**Procedure.**

1. Pick a small, well-scoped change with a clear target file.
2. `outsource write "<task>" --apply` (live backend).
3. **Verify by diff, not by the drive summary:** `git diff main...HEAD --stat`
   and inspect — confirm the target file changed, no stray files (e.g.
   `colleague-mock.md`) appeared, **and the diff is lint-clean** (run `flake8` on
   the touched file — a whole-file rewrite can drop the EOF newline or overshoot
   the line length).
4. Re-run the affected tests; confirm green.
5. Repeat 1–4 three times on different tasks.
6. Run `outsource write "<task>" --pr` once; confirm a real PR opens against the
   correct base.

**Acceptance.** 3 consecutive `write --apply` runs verified by diff + tests; one `write --pr`
opens a correct PR; the root cause of any prior "flake" is understood.

**Result — 2026-06-04 (validated).** 3 `--apply` drives (`b885fbb` tools.py,
`5bc48e7` subagents.py, `f51427e` vllm_openai.py) + 1 `--pr` drive (`221b4ce`,
opened **PR #130** against `main`), each a real docstring micro-improvement,
diff-verified.

- **Intent reliability: 4/4.** Every drive touched the right file with the right
  change on the live vLLM engine; no stray `colleague-mock.md`. `--pr` pushed +
  opened a correct PR against `main`.
- **Edit fidelity to lint: the weak spot.** 2 of 3 `--apply` outputs were
  lint-failing before cleanup — `f51427e` dropped the trailing newline (W292),
  `b885fbb` overshot 100 cols (E501). The lint gate + verify-by-diff catch these;
  a whole-file rewrite is the failure mode. **Mitigated** by a new `write.md` rule
  ("keep edits lint-clean: max line length + one trailing newline").
- **Commit subject was boilerplate.** Every write commit/PR title came out as
  `colleague: Implement the following task in this repository:` — `write.md` led
  with the preamble and `handoff._commit_subject` takes the instruction's first
  line. **Fixed** by leading `write.md` with `$ARGUMENTS` (locked by
  `tests/test_ask_colleague_skill.py`).
- **Prior "flake" evidence was confounded, not a write bug.** The rated-1 drive
  `1bcabd9095d3` is an `outsource explore` probe, misattributed via `feedback
  record last` (the `last_drive` pointer is shared across verbs). The stray
  `colleague-mock.md` files came from explicit `--engine mock` smoke drives
  (`8b8d43bd26cf` et al.); there is **no silent mock fallback** (`resolve_engine`,
  pinned by `tests/test_config.py`). The render-order bug (#63 #3) is **already
  fixed** here (single-pass `re.sub` in `ask-colleague.sh`).
  **Fixed (#132):** read-only probes (`explore`/`review`) no longer move `last`
  (the skill's `_preserve_artifact` stopped writing the pointer), so `last`
  tracks the most recent **write**; resolving `last` echoes the id + request to
  stderr, and `colleague feedback list` / `ask-colleague feedback list` surfaces
  every drive by request + grade so a drive is recoverable without trusting
  order. Locked by `tests/test_feedback*.py` + `tests/test_ask_colleague_skill.py`.

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

**Result — 2026-06-04 (validated).** Live drive `6c27147eb917` against the
reference rig delegated via the parallel `subagents` tool with
`COLLEAGUE_SUBAGENT_CONCURRENCY=2`: two children (`9eb32e45cacd`, `6a95f13eb2e7`)
ran in isolated `sub/<id>` worktrees, a sequential merge child
(`merge-d9b20b4d3896-0`) integrated both branches cleanly, the worktrees were
torn down, and `sub_results` was folded into the artifact. Pinned by the gated
`tests/test_vllm_live_subagents.py` (`COLLEAGUE_VLLM_E2E=1`,
`COLLEAGUE_SUBAGENT_CONCURRENCY=2`).

- **Delegation needs an explicit invite.** The improved `_DEFAULT_SYSTEM`
  subagents paragraph now names the parallel `subagents` tool (it previously
  described only the singular `subagent` and called delegation "sequential", so
  the live model had no signal the batch tool existed). A task that *explicitly*
  asks to "delegate as parallel subagents" reliably fires the tool. A purely
  *implicit* two-file task (drive `65ab1129dbe0`: "Make two changes: in x.py …; in
  y.py …") still did the work itself with the base five — **no spontaneous
  delegation**. So this row is ✅ for the *capability* — the machinery (tool
  choice → parallel worktrees → merge child → `sub_results` in the artifact) runs
  end-to-end against a real model — with the honest caveat that the live model
  does not yet delegate unprompted.
- **Caps + conflict-surfacing are unit-proven, not forced live.**
  `MAX_SUBAGENT_DEPTH=2` / `MAX_SUBAGENT_FANOUT=4` are enforced structurally
  (`colleague/config.py`, checked before any child work) and pinned by
  `tests/test_subagents.py` (`test_depth_cap_refuses_before_work`) and
  `tests/test_config_subagent.py`. The no-force-merge conflict path is pinned by
  `tests/test_subagents_parallel.py::TestMerge`
  (`test_conflicting_merge_surfaces_conflict`,
  `test_conflict_removes_worktree_but_RETAINS_branch`). Deterministically inducing
  two children that edit the *same lines* with a live model is unreliable, so the
  conflict checkbox rests on the unit proof rather than a flaky live trigger; the
  live drive above exercised a *clean* merge.

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

**Result — 2026-06-04 (validated).** Gated live tests
(`tests/test_vllm_live_gated_configs.py`, `COLLEAGUE_VLLM_E2E=1`) prove the
config-present gates fire in a real drive; the engine-agnostic mechanics (3b
checksum-void, 3e prompt composition) are proven deterministically
(`tests/test_gated_configs_enforcement.py`). All validation config lives in
throwaway `tmp_path` fixtures — the repo still ships none.

- **3a Approvals `run_command` — ✅ LIVE.** Drive `324819918d83`: a real
  `run_command("curl …")` was blocked by `_deny_by_policy` (Step `ok=False`,
  "on the deny list"). Drive `21dff9b0fb93`: an allowed `echo` ran (Step
  `ok=True`, `exit=0`).
- **3b Checksum-void + command-expand-refused — ✅ DETERMINISTIC**
  (engine-agnostic). An approved deny-hook fires; editing the script voids the
  approval → `HookFiring(decision="skipped")` and the tool is no longer blocked;
  a drifted command template raises `CommandError` at expand time. Pinned by
  `tests/test_gated_configs_enforcement.py`. The live model adds no signal — the
  skip is model-independent loop mechanics.
- **3c Hooks deny + rewrite — ✅ LIVE.** Drive `a30324e89aa3`: a `pre_tool` hook
  denied a real `write_file` (`HookFiring` deny + Step `ok=False`, file not
  written). Drive `23fa581fc19a`: a rewrite hook swapped the `write_file` path
  (`HookFiring` rewrite + `rewritten.txt` in `changed_files`, original gone).
- **3d Per-model hooks overlay — ✅ LIVE.** Drive `5a590ffb360f`: a deny hook
  present ONLY in `.colleague/sakamakismile-Qwen3.6-27B-Text-NVFP4-MTP/hooks.json`
  (no base `hooks.json`) fired — proving `load_hooks(repo, model=config.model)`
  loads the overlay. Precedence/isolation unit-proven by
  `tests/test_hooks_per_model.py`.
- **3e Per-model AGENTS/skills — ✅ DETERMINISTIC** (per the #123 decision;
  colleague records the composed prompt nowhere). `system_prompt_for(repo, model,
  base=_DEFAULT_SYSTEM)` — the EXACT engine path (`engine.py`, parity locked by
  `tests/test_layers_engine_parity.py`) — folds the `AGENTS.colleague.<model>.md`
  marker + skill summary into the prompt; a sibling model sees neither
  (exact-path isolation). A soft live marker drive (`f41df9a91008`) saw the model
  echo the layer's requested summary, but that is advisory only.

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

**Result — 2026-06-05 (validated).** Two gated live drives
(`tests/test_vllm_live_loop_tools.py`, `COLLEAGUE_VLLM_E2E=1`) prove the model
reaches each tool and it shells out to the real operator-installed CLI. The
**root-cause fix mirrored #122**: `_DEFAULT_SYSTEM` named `devague`/`subagent` but
never `culture`, so a "Culture tools (optional)" paragraph was added (pinned by
`tests/test_destination_loop.py::test_default_system_advertises_culture_tools`).

- **4a `culture` — ✅ LIVE.** Drive `2395f7d5d9b9`: the model called
  `culture(cli='devex', args=['--version'])` and it shelled out (`exit=0`, identity
  injected, cwd at repo root). Constrained to `--version` — zero side effects;
  `agtag` cannot post without an explicit `--repo` and the tmp repo has no remote.
- **4b `devague` — ✅ LIVE.** Drive `80cb15c5f9cd`: the model called
  `devague(move='new', …)` then `devague(move='status')`, both shelling out
  (`exit=0`). `new` wrote only a self-contained `.devague/` in the tmp repo (no
  global `~/.devague`, no network). **Bonus:** the model also declared
  `destination='users-can-export-their-dashboard-as-a-pdf'` on finish, so the
  artifact carried it (announcement was `None`) — a live confirmation on top of the
  deterministic proof.
- **DETERMINISTIC (cited, not re-proven live).** The allow-lists and the
  `confirm`/`reject`/`export` exclusions are enforced by the schema `enum` **and**
  in code, so a compliant model cannot emit a forbidden `cli`/`move` — these are
  reachable only deterministically, never live: culture allow-list/identity
  (`tests/test_culture_tools.py`, `tests/test_identity.py`); devague
  allow-list/exclusions/identity (`tests/test_devague.py`,
  `tests/test_devague_tool.py`); destination+announcement-in-artifact
  (`tests/test_destination_e2e.py`). The live drives prove the *positive* path
  (model calls the tool → it shells out); the gates are deterministic by construction.

### 5. Neighbours read-only clones live

**Evidence of the gap.** No `neighbours.json`; the feature has never run.

**Procedure.** Add `.colleague/neighbours.json` with one `{name, url}`; run a drive
that reads a neighbour file; confirm a shallow clone appears under
`.colleague/neighbours/<name>/`, is gitignored, and is cleaned up on drive finish.

**Acceptance.** Clone-on-demand + cleanup observed; empty-config default still a
no-op.

**Result — 2026-06-05 (validated).** A gated live test
(`tests/test_vllm_live_neighbours.py`, `COLLEAGUE_VLLM_E2E=1`) proves this
config-present-to-fire surface works end-to-end against a real model. The
neighbour is a hermetic local git repo (file:// URL), so the only live element is
the model performing the read.

- **Clone-on-start + read — ✅ LIVE.** Drives `711505cb4c3f` and `09d31abcf160`
  (two clean runs): with one `{name, url}` in `.colleague/neighbours.json`, the
  runtime shallow-cloned the neighbour into `.colleague/neighbours/sibling/`
  *before* the loop, and the model read a sentinel file out of it
  (`read_file(.colleague/neighbours/sibling/GREETING.txt)`, Step `ok=True`, the
  result carried the sentinel). A successful read of the sentinel proves the clone
  was present and readable mid-drive.
- **Cleanup-on-finish — ✅ LIVE.** After each drive `.colleague/neighbours/` was
  gone — `cleanup()` fires on every loop exit, before the handoff (asserted in the
  test).
- **Gitignored — ✅ LIVE.** The clone root is matched by the repo's `.gitignore`
  (`git check-ignore` exits 0) and never tracked (`git ls-files` empty), so a
  neighbour cannot leak into the drive branch commit.
- **No `_DEFAULT_SYSTEM` change needed (the honest distinction from #122/#124).**
  Neighbours is not a model-chosen tool: the clone is automatic (runtime-owned,
  all-engines rule) and the model consults it via the base `read_file` tool.
  Handing it the explicit path fired the read reliably — no prompt paragraph
  required, unlike the subagents (#122) and culture/devague (#124) gaps.
- **Empty-config no-op — ✅ DETERMINISTIC (cited, not re-proven live).** A drive
  with no `neighbours.json` never creates `.colleague/neighbours/` — purely
  model-independent loop mechanics, proven by
  `tests/test_clone_lifecycle.py::TestCleanupAtFinish::test_empty_allowlist_noop`.
  The clone/refresh/cleanup mechanics, path-traversal guards, and never-execute
  confinement are unit-proven (`tests/test_neighbours.py`,
  `tests/test_clone_lifecycle.py`). All validation config lives in throwaway
  `tmp_path` fixtures — the repo still ships no `neighbours.json`.

### 6. Telemetry end-to-end live

**Evidence of the gap.** Off by default; never run against a collector.

**Procedure.** `uv sync --extra otel`, run an OTLP collector (or point at a
file/debug exporter), then drive with telemetry on:

```bash
COLLEAGUE_OTEL_ENABLED=1 \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  colleague drive "<task>" --repo . --no-pr
```

Confirm root + per-tool + handoff spans and the metrics
`colleague.generated.chars` / `colleague.bytes_written`. Re-confirm that with the
flag off there are no spans and no SDK import (strict no-op).

**Acceptance.** Spans + metrics observed when on; verified no-op when off.

**Result — 2026-06-05 (validated).** Telemetry is **engine-agnostic** (the
all-engines rule): the spans/metrics fire identically for every backend, so the
core proof drives the full production `execute_drive` path with the `[otel]` SDK
installed and an in-memory (debug) exporter — the procedure's allowed
file/debug-exporter alternative to a wire collector. A gated live drive adds the
real-model composition stamp.

- **Full span tree + metrics — ✅ (engine-agnostic, runs in CI).**
  `tests/test_telemetry_e2e.py` drives `execute_drive` (mock backend) and captures,
  in one trace: the root `colleague.drive` span, per-tool `colleague.tool.*` spans,
  and the `colleague.handoff` span — every child parented under the drive span, and
  the handoff `committed=True`. Metrics emitted: `colleague.steps`,
  `colleague.tokens`, `colleague.generated.chars`, `colleague.bytes_written`,
  `colleague.tool.calls`, `colleague.tool.latency`, `colleague.drive.duration`. A
  second test exercises a `pre_tool` deny to emit the previously-untested
  `colleague.hook.denials`. (Before this, no test went through `execute_drive`; the
  handoff span, drive.duration, and hook.denials had no coverage at all.)
- **Live composition — ✅ LIVE.** Drives `eff14af763d4` and `02c811085cb6`
  (`tests/test_vllm_live_telemetry.py`, `COLLEAGUE_VLLM_E2E=1`) against the
  reference rig emitted the same span tree (`colleague.drive`, `colleague.tool.*`,
  and `colleague.handoff`; trace `36af5dd80d0f…`) and the headline metrics with
  **real** model usage — `colleague.tokens` from the response, `generated.chars`
  from real reasoning/answer text, `bytes_written` from a real `HELLO.txt` write.
- **Strict no-op when off — ✅ DETERMINISTIC (cited, not re-proven live).** With
  telemetry off (the default) there are no spans and the OTel SDK / `_otel` is never
  imported — even when the `[otel]` extra IS installed. Locked by
  `tests/test_zero_deps.py::test_no_third_party_imports` (loading `colleague.loop`/
  `colleague.telemetry`/`colleague.cli` introduces no third-party import) and
  `tests/test_telemetry.py::test_loop_default_telemetry_is_noop`. Config resolution
  and SDK-backed emission are unit-proven by `tests/test_telemetry.py`.
- **Honest limit.** Capture is via an in-memory/debug exporter, not a wire OTLP
  collector; OTLP-over-HTTP shipping is the SDK's concern (exporter construction is
  unit-proven, `tests/test_telemetry.py`). All telemetry config lives in env/
  fixtures — the repo ships telemetry off by default and no collector config.

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

**Result — 2026-06-05 (validated).** Two gated live drives
(`tests/test_vllm_live_context_budget.py`, `COLLEAGUE_VLLM_E2E=1`) exercise both
degradation paths against the reference rig by spying on the engine's HTTP seam
(`vllm_openai._post_json`) — observe for the proactive path, inject for the
reactive one — without leaving the production `execute_drive` path.

- **Proactive windowing — ✅ LIVE.** Drives `36b022abc7f0` / `1e530fa42dd7`: a
  small `context_budget=1000` + a 4-file *chain* task (each file names the next, so
  the model must take sequential, content-pulling turns — `run_command` can't
  shortcut it and the reads can't be batched). After two chained reads the history
  blew past the budget, so every later real chat request was windowed to
  `[system, user, <placeholder>, assistant, tool]` — the placeholder
  (`context._PLACEHOLDER_TEXT`) landed in actual model requests and the message
  count stayed pinned at 5 across four reads (`[2, 5, 5, 5, 5]`) instead of growing.
  The drive finished OK — graceful degradation, no crash.
- **Reactive trim+retry → real recovery — ✅ LIVE (induced).** Drives
  `0323db53b1dd` / `242ee473debd`: the procedure's "induced overflow" — the first
  chat call raises a real-shaped overflow (matches `is_context_overflow`), the loop
  shrinks the budget and retries, and the retry **recovers against the real model**
  (3 chat calls: 1 raised + 2 served; `write_file` then `finish`, status OK).
- **Bounded termination + non-recoverable partial — ✅ DETERMINISTIC (cited).** The
  retry cap (`_MAX_OVERFLOW_RETRIES`) and the preserved partial on a never-recovering
  overflow are engine-agnostic loop mechanics, proven by
  `tests/test_loop_degradation.py` (`test_non_recoverable_overflow_preserves_partial`,
  retry-bound) and `tests/test_e2e_degradation.py` (full vLLM-engine path, partial
  JSON to stdout). Windowing primitives + overflow-phrase detection:
  `tests/test_context_window.py`.
- **Honest limit.** A real server-side 262k overflow is not deliberately induced
  (proactive windowing trims below the budget first, so it would be unreliable and
  costly to force); the overflow is injected at the HTTP seam — exactly the
  procedure's "induced overflow" — with the *recovery* served by the real model.
  No `COLLEAGUE_CONTEXT_BUDGET` ships in the repo; the budget is set per-test.

With this row validated, every feature in the [matrix](#validation-matrix) — and
the tracking epic [#128](https://github.com/agentculture/colleague/issues/128) — is
now validated live (or live + cited-deterministic where the model adds no signal).

## Mode profiles / backpressure / rig budget (spec 2026-07-01, issues #254–#259)

- **Validated (mock + deterministic).** `tests/test_mode_e2e_validation.py` runs the
  REAL mock-engine pipeline end-to-end with zero env tuning (`--mode explore` →
  artifact carries `mode`, run completes inside the profile); the seam-level proofs
  are `tests/test_work_mode_wiring.py` (profile → resolved config, precedence),
  `tests/test_loop_backpressure_integration.py` (fake-clock latency → shrink +
  throttle + advisory), `tests/test_rig.py` (cross-process slot semantics incl. a
  live `execute_work` hold/release), and `tests/test_loop_acceptance_selfcheck.py`
  (goal block + advisory self-check).
- **VALIDATED live — `bf6cf2d` · 2026-07-02.** The rig came back with tool
  calling (the 27B serves and the `doctor --probe` tool-calling round-trip
  passes), and `COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live_mode.py`
  **PASSED** (`test_mode_explore_live`, 30s): a live `--mode explore` run
  completed inside its profile. The profile *numbers* remain conservative
  defaults pending broader live tuning (plan risk r1 — tuning, not validity).

## Dual-model deepthink escalation (spec 2026-07-01, plan task t10)

- **Validated (mock + deterministic).** The config resolution
  (`tests/test_deepthink_config.py`), the one-shot windowed/degrading
  `make_complete` seam (`tests/test_deepthink.py`), the `TaskResult.deepthink`
  block shape (`tests/test_contract_deepthink.py`), the loop tool + role
  curation (`tests/test_deepthink_tool.py`), the loop wiring + all-engines
  forwarding + acceptance-selfcheck escalation (`tests/test_loop_deepthink.py`),
  the plan-mode proposal routing (`tests/test_plan_deepthink.py`), and the
  test-integrity reviewer default (`tests/test_deepthink_reviewer_default.py`)
  all pass against the `mock` engine and fixtures: a no-deepthink-config run is
  byte-identical to today, and a dual-config run against `mock` records a
  degraded no-op (the lint fix-turn precedent) instead of failing.
- **VALIDATED live — `bf6cf2d` · 2026-07-02.** The rig now serves multiple
  models on one endpoint, so the dual pair ran as main =
  `sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP` (tool-calling verified) +
  deepthink = `coolthor/gemma-4-12B-it-NVFP4A16` (tools-off bare completion —
  a deepthink target needs no tool parser). `COLLEAGUE_DUAL_E2E=1
  COLLEAGUE_DEEPTHINK_MODEL=coolthor/gemma-4-12B-it-NVFP4A16 uv run pytest
  tests/test_dual_live.py` — **both tests PASSED**:
  - *deepthink tool:* the main model escalated the judgment question —
    `read_file → deepthink → finish`, `DeepthinkCall(point='tool',
    tokens=825, duration=36.4s, degraded=False)` on the artifact.
  - *acceptance self-check:* `DeepthinkCall(point='acceptance_selfcheck',
    tokens=246, duration=2.0s, degraded=False)`.
  - *degrade path (bonus, proven live):* pointing the deepthink target at the
    endpoint's stale-listed `nvidia/Qwen3-14B-NVFP4` (models-list entry whose
    completions 404 — evidence commented on
    [#66](https://github.com/agentculture/colleague/issues/66)) produced a
    clean OK run with `DeepthinkCall(degraded=True, duration=0.019s)` — the
    dual run never fails because deepthink is unreachable, exactly as spec'd.
  Two test-infra fixes were needed to make the proof runnable at all,
  recorded honestly: the autouse conftest env-scrub hid the deepthink target
  from the gate (fixed with an import-time env snapshot), and the judgment
  task needed the #122-style explicit invite (the 27B happily answers without
  escalating; the row proves the escalation *plumbing*, not spontaneity).
  Residuals: the intended role-optimal pairing (wide-window main + stronger
  reasoner deepthink) awaits serving both with tool parsers, and the
  wall-clock/quality benchmark (`scripts/bench_dual.py`) has not been run —
  the mechanism rows above are what this validates.

## Substantial decomposed write (best-colleague arc h9, plan task t9)

The h9 protocol: hand the loop a genuinely multi-part assignment (a 3-module
Python package + per-module tests, explicit instruction to DELEGATE via
`subagents`), run it live, and record the outcome honestly — a model that
cannot land it decomposed is recorded as a model limit, never claimed solved.

- **Pre-fix run `4c6a96107269` (CRASH — real harness bug caught live).** The
  27B delegated correctly (4 folded sub_results) but at step 12 emitted a
  tool call with empty arguments; the bare `arguments["path"]` `KeyError`
  escaped the dispatch (which caught only `ToolError`) and aborted the whole
  run as `engine 'vllm-openai' failed: 'path'`. Fixed in `22adbb3` (two
  layers: per-tool `_require` validation + argument-shaped-error conversion
  at the dispatch boundary), pinned by `tests/test_tool_arg_errors.py`.
- **Post-fix run `55859cb1d605` (survived — honest `incomplete`, 460s).** The
  identical task re-run: the parent spawned 3 children + merge
  (`COLLEAGUE_SUBAGENT_CONCURRENCY=2`); malformed/err steps cost one step
  each and the run kept going (the fix, proven live). Child 0 (tokenizer)
  delivered module+tests; child 1 (counter) delivered module+tests but ALSO
  re-wrote `tokenizer.py`/`__init__.py` as its own dependency stubs; child 2
  (report) stalled emitting literal tool-markup and wrote nothing. The merge
  child integrated child 0, no-op'd child 2, and **surfaced (did not
  force-merge) the child-1 conflict** — exactly the designed behavior. The
  parent ran out of budget resolving it; forced synthesis fired but its own
  output was literal markup, so the terminal summary is honest-but-garbled.
  The delivered half is real: **13/13 tests pass** on the work branch
  (`python3 -m pytest tests/` on `colleague/55859cb1d605-…`).
- **Verdict.** Harness: VALIDATED — the crash class is fixed live; isolation,
  fan-out, conflict-surfacing, and honest `incomplete` all behaved. Model:
  the served 27B under concurrent self-load still cannot land a 3-way
  decomposed write end-to-end (markup-emission stalls + duplicate-dependency
  conflicts) — recorded per h9 as a model limit, not claimed solved.
- **Follow-ups filed from this run:**
  [#264](https://github.com/agentculture/colleague/issues/264) — forced-synthesis output can itself be
  literal markup (the t5 re-parse targets a *finish* shape, not synthesis
  text); [#265](https://github.com/agentculture/colleague/issues/265) — the
  WIP-on-stop sweep commits `.colleague/worktrees/` lock files and
  `__pycache__` residue onto the work branch.

## Livecheck closing regression (best-colleague arc R7, 2026-07-02)

`colleague livecheck --repo . --json` ran as the arc's closing regression
(the verb's own first full live outing). Results, recorded honestly:

- **Passed live in the battery:** loop tools, live mode, neighbours, and the
  dual-model proof (4 rows).
- **Skipped by the runner:** the basic-drive, context-budget, and
  gated-configs proofs hit livecheck's fixed 120s per-proof cap — too tight
  for full drives on the reference 27B (each passed historically; the cap is
  a v1 constant in `colleague/livecheck.py`; tunable follow-up filed as
  [#266](https://github.com/agentculture/colleague/issues/266)).
- **Failed in the battery, passed on re-run — a serving-side window, proven
  byte-identical:** the telemetry and subagents proofs failed during a window
  where the endpoint emitted malformed literal tool-markup instead of parsed
  tool calls. Diagnosis: `COLLEAGUE_DUMP_REQUEST=1` captured the exact
  outgoing payload; a byte-for-byte identical request (same system prompt,
  same 13 tool schemas, `temperature: 0.0` greedy decoding) failed 3/3 in one
  window and passed 3/3 (curl) + end-to-end (CLI) minutes later. Identical
  greedy requests giving different outputs over time is endpoint-side
  nondeterminism (speculative-decoding/batching state on the MTP-served 27B —
  the #66 family), not a harness or test bug. Both proofs **passed** on
  re-run (`2 passed in 699.70s`). This is the same markup-emission pathology
  that limited the h9 substantial-write run — now isolated to the serving
  layer with wire-level evidence.
