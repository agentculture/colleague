# adopt-from-qwen-code — the harness mechanics ported from Qwen Code

**Status:** built on the adopt-from-qwen-code arc (spec
`docs/specs/2026-08-27-adopt-from-qwen-code.md`, plan
`docs/plans/2026-08-27-adopt-from-qwen-code.md`, 2026-08-27). The **sixth
recorded v0 → v1 convention change** (see `CLAUDE.md` § v1 scope): threads
extend to ONE bounded read-only tool-batch pool. Provenance ledger:
[`docs/adopted-from.md`](../adopted-from.md); attribution: [`NOTICE`](../../NOTICE).

Three readers take three things from this page. **Operators running colleague
against a local vLLM rig** take the mechanisms and their knobs (§ What shipped,
§ Knobs) — every one is a Python re-implementation with an off-switch that is
byte-identical to the pre-arc harness. **Agents that dispatch through
`ask-colleague`** take the changed tool surface (`grep_search`, `glob`, paged
`read_file`, the prior-read rule on `edit_file`, batched read-only calls) and
the honest limits below. **Mesh peers reading colleague's provenance ledger**
take the credit trail: which Qwen Code / Gemini CLI source each mechanism was
read from, and why no third project is credited (§ Credit).

## Before → after

**Before** (spec claims c3/c26, measured 2026-08-22/23): colleague and Qwen Code
drove the SAME served model on the SAME rig (`unsloth/Qwen3.8-27B-NVFP4` @
`localhost:8001`), yet Qwen Code's own usage records —
`~/.qwen/usage_record.jsonl, project colleague: 109 requests, 18.4M input
tokens, 9577s model latency` — belong to a session that shipped PR #428,
issue #429, Qodo fixes and a conflict resolution, while colleague ran with no
`max_tokens` (generation bounded only by `max_model_len`), a blocking
`/tokenize` POST every turn, strictly sequential tools, no search tool,
whole-file reads cut at 68K chars, exact-only edits and unrecoverable
truncation. The gap was turns-to-deliverable and reliability, not model
latency (Qwen Code averaged ~88 s and ~169K input tokens per request there).

**Why the lever order** (assumption c23): Qwen Code's own RT design doc,
`docs/design/rt-optimization/rt-optimization-design.md` §1.2 (2026), measures
its agent loop as "LLM 调用占 78%，工具执行 19%，框架 3%" — LLM calls 78 %,
tool execution 19 %, framework 3 % — and concludes the levers are fewer LLM
calls and shorter calls. Hence: bounded generation > fewer round trips per step
> cheaper context > prompt text.

**After** (c25): every completion carries a window-clamped `max_tokens`; no
`/tokenize` round-trip precedes a turn; read-only tool calls in one turn run as
a parallel batch; the model can grep/glob/page files instead of shelling out; a
whitespace-drifted edit lands on the first try; and `NOTICE` +
`docs/adopted-from.md` credit Qwen Code and Gemini CLI for every ported
mechanism. Which clauses are proven live and which are still pending is stated
in § Measurement and § Honest limits — nothing here is claimed on a hunch.

## What shipped

Each mechanism is a NEW standalone stdlib module whose docstring carries an
`adapted-from: qwen-code <path:lines>` marker (copied prose additionally keeps
the upstream copyright lines, Apache-2.0 §4(c)); the pre-existing modules were
edited net-zero under the file-length ratchet (`tests/test_file_length_ratchet.py`).

- **Output-token clamp (c4/c48, `colleague/outputclamp.py` +
  `colleague/turnbudget.py`).** `max_tokens = min(ceiling, window − prompt −
  margin)`, margin `max(10 000, 5 %·window)`, floor 4 000; acting seats ceiling
  64 000, `deepthink`/`design` seats 131 072 (`COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN`);
  a `finish_reason=length` cut retries ONCE at the ceiling, then the existing
  truncated-turn handling. Window precedence: lobes-advertised `context` →
  the run-start `/tokenize` `max_model_len` → `COLLEAGUE_CONTEXT_BUDGET`
  (`resolve_window`). adapted-from `core/tokenLimits.ts:36-77`.
