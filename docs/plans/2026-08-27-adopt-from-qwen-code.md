# Build Plan — adopt-from-qwen-code

slug: `adopt-from-qwen-code` · status: `exported` · from frame: `adopt-from-qwen-code`

> colleague adopts the harness mechanics that let Qwen Code drive the same Qwen3.8-27B to finished PRs on this rig — parallel read-only tool batches, an output-token clamp, no per-turn /tokenize round-trip, grep/glob tools, paged reads, tolerant edit matching, spill-to-disk truncation, rule-based microcompaction — and credits Qwen Code (Alibaba) and its Google Gemini CLI lineage in the provenance ledger

## Tasks

### t1 — NOTICE + docs/adopted-from.md ledger + antigravity guard

- instruction: Files: NOTICE (new), docs/adopted-from.md (new), README.md + CLAUDE.md (one link line each), tests/`test_adopted_from.py` (new). Model the ledger on docs/skill-sources.md's table. Start the ledger with the rows the later tasks will fill (one per mechanism, colleague path TBD until each lands); the test tolerates a 'pending' colleague path only while the row's date column reads 'pending'.
- covers: c15, h12, c16, h13
- acceptance:
  - NOTICE exists at repo root naming Qwen Code (QwenLM/qwen-code v0.22.2, Apache-2.0, Copyright Qwen Team) and Google Gemini CLI v0.8.2 (Apache-2.0, Copyright Google LLC) with license, version and copyright holder each
  - docs/adopted-from.md exists with the header row 'mechanism | qwen-code path:lines | colleague path | date' and is linked from README.md and CLAUDE.md
  - tests/`test_adopted_from.py` asserts every colleague path listed in the ledger exists and contains the literal 'adapted-from: qwen-code', and that grep -ri antigravity over NOTICE docs/ colleague/ returns nothing
  - tests/`test_zero_deps.py` still allow-lists exactly agentfront

### t2 — colleague/toolbatch.py — partition + read-only shell checker (pure)

