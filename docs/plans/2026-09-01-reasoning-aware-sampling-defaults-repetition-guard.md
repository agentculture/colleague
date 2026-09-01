# Build Plan — reasoning-aware sampling defaults + repetition guard (#479)

slug: `reasoning-aware-sampling-defaults-repetition-guard` · status: `exported` · from frame: `reasoning-aware-sampling-defaults-repetition-guard`

> Colleague sends each model's recommended sampling profile on every turn — a thinking profile when a reasoning rung is armed, a non-thinking profile when effort is off — instead of hard-coded greedy decoding; a model-independent guard cuts a turn whose reasoning has started repeating itself instead of riding it into the output budget; and a long turn keeps reporting liveness while it runs, so a runaway is visible while it happens rather than at the post-mortem.

## Tasks

### t1 — Oilcheck probes stay greedy and byte-identical

- instruction: Tests only — do not edit the oilcheck modules. Their greedy setting is deliberate: these are determinism probes, not reasoning work.
- covers: c22, h21
- acceptance:
  - A test asserts the request bodies built by oilcheck/`tool_calling.py` and oilcheck/`three_tier.py` are unchanged, temperature 0.0 included, and carry no sampling keys

### t2 — Sampling leaf module: profile table, model-id match rule, resolution ladder

- instruction: New file colleague/sampling.py plus tests/`test_sampling_table.py`; touch nothing else. Model the shape on colleague/`associate_config.py`: a frozen dataclass, a FIXED builtin table, per-value resolution that ignores an unparseable value rather than raising. Consume the rung from the caller — the value `vllm_payload`.`_effort_for` already computes — and do NOT resolve thinking-ness yourself. Normalisation strips the organisation prefix and quantisation suffix and lowercases; enumerate the ids a row claims rather than relying on a loose prefix, so Qwen3.8-4B cannot inherit the 27B card.
- covers: c5, h8, c6, h16, c7, h9, c15, h19, c48, h36, c52, h41
- acceptance:
  - colleague/sampling.py imports only stdlib plus colleague.effort — an import check asserts it pulls nothing from colleague.config or colleague.loop
  - The builtin Qwen3.8 rows equal the card values in issue #479: thinking 1.0/0.95/`top_k` 20/`min_p` 0.0/presence 0.0/repetition 1.0, non-thinking 0.7/0.80/`top_k` 20/presence 1.5
  - The match rule resolves the LIVE served id unsloth/Qwen3.8-27B-NVFP4 and the card id Qwen/Qwen3.8-27B to the same row, both pinned as fixtures; an unrelated model resolves to no row
  - The ladder resolves most-specific-wins across model+role+half, model+half, role+half, default, with a table-driven test where two rows match and the more specific one wins
  - An unmatched model and a None or default-sentinel rung each resolve to no sampling keys at all
  - tests/`test_file_length_ratchet.py` passes with no baseline bump for any pre-existing module

### t3 — models.json: tracked file, loader, merge granularity, gitignore allow-list

- instruction: New file colleague/samplingfile.py plus tests; the ONLY edit to an existing module is the allow-list line in colleague/artifact.py near lines 52-66 where the .gitignore body is built. models.json is a NEW file with its own loader — do not route it through `config_files.py`'s per-top-level-key merge, which is config.json's story and is exactly what this arc says must be decided deliberately.
- covers: c44, h33, c55, h47, c56, h43, c59, h49
- acceptance:
  - colleague/samplingfile.py reads .colleague/models.json across configdir roots; a missing or malformed file is a clean no-op, never a refusal
  - Merge granularity is per model key, so a repo-level file naming one model does not erase a user-level row for a different model — asserted with both files present
  - colleague/artifact.py's auto-written .gitignore allow-lists models.json beside commands/ and skills/, asserted against a freshly written file
  - A work item dispatched into a throwaway worktree resolves the operator repo's declared rows, asserted by a test that runs one in a worktree
  - An operator config predating this arc resolves to the same values it does today

### t4 — Repetition detector: pure tail-repeat function, turn-scoped state, escalation constant

- instruction: New file colleague/repetitionguard.py plus tests/`test_repetitionguard.py`; touch nothing else. Deliberately conservative: the incident gives five orders of magnitude of margin at 271,486 characters, so spend none of it on cleverness. Verbatim-tail only — the entropy tier is the one qwen-code disabled for false positives and loopguards.py records declining.
- covers: c39, h31, h26
- acceptance:
  - colleague/repetitionguard.py exposes one detector function importing nothing from the adapter or the loop, so the streaming and blocking call sites cannot drift into two definitions of repetition
  - Detector state is passed in and returned, never held at module scope — two detectors run concurrently over one repeating and one healthy stream report a trip only for the repeating one
  - The escalation bound is a named module constant; the detector trips on a verbatim tail repeat of at least 48 characters recurring at least 8 times, never on an entropy heuristic
  - Ordinary reasoning prose with repeated identifiers and numbered lists does not trip the detector