- **One `/tokenize` per run, not per turn (c5, `colleague/tokenestimate.py`).**
  The first count is exact and learns `max_model_len`; every later count is an
  estimate anchored on the last `usage.prompt_tokens` + chars/4 (a conservative
  lower bound on room — compaction over-triggers, never skips).
  `COLLEAGUE_EXACT_TOKENS=1` restores the per-turn call. The artifact's token
  fields still come from `usage` only. adapted-from `services/tokenEstimation.ts`.
- **Batched tool execution (c6/c35/c36, `colleague/toolbatch.py` +
  `colleague/toolbatch_loop.py`).** `partition_by_concurrency_safety` merges
  consecutive read-only calls (`read_file`, `list_dir`, `grep_search`, `glob`,
  `view_media`, memory recall, and a `run_command` the fail-closed allow-list
  checker `is_shell_command_read_only` accepts) into one parallel batch under
  `COLLEAGUE_TOOL_CONCURRENCY` (default 10); mutating calls stay sequential.
  The lifecycle is split: pre_tool hook → TAE verdict → policy verdict on the
  MAIN thread in request order before the pool; only `executor.execute` runs
  in the pool; step indices, messages, post_tool hooks, progress and flight
  records land on the main thread in request order after the join (an AST
  guard pins that the pool target references no `ctx`). One call erroring
  never cancels siblings. adapted-from `core/coreToolScheduler.ts:1284-1348,
  4208-4293`, `tools/tools.ts:1111`, `utils/shellReadOnlyChecker.ts`.
- **`grep_search` + `glob` (c7, `colleague/search_tools.py` +
  `colleague/search_schemas.py`).** ripgrep when on PATH, a pure-stdlib walker
  otherwise — identical output, `path:line: text`, repo-confined through the
  same `resolve()` check as `read_file` (neighbour clones readable, never
  written); `glob` is mtime-sorted. Offered to every read-capable role;
  `COLLEAGUE_TOOLS_LEGACY=1` hides both. adapted-from `tools/ripGrep.ts`,
  `tools/grep.ts`, `tools/glob.ts`, `config.ts:9280-9315`.