- instruction: New file colleague/toolbatch.py + tests/`test_toolbatch.py`. Port the ALGORITHM of qwen-code coreToolScheduler.ts:1331 partitionByConcurrencySafety and the allow-list form of utils/shellReadOnlyChecker.ts (root-command allow-list via shlex; fail closed on any shell metachar). Docstring marker: adapted-from: qwen-code packages/core/src/core/coreToolScheduler.ts:1284-1348, utils/shellReadOnlyChecker.ts. Add a one-paragraph note that the checker decides batch parallelism only, never permission.
- covers: c40, h29
- acceptance:
  - `partition_by_concurrency_safety`(calls, `is_safe`) is a pure function whose docstring example \[Read,Read,Edit,Read\] -> \[\[Read,Read\],\[Edit\],\[Read\]\] is asserted by a test
  - `is_shell_command_read_only`(cmd) is table-tested on at least 30 commands; every compound form (; | & $( backticks > >> < sh -c xargs find -exec find -delete sed -i awk system()) is unsafe; unknown root commands are unsafe
  - `CONCURRENCY_SAFE_TOOLS` is a frozenset {`read_file`, `list_dir`, `grep_search`, glob, `view_media`} plus memory recall; edit/write/`run_tests`/subagent/subagents/finish/devague/culture are never safe
  - no import of loop.py or tools.py — the module is standalone stdlib

### t3 — colleague/outputclamp.py — window-clamped `max_tokens` with per-seat ceilings (pure)

- instruction: New file colleague/outputclamp.py + tests/`test_outputclamp.py`. adapted-from: qwen-code packages/core/src/core/tokenLimits.ts:36-77 (clampOutputTokensToWindow, `MIN_CLAMPED_OUTPUT_TOKENS`, `OUTPUT_TOKEN_CEILING`). Pure functions only; the loop wiring is t15.
- covers: c4, h2, c38, h27, c48, h35
- acceptance:
  - `clamp_output_tokens`(ceiling, window, `prompt_tokens`) returns min(ceiling, window - `prompt_tokens` - margin) with margin max(10000, 5% of window), floored at 4000; tested against the qwen-code numbers (window 262144, prompt 200000 -> 48934 at ceiling 64000)
  - `resolve_window`(`lobes_context`, `tokenize_max_model_len`, budget) applies the precedence lobes context -> /tokenize `max_model_len` -> `COLLEAGUE_CONTEXT_BUDGET` and reports which source won
  - `seat_ceiling`(seat) returns 64000 for acting seats and the design ceiling (`COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN`, default 131072) for deepthink/design seats; `COLLEAGUE_MAX_OUTPUT_TOKENS`=0 means no clamp (returns None)

### t4 — colleague/microcompact.py — rule-based blanking of old tool results (pure)

- instruction: New file colleague/microcompact.py + tests/`test_microcompact.py`. adapted-from: qwen-code packages/core/src/services/microcompaction/microcompact.ts:14,40-64 and services/chatCompressionService.ts:109-124 (thresholds). The marker must name the path so the model knows to re-read (hard question on c11). Loop wiring + fill-line ordering is t15.
- covers: c11, h9
- acceptance:
  - microcompact(messages, `keep_recent`=10) replaces the content of tool-role messages older than the most recent N with a one-line marker naming the tool and path, leaves every assistant message and `tool_calls` entry intact, and returns (messages, `blanked_count`)
  - a wire-validity test proves every `tool_call` id still has exactly one paired tool message after blanking
  - `should_microcompact`(`prompt_tokens`, budget) returns True at >= 0.85 of budget; the module never imports an engine or makes a network call

### t5 — colleague/`search_tools.py` — `grep_search` + glob (ripgrep with stdlib fallback)

- instruction: New file colleague/`search_tools.py` + tests/`test_search_tools.py`. adapted-from: qwen-code packages/core/src/tools/ripGrep.ts, tools/grep.ts, tools/glob.ts and config.ts:9280-9315 (backend selection). Reuse tools.py's resolve()-based confinement by importing its helper, do not duplicate it. Registration into SCHEMAS/`curate_schemas` is t13.
- covers: c7, h5
- acceptance:
  - `grep_search`(root, pattern, path=None, glob=None, `max_results`) uses rg when on PATH else a pure-stdlib walker, and both backends produce identical output on a fixture tree (test runs both)
  - glob(root, pattern) returns matches sorted by mtime descending, repo-confined; a pattern or path escaping the root (including via symlink) is refused with the same error shape `read_file` uses
  - neighbour clones under .colleague/neighbours are searchable read-only; .git and .colleague/worktrees are excluded by default

### t6 — colleague/editmatch.py — tolerant edit match + prior-read set (pure)

- instruction: New file colleague/editmatch.py + tests/`test_editmatch.py`. adapted-from: qwen-code packages/core/src/utils/editHelper.ts:313-380 (normalizeEditStrings, findMatchedSlice) and tools/priorReadEnforcement.ts. Wiring into `edit_file` is t12.
- covers: c9, h7
- acceptance:
  - `normalize_edit_strings`(text, old, new) returns the exact on-disk slice for a match that differs only by smart quotes or per-line leading/trailing whitespace, never rewrites `new_string`, and returns None (caller falls to the exact path) when the exact match already succeeds
  - a CRLF- or indent-drifted `old_string` lands; two relaxed matches still raise the ambiguity error; there is no LLM call and no import of an engine
  - ReadSet records (path, line ranges) fully read in this work item; `is_read_for_edit`(path, span) is False for a paged/truncated read whose span was not shown

### t7 — Stream guards — idle + lifetime watchdog on the SSE path (`vllm_openai.py`)

- instruction: Files: colleague/engines/`vllm_openai.py` (stream reader around :368 stallguard.check), colleague/stallguard.py, tests/`test_stream_guards.py`. adapted-from: qwen-code packages/core/src/core/openaiContentGenerator/constants.ts:1-68 and pipeline.ts:412-530 (withStreamGuards). Keep the blocking-fallback ladder (:723-789) untouched. This task owns `vllm_openai.py` in its wave; t9 follows it.
- covers: c12, h10
- acceptance:
  - `COLLEAGUE_STREAM_IDLE_TIMEOUT` (default 240) and `COLLEAGUE_STREAM_MAX_LIFETIME` (default 900) are read in the stream reader; 0 disables; a trip raises the existing TurnStalled path and TaskResult.warnings names which guard tripped
  - tests use a real os.pipe/PTY drip-feed server (never a fake stream): an idle gap trips at the idle bound; a 1-byte-per-second stream trips at the lifetime bound
  - stallguard's 6x-mean scaling is removed and its tests updated; `COLLEAGUE_TIMEOUT` semantics unchanged

### t8 — Prompt text adoption — colleague/prompttext.py with per-model examples + variant knob

- instruction: Files: colleague/prompttext.py (new), colleague/loop.py (only the `_DEFAULT_SYSTEM` import at :105-164 — one hunk), tests/`test_prompttext.py` with snapshots. Prose is adapted, not pasted wholesale: keep colleague's Destination/Subagents/Culture/Test-integrity sections. The env/context prelude stays a first user message.
- covers: c14, h11, c47, h34
- acceptance:
  - `_DEFAULT_SYSTEM` moves to colleague/prompttext.py; the adopted sections (Core Mandates, Using Your Tools, Executing actions with care, Final Reminder) carry the marker 'adapted-from: qwen-code core/prompts.ts:278-440 — Copyright 2025 Google LLC, Copyright 2026 Qwen Team, Apache-2.0' and a test greps both copyright holders
  - tool-call example blocks are keyed by model id (qwen-coder, qwen-vl, gemma4, default) with a snapshot test per family; the headless variant omits ask-style guidance and the matching tools are absent from the offered schemas
  - `COLLEAGUE_PROMPT_VARIANT`=v1 yields the pre-arc `_DEFAULT_SYSTEM` byte-for-byte (snapshot pinned from main); the prompt is still built once per run (prefix-stable)

### t10 — Measurement harness — scripts/`compare_arms.py` + pre-registration + before-state row

- instruction: Files: scripts/`compare_arms.py` (new), tests/`test_compare_arms.py`, docs/live-testing.md (two rows). Run the main arm on this rig now (wave 1) so the baseline predates the port; use the game-benchmark command template at ~/.colleague/commands/game-benchmark.md plus one small repo task; cap at 2 concurrent loops, `COLLEAGUE_TIMEOUT`=300.
- covers: c22, h16, c26, h19
- acceptance:
  - scripts/`compare_arms.py` reads N lists of artifact ids, computes wall-clock and `model_turns` ratios from artifact `duration_seconds`/`model_turns` (never prose), prints them, and exits 1 when a ratio misses the c28 bar (<= 0.7 wall, <= 0.8 turns) — unit-tested on fixture artifacts
  - docs/live-testing.md carries a pre-registration row naming the brief (game-benchmark + one repo task), n>=3 per brief, the arms (main / branch associate-unarmed / branch associate-armed / temperature arm per c51), the rig, model and effort table, BEFORE any arm runs
  - the before-state row exists: main at the arc's base SHA, `COLLEAGUE_DUMP_REQUEST`=1 dump showing no `max_tokens`, and the artifact ids of the n>=3 main runs

### t11 — colleague/truncation.py — head+tail truncation with spill-to-disk (pure + fs)

- instruction: New file colleague/truncation.py + tests/`test_truncation.py`. adapted-from: qwen-code packages/core/src/tools/truncation.ts:22,200-296 and tools/shell.ts:91-112. Spill dir is <repo>/.colleague/tool-output/ (gitignored via .colleague/\*); the reap hook in colleague clean is wired in the observability task.
- covers: c10, h8
- acceptance:
  - `truncate_output`(text, `max_chars`, `max_lines`, `spill_dir`) keeps head and tail, writes the full text to `spill_dir`/<hash>.txt with mode 0o600, and returns text that names the spilled file's absolute path; spilled content == original (test)
  - per-tool defaults: 25000 chars / 1000 lines for tools, 30000 for `run_command`; `COLLEAGUE_MAX_OUTPUT_CHARS` acts as a CEILING over both, and `COLLEAGUE_READ_MAX_CHARS` / `COLLEAGUE_SHELL_MAX_CHARS` set a tool beneath it (decision c50 test: exported `COLLEAGUE_MAX_OUTPUT_CHARS`=100000 leaves `read_file` at 25000)
  - a session cap (500 MB) stops spilling with a recorded warning; `COLLEAGUE_TOOL_SPILL`=0 disables spilling and falls back to head+tail only

### t12 — Drop the per-turn /tokenize — run-start window discovery + `COLLEAGUE_EXACT_TOKENS`

- instruction: Files: colleague/context.py (`window_messages` counter path :232-282), colleague/engines/`vllm_openai.py` (counter closure :976-998 → run-start call), config.py knob, tests. adapted-from: qwen-code services/tokenEstimation.ts (estimatePromptTokens) — cite in context.py's docstring. Runs after t7 because both edit `vllm_openai.py`.
- depends on: t7, t3
- covers: c5, h3, c38, h27
- acceptance:
  - with a counting fake server, a 3-turn run makes exactly one /tokenize call (at run start) and one /chat/completions per turn; `COLLEAGUE_EXACT_TOKENS`=1 restores the per-turn call
  - `window_messages` counts with the last usage.`prompt_tokens` plus the chars/4 estimate for new messages (context.py), never a network call per turn; the artifact's token fields still come from usage only
  - the run-start /tokenize reply's `max_model_len` feeds outputclamp.`resolve_window` with the documented precedence; a fake server advertising `max_model_len`=8192 never sees prompt + `max_tokens` above 8192, and the vLLM 400 'maximum context length' reply is reproduced in a test that proves the clamp prevents it
  - docs/features/graceful-degradation.md and CLAUDE.md's vLLM carve-out list read two carve-outs, not three

### t18 — Associate seat A — opt-in resolution, role-name addressing, streaming, config/lobes show

- instruction: Files: colleague/config.py (mirror the deepthink keys at :2301 and the lobes sentinel at :3417-3431), colleague/lobes.py (role list), colleague/effort.py, colleague/cli/`_commands`/config.py + lobes.py (show lines), tests/`test_associate_config.py`. Do NOT touch subagents.py/roles.py here (Associate seat B).
- covers: c37, h26, c49, h36
- acceptance:
  - `COLLEAGUE_ASSOCIATE_MODEL`=lobes (or an explicit id) resolves a second EngineConfig via the lobes gateway the way deepthink does; unset -> byte-identical to main (pinning test with lobes armed)
  - the associate EngineConfig sends model='associate' on the wire and records the SERVED model from the reply's model field on the artifact/ledger; a gateway rejecting the role name falls back once to the model id, then to cortex@low with a recorded warning
  - associate completions stream (stream + `stream_options`.`include_usage`) on the same engine path as cortex, headless included (decision c52)
  - config show prints 'associate → <served model> (addressed as role name via proxy)' when armed and 'not consumed (opt-in): associate → …' when advertised but unarmed; lobes show lists the associate role; effort.py's table gains an 'associate' row defaulting to off

### t19 — Associate seat B — the enumerated consumers (scout child, compact summary, synthesis, digests, distill rung)

- instruction: Files: colleague/subagents.py (child EngineConfig swap near `_child_config_lifecycle` :238-270), colleague/roles.py (scout role), colleague/distill.py (author precedence :101-138 gains the associate rung after deepthink/muse), colleague/loop.py (compact/synthesis author selection — one hunk each), tests. Keep the resolution-rung shape: precedence deepthink/muse > associate > cortex@low, recorded on the artifact.
- depends on: t18
- covers: c33, h22
- acceptance:
  - `ASSOCIATE_SEATS` is one module-level tuple listing the scout subagent role, fill-line compact author, forced synthesis, lint/affected-tests digest and rung-2 distill author rung; docs/features/thinking-effort.md's table has the row; an AST guard pins that no other call site references the associate config
  - a read-only scout child (roles.py) runs on the associate EngineConfig with a tool surface that is a strict subset of the parent's read-only set (`edit_file`/`write_file`/`run_tests` absent — test); an associate reply containing a repo-mutating tool call is refused and recorded, not executed
  - unarmed, every seat runs on cortex with `chat_template_kwargs` for 'low' (test), and the code-authoring seats never reference the associate config

### t9 — tools.py wiring A — `read_file` offset/limit + spill truncation

- instruction: Files: colleague/tools.py (`read_file` :927-939, `_truncate` :838-842, SCHEMAS entry for `read_file`), tests/`test_tools_read.py`. This task owns tools.py in its wave; t12 and t13 chain after it.
- depends on: t5, t11
- covers: c8, h6, c10, h8
- acceptance:
  - `read_file`(path, offset=None, limit=None) numbers lines with the ORIGINAL file line numbers when paged (test at offset 500 keeps #240 grounding), defaults 1000 lines / 25000 chars, and a truncated read ends with exactly 'Read lines X-Y of N'
  - ToolExecutor.`_truncate` delegates to colleague/truncation.py: `run_command` output is head+tail at 30000 with the spilled path named; `read_file` at 25000; spilled files land under .colleague/tool-output/
  - tests/`test_e2e_mock.py` passes unchanged

### t13 — tools.py wiring B — `edit_file` tolerant tier + prior-read enforcement

- instruction: Files: colleague/tools.py (`edit_file` :992-1059; ToolExecutor gains a ReadSet fed by `read_file`), tests/`test_tools_edit.py`. The refusal message must say 'read the file (or that span) first' — a cheap model must recover in one step.
- depends on: t6, t9
- covers: c9, h7
- acceptance:
  - `edit_file` tries the exact match first, then editmatch.`normalize_edit_strings`; a whitespace-drifted `old_string` lands in one step; ambiguity still errors naming the count
  - editing a file not read in this work item (or a span not shown by a paged/truncated read) is refused with a typed error naming the rule; `write_file` of a NEW file is unaffected
  - no LLM call anywhere in tools.py (grep test for engine imports)

### t14 — tools.py wiring C — register `grep_search` + glob, concurrency kinds, role curation

- instruction: Files: colleague/tools.py (SCHEMAS, execute dispatch :867-916, `curate_schemas` :590-626), colleague/roles.py (read-only role tool sets), tests. Last tools.py task in the chain.
- depends on: t5, t13
- covers: c7, h5
- acceptance:
  - SCHEMAS contains `grep_search` and glob with descriptions naming ripgrep-style patterns; ToolExecutor.execute dispatches them; `curate_schemas` offers them to every read-capable role (read-only roles included)
  - both go through truncation.py; both are listed in toolbatch.`CONCURRENCY_SAFE_TOOLS`; `COLLEAGUE_TOOLS_LEGACY`=1 hides both schemas (the byte-identical proof path)
  - docs/features/work-and-loop.md's tool table lists both

### t15 — loop.py — batched tool execution (lifecycle split, pool, failure + stop semantics, convention change 6)

- instruction: Files: colleague/loop.py (`_run_tool_calls` :1246-1258 and the `_run_tool_call` split :1071-1204), tests/`test_boundary.py`, CLAUDE.md (conventions + v1 scope), tests/`test_toolbatch_loop.py`. Put the ThreadPoolExecutor in colleague/toolbatch.py behind `run_batch`(execute, calls, width) so loop.py does not import concurrent.futures directly. Batch-boundary stop latency is documented honestly (the docs task writes the doc; this task adds the docstring).
- depends on: t2, t14
- covers: c6, h4, c35, h24, c36, h25
- acceptance:
  - `_run_tool_calls` partitions via toolbatch and runs `pre_tool` hook, TAE gate and policy gate on the main thread in request order BEFORE the pool; only executor.execute runs in the pool; step indices, Step/tool-message appends, `post_tool` hooks, progress and flight records happen on the main thread in request order after the join (test with inverted sleep durations pins order and indices)
  - an AST test proves the pool target references no ctx/`_Work` attribute; `COLLEAGUE_TOOL_CONCURRENCY` (default 10, 1 = sequential) — at 1 the mock e2e suite is byte-identical
  - a batch of \[ok, error, ok\] yields three ordered steps with one non-ok; a flight stop written mid-batch takes effect before the next batch and the artifact carries the completed batch; SIGTERM handling unchanged
  - tests/`test_boundary.py`'s thread allow-list adds colleague/toolbatch.py with its stated reason; CLAUDE.md's v1 section records convention change (6)

### t16 — loop.py — clamp, microcompaction, loop guards, ledger event

- instruction: Files: colleague/loop.py (turn path :2072-2151 for the clamp; `_maybe_offer_fillline` :1480 ordering; a new `_loop_guards` check next to `_tool_protocol_broken` :1240), colleague/engines/`vllm_openai.py` gets `max_tokens` in `_build_chat_payload` (one hunk), colleague/agents/runtime.py (ledger event), tests. adapted-from markers: loopDetectionService.ts:35,140 on the guards.
- depends on: t15, t3, t4
- covers: c4, h2, c11, h9, c20, h15, c42, h31
- acceptance:
  - every main-loop payload carries `max_tokens` from outputclamp (seat-aware); a `finish_reason`=length turn retries once at the seat ceiling then falls to the existing `TRUNCATED_TURN_MARKER` handling; distill/oilcheck payloads unchanged
  - microcompact runs BEFORE the fill-line offer at >= 0.85 of budget; the fill-line offer fires only if still over the line afterwards; `blanked_count` lands on the artifact; `COLLEAGUE_MICROCOMPACT`=0 restores today's path
  - 5 consecutive identical (name+arguments) tool calls or 100 calls in one turn halt the run with a named warning and drop pending calls; the unknown-tool streak test is unchanged
  - with agents armed, each microcompaction pass appends one ledger event (count + blanked step indices) and rehydration reproduces the blanked history

### t17 — mock engine batch scenario + all-engines pin

- instruction: Files: colleague/engines/mock.py, tests/`test_e2e_mock.py`, tests/`test_all_engines_batch.py`. Keep the mock's contract-reference role: the fixture is the source of truth both engines are compared against.
- depends on: t15
- covers: c39, h28, c19, h14
- acceptance:
  - engines/mock.py gains an opt-in scenario (task text trigger, like existing recipes) returning one turn with three read-only calls plus one write; default mock output is unchanged
  - tests/`test_e2e_mock.py` pins the batch Step sequence and result shape via a shared fixture also run against a fake vllm-openai server — identical
  - a diff-scope test asserts `vllm_openai.py`'s payload keys are OpenAI-surface keys plus `chat_template_kwargs`, and that no per-turn /tokenize call remains

### t20 — Observability — doctor rows, config show clamp/window, artifact counts, clean reaps spill

- instruction: Files: colleague/doctor.py, colleague/cli/`_commands`/config.py (show), colleague/contract.py + colleague/artifact.py (WorkStats fields), colleague/cleanup.py, tests. Counts are incremented in loop.py by the two loop tasks — read them here, add the fields here.
- depends on: t16, t18
- covers: c43, h32
- acceptance:
  - doctor --json gains informational rows: stream guards (idle < lifetime), tool concurrency cap, ripgrep presence, associate resolution state (consumed / opt-in / fallback); snapshot test
  - config show prints the `max_tokens` ceiling and the window source that won; TaskResult/WorkStats carry exact integer counts: `batches_run`, `calls_parallelised`, `results_blanked`, `outputs_spilled`, `guard_trips` (artifact schema test; mock shape unchanged when all are 0)
  - colleague clean reaps .colleague/tool-output/ and reports the bytes freed

### t21 — Continuation — no read-set across work --continue

- instruction: Files: colleague/continuation.py (seed body :304), tests/`test_continuation_readset.py`. The ReadSet is simply not persisted — verify nothing in the snapshot carries it.
- depends on: t13
- covers: c41, h30
- acceptance:
  - a continued run that edits a file before reading it gets the typed refusal naming the rule and the continuation id; read-then-edit succeeds
  - the continuation seed body states the rule up front (snapshot test of render)

### t22 — Reversibility — one off-knob per mechanism, byte-identical pinning suite

- instruction: Files: tests/`test_knobs_byte_identical.py` (new), tests/fixtures/`main_baseline`/ (recorded from the arc's base SHA), docs/features/adopt-from-qwen-code.md (knob table section only — the docs task writes the rest). Record the baseline fixtures FIRST from main before any mechanism lands.
- depends on: t16, t8, t14, t18
- covers: c1, h1, c44, h33
- acceptance:
  - tests/`test_knobs_byte_identical.py` flips each knob to its off value (`COLLEAGUE_MAX_OUTPUT_TOKENS`=0, `COLLEAGUE_EXACT_TOKENS`=1, `COLLEAGUE_TOOL_CONCURRENCY`=1, `COLLEAGUE_MICROCOMPACT`=0, `COLLEAGUE_STREAM_IDLE_TIMEOUT`=0 + `COLLEAGUE_STREAM_MAX_LIFETIME`=0, `COLLEAGUE_TOOL_SPILL`=0, `COLLEAGUE_PROMPT_VARIANT`=v1, `COLLEAGUE_TOOLS_LEGACY`=1, `COLLEAGUE_ASSOCIATE_MODEL` unset) and diffs request payloads, offered tool schemas and messages against main's recorded fixtures — identical
  - the knob table lives once in docs/features/adopt-from-qwen-code.md and a test asserts every knob in the table is read somewhere in colleague/ (grep) and vice versa

### t23 — Docs — feature doc, CLAUDE.md bullet + carve-outs, ledger rows, approval-gate + work-and-loop paragraphs

- instruction: Files: docs/features/adopt-from-qwen-code.md (new), CLAUDE.md, docs/features/{approval-gate,work-and-loop,graceful-degradation,thinking-effort}.md, docs/adopted-from.md, README.md. Trim discipline c17: bullets point to the feature doc.
- depends on: t22, t19, t20, t21, t17, t12
- covers: c24, h17, c25, h18, c27, h20, c15, h12
- acceptance:
  - docs/features/adopt-from-qwen-code.md: first paragraph names the three readers and what each takes; every after-state clause maps to a requirement with its live-testing row or is listed under Honest limits; cites the qwen-code session usage line and rt-optimization-design.md §1.2 verbatim with dates
  - CLAUDE.md gains the architecture bullet + the carve-out list reads two; docs/features/approval-gate.md gains the 'batch checker is a parallelism hint, not permission' paragraph; docs/features/work-and-loop.md states batch-boundary stop latency honestly
  - docs/adopted-from.md rows are complete (no 'pending' dates) and tests/`test_adopted_from.py` passes; markdownlint-cli2 passes on every touched doc

### t24 — Run the arms — three model arms + temperature arm, ratios recorded, revert-or-flag

- instruction: Run on this rig within one day of the main arm, same effort table; associate via model='associate' through spark's gateway. Cap 2 concurrent loops. Attach artifact ids, not prose.
- depends on: t23, t10
- covers: c28, h21, c34, h23
- acceptance:
  - docs/live-testing.md carries one row per arm with artifact ids; `compare_arms.py` output is pasted verbatim; arm 3 reads 'blocked: gateway' if associate is not routable at run time rather than being skipped
  - if a ratio misses the bar the feature doc's Honest limits says so and the responsible mechanism is reverted or flagged in the PR — never kept silently; the summarize-delivery record cites the script output
  - the temperature arm (T=0.0 vs model default, decision c51) is reported beside the model arms

## Risks

- [unknown_nonblocking] GPU serialisation: on this rig only ~2 colleague loops run concurrently, so wide waves execute mostly serially in practice — plan waves are content-parallel, not throughput-parallel
- [unknown_nonblocking] loop.py (270 KB) is edited by t10 (one hunk), t14, t15 and t18 — chained by dependency, but each merge must re-run tests/`test_e2e_mock.py` before the next loop.py task starts; colleague itself times out editing large files, so these tasks are Claude-side or narrowly briefed
- [unknown_nonblocking] Arm 3 depends on spark's proxied associate staying routable by role name; the advert currently says ready:false — if the proxy regresses, t24 records 'blocked: gateway' and the arc still ships the mechanics ratio
