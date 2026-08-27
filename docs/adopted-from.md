# Adopted from Qwen Code / Google Gemini CLI

colleague ports several harness mechanisms — as small, standalone stdlib
Python modules, never a vendored dependency — from
[QwenLM/qwen-code](https://github.com/QwenLM/qwen-code) (v0.22.2,
Apache-2.0, Copyright Qwen Team), which was itself "originally based on
[Google Gemini CLI](https://github.com/google-gemini/gemini-cli) v0.8.2"
(README.md:158-160) before it stopped syncing with upstream at Qwen Code
v0.1; Apache-2.0, Copyright Google LLC. See [`NOTICE`](../NOTICE) for the
full attribution and [`LICENSE`](../LICENSE) for the license text. This
file tracks provenance the way
[`docs/skill-sources.md`](skill-sources.md) tracks vendored-skill
provenance, so re-reads stay deterministic: every ported
function/module's docstring also carries an inline
`adapted-from: qwen-code <path:lines>` marker (copied prose additionally
retains the upstream copyright lines, per Apache-2.0 §4(c)).

**cite-don't-import**: every row below is a Python re-implementation of an
algorithm or prompt text read from the qwen-code source — never a copied
file, never an npm/TypeScript dependency (`tests/test_zero_deps.py`
allow-lists exactly `agentfront` as colleague's one base dependency).

A row's `colleague path` reads `pending` (and its `date` reads `pending`)
until the task that lands the mechanism merges;
[`tests/test_adopted_from.py`](../tests/test_adopted_from.py) tolerates a
`pending` colleague path **only** while that row's date is also `pending` —
once a date is filled in, the colleague path must exist and contain the
literal `adapted-from: qwen-code`.

| mechanism | qwen-code path:lines | colleague path | date |
|-----------|----------------------|-----------------|------|
| toolbatch (partition by concurrency safety + read-only shell checker) | `packages/core/src/core/coreToolScheduler.ts:1284-1348, tools/tools.ts:1111, utils/shellReadOnlyChecker.ts` | `colleague/toolbatch.py` | 2026-08-27 |
| outputclamp (window-clamped `max_tokens`) | `packages/core/src/core/tokenLimits.ts:36-77` | `colleague/outputclamp.py` | 2026-08-27 |
| microcompact (rule-based blanking of old tool results) | `packages/core/src/services/microcompaction/microcompact.ts:14,40-64, services/chatCompressionService.ts:109-124` | `colleague/microcompact.py` | 2026-08-27 |
| truncation (head+tail with spill-to-disk) | `packages/core/src/tools/truncation.ts:22,200-296, tools/shell.ts:91-112` | `colleague/truncation.py` | 2026-08-27 |
| search_tools (`grep_search` + glob) | `packages/core/src/tools/ripGrep.ts, tools/grep.ts, tools/glob.ts and config.ts:9280-9315` | `colleague/search_tools.py` | 2026-08-27 |
| editmatch (tolerant edit match + prior-read enforcement) | `packages/core/src/utils/editHelper.ts:313-380, tools/priorReadEnforcement.ts` | `colleague/editmatch.py` | 2026-08-27 |
| stream guards (idle + lifetime watchdog) | `packages/core/src/core/openaiContentGenerator/constants.ts:1-68, pipeline.ts:412-530` | `colleague/streamguards.py` | 2026-08-27 |
| prompttext (base system prompt structure) | `core/prompts.ts:278-440` | `colleague/prompttext.py` | 2026-08-27 |
| loop guards (repeated/excess tool-call halting) | `packages/core/src/services/loopDetectionService.ts:35,140, core/client.ts:3717` | `colleague/loopguards.py` | 2026-08-27 |
| token estimation (chars/4 fallback, no per-turn count API) | `packages/core/src/services/tokenEstimation.ts` | `colleague/tokenestimate.py` | 2026-08-27 |
| readpage (paged, grounded `read_file` rendering + tool-output bound) | `packages/core/src/tools/read-file.ts:102-158, utils/fileUtils.ts:1440-1560` | `colleague/readpage.py` | 2026-08-27 |
| search_schemas (search tool declarations + dispatch glue) | `packages/core/src/tools/ripGrep.ts, tools/grep.ts, tools/glob.ts` | `colleague/search_schemas.py` | 2026-08-27 |
| editgate (prior-read enforcement glue over `edit_file`/`write_file`) | `packages/core/src/tools/priorReadEnforcement.ts and utils/editHelper.ts:313-380` | `colleague/editgate.py` | 2026-08-27 |
| toolbatch_loop (batched tool execution for one model turn) | `packages/core/src/core/coreToolScheduler.ts:4208-4293 and cli/src/nonInteractiveCli.ts:471-483, 1868-1871` | `colleague/toolbatch_loop.py` | 2026-08-27 |

## Re-sync procedure

Each row lands with the task that ports its mechanism (see
`docs/plans/2026-08-27-adopt-from-qwen-code.md`): the task fills in the
`colleague path` and `date` columns and adds the `adapted-from: qwen-code
<path:lines>` marker to the new module's docstring. No row is removed once
a mechanism lands — if a mechanism is later reverted (per the arc's
reversibility gate), record that in the row rather than deleting it.