- **Paged, grounded `read_file` (c8, `colleague/readpage.py`).** `offset`/`limit`
  with ORIGINAL line numbers (#240's `cat -n` grounding kept), defaults 1 000
  lines / 25 000 chars, a truncated read ends with exactly `Read lines X-Y of N`.
  adapted-from `tools/read-file.ts:102-158`, `utils/fileUtils.ts:1440-1560`.
- **Tolerant edit match + prior-read rule (c9/c41, `colleague/editmatch.py` +
  `colleague/editgate.py`).** Exact match first, then a deterministic relaxed
  tier (smart quotes → ASCII, per-line whitespace trim, CRLF) that returns the
  canonical on-disk slice and never rewrites `new_string`; relaxed ambiguity
  errors name the count. `edit_file` on a file (or span) not read in this work
  item is refused with a message that says how to recover
  (`COLLEAGUE_PRIOR_READ=0` disables); the read set is per work item and never
  survives `work --continue` — the continuation seed says so up front. NO LLM
  repair anywhere (qwen-code deleted Gemini CLI's `ensureCorrectEdit`).
  adapted-from `utils/editHelper.ts:313-380`, `tools/priorReadEnforcement.ts`.
- **Head+tail truncation with spill-to-disk (c10/c50, `colleague/truncation.py`).**
  25 000 chars / 1 000 lines per tool, 30 000 for `run_command`; the full
  output is written to `<repo>/.colleague/tool-output/<sha256>.txt` (mode
  0600, 500 MB session cap) and its path is named so the model can page it.
  `COLLEAGUE_MAX_OUTPUT_CHARS` is a CEILING over the per-tool defaults (decision
  c50); `colleague clean` reaps the spill dir. adapted-from
  `tools/truncation.ts:22,200-296`, `tools/shell.ts:91-112`.
- **Rule-based microcompaction (c11, `colleague/microcompact.py` +
  `colleague/turnbudget.py`).** At ≥ 0.85 of the budget, tool results older than
  the most recent 10 are replaced by a one-line marker naming the tool and
  path (so the model knows to re-read); every assistant message and
  `tool_call` id stays paired; it runs BEFORE the fill-line offer, which fires
  only if still over the line; no model call. Blanking counts land on the
  artifact; with agents armed each pass appends an `evidence` ledger event.
  adapted-from `services/microcompaction/microcompact.ts:14,40-64`,
  `services/chatCompressionService.ts:109-124`.
- **Stream guards (c12, `colleague/streamguards.py`).** `COLLEAGUE_STREAM_IDLE_TIMEOUT`
  (240 s) and `COLLEAGUE_STREAM_MAX_LIFETIME` (1800 s, raised from 900 s after
  the purpose-tools-get-chosen wave-1 runs were cut mid-build) beside the request
  timeout; 0 disables; a trip surfaces as the existing `TurnStalled` path with
  the guard named on `TaskResult.warnings`; stallguard's 6×-mean scaling is
  retired for the fixed floor. adapted-from
  `openaiContentGenerator/constants.ts:1-68`, `pipeline.ts:412-530`.
- **Loop guards (c20, `colleague/loopguards.py`).** 5 consecutive identical
  tool calls (name + arguments) or 100 calls in one turn halt the run with a
  named warning and drop the pending calls — only the always-on tier; qwen-code's
  heuristic tier (off upstream) is not ported. adapted-from
  `services/loopDetectionService.ts:35,140`, `core/client.ts:3717`.
- **Prompt text (c14/c47, `colleague/prompttext.py`).** `_DEFAULT_SYSTEM` adopts
  the Core Mandates / Using Your Tools / Executing actions with care / Final
  Reminder structure with per-model tool-call example families
  (`general` / `qwen-coder` / `qwen-vl`; no `gemma4` family — the
  qwen-direct-no-gemma guard forbids the literal) and a headless variant;
  colleague's own Destination/Purpose-tools/Culture/Test-integrity sections stay
  (the `SUBAGENTS` section was replaced by `PURPOSE_TOOLS` in the
  `purpose-tools-get-chosen` arc — 174 words → 165 — so the default prompt
  names the six tools the acting seat actually holds and no longer names
  `subagent`/`subagents`; the section still says "never delegate just to
  delegate" and carries no encouragement to delegate).
  `COLLEAGUE_PROMPT_VARIANT` unset or `v1` (the default since the measurement) is the pre-arc text byte-for-byte; `qwen` opts into the adopted text. The marker
  keeps both copyright holders. adapted-from `core/prompts.ts:278-440,
  1131-1171`.
- **Observability (c43, `colleague/oilcheck/harness.py`, `colleague/harness_cli.py`,
  `colleague/runcounts.py`).** `doctor` gains informational `harness_*` rows
  (stream guards, tool concurrency, ripgrep, associate state); `config show`
  prints the per-seat `max_tokens` ceilings and the window source; `WorkStats`
  carries an omit-when-zero `counts` block (`batches_run`,
  `calls_parallelised`, `results_blanked`, `outputs_spilled`, `guard_trips`).
- **Reversibility (c44, `tests/test_knobs_byte_identical.py`).** Every mechanism
  has one off-knob (§ Knobs); with all off, request payload keys, offered tool
  NAMES, the system prompt and the Step sequence match fixtures recorded from
  `main @ ff7331e`; flipping any one knob on changes the diff — a dead knob is
  caught.

## The associate seat (c32/c33/c37/c49)

`associate` is a fourth consumed lobes role — the operator's "faster qwen for
non-coding tasks" (Nemotron 3.5 Lightning on Orin, proxied by spark's gateway;
measured 89.7 tok/s on a 256-token decode, 2026-08-27). It is **opt-in** like
senses/muse: `COLLEAGUE_ASSOCIATE_MODEL=lobes` (or an explicit id) resolves a
second `EngineConfig` (`colleague/associate_config.py`, `colleague/associate.py`);
unarmed, `config show` prints `not consumed (opt-in): associate → …`. On the
wire the seat is addressed **by role name** — `{"model": "associate"}` is the
only route through the proxy (the raw model id and `worker` return
`role_infeasible`, probed 2026-08-27) — and the artifact records the SERVED
model from the reply; a gateway that rejects the role name falls back once to
the model id, then propagates. It streams exactly like cortex (decision c52).
The consumers are one enumerated tuple, `ASSOCIATE_SEATS = ("scout",
"compact", "synthesis", "digest", "distill")` in `colleague/associate_seats.py`:
the read-only `scout` subagent role (tool surface ⊆ the parent's read-only
set; a repo-mutating reply is refused and recorded), the fill-line compact
author, forced synthesis, the digest seat (enumerated, no consumer yet), and
the rung-2 distill author rung (after deepthink/muse, before the cortex
floor). Code-authoring seats never route to associate. **Never a per-turn
choice.** The recorded reading of the fallback (deviation d16): with the knob
unset every seat is **byte-identical to main** (the arc's standing invariant
wins over c33's "absent = cortex@low"); cortex@low fires only when the seat is
**armed but unreachable**, with one `TaskResult.warnings` entry — the plan's
cortex@low-when-absent is realised only on the new `scout` role
(`ROLE_TABLE["scout"] = "off"` — t19: a read-only scout with thinking OFF, the
same rung the associate seat row carries; `docs/features/thinking-effort.md`).

## Measurement

Pre-registered before any arm ran — `docs/live-testing.md` row 41 (the brief:
the `game-benchmark` command template + one small repo task, n ≥ 3 per brief;
arms: main / branch associate-unarmed / branch associate-armed / a temperature
arm T=0.0 vs the served default (decision c51); rig `localhost:8001`
`unsloth/Qwen3.8-27B-NVFP4`; bar: wall-clock ≤ 0.7×, model turns ≤ 0.8×,
success ≥ main). `scripts/compare_arms.py` computes the ratios from artifact
`duration_seconds` / `model_turns` and exits 1 on a miss — never from prose.

**Before-state arm (row 42, main @ `ff7331e`, 2026-08-27, GPU otherwise idle):**
game-benchmark `15bda418a881` ok 817 s / 15 turns, `602a40e5a2ee` ok 581 s /
13 turns, `184e9f98957e` **STALLED at step 5/40** — the flight heartbeat went
stale for 17 min at GPU 7 %, vLLM's own `/metrics` read `num_requests_running
0, num_requests_waiting 0` while the client waited, and the gateway log carried
`JSONDecodeError`/`BrokenPipe` tracebacks in the same window; SIGTERM'd and
scored as a failure (the #415 shape the branch's stream-idle guard cuts at
240 s). Repo task: `ed07bc33333f` 33 s / 3 turns, `621d22eb6469` 26 s / 3 turns,
`c8b1de2bf765` 32 s / 4 turns, all ok.

**Dogfood through the updated harness (same rig, 2026-08-27):**

- explore-1 `41bb8b0a9cf5` @ spec `b70d193`, 19:06 — ok, **368 s, 3 model
  turns, 15 steps**: one `grep_search`, then ONE turn with 13 paged `read_file`
  calls executed as a single parallel batch, then `finish`; it found all 13
  adapted-from modules. On main the same survey costs ~15 sequential turns.
- ledger-1 `5e097e2aabf7` @ spec `b70d193`, 19:12 — ok, **479 s, 9 model turns,
  23 steps**: `grep_search`(1), `read_file`(16, paged, batched), `edit_file`(4,
  through the prior-read gate), `run_tests`(1) green; only `docs/adopted-from.md`
  changed — the ledger rows on this branch were written by colleague itself.

### Results

Measured 2026-08-27/28 on this rig (Qwen3.8-27B @ `localhost:8001`, GPU
otherwise idle, `COLLEAGUE_TIMEOUT=300`), `scripts/compare_arms.py` over the
artifact ids in `docs/live-testing.md` rows 42–46. Bar (c28): ≤ 0.7× wall-clock
**and** ≤ 0.8× model turns vs `main @ ff7331e`.

| arm | game-benchmark | wall / turns vs main | repo task | wall / turns vs main | finished |
|---|---|---|---|---|---|
| main | 699 s / 14 (n=2) | — | 30 s / 3.3 | — | 2/3 (1 gateway stall, 5,400 s floor) |
| branch, all mechanics, adopted prompt | 1604 s / 19.3 | **2.30× / 1.38×** | 52 s / 5.3 | 1.70× / 1.60× | 3/3 |
| branch + `COLLEAGUE_PROMPT_VARIANT=v1` | 769 s / 15 | **1.10× / 1.07×** | 36 s / 3.7 | 1.18× / 1.10× | 2/3 (1 cut by the 900 s guard) |
| branch + associate armed | 1367 s / 26 | 1.96× / 1.86× | 38 s / 4.0 | 1.25× / 1.20× | 3/3 (associate never called) |
| branch + temperature 0.6 | 1029 s / 12 (n=1) | 1.47× / 0.86× | 38 s / 3.7 | 1.26× / 1.10× | 1/3 (2 gateway hangs) |

**Every arm misses the bar.** Stated plainly, per h21/c28 (revert-or-flag, never
keep silently):

- The **adopted prompt text (t8) is the cost**: on the same code, reverting only
  the prompt moves the game brief from 2.30× to 1.10× and the repo brief from
  1.70× to 1.18×. The artifacts show ~3× the reasoning per turn (99–101k vs
  24–37k reasoning chars per run) and 2–3 extra `grep_search`/`glob`
  verification turns on a fully specified task. **Decision:** the adopted text
  is now **opt-in** (`COLLEAGUE_PROMPT_VARIANT=qwen`); the default is the
  pre-arc `v1` text. Re-adopt per section under measurement — #437.
- The **mechanics are at parity, not faster** (1.10× / 1.07× with the v1 prompt,
  inside main's own 581–817 s spread) — and **more reliable**: branch game runs
  finished 8/9 vs main's 2/3, and the stream-lifetime guard cut two gateway hangs
  at 900 s where main sat 5,400 s. Batches and search tools pay on read-heavy work
  (a 13-file survey in 3 turns vs ~15 — dogfood explore-1), not on a brief that
  writes one file per turn. They stay on.
- **Associate** was never called by the armed arm: cortex spawned no scout
  (#435) and the throwaway repo has no eidetic store, so the distill seat never
  fired. Its evidence is the direct seat runs (survey 17 s / digest 9 s with
  reasoning off; 25 s / 61 s at `low`) — #439.
- **Temperature** is underpowered (the gateway ate two of three game runs); the
  one run had 0.86× turns — rerun after #438.
- The **gateway stall** (vLLM idle while the client waits) hit 5 of 15 game runs
  and is the rig's dominant failure: colleague now bounds most of them (900 s) but
  two escaped through the blocking-fallback path — #438, lobes-cli#220.

Anchor: #440. The levers that move wall-clock on this model are **prompt
wording and thinking effort** (#421), not the ported mechanics.

## Honest limits

- **Delegation is never chosen by the model on these briefs.** Every measured run so far (main and branch game-benchmark arms, the three dogfood runs) shows zero `subagent`/`subagents` calls and no `sub-<id>` worktrees — cortex did all the work itself even with delegation on the offered surface. So the associate arm exercises associate only where the *harness* routes to it (the rung-2 distill seat; compact/synthesis when a run crosses the fill-line), not the scout child. Recorded, not forced (operator, 2026-08-27): the intended shape is cortex **handing over** scoped tasks to scouts/workers, **reviewing** what comes back and **collecting** the results — how much prompt guidance or role shaping that needs is a follow-up to adjust against these numbers.
  - **Follow-up, now measured (2026-08-30, `purpose-tools-get-chosen`, `docs/live-testing.md` rows 51–58).** The follow-up above ran as a pre-registered 21-run matrix and the answer is: **prompt guidance did not move it, and neither did the tool surface.** Three prose rungs delivered as operator role overlays gave 0/3 delegating runs each on the small decomposable brief (wall/turns vs baseline 0.560/0.826, 0.908/0.913, 0.866/0.783), and restoring the raw `subagent`/`subagents` pair to the acting seat also gave 0/3 (0.522/0.783) — indeed **no `subagent`/`subagents` call occurred anywhere in the 21 runs**, so the sentence above extends unchanged to the current tip. What did move delegation was **task shape**: 0 of 15 small-brief runs versus 5 of 6 large-surface runs, every one of them a typed `code_survey` call. The mechanism is that cortex substitutes the parallel read-only tool batch (`batches_run` 1–2, `calls_parallelised` 3–7 on the small brief) for delegation, and prefers that cheaper form until the surface is genuinely too large. Task success was **equal** either way: 5/5 `ok` delegating, 16/16 `ok` non-delegating. Two limits: the small-brief result is a delegation **floor**, not a null (all five small-brief arms sat at exactly zero, so the brief cannot detect a prose effect), and the one arm that did meet the promotion numbers is **confounded** (no P0 control on the large-surface brief) and was not promoted. The imperative prose tested here lives only in staged overlays under `docs/live-testing/overlays/`; **no encouragement was added to the shipped prompt**.
- **The c28 ratios are not yet measured** — every after-state clause about
  fewer turns / less wall-clock rests on the two dogfood runs above until t24
  lands its rows.
- **Arm 3 (associate armed) is blocked until the proxied seat is routable
  end-to-end**; the spark advert currently says `ready: false` and claims a
  1 048 576 context (Orin's own advert says 128 000 — the origin's number wins).
- **Under `thought_action_evaluation`, batches serialise behind the per-boundary
  evaluator call** — TAE users may see no gain from batching (park v7).
- **ripgrep is absent from this machine's default PATH** — the stdlib walker
  runs; parity was proven with a real `rg 14.1.1`, speed on large repos is
  unmeasured (park v8).
- **`read_file`'s `offset`/`limit` schema is additive with no off-knob** — the
  byte-identical suite compares tool NAMES, payload keys, prompt and steps, not
  every parameter shape.
- **`loop._DEFAULT_SYSTEM` is built once at import time** — `COLLEAGUE_PROMPT_VARIANT`
  is read when the module loads, not per call.
- **Plan mode's raw `SCHEMAS` ignores `COLLEAGUE_TOOLS_LEGACY`** — the knob hides
  the search tools on the curated `work` surface and refuses at dispatch; the
  static full list handed to `complete(tools=None)` is unchanged.
- **The `digest` seat is enumerated but has no consumer** — lint/affected-tests
  make no model call today.
- **The prior-read rule gates `edit_file` only** — `write_file` over an existing
  unread file is not refused (gating it broke the mock engine's deterministic
  rerun, i.e. the all-engines contract).
- **A mid-turn stop is honoured between batches** — up to the slowest in-flight
  tool's own timeout (`run_command` 300 s); a single-batch turn stops at the
  turn boundary as before.
- **The batch read-only checker decides parallelism only, never permission** —
  the policy gate still gates every command
  ([approval-gate.md](approval-gate.md)).
- The gateway hang recorded on row 42 is a **lobes-cli issue candidate** (a
  proxied SSE stream dropped on a JSON decode error without closing the client
  connection); colleague's guard is the mitigation, not the fix.

## Knobs

> This section is task t22's deliverable only (the reversibility pinning
> suite, `tests/test_knobs_byte_identical.py` + `tests/fixtures/main_baseline/`).
> Every other section of this doc (Audience, Before → After, Honest limits,
> the provenance ledger cross-links, …) is task t23's — do not add them here.

Every mechanism this arc ports from Qwen Code carries an env knob read
directly from `os.environ` (never through `colleague.config`'s
resolve-once pipeline, so a value change takes effect on the very next call,
same as every other knob this table names). Eleven of the knobs below are
**off-switches**: set to the value in the *Off value* column, the mechanism
is inert and the module's own docstring states (and
`tests/test_knobs_byte_identical.py` proves, for the ones with a
wire-visible effect) that behavior is byte-identical to `main` before this
arc landed. The remaining knobs in this table are **value overrides** — they
have no single off-state because they tune an already-active mechanism (a
budget, a ceiling, a style hint); each is still read somewhere in
`colleague/` per this table (`test_knobs_byte_identical.py::test_every_table_knob_is_read_in_colleague`) and its literal was introduced by one
of the ported modules per
`test_knobs_byte_identical.py::test_every_introduced_literal_is_in_the_table`.

One exception is called out in place rather than glossed over:
`COLLEAGUE_PRIOR_READ=0` disables the prior-read rule entirely, so the
*outcome* (an unread edit proceeds) matches `main` — but `main` never had a
refusal message to reproduce, so there is no byte-identical *message* to
pin for the on-state; see the row's note.

| Knob | Off value | Mechanism | Module |
| --- | --- | --- | --- |
| `COLLEAGUE_MAX_OUTPUT_TOKENS` | `0` | Output-token clamp: `0` is the kill-switch — `max_tokens` is omitted from the `/chat/completions` payload entirely, byte-identical to the pre-arc body. | `colleague/turnbudget.py` (`colleague/outputclamp.py`) |
| `COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN` | n/a — value override | The output-ceiling override for the two high-ceiling seats (`deepthink`, `design`) once the clamp is armed; no off-state of its own (it is inert whenever `COLLEAGUE_MAX_OUTPUT_TOKENS=0`). | `colleague/outputclamp.py` |
| `COLLEAGUE_EXACT_TOKENS` | `1` | Restores the pre-arc per-turn `/tokenize` round-trip (one exact count per turn) instead of the run-start-once + `usage`-anchored estimate. | `colleague/tokenestimate.py` |
| `COLLEAGUE_TOOL_CONCURRENCY` | `1` | Sequential (width-1) tool execution — a batch of size 1 (or width 1) takes the pre-arc `run_one` path untouched. | `colleague/toolbatch_loop.py` |
| `COLLEAGUE_WEB_CONCURRENCY` | n/a — value override, default `3` | In-flight cap on `web` calls whose `verb` is a `page *` verb inside a parallel batch (a `threading.Semaphore` in `run_batch`, the SAME pool — never a second one); `search` is bounded only by `COLLEAGUE_TOOL_CONCURRENCY`, and this knob is inert whenever that width is `1` (t4, plan `web-scout-associate`). | `colleague/toolbatch.py` |
| `COLLEAGUE_MICROCOMPACT` | `0` | Disables the rule-based microcompaction floor (blanking old tool results ahead of the fill-line offer); today's windowing-only path is unchanged. | `colleague/turnbudget.py` |
| `COLLEAGUE_STREAM_IDLE_TIMEOUT` | `0` | Disables the stream idle-timeout watchdog. Together with `COLLEAGUE_STREAM_MAX_LIFETIME=0`, `StreamGuards.from_env()` returns `None` and the SSE reader is byte-identical to the unguarded one. | `colleague/streamguards.py` |
| `COLLEAGUE_STREAM_MAX_LIFETIME` | `0` | Disables the stream max-lifetime watchdog (see the row above — both must be `0` together for a fully unguarded stream). | `colleague/streamguards.py` |
| `COLLEAGUE_TOOL_SPILL` | `0` | Disables spill-to-disk on an over-budget tool result: head+tail truncation only, no file written under `.colleague/tool-output/`. | `colleague/truncation.py` |
| `COLLEAGUE_READ_MAX_CHARS` | n/a — value override | Per-tool char budget override for every tool but `run_command` (default 25000); `COLLEAGUE_MAX_OUTPUT_CHARS` still applies on top as a ceiling. | `colleague/truncation.py` |
| `COLLEAGUE_SHELL_MAX_CHARS` | n/a — value override | `run_command`'s char budget override (default 30000); same ceiling rule as the row above. | `colleague/truncation.py` |
| `COLLEAGUE_PROMPT_VARIANT` | unset / `v1` (the default) | The pre-arc `_DEFAULT_SYSTEM` text byte-for-byte is the DEFAULT since the measurement (rows 43–44); `qwen` (or `adopted`) opts into the qwen-code-structured prompt. | `colleague/prompttext.py` |
| `COLLEAGUE_PROMPT_INTERACTIVE` | n/a — value override | Selects the interactive vs. headless identity/Questions guidance inside the ADOPTED prompt; has no effect under `COLLEAGUE_PROMPT_VARIANT=v1` (the v1 text is fixed). | `colleague/prompttext.py` |
| `COLLEAGUE_PROMPT_SECTIONS` | unset (t8) | Comma-separated opt-in into named ADOPTED-prompt sections beyond the fixed core list — currently only `HANDOVER_EXAMPLE` (a worked hand-over → review → collect example, which still names the raw `subagent` tool and is therefore never spliced into the default prompt); has no effect under `COLLEAGUE_PROMPT_VARIANT=v1` (proven, not asserted, by the t9 tests: `default_system` returns V1 at the variant guard before it reads `sections`). The `qwen-handover` named variant opts into the same section without the env var. | `colleague/prompttext.py` |
| `COLLEAGUE_TOOL_CALL_STYLE` | n/a — value override | Forces one tool-call example family (`qwen-coder` / `qwen-vl` / `general`) inside the ADOPTED prompt instead of the model-id-keyed default; has no effect under `COLLEAGUE_PROMPT_VARIANT=v1`. | `colleague/prompttext.py` |
| `COLLEAGUE_TOOLS_LEGACY` | `1` | Hides `grep_search`/`glob` from both the offered tool schemas and dispatch — `curate_schemas` offers exactly the pre-arc surface. | `colleague/search_schemas.py` |
| `COLLEAGUE_ASSOCIATE_MODEL` | unset | No associate seat is resolved (`EngineConfig.associate` stays `None`) — the pre-arc config shape, absent this arc's t18 seat entirely. | `colleague/associate_config.py` |
| `COLLEAGUE_ASSOCIATE_BASE_URL` | n/a — value override | The associate seat's endpoint override; inert while `COLLEAGUE_ASSOCIATE_MODEL` is unset. | `colleague/associate_config.py` |
| `COLLEAGUE_ASSOCIATE_API_KEY` | n/a — value override | The associate seat's API key override; inert while `COLLEAGUE_ASSOCIATE_MODEL` is unset. | `colleague/associate_config.py` |
| `COLLEAGUE_ASSOCIATE_CONTEXT_BUDGET` | n/a — value override | The associate seat's windowing budget override; inert while `COLLEAGUE_ASSOCIATE_MODEL` is unset. | `colleague/associate_config.py` |
| `COLLEAGUE_PRIOR_READ` | `0` | Disables the prior-read rule: an edit proceeds without a prior `read_file` of its span, the same as `main` (which never enforced the rule). **No off-state for the REFUSAL message** — `main` never produced one to be byte-identical to, so only the on-state (edit refused unless read first) is new; the off-state's *outcome* (edit proceeds) matches `main`, not its wording (there is none to match). | `colleague/editgate.py` |

## Provenance

- Spec: `docs/specs/2026-08-27-adopt-from-qwen-code.md` (frame
  `adopt-from-qwen-code`: `/scope` → `/think` → `/challenge`, 51 claims, 36
  honesty conditions, 33 scope entries — every boundary claim cites the
  qwen-code or colleague `file:lines` it was read from).
- Plan: `docs/plans/2026-08-27-adopt-from-qwen-code.md` (24 tasks / 9 waves,
  fanned out via `/assign-to-workforce`; TDD-gated merges).
- Deviations d1–d23 are recorded in the plan's deviation ledger
  (`devague deviate --list`), each classified; d16 (the associate fallback
  reading) is `risky` and awaits the operator's confirm.
- Ledger: [`docs/adopted-from.md`](../adopted-from.md) — one row per ported
  mechanism (mechanism | qwen-code path:lines | colleague path | date), pinned by
  `tests/test_adopted_from.py`.

## Credit

[`NOTICE`](../../NOTICE) names **Qwen Code** (QwenLM/qwen-code v0.22.2,
Apache-2.0, Copyright Qwen Team) as the source and **Google Gemini CLI**
v0.8.2 (Apache-2.0, Copyright Google LLC) as its lineage — qwen-code's own
README (§ Acknowledgments, lines 158-160) states it was "originally based on
Google Gemini CLI v0.8.2" and stopped syncing at Qwen Code v0.1; 427 core files
still carry Google's copyright header. **No third project is credited**
(decision q1 / boundary c16 in the spec): the Google agentic IDE the operator
first named as qwen-code's basis has no reference anywhere in qwen-code's
source, docs or git history, and the similarly named daemon in this workspace
is agentculture's own — crediting it would be a fabricated attribution.
`tests/test_adopted_from.py` keeps `NOTICE`, `colleague/` and `docs/` (outside
the arc's own spec/plan, which name the product and explain the decision) free
of its name.