### t5 — Adapter wiring: send the resolved profile, only differing keys, plus the `COLLEAGUE_SAMPLING` kill switch

- instruction: Edit colleague/engines/`vllm_openai.py` and colleague/engines/`vllm_payload.py` only. The write site is `_build_chat_payload`'s non-associate branch, beside the existing effort fragment — the associate branch returns before it and must not be touched. Model the scripted-refusal test on tests/`test_vllm_thinking_effort.py`'s ladder-400 cases. Do NOT add a retry path: exposure is already bounded because an unmatched model sends nothing.
- depends on: t2
- covers: c1, h1, c2, h7, c4, h15, c8, h10, c17, h20, c24, h2, c34, h27, c37, h29
- acceptance:
  - A grep for the sampling key names finds exactly one write site, in the adapter payload builder; no seat builder, loop module or CLI command writes them
  - Only keys a resolved row explicitly sets are sent, so the builtin Qwen rows put `top_k` on the wire while `min_p` 0.0 and `repetition_penalty` 1.0 stay off it
  - `COLLEAGUE_SAMPLING`=0 produces the pre-change payload key for key, and two concurrent processes on one checkout can differ in sampling without touching a shared file
  - With no row matched and the kill switch unset, an outgoing payload is byte-identical to today
  - tests/`test_associate_sampling.py` passes unchanged — the associate branch is untouched
  - A scripted server refusal of the extension keys leaves the run working, and no retry-without-sampling-keys path exists
  - tests/`test_e2e_mock.py` passes unchanged

### t6 — Guard wiring: cut the turn on the streaming and blocking paths, record what it cost

- instruction: Edit colleague/engines/`vllm_transport.py`, colleague/`loop_transport.py` and loopguards.py's docstring. Feed the detector from the streaming accumulator's reasoning deltas; on the blocking path run it once on the finished text. Trip semantics are deliberately NOT loopguards' — that guard ends the run, this one cuts a turn into the recovery path that demonstrably rescued run 2bd306a6916a. Aborting the read discards the final usage frame, and CLAUDE.md forbids estimating tokens: check what the existing StreamGuardTripped path records and match it, never invent an estimate.
- depends on: t4
- covers: c10, h17, c13, h18, c33, h25, c54, h42
- acceptance:
  - A repeating streamed reasoning stream aborts the SSE read and records one warning; the run continues into the existing tighter-window retry rather than ending
  - The same detector runs post-turn on the blocking path and records the same warning shape
  - The Nth trip in one run ends the run with the warning, N being the detector module's named constant
  - A guard-cut turn's warning carries `reasoning_chars`, and the artifact makes the unrecorded-token state readable rather than implying the turn was free
  - No second warning duplicates truncated-turn: a run tripping the reasoning-exhaustion case carries exactly one warning for it
  - loopguards.py's docstring records that the repetition tier was ported after all, on which evidence, accepting which false-positive risk

### t7 — Config lane: deprecate the env knobs, render the sampling match in config show

- instruction: Walk the five mirrored surfaces to REMOVE, not to add: `config_resolve.py`'s scalar block, the EngineConfig field, `config_snapshot.py`, cli/`_commands`/config.py and explain/`catalog_ops.py`. EngineConfig keeps a resolved temperature for the payload builder; only its environment source eventually goes. `COLLEAGUE_SAMPLING` is a boolean kill switch and does not join the scalar lane.
- depends on: t2
- covers: c9, h11, c42, h32, c45, h44, c49, h37, c53, h40
- acceptance:
  - `CONVERTIBLE_TEMPERATURE` is removed and warns if set; `COLLEAGUE_TEMPERATURE` still applies, still means what it means today, and warns that it is deprecated, naming .colleague/models.json
  - An operator config predating this arc resolves to the same values in this release, changing behaviour only in the release that removes the variable
  - A run with a removed or deprecated variable set carries the warning on TaskResult.warnings and prints it once; a run without it is silent
  - config show states the sampling match positively — the row that matched and the model it matched for, or an explicit no-row-matched line
  - A deliberately misspelt model row renders as no-row-matched in config show rather than resolving quietly to the default
  - A run with the global temperature pin set records enough for a reader to tell both halves collapsed to one value

### t8 — Distill child: the second greedy site gets the same profile

- instruction: Edit colleague/distill.py's bounded completion, which today hard-codes temperature 0 in the same payload that may carry an armed thinking rung. The child is a detached subprocess reading `COLLEAGUE_DISTILL_`\* env, so the sampling module must be importable and callable there with a model id and a rung. distill.py has NO `COLLEAGUE_DUMP_REQUEST` path — add one or verify the body another way; the dump as originally written is unfulfillable.
- depends on: t2
- covers: c14, h12
- acceptance:
  - The distill child's request body carries the same sampling profile as an equivalently-runged acting turn, verified from a dumped payload
  - The child resolves its half from its own distilleffort rung, not from the acting seat's

