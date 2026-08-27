# adopt-from-qwen-code

> This file is a work in progress: task t22 (this task) lands ONLY the
> `## Knobs` section below. Every other section a finished feature doc
> carries (Audience, Before → After, Why it matters, Honest limits, the
> provenance-ledger cross-link, …) is task t23's to add.

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
| `COLLEAGUE_MICROCOMPACT` | `0` | Disables the rule-based microcompaction floor (blanking old tool results ahead of the fill-line offer); today's windowing-only path is unchanged. | `colleague/turnbudget.py` |
| `COLLEAGUE_STREAM_IDLE_TIMEOUT` | `0` | Disables the stream idle-timeout watchdog. Together with `COLLEAGUE_STREAM_MAX_LIFETIME=0`, `StreamGuards.from_env()` returns `None` and the SSE reader is byte-identical to the unguarded one. | `colleague/streamguards.py` |
| `COLLEAGUE_STREAM_MAX_LIFETIME` | `0` | Disables the stream max-lifetime watchdog (see the row above — both must be `0` together for a fully unguarded stream). | `colleague/streamguards.py` |
| `COLLEAGUE_TOOL_SPILL` | `0` | Disables spill-to-disk on an over-budget tool result: head+tail truncation only, no file written under `.colleague/tool-output/`. | `colleague/truncation.py` |
| `COLLEAGUE_READ_MAX_CHARS` | n/a — value override | Per-tool char budget override for every tool but `run_command` (default 25000); `COLLEAGUE_MAX_OUTPUT_CHARS` still applies on top as a ceiling. | `colleague/truncation.py` |
| `COLLEAGUE_SHELL_MAX_CHARS` | n/a — value override | `run_command`'s char budget override (default 30000); same ceiling rule as the row above. | `colleague/truncation.py` |
| `COLLEAGUE_PROMPT_VARIANT` | `v1` | Selects the pre-arc `_DEFAULT_SYSTEM` text byte-for-byte (the reversibility floor); any other value builds the adopted qwen-code-structured prompt. | `colleague/prompttext.py` |
| `COLLEAGUE_PROMPT_INTERACTIVE` | n/a — value override | Selects the interactive vs. headless identity/Questions guidance inside the ADOPTED prompt; has no effect under `COLLEAGUE_PROMPT_VARIANT=v1` (the v1 text is fixed). | `colleague/prompttext.py` |
| `COLLEAGUE_TOOL_CALL_STYLE` | n/a — value override | Forces one tool-call example family (`qwen-coder` / `qwen-vl` / `general`) inside the ADOPTED prompt instead of the model-id-keyed default; has no effect under `COLLEAGUE_PROMPT_VARIANT=v1`. | `colleague/prompttext.py` |
| `COLLEAGUE_TOOLS_LEGACY` | `1` | Hides `grep_search`/`glob` from both the offered tool schemas and dispatch — `curate_schemas` offers exactly the pre-arc surface. | `colleague/search_schemas.py` |
| `COLLEAGUE_ASSOCIATE_MODEL` | unset | No associate seat is resolved (`EngineConfig.associate` stays `None`) — the pre-arc config shape, absent this arc's t18 seat entirely. | `colleague/associate_config.py` |
| `COLLEAGUE_ASSOCIATE_BASE_URL` | n/a — value override | The associate seat's endpoint override; inert while `COLLEAGUE_ASSOCIATE_MODEL` is unset. | `colleague/associate_config.py` |
| `COLLEAGUE_ASSOCIATE_API_KEY` | n/a — value override | The associate seat's API key override; inert while `COLLEAGUE_ASSOCIATE_MODEL` is unset. | `colleague/associate_config.py` |
| `COLLEAGUE_ASSOCIATE_CONTEXT_BUDGET` | n/a — value override | The associate seat's windowing budget override; inert while `COLLEAGUE_ASSOCIATE_MODEL` is unset. | `colleague/associate_config.py` |
| `COLLEAGUE_PRIOR_READ` | `0` | Disables the prior-read rule: an edit proceeds without a prior `read_file` of its span, the same as `main` (which never enforced the rule). **No off-state for the REFUSAL message** — `main` never produced one to be byte-identical to, so only the on-state (edit refused unless read first) is new; the off-state's *outcome* (edit proceeds) matches `main`, not its wording (there is none to match). | `colleague/editgate.py` |