### t9 — Record the resolved profile on the run artifact

- instruction: Follow colleague/effortrecord.py exactly, including its presence rule: a seat that resolved records, a seat that did not is simply absent, never an invented row. FILE OWNERSHIP for wave 2: this task owns a new leaf module plus its single fold-in point in colleague/`loop_outcomes.py`. Do not touch colleague/`loop_progress.py` or colleague/`loop_accounting.py` — task t10 owns those in the same wave.
- depends on: t5
- covers: c38, h30
- acceptance:
  - A run records the sampling profile each seat resolved, the way effortrecord.py records each seat's rung
  - A run whose model matched no row carries no sampling record at all, so absence reads as nothing-was-sent rather than not-recorded

### t10 — In-flight liveness on the streaming path

- instruction: FILE OWNERSHIP for wave 2: this task owns colleague/`loop_progress.py` and colleague/`loop_accounting.py` only. Do not touch colleague/`loop_outcomes.py` (task t9 owns it this wave) or colleague/engines/`vllm_transport.py` (task t6 owned it last wave). The heartbeat today fires only at phase notices, which is why a long turn is silent by construction: piggyback on delta arrival, throttled, with no timer thread — tests/`test_boundary.py`'s thread allow-list must be unchanged. The stream guards are NOT broken: idle restarts on payload bytes and the lifetime default is 1800 s, so a byte-producing 25-minute turn trips neither, correctly.
- depends on: t6
- covers: c19, h22, c32, h24
- acceptance:
  - A long streamed completion gains flight-feed records while it is still in flight, proven against a real slow turn rather than a fake
  - Liveness piggybacks on delta arrival and is throttled; no timer thread is introduced and tests/`test_boundary.py`'s thread allow-list is unchanged
  - A missing or raising sink stays a no-op and no liveness record advances `step_count`
  - The arc states plainly that the blocking path gets no in-flight liveness, rather than implying coverage it does not have
  - No change is made to streamguards' idle or lifetime bounds without a measurement justifying it

### t11 — Documentation, the fourth carve-out, and the recorded probe evidence

- instruction: Docs and one doc-agreement test; touch no runtime module. The probe evidence and its limits are the point — a reader should be able to check every number rather than take it on faith.
- depends on: t5, t6, t7, t8
- covers: c23, h14, c25, h3, c27, h5, c58, h48
- acceptance:
  - CLAUDE.md's vLLM-adapter convention bullet names the fourth carve-out beside /tokenize, the stale-pin refresh and `chat_template_kwargs`
  - A new sampling feature doc covers models.json — schema, merge granularity, the four reasons the file is not called agents.json, and the tracked-at-HEAD rule
  - thinking-effort.md's The wire section no longer claims `chat_template_kwargs` is the only per-seat body key; model-selection.md and config-resolution.md carry the new resolution
  - A doc-agreement test in the style of tests/`test_thinking_effort_docs.py` fails when a shipped value and its documented value diverge
  - The four live probe results are recorded with their honest limits: keys honoured, a 200 proving nothing, presence 1.5 harmless to tool calls and to code emission, and an abort stopping generation

### t12 — The definitive measurement arm and its behavioural discriminator

- instruction: No status code may stand as proof the profile applied — an invented key returns 200 on this gateway, which is exactly why the discriminator exists. Compare against low plus greedy, medium plus greedy at 2851 s incomplete, and the Claude control at 506 s complete. The two halves must be independently falsifiable: the sampling arm can complete while the guard never fires, and the guard test passes with sampling reverted.
- depends on: t9, t10, t11
- covers: c20, h13, c26, h4, c28, h6, c36, h28
- acceptance:
  - `COLLEAGUE_DUMP_REQUEST` on an armed turn and an off-rung turn yields two bodies differing in exactly the profile keys and the `chat_template_kwargs` fragment
  - The discriminator runs as a test or recorded probe: three completions at temperature 2.0 with `top_k` 1 are identical and the same three without `top_k` are not, so a rig that stops honouring the keys is caught rather than read as a sampling result
  - The preserved brief rerun at the full Qwen3.8 thinking profile completes inside its bound where low plus greedy did not, with longest-turn reasoning under 50,000 characters and zero repetition-guard trips
  - With sampling reverted, the guard alone cuts a synthetic repeating stream within 5 detections instead of riding to `finish_reason`=length
  - The row lands in docs/live-testing.md with every comparison figure, and the voided temp-1.0 attempt stays recorded as voided

## Risks

- [unknown_nonblocking] The definitive arm cannot run until an operator has a rig in the state the arc assumes; a rig change that silently stops honouring `top_k` would read as a sampling result rather than a rig failure, which is what t12's discriminator exists to catch. (task t12)
- [unknown_nonblocking] Whether the official Qwen3.8 thinking sampler alone stops the spiral is unknown until t12 runs — the guard is specified independently precisely because sampling lowers the attractor's probability without proving it unreachable.
